"""Persona spec -> Sarvam Voice Agent variables (+ which agent variant voices it).

Variables are written in English (the platform rule: hand-written copy is English; the agent speaks the configured
language). They describe delivery only; facts stay in the prompt's Facts section.

    python -m sarvam_agent.to_variables --seller-id 331550          # print variables for one seller
    python -m sarvam_agent.to_variables --cohort out/sarvam/cohort.csv [--ids 1,2,3]   # campaign cohort CSV
"""
import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from sarvam_agent.variants import SPEAKER_TO_VARIANT, VARIANTS  # noqa: E402

LANG_NAME = {"hi-IN": "Hindi", "en-IN": "English", "gu-IN": "Gujarati", "ta-IN": "Tamil", "bn-IN": "Bengali",
             "mr-IN": "Marathi", "te-IN": "Telugu", "kn-IN": "Kannada", "pa-IN": "Punjabi"}
SITUATION_TEXT = {
    "busy_no_time": "Busy or no time",
    "out_of_station": "Out of station or not available on the day",
    "seller_gives_time": "User offers a day or time",
    "not_interested": "Not interested or no requirement",
    "price_question": "Asks about price or charges",
    "already_in_touch": "Already met or in touch with an IndiaMART executive",
    "who_are_you_or_bot": "Asks who is calling or whether this is a bot",
    "bad_past_experience": "Complains about no leads or a bad past experience",
    "send_details": "Asks for details on WhatsApp or mail",
}
HOOK_TEXT = {
    "paid_services": "the user recently looked at IndiaMART paid services",
    "buylead": "the user recently checked buy leads for {cat} on IndiaMART",
    "category_demand": "buyers in {city} are sending enquiries for {cat}",
    "catalogue_improvement": "a stronger {cat} catalogue on IndiaMART would reach more buyers",
    "callback_with_reason": "the user asked for a call back today about buyer enquiries for {cat}",
}


def _v(spec, sec, key):
    return spec[sec][key]["value"]


def _trim(s, n: int) -> str:
    """Cut at the last full sentence (or word) before n characters."""
    s = str(s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[:end + 1] if end > n // 2 else cut[:cut.rfind(" ")] + "..."


def _level(n: int) -> str:
    return {1: "very low", 2: "low", 3: "moderate", 4: "high", 5: "very high"}.get(int(n), "moderate")


def language_style(spec) -> str:
    lang = LANG_NAME.get(_v(spec, "language", "primary"), "Hindi")
    es = _v(spec, "language", "english_share")
    form = _v(spec, "language", "formality")
    addr = _v(spec, "language", "address_form")
    if lang == "English":
        base = "Simple, clear Indian English with short sentences."
    elif es <= 15:
        base = f"Plain everyday Hindi; only common business words in English (about {es} percent English)."
    elif es >= 40:
        base = f"Business Hinglish with about {es} percent English terms."
    else:
        base = f"Natural Hinglish with about {es} percent English words."
    return f"{base} Formality: {form}. Address form: {addr}."


def tone_profile(spec) -> str:
    t = spec["tone"]
    return (f"Warmth {_level(t['warmth']['value'])}, empathy {_level(t['empathy']['value'])}, "
            f"assertiveness {_level(t['assertiveness']['value'])}.")


def sensitivity(spec) -> str:
    thr = spec["live_adaptation"]["thresholds"]["value"]
    words = []
    for sig, label in [("rush", "Rush"), ("unavailable", "Unavailability"), ("frustration", "Frustration"),
                       ("confusion", "Confusion"), ("interest", "Interest")]:
        v = thr.get(sig, 0.6)
        words.append(f"{label}: {'switch at the first hint' if v <= 0.45 else 'switch on a clear signal'}")
    return "; ".join(words) + "."


def seller_history(spec) -> str:
    s = spec["seller_snapshot"]
    parts = []
    att, ans = int(s.get("bot_attempts") or 0), int(s.get("bot_answered") or 0)
    if att:
        parts.append(f"{att} earlier IndiaMART bot calls, {ans} answered")
    for k, label in [("calls_not_interested", "said not interested"), ("calls_call_later", "asked to call later"),
                     ("calls_meeting_fixed", "agreed to a meeting")]:
        n = int(s.get(k) or 0)
        if n:
            parts.append(f"{label} {n} time{'s' if n > 1 else ''}")
    if s.get("avg_answered_call_sec"):
        parts.append(f"average answered call {int(s['avg_answered_call_sec'])} seconds")
    kh = spec["live_adaptation"]["known_history"]["value"]
    text = ("; ".join(parts) + ".") if parts else "No earlier calls on record."
    if kh and kh.get("example") and kh["example"].get("seller_said"):
        # Only what the user said and what went wrong. The evaluator's suggested replies sometimes promise things
        # VANI cannot do (send SMS links) or cite numbers outside the fact sheet, so they stay out of the prompt;
        # how to respond comes from the vetted objection playbook instead.
        ex = kh["example"]
        what = {"rush": "ignored that the user was busy", "ignored_or_repeated": "repeated the pitch",
                "confusion": "did not clear the user's confusion", "frustration": "did not respond to frustration",
                "price": "mishandled a price question", "time_offered": "did not accept the time the user offered"}
        issues = ", ".join(what[t] for t in (kh.get("themes") or []) if t in what) or "did not respond to it well"
        text += f" Audit of an earlier call: the user said {_trim(ex['seller_said'], 140)} and the bot {issues}."
    return text


def objection_priorities(spec) -> str:
    pb = spec["conversation_plan"]["objection_playbook"]["value"][:5]
    return " ".join(f"{i + 1}. {SITUATION_TEXT.get(p['situation'], p['situation'])}: {p['approach']}"
                    for i, p in enumerate(pb))


def personal_details(spec) -> str:
    slots = spec["conversation_plan"]["personalisation"]["value"] or []
    names = {"city": "City", "category": "Main product", "enquiries_90d": "Buyer enquiries in the last 90 days",
             "catalogue_score": "Catalogue quality score out of 100", "product_count": "Products listed"}
    return "; ".join(f"{names.get(x['slot'], x['slot'])}: {x['value']}" for x in slots) or "None on file."


def variables(spec) -> tuple[str, dict]:
    variant = SPEAKER_TO_VARIANT.get(_v(spec, "voice", "speaker"), "clear_hinglish")
    s = spec["seller_snapshot"]
    cat = str(s.get("top_category_1") or "their products")
    city = str(s.get("seller_city") or "their area")
    hook = _v(spec, "conversation_plan", "opening_hook")
    switch_opt = LANG_NAME.get(_v(spec, "language", "switch_option"), "English")
    return variant, {
        "agent_name": VARIANTS[variant]["agent_name"],
        "seller_id": str(spec["seller_id"]),
        "seller_city": city,
        "seller_category": cat,
        "call_reason": HOOK_TEXT[hook].format(cat=cat, city=city),
        "opening_style": _v(spec, "conversation_plan", "opening_style"),
        "attempt_number": str(int(s.get("bot_attempts") or 0) + 1),
        "persona_label": spec["persona_label"],
        "language_style": language_style(spec),
        "tone_profile": tone_profile(spec),
        "max_words_per_turn": str(_v(spec, "tone", "max_words_per_turn")),
        "personal_details": personal_details(spec),
        "seller_history": seller_history(spec),
        "objection_priorities": objection_priorities(spec),
        "adaptation_sensitivity": sensitivity(spec),
        "regional_language": switch_opt,
        "best_callback_window": _v(spec, "conversation_plan", "best_call_window"),
    }


INPUT_VARIABLE_DOCS = {
    "agent_name": "Name the agent introduces itself with (matches the variant's voice gender)",
    "seller_id": "IndiaMART seller GLID, for records only",
    "seller_city": "Seller's city from the seller file",
    "seller_category": "Seller's top product category",
    "call_reason": "True reason for the call, from the lead bucket; never changed by the persona",
    "opening_style": "Persona opening style: standard, short_acknowledging, ultra_short, disclosure_first, "
                     "exec_follow_up or compliance_only",
    "attempt_number": "Which bot call attempt this is for the seller",
    "persona_label": "Human-readable persona name from the generator",
    "language_style": "Language mix, formality and address form for this seller",
    "tone_profile": "Warmth, empathy and assertiveness for this seller",
    "max_words_per_turn": "Turn length cap for this seller",
    "personal_details": "Seller-file details the agent may mention",
    "seller_history": "Earlier calls and audited mishandled turns for this seller",
    "objection_priorities": "Objection playbook ordered by this seller's own history",
    "adaptation_sensitivity": "How readily each live switch fires for this seller",
    "regional_language": "Regional language the user may switch to",
    "best_callback_window": "Callback window that converts best",
}


def iter_specs():
    with gzip.open(config.OUT_DIR / "persona_specs.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seller-id", type=int)
    ap.add_argument("--cohort")
    ap.add_argument("--ids")
    a = ap.parse_args()
    if a.seller_id:
        p = config.OUT_DIR / "personas" / f"{a.seller_id}.json"
        spec = json.loads(p.read_text(encoding="utf-8")) if p.exists() else next(
            s for s in iter_specs() if s["seller_id"] == a.seller_id)
        variant, vars_ = variables(spec)
        print(json.dumps({"variant": variant, "agent": VARIANTS[variant]["name"], "variables": vars_},
                         ensure_ascii=False, indent=1))
        return
    if a.cohort:
        ids = set(map(int, a.ids.split(","))) if a.ids else None
        out = Path(a.cohort)
        out.parent.mkdir(parents=True, exist_ok=True)
        files = {}
        for spec in iter_specs():
            if ids and spec["seller_id"] not in ids:
                continue
            variant, vars_ = variables(spec)
            if variant not in files:
                fh = open(out.with_name(f"{out.stem}_{variant}.csv"), "w", newline="", encoding="utf-8")
                w = csv.DictWriter(fh, fieldnames=["phone_number", "initial_language", *vars_.keys()])
                w.writeheader()
                files[variant] = (fh, w)
            # phone numbers are not in the dataset; IndiaMART fills them before upload
            files[variant][1].writerow({"phone_number": "", "initial_language":
                                        VARIANTS[variant]["initial_language"], **vars_})
        for fh, _ in files.values():
            fh.close()
        print("cohort files:", ", ".join(str(out.with_name(f"{out.stem}_{k}.csv")) for k in files))


if __name__ == "__main__":
    main()
