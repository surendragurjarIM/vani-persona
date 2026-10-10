"""Persona generator: seller features -> PersonaSpec (dict), with a reason, evidence and confidence per setting.

Pipeline per seller
  1. defaults (low confidence; marked as defaults so live adaptation can correct them)
  2. rules R-01..R-23 in order (persona/rules.py), each citing evidence ids
  3. voice resolver: language + gender + style + register -> one Bulbul speaker
  4. opening line rendered from templates + the seller's own data (no invented facts)
  5. manual overrides from manual/ (highest priority, reviewer-approved)
"""
import copy
import json
import math

import config
from persona import rules as R
from persona.facts import COMPLIANCE, FACTS
from persona.playbook import load_library
from persona.voices import LANG_NAMES, REGIONAL, VOICES

GENERATOR_VERSION = "2026-10-09"
BASE_THRESHOLDS = {"frustration": 0.6, "rush": 0.6, "unavailable": 0.6, "confusion": 0.5, "interest": 0.6,
                   "not_interested": 0.6, "language_switch": 0.7}
BASE_GUARDRAILS = [
    "Change delivery only: facts, prices and compliance lines come verbatim from the fact sheet (persona/facts.py).",
    f"Price, if asked: {FACTS['price_line_hi']} (quote once, then bridge to the free meeting).",
    COMPLIANCE["no_false_confirmation"] + " (EV-34: some 'fixed' meetings were actually rejected)",
    "Never repeat the same pitch sentence twice; rephrase or move on (EV-36: 44% of mishandled turns).",
    "If asked whether this is a bot, say yes: IndiaMART's AI assistant.",
    "Do-not-call request -> acknowledge, stop, end the call.",
]
BASE_ESCALATION = [
    {"when": "seller shows interest (price, how it works, gives a time)",
     "do": "Move to a concrete slot at once: offer 2 options, then confirm day + time + place (EV-28)."},
    {"when": "seller gives a time", "do": "Accept it immediately and confirm once; never re-ask (EV-36, 601 gaps)."},
    {"when": "frustration detected twice", "do": "Apologise, offer a callback at a time they choose, end politely "
     "(EV-35)."},
    {"when": "seller says do not call", "do": COMPLIANCE["dnc_ack_hi"]},
    {"when": "wrong person / not the decision-maker", "do": "Ask for the right person's name and a good time; "
     "do not pitch."},
]
EV_BASE = {"voice.pace": ["EV-00"], "voice.gender": ["EV-G1"]}


def _clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if hasattr(v, "tolist"):
        return _clean(v.tolist())
    return v


class Builder:
    def __init__(self, f: dict):
        self.f = f
        self.s: dict[str, dict] = {}
        self.fired: list[str] = []
        self.thresholds = dict(BASE_THRESHOLDS)
        self.thr_why: dict[str, list] = {}
        self.escalation = copy.deepcopy(BASE_ESCALATION)
        self.guardrails = list(BASE_GUARDRAILS)
        self.dnc = False
        self.missing: list[str] = []

    # settings
    def set(self, path, value, reason, evidence, confidence, rule):
        self.s[path] = {"value": _clean(value), "reason": reason, "evidence": list(evidence),
                        "confidence": confidence, "source": f"rule:{rule}" if rule.startswith("R-") else rule}
        if rule.startswith("R-") and rule not in self.fired:
            self.fired.append(rule)

    def get(self, path):
        return self.s[path]["value"]

    # live thresholds
    def thr(self, signal, value, why, evidence, rule):
        if value < self.thresholds[signal]:
            self.thresholds[signal] = value
            self.thr_why.setdefault(signal, []).append(f"{rule}: {why} ({', '.join(evidence)})")
            if rule not in self.fired:
                self.fired.append(rule)

    def thr_get(self, signal):
        return self.thresholds[signal]

    def add_escalation(self, item, rule, evidence):
        item = dict(item, rule=rule, evidence=evidence)
        if item not in self.escalation:
            self.escalation.insert(0, item)

    def add_guardrail(self, text, rule):
        self.guardrails.append(f"{text} [{rule}]")


def defaults(b: Builder):
    f = b.f
    miss = []
    if not R._ok(f.get("annual_turnover")):
        miss.append("annual_turnover")
    if not f.get("eng_known"):
        miss.append("engagement history (eng_*)")
    if R.num(f, "bot_answered") < 1:
        miss.append("no answered bot call yet")
    if not R._ok(f.get("top_category_1")):
        miss.append("top_category_1")
    if not R._ok(f.get("nature_of_business")):
        miss.append("nature_of_business")
    b.missing = miss
    d = "Default (no seller-specific signal). Live adaptation will correct it on the call."
    b.set("voice.gender", "female", "Default: female voice, the only voice VANI has used, with the observed "
          f"baseline {100 * R.EVIDENCE()['EV-00']['rate']:.1f}% meeting-fix (EV-00). Gender cannot be compared "
          "from data (EV-G1).", ["EV-00", "EV-G1"], "low", "default")
    b.set("voice.pace", 1.0, ("Turnover unknown: default pace. " if "annual_turnover" in miss else "") + d,
          ["EV-00"], "low", "default")
    b.set("voice.style", "sales", d, [], "low", "default")
    b.set("language.primary", "hi-IN", "Default Hinglish: VANI's current language, used across the Hindi belt "
          "where most sellers are.", ["EV-23"], "medium", "default")
    b.set("language.english_share", 25, "Typical Hinglish mix for the seller base (sellers speak ~14% English "
          "words on average, EV-23); business terms stay in English.", ["EV-23"], "low", "default")
    b.set("language.formality", "medium", d, [], "low", "default")
    b.set("language.address_form", "aap + ji", d, [], "low", "default")
    b.set("language.switch_option", "en-IN", "Switch to English if the seller does.", ["EV-23b"], "low", "default")
    b.set("tone.warmth", 3, d, [], "low", "default")
    b.set("tone.empathy", 3, d, [], "low", "default")
    b.set("tone.assertiveness", 3, d, [], "low", "default")
    b.set("tone.max_words_per_turn", 32, "Default: one or two short sentences per turn.", [], "low", "default")
    b.set("conversation_plan.opening_style", "standard", d, [], "low", "default")
    b.set("conversation_plan.personalisation", [], "No usable personal details in the seller file.", [], "low",
          "default")
    b.set("conversation_plan.best_call_window", "09:00-11:00 or 17:00-20:00 (avoid 11:00-13:00)",
          f"Late-morning calls fix far fewer meetings ({R.stat('EV-10')}).", ["EV-10"], "high", "default")


# --------------------------------------------------------------------------- voice

def resolve_voice(b: Builder):
    lang, gender = b.get("language.primary"), b.get("voice.gender")
    style, emp, form = b.get("voice.style"), b.get("tone.empathy"), b.get("language.formality")
    if lang in REGIONAL:
        vid, why = REGIONAL[lang][gender], f"native {LANG_NAMES[lang]} {gender} voice"
    elif lang == "en-IN":
        if gender == "male":
            vid, why = "shubh_enhi_banking", "formal Indian-English male voice"
        elif b.get("language.english_share") >= 70:
            vid, why = "neha_en_customer", "neutral Indian-English female voice"
        else:
            vid, why = "simran_enhi_customer", "Indian-English female voice that handles Hindi words naturally"
    elif gender == "male":
        vid, why = (("shubh_hi_customer", "calm, deep Hindi male voice for an empathetic call") if emp >= 5
                    else ("aditya_hi_sales", "measured Hinglish male sales voice"))
    elif emp >= 5 or style in ("customer-warm", "conversational"):
        vid, why = "ritu_hi_customer_warm", "soft, warm Hinglish female voice"
    elif form == "low":
        vid, why = "simran_hi_sales", "bright, friendly Hinglish female voice for an informal trader call"
    else:
        vid, why = "ritu_hi_sales", "clear Hinglish female sales voice"
    v = VOICES[vid]
    drivers = f"language={lang}, gender={gender}, empathy={emp}, formality={form}, style={style}"
    ev = sorted({e for p in ("language.primary", "voice.gender", "tone.empathy", "language.formality")
                 for e in b.s[p]["evidence"]})
    conf = min((b.s[p]["confidence"] for p in ("language.primary", "voice.gender")),
               key=lambda c: {"high": 3, "medium": 2, "low": 1}[c])
    b.set("voice.speaker", vid, f"{why} ({drivers}).", ev, conf, "voice-resolver")
    b.set("voice.accent", v.accent, f"Comes with speaker {vid}.", ev, conf, "voice-resolver")
    b.set("voice.pitch", f"{v.register} register (via speaker choice)",
          "Bulbul v3/v4 has no pitch control; pitch is set by choosing a speaker with this natural register "
          f"({'deeper, calmer' if v.register == 'deep' else 'brighter, more energetic' if v.register == 'bright' else 'neutral'}).",
          ev, conf, "voice-resolver")
    b.set("voice.tts_model", v.model, "Model that serves this speaker.", [], "high", "voice-resolver")


# --------------------------------------------------------------------------- opening line

HOOK = {
    "hi": {"paid_services": "aap IndiaMART ki paid services dekh rahe the",
           "buylead": "aap IndiaMART par {cat} ke buy leads check kar rahe the",
           "category_demand": "{city} mein {cat} ke buyers ki enquiries aa rahi hain",
           "catalogue_improvement": "aapka {cat} catalogue thoda behtar ho jaye to zyada buyers tak pahunchega",
           "callback_with_reason": "aapne aaj baat karne ko kaha tha, {cat} ki buyer enquiries ke baare mein"},
    "en": {"paid_services": "you were looking at IndiaMART's paid services",
           "buylead": "you were checking buy leads for {cat} on IndiaMART",
           "category_demand": "buyers in {city} are sending enquiries for {cat}",
           "catalogue_improvement": "a stronger {cat} catalogue would reach more buyers",
           "callback_with_reason": "you asked us to call back today about buyer enquiries for {cat}"},
}
TEMPLATE = {
    "hi": {
        "standard": "Namaste{addr}, main {agent} IndiaMART se bol {verb} hoon. Maine dekha ki {hook}. Isliye hamare "
                    "sales executive aapse 15-20 minute ki ek free meeting karna chahte hain. Kal kaunsa time theek "
                    "rahega?",
        "short_acknowledging": "Namaste{addr}, {agent}, IndiaMART se. Pehle bhi call kiya tha, isliye seedha point "
                               "par: {hook}. Kal 15 minute ki free meeting rakh dein, subah 10 baje ya shaam 5 baje?",
        "ultra_short": "{agent}, IndiaMART se{addr}. Bas ek minute: {hook}. Kal 15 minute ki free meeting, subah ya "
                       "shaam?",
        "disclosure_first": "Namaste{addr}, main {agent}, IndiaMART ki AI assistant. {Hook}, isliye hamare executive "
                            "aapse 15 minute milna chahte hain. Kal kaunsa time theek rahega?",
        "exec_follow_up": "Namaste{addr}, main {agent} IndiaMART se. Aapki hamare executive se pehle baat hui thi; "
                          "unke saath ek chhoti follow-up meeting rakh dein? Kal subah ya shaam?",
    },
    "en": {
        "standard": "Hello{addr}, this is {agent} from IndiaMART. I noticed {hook}, so our sales executive would "
                    "like a free 15 to 20 minute meeting with you. What time tomorrow suits you?",
        "short_acknowledging": "Hello{addr}, {agent} from IndiaMART. We've called before, so I'll be brief: {hook}. "
                               "Could we fix a free 15-minute meeting tomorrow, 10 am or 5 pm?",
        "ultra_short": "{agent} from IndiaMART{addr}, just one minute: {hook}. A free 15-minute meeting tomorrow, "
                       "morning or evening?",
        "disclosure_first": "Hello{addr}, I'm {agent}, IndiaMART's AI assistant. {Hook}, so our executive would like "
                            "to meet you for 15 minutes. What time tomorrow suits you?",
        "exec_follow_up": "Hello{addr}, {agent} from IndiaMART. You've spoken with our executive before; shall I "
                          "set up a short follow-up meeting with them tomorrow, morning or evening?",
    },
}


def render_opening(b: Builder):
    f = b.f
    style = b.get("conversation_plan.opening_style")
    if style == "compliance_only":
        b.set("conversation_plan.opening_line", COMPLIANCE["dnc_ack_hi"], "Do-not-call: compliance line only.",
              ["COMPLIANCE"], "high", "renderer")
        return
    fam = "en" if b.get("language.primary") == "en-IN" else "hi"
    gender = b.get("voice.gender")
    hook_key = b.get("conversation_plan.opening_hook")
    cat = str(f.get("top_category_1") or ("your products" if fam == "en" else "aapke products")).strip()
    city = str(f.get("seller_city") or ("your area" if fam == "en" else "aapke area")).strip()
    hook = HOOK[fam][hook_key].format(cat=cat, city=city)
    formal = b.get("language.formality") == "high"
    addr = (" sir" if formal else "") if fam == "en" else (" sir" if formal else " ji")
    line = TEMPLATE[fam][style].format(addr=addr, agent=FACTS["agent_name"][gender],
                                       verb="rahi" if gender == "female" else "raha", hook=hook,
                                       Hook=hook[0].upper() + hook[1:])
    if b.get("tone.empathy") >= 5 and style in ("standard", "short_acknowledging"):
        line = ("Maaf kijiye, sirf ek minute " + ("lungi" if gender == "female" else "lunga") + ". "
                if fam == "hi" else "Sorry to disturb you, just one minute. ") + line
    b.set("conversation_plan.opening_line", line,
          f"Template '{style}' + hook '{hook_key}' + seller's city/category. Facts only from the fact sheet and the "
          "seller file. Live LLM may paraphrase but not change facts.",
          b.s["conversation_plan.opening_hook"]["evidence"] + b.s["conversation_plan.opening_style"]["evidence"],
          b.s["conversation_plan.opening_style"]["confidence"], "renderer")


# --------------------------------------------------------------------------- label + overrides + assembly

def persona_label(b: Builder) -> str:
    f = b.f
    if b.dnc:
        return "Do-not-call: compliance only"
    pace = b.get("voice.pace")
    pace_w = "Calm" if pace <= 0.9 else "Brisk" if pace > 1.0 else "Steady"
    tone_w = ("empathetic" if b.get("tone.empathy") >= 5 else "formal" if b.get("language.formality") == "high"
              else "friendly" if b.get("language.formality") == "low" else "clear")
    lang = b.get("language.primary")
    lang_w = ("Hinglish" if b.get("language.english_share") >= 20 else "Hindi") if lang == "hi-IN" \
        else LANG_NAMES.get(lang, lang)
    seg = []
    if b.get("conversation_plan.opening_style") in ("short_acknowledging", "ultra_short"):
        seg.append("repeat-called" if "R-02" in b.fired else "short-call")
    seg.append({"micro": "micro", "small": "small", "large": "large"}.get(f.get("turnover_band"), ""))
    seg.append(f.get("biz_kind") if f.get("biz_kind") != "other" else "seller")
    return f"{pace_w}, {tone_w} {lang_w} · {' '.join(x for x in seg if x)}"


def load_manual_overrides() -> list[dict]:
    p = config.OUT_DIR / "manual_overrides.json"
    return json.loads(p.read_text(encoding="utf-8")).get("overrides", []) if p.exists() else []


def _matches(scope: str, f: dict) -> bool:
    if scope == "all":
        return True
    if scope.startswith("seller:"):
        return str(f.get("fk_glusr_usr_id")) == scope.split(":", 1)[1].strip()
    if scope.startswith("segment:"):
        for cond in scope.split(":", 1)[1].split("&"):
            k, _, v = cond.partition("=")
            if str(f.get(k.strip())) != v.strip():
                return False
        return True
    return False


def apply_manual(b: Builder, overrides: list[dict]) -> list[str]:
    applied = []
    for o in sorted(overrides, key=lambda o: o.get("priority", 3)):  # higher priority applied last -> wins
        if not _matches(o["applies_to"], b.f):
            continue
        path = o["setting"]
        if path.startswith("live_adaptation.thresholds."):
            sig = path.rsplit(".", 1)[1]
            b.thresholds[sig] = float(o["value"])
            b.thr_why.setdefault(sig, []).append(f"MANUAL {o['id']}: {o['reason']}")
        elif path == "conversation_plan.guardrails":
            b.guardrails.insert(0, f"{o['value']} [MANUAL {o['id']}]")
        elif path == "conversation_plan.escalation_rules":
            b.escalation.insert(0, {"when": o.get("when", "see manual gap"), "do": o["value"], "rule": o["id"],
                                    "evidence": [o["id"]]})
        else:
            b.set(path, o["value"], f"Manual review {o['id']} by {o.get('reviewer', '?')}: {o['reason']}",
                  [o["id"]] + o.get("evidence", []), "high", f"manual:{o.get('reviewer', '?')}")
        applied.append(o["id"])
    return applied


SNAPSHOT_FIELDS = ["seller_city", "seller_state", "business_type", "annual_turnover", "nature_of_business",
                   "top_category_1", "num_categories", "gst_registration_year", "bot_attempts", "bot_answered",
                   "calls_meeting_fixed", "calls_not_interested", "calls_call_later", "avg_answered_call_sec",
                   "last_bucket", "eng_enq_received_90d", "eng_cqs", "own_en_share", "n_transcribed_calls",
                   "n_gaps", "past_objections", "past_dispositions_detailed", "already_in_touch_with_executive",
                   "do_not_call_requested", "turnover_band", "biz_kind", "region"]


def generate(f: dict, library: dict | None = None, overrides: list[dict] | None = None) -> dict:
    library = library or load_library()
    overrides = load_manual_overrides() if overrides is None else overrides
    f = {k: (list(v) if getattr(v, "ndim", 0) == 1 else v) for k, v in f.items()}  # parquet arrays -> lists
    b = Builder(f)
    defaults(b)
    for rid, _title, fn in R.RULES:
        fn(f, b)
    if b.dnc:  # compliance beats every other rule: re-assert after all rules ran
        R.r13_dnc(f, b)
    R.r23_objection_playbook(f, b, library)
    if "R-23" not in b.fired and b.s["conversation_plan.objection_playbook"]["confidence"] == "high":
        b.fired.append("R-23")
    resolve_voice(b)
    manual = apply_manual(b, overrides)
    if any(o["setting"].startswith(("voice.gender", "language.primary", "tone.empathy")) for o in overrides
           if o["id"] in manual):
        resolve_voice(b)
    render_opening(b)

    if b.dnc:
        b.escalation = [{"when": "always", "do": COMPLIANCE["dnc_ack_hi"], "rule": "R-13",
                         "evidence": ["COMPLIANCE"]}]
    b.set("conversation_plan.escalation_rules", b.escalation, "Base rules + seller-specific rules; each item cites "
          "its rule/evidence.", ["EV-28", "EV-35", "EV-36"], "high", "assembler")
    b.set("conversation_plan.guardrails", b.guardrails, "Personas change delivery, never facts, prices or "
          "compliance.", ["EV-34", "EV-36", "COMPLIANCE"], "high", "assembler")
    lad = {
        "thresholds": {"value": dict(b.thresholds), "reason": "Score (0-1) a signal must reach to trigger a switch. "
                       "Base values tuned on 2,986 audited turns (out/signals_eval.json). Seller-specific: "
                       + ("; ".join(f"{k}: {' | '.join(v)}" for k, v in b.thr_why.items()) or "none"),
                       "evidence": ["signals_eval"], "confidence": "medium",
                       "source": "rules" if b.thr_why else "default"},
        "priority": {"value": ["frustration", "not_interested", "rush", "unavailable", "confusion", "language_switch",
                               "interest"], "reason": "Protect the relationship first (frustration hangs up calls, "
                     "EV-35), then time, then understanding, then opportunity.", "evidence": ["EV-35", "EV-24.rush"],
                     "confidence": "medium", "source": "default"},
        "cooldown_turns": {"value": 2, "reason": "At most one switch per signal every 2 seller turns, to avoid "
                           "flapping.", "evidence": [], "confidence": "medium", "source": "default"},
        "language_switch_confirm_utterances": {
            "value": 2, "reason": "Saaras mislabels the language of 1-2 word replies on phone audio (smoke test: "
            "'achha' tagged mr-IN); switch only after 2 consecutive utterances of 3+ words.",
            "evidence": ["smoke_test"], "confidence": "high", "source": "default"},
        "known_history": b.s.get("live_adaptation.known_history",
                                 {"value": None, "reason": "No audited calls for this seller.", "evidence": [],
                                  "confidence": "low", "source": "default"}),
    }
    sec = lambda prefix: {k.split(".", 1)[1]: v for k, v in b.s.items() if k.startswith(prefix + ".")}  # noqa: E731
    voice = sec("voice")
    confs = [v["confidence"] for k, v in b.s.items() if not k.startswith("live_adaptation")]
    score = sum({"high": 1, "medium": 0.6, "low": 0.2}[c] for c in confs) / len(confs)
    return {
        "seller_id": int(f["fk_glusr_usr_id"]),
        "persona_label": persona_label(b),
        "seller_snapshot": {k: _clean(f.get(k)) for k in SNAPSHOT_FIELDS},
        "voice": {k: voice[k] for k in ("speaker", "gender", "accent", "pitch", "pace", "style", "tts_model")},
        "language": sec("language"),
        "tone": sec("tone"),
        "conversation_plan": {k: v for k, v in sec("conversation_plan").items()},
        "live_adaptation": lad,
        "rules_fired": b.fired,
        "manual_overrides": manual,
        "missing_fields": b.missing,
        "overall_confidence": "high" if score >= 0.65 else "medium" if score >= 0.45 else "low",
        "generator_version": GENERATOR_VERSION,
    }
