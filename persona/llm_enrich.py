"""LLM enrichment for selected personas (demo sellers / on demand in the UI), using sarvam-105b.

Adds to a spec:
  enrichment.rationale      4-6 sentences a reviewer can read: why this persona fits this seller
  enrichment.opening_line   the rule-based opening rewritten to sound natural in the persona's language/mix
The rewrite is checked: it may not add numbers, prices or claims that are not in the original line; otherwise the
rule-based line is kept.

    python -m persona.llm_enrich 127142815 [more ids]
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from persona.facts import FACTS  # noqa: E402

ENRICH_MODEL = "sarvam-105b-conversations"

SYSTEM = """You help design the voice persona of VANI, IndiaMART's AI calling agent that books short meetings \
between sellers and IndiaMART sales executives. You get a persona spec built from seller data.
Return ONLY a JSON object with two keys:
"rationale": 4-6 plain sentences for a reviewer explaining why this persona (voice, language, pace, tone, opening, \
live thresholds) fits this seller. Mention the seller facts and evidence numbers given in the spec; do not invent any.
"opening_line": the given opening line rewritten so it sounds natural when spoken in the target language and mix. \
Keep the same meaning, the same facts and every number exactly; add no new facts, claims, prices or promises; \
keep it within the word limit. Write Hindi/Hinglish in Roman script."""


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s or ""))


def enrich(spec: dict, client=None) -> dict:
    from sarvamai import SarvamAI
    c = client or SarvamAI(api_subscription_key=config.require_key())
    lang = spec["language"]
    brief = {
        "persona_label": spec["persona_label"],
        "vani_agent_name": FACTS["agent_name"][spec["voice"]["gender"]["value"]],
        "note": "The agent name belongs to VANI, not the seller. The seller's name is unknown; do not name them.",
        "seller": spec["seller_snapshot"],
        "voice": {k: spec["voice"][k]["value"] for k in ("speaker", "gender", "pace", "pitch")},
        "language": {k: lang[k]["value"] for k in ("primary", "english_share", "formality", "address_form")},
        "tone": {k: v["value"] for k, v in spec["tone"].items()},
        "opening_hook": spec["conversation_plan"]["opening_hook"],
        "opening_style": spec["conversation_plan"]["opening_style"],
        "pace_reason": spec["voice"]["pace"]["reason"], "language_reason": lang["primary"]["reason"],
        "thresholds": spec["live_adaptation"]["thresholds"]["value"],
        "rules_fired": spec["rules_fired"],
        "opening_line": spec["conversation_plan"]["opening_line"]["value"],
        "word_limit": spec["tone"]["max_words_per_turn"]["value"] + 12,
    }
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(brief, ensure_ascii=False, default=str)}]
    for attempt in range(4):
        try:
            # sarvam-105b spends 3000+ tokens on hidden reasoning and returns no content (tested 2026-10-09),
            # so enrichment uses the conversations model: ~1 s, JSON output.
            r = c.chat.completions(messages=msgs, model=ENRICH_MODEL, temperature=0.3, max_tokens=900)
            break
        except Exception as e:
            if "429" not in str(e):
                raise
            time.sleep(2 ** attempt)
    text = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", text, re.S)
    out = json.loads(m.group(0)) if m else {}
    orig = brief["opening_line"]
    line = out.get("opening_line", "")
    ok = bool(line) and _numbers(line) <= _numbers(orig) and not re.search(r"₹|rupa|discount|offer", line, re.I)
    spec["enrichment"] = {
        "model": ENRICH_MODEL,
        "rationale": out.get("rationale", ""),
        "opening_line": line if ok else orig,
        "opening_line_source": "llm (fact-checked)" if ok else "rules (LLM rewrite rejected by fact check)",
    }
    return spec


if __name__ == "__main__":
    from persona.generator import generate
    from persona.seller_features import load_features
    feats = load_features()
    (config.OUT_DIR / "personas").mkdir(parents=True, exist_ok=True)
    for sid in map(int, sys.argv[1:]):
        spec = enrich(generate(feats[feats.fk_glusr_usr_id == sid].iloc[0].to_dict()))
        (config.OUT_DIR / "personas" / f"{sid}.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1),
                                                                 encoding="utf-8")
        print(f"\n== {sid}: {spec['persona_label']}\n{spec['enrichment']['rationale']}\n"
              f"OPENING ({spec['enrichment']['opening_line_source']}): {spec['enrichment']['opening_line']}")
