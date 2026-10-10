"""Persona rules. Each rule reads seller features, sets persona settings, and cites evidence ids from
out/evidence.json. Reasons quote the seller's own data and the evidence numbers, so a reviewer can see why.

Order matters: later rules refine earlier ones. Manual overrides (manual/) are applied after all rules.
Rule ids are stable (R-xx) and appear in every spec's `rules_fired` and each setting's `source`.
"""
import json
import math
from functools import lru_cache

import config
from persona.facts import COMPLIANCE
from persona.playbook import objection_key

# --------------------------------------------------------------------------- evidence helpers

@lru_cache(maxsize=1)
def EVIDENCE() -> dict:
    recs = json.loads((config.OUT_DIR / "evidence.json").read_text(encoding="utf-8"))["records"]
    return {r["id"]: r for r in recs}


def stat(eid: str) -> str:
    r = EVIDENCE().get(eid)
    if not r:
        return f"[{eid} missing]"
    if "rate_a" in r:
        return (f"{r['choice_a']} {100 * r['rate_a']:.1f}% vs {r['choice_b']} {100 * r['rate_b']:.1f}% "
                f"meeting-fix, {r['strength']}, {eid}")
    return f"{r['strength']}, {eid}"


def conf_from(*eids: str, cap: str = "high") -> str:
    order = {"high": 3, "medium": 2, "low": 1}
    best = "low"
    for e in eids:
        s = EVIDENCE().get(e, {}).get("strength")
        c = {"strong": "high", "moderate": "medium"}.get(s, "low")
        if order[c] > order[best]:
            best = c
    return best if order[best] <= order[cap] else cap


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def num(f, k, default=0.0) -> float:
    v = f.get(k)
    return float(v) if _ok(v) else default


# --------------------------------------------------------------------------- rules
# each rule: (id, title, fn(f, b) -> bool fired). `b.set(path, value, reason, evidence, confidence, rule)`

def r01_true_reason(f, b):
    reason, bucket = f["true_reason"], f.get("last_bucket")
    if reason == "paid_services":
        b.set("conversation_plan.opening_hook", "paid_services",
              f"Lead bucket {bucket}: the seller explored IndiaMART paid services. Naming the seller's own action "
              f"beats generic framing in this bucket ({stat('EV-20b.PIM.paid_services')}).",
              ["EV-20b.PIM.paid_services", "EV-20.paid_services"], conf_from("EV-20b.PIM.paid_services"), "R-01")
    elif reason == "buylead":
        b.set("conversation_plan.opening_hook", "buylead",
              f"Lead bucket {bucket}: the seller was checking buy leads. Naming that action beats generic framing "
              f"({stat('EV-20b.PUA.buylead')}).", ["EV-20b.PUA.buylead", "EV-20.buylead"],
              conf_from("EV-20b.PUA.buylead"), "R-01")
    elif reason == "callback":
        b.set("conversation_plan.opening_hook", "callback_with_reason",
              "Scheduled callback. 'We spoke earlier' openings convert worse than stating the concrete reason "
              f"({stat('EV-20b.PUA.last_met')}), so the callback names the reason in the first sentence.",
              ["EV-20b.PUA.last_met", "EV-20b.PIM.last_met"], "medium", "R-01")
    else:
        cqs, enq = f.get("eng_cqs"), f.get("eng_enq_received_90d")
        if _ok(cqs) and cqs < 15:
            b.set("conversation_plan.opening_hook", "catalogue_improvement",
                  f"No explicit lead action (bucket {bucket}); catalogue quality score is {cqs:.0f}/100 (below the "
                  f"median 15), and low-CQS sellers convert better ({stat('EV-12')}). Framings within this bucket "
                  f"are statistically tied (EV-20b.UA.*), so this is a data-led but low-confidence choice.",
                  ["EV-12", "EV-20b.UA.catalogue"], "low", "R-01")
        else:
            extra = f" ({enq:.0f} enquiries in the last 90 days)" if _ok(enq) and enq >= 1 else ""
            b.set("conversation_plan.opening_hook", "category_demand",
                  f"No explicit lead action (bucket {bucket}); lead with buyer demand in their category{extra}. "
                  f"Within this bucket framings are tied ({stat('EV-20b.UA.enquiry_count')}).",
                  ["EV-20b.UA.enquiry_count"], "low", "R-01")
    return True


def r02_repeat_called(f, b):
    n = int(f["next_attempt"])
    if n < 4:
        return False
    b.set("conversation_plan.opening_style", "short_acknowledging",
          f"This will be bot attempt #{n}. Meeting-fix collapses on repeat attempts ({stat('EV-02')}); open by "
          f"acknowledging earlier calls and get to the ask within ~8 seconds.", ["EV-02", "EV-32"], "high", "R-02")
    b.set("tone.max_words_per_turn", 20, f"Attempt #{n}: keep every turn short ({stat('EV-02')}).",
          ["EV-02"], "high", "R-02")
    return True


def r03_short_call_history(f, b):
    sc, ans = int(num(f, "short_calls")), int(num(f, "bot_answered"))
    avg = num(f, "avg_answered_call_sec", 99)
    if not (sc >= 2 or (ans >= 2 and avg < 15)):
        return False
    b.set("conversation_plan.opening_style", "ultra_short",
          f"{sc} of this seller's past calls ended under 15 s (avg answered call {avg:.0f} s). Sellers who cut "
          f"calls short rarely convert on a full pitch ({stat('EV-05')}); one-line reason + direct slot ask.",
          ["EV-05", "EV-32"], "high", "R-03")
    b.set("tone.max_words_per_turn", 16, "Past calls were cut short: one idea per turn, <=16 words.",
          ["EV-05"], "high", "R-03")
    b.thr("rush", 0.45, "Short-call history: react to the first sign of hurry.", ["EV-05", "EV-25b"], "R-03")
    return True


def r04_pace_by_size(f, b):
    tb = f.get("turnover_band")
    if tb == "micro":
        b.set("voice.pace", 0.9, f"Turnover 0-40L: a slower pitch converts better for micro sellers "
              f"({stat('EV-22p.micro')}).", ["EV-22p.micro", "EV-22p"], conf_from("EV-22p.micro"), "R-04")
    elif tb == "small":
        b.set("voice.pace", 0.9, f"Turnover 40L-1.5Cr: slower pitch helps small sellers ({stat('EV-22p.small')}).",
              ["EV-22p.small", "EV-22p"], conf_from("EV-22p.small"), "R-04")
    elif tb == "large":
        b.set("voice.pace", 1.0, f"Turnover 1.5Cr+: slowing down showed no benefit for large sellers "
              f"({stat('EV-22p.large')}); keep a normal, business-like pace.", ["EV-22p.large"], "low", "R-04")
    else:
        return False
    return True


def r05_pace_by_kind(f, b):
    k = f.get("biz_kind")
    if k in ("manufacturer", "wholesaler") and f.get("turnover_band") != "large":
        e = f"EV-22p.{k}"
        b.set("voice.pace", 0.85, f"{k.title()}: slower delivery converts better ({stat(e)}).", [e, "EV-22p"],
              conf_from(e), "R-05")
        return True
    return False


def r06_large_business(f, b):
    if f.get("turnover_band") != "large":
        return False
    b.set("language.formality", "high", f"Turnover {f.get('annual_turnover')}: the generic informal pitch "
          f"underperforms with larger businesses ({stat('EV-06')}).", ["EV-06"], "medium", "R-06")
    b.set("language.address_form", "aap + sir/madam, no slang", "Large business owner: respectful, formal address.",
          ["EV-06", "EV-07"], "medium", "R-06")
    b.set("language.english_share", 45, "Large businesses use more English business vocabulary; mixed "
          "Hinglish with ~45% English terms.", ["EV-23"], "low", "R-06")
    b.set("tone.assertiveness", 2, "Consultative, not pushy, with senior decision-makers.", ["EV-06"], "low", "R-06")
    b.set("voice.gender", "male", "Informed guess: a measured male voice for formal large-company calls. Every "
          "past call used one female voice, so this cannot be backed by data yet (EV-G1); flagged for A/B.",
          ["EV-G1"], "low", "R-06")
    b.set("tone.max_words_per_turn", min(b.get("tone.max_words_per_turn"), 30),
          "Senior owners: crisp, value-first turns.", ["EV-06"], "low", "R-06")
    return True


def r07_formal_entity(f, b):
    if not f.get("formal_entity") or f.get("turnover_band") == "large":
        return False
    b.set("language.formality", "high", f"{f.get('business_type')}: companies/partnerships respond worse to the "
          f"default informal pitch ({stat('EV-07')}).", ["EV-07"], "medium", "R-07")
    b.set("language.address_form", "aap + sir/madam", "Registered company: formal address.", ["EV-07"], "medium",
          "R-07")
    b.set("language.english_share", 40, "Company-run business: more English business terms.", ["EV-07"], "low",
          "R-07")
    return True


def r08_micro_trader(f, b):
    if f.get("turnover_band") != "micro" or f.get("formal_entity"):
        return False
    b.set("language.formality", "low", "Proprietor, turnover 0-40L: the current informal style already converts "
          f"best here ({stat('EV-06')}); keep it friendly and simple.", ["EV-06"], "medium", "R-08")
    b.set("language.address_form", "aap + ji", "Small proprietor: warm, everyday address ('ji').", ["EV-06"],
          "medium", "R-08")
    b.set("language.english_share", 15, "Everyday Hindi with only common business words in English.",
          ["EV-23"], "low", "R-08")
    b.set("tone.warmth", 4, "Friendly shopkeeper-to-shopkeeper warmth.", ["EV-06"], "low", "R-08")
    return True


REGION_LANG = {
    "south_ta": ("en-IN", 70, "ta-IN", "Tamil Nadu"), "south_te": ("en-IN", 60, "te-IN", "Telangana/AP"),
    "south_kn": ("en-IN", 60, "kn-IN", "Karnataka"), "south_ml": ("en-IN", 60, None, "Kerala"),
    "west_gu": ("hi-IN", None, "gu-IN", "Gujarat"), "east_bn": ("hi-IN", None, "bn-IN", "West Bengal"),
    "west_mh": ("hi-IN", None, "mr-IN", "Maharashtra"), "north_pa": ("hi-IN", None, "pa-IN", "Punjab"),
}


def r09_region_language(f, b):
    reg = f.get("region")
    if reg not in REGION_LANG:
        b.set("language.switch_option", "en-IN", "Hindi belt: Hinglish start; switch to English only if the "
              "seller does.", ["EV-23"], "medium", "R-09")
        return False
    primary, en_share, switch, name = REGION_LANG[reg]
    if primary == "en-IN":
        b.set("language.primary", "en-IN", f"{name}: sellers there used the most English on past calls "
              f"(EV-23 table) while VANI spoke Hindi; Hindi-only VANI in {name}: {stat('EV-08a')}. Start in "
              f"English, offer the regional language on a switch.", ["EV-23", "EV-08a", "EV-G2"], "medium", "R-09")
        b.set("language.english_share", en_share, f"{name}: English-led delivery.", ["EV-23"], "medium", "R-09")
    if switch:
        b.set("language.switch_option", switch, f"{name}: VANI switches to {switch} only after the seller speaks "
              f"it for 2 consecutive utterances (regional language is an informed guess, EV-G2; Hindi works "
              f"there today, e.g. {stat('EV-08c') if reg == 'west_gu' else stat('EV-08b')}).",
              ["EV-G2", "EV-08c" if reg == "west_gu" else "EV-08b"], "low", "R-09")
    return True


def r10_own_language(f, b):
    en = f.get("own_en_share")
    if not _ok(en):
        return False
    n = int(num(f, "n_transcribed_calls"))
    if en >= 0.35:
        b.set("language.primary", "en-IN", f"On {n} transcribed call(s) this seller spoke {en:.0%} English words: "
              f"start in English. English-leaning sellers convert worse on a Hindi-heavy bot "
              f"({stat('EV-23b')}).", ["EV-23b", "EV-23"], "high", "R-10")
        b.set("language.english_share", 75, f"Seller's own speech is {en:.0%} English.", ["EV-23b"], "high", "R-10")
    elif en <= 0.08:
        b.set("language.english_share", 10, f"On {n} transcribed call(s) this seller spoke almost only Hindi "
              f"({en:.0%} English): use plain Hindi words.", ["EV-23"], "high", "R-10")
        b.set("language.primary", "hi-IN", "Seller speaks Hindi on calls.", ["EV-23"], "high", "R-10")
    else:
        b.set("language.english_share", int(round(en * 100 + 10)), f"Mirror the seller's own mix ({en:.0%} English "
              f"on {n} call(s)).", ["EV-23"], "high", "R-10")
    return True


def r11_prior_refusal(f, b):
    ni = num(f, "calls_not_interested")
    objs = " ".join(f.get("obj_list") or []) + " " + str(f.get("audited_objections") or "")
    explicit = "Disinterest" in objs
    if ni < 1 and not explicit:
        return False
    strong = ni >= 2 or explicit
    what = f"said 'not interested' on {int(ni)} earlier call(s)" + (" and raised an explicit refusal objection"
                                                                   if explicit else "")
    b.set("tone.empathy", 5 if strong else 4, f"Seller {what}. A prior refusal halves the odds ({stat('EV-04')}); "
          "lead with respect, not pressure." + ("" if strong else " One refusal only: moderate empathy."),
          ["EV-04", "EV-17b"] if explicit else ["EV-04"], "high", "R-11")
    b.set("tone.assertiveness", 2, "Low pressure after a past refusal.", ["EV-04"], "high", "R-11")
    b.set("tone.warmth", 5 if strong else 4, "Warm, sorry-to-disturb tone.", ["EV-04"], "medium", "R-11")
    if strong:
        b.set("voice.style", "customer-warm", "Softer, warmer voice style for a seller who refused more than once.",
              ["EV-04", "EV-17b"], "medium", "R-11")
        b.thr("frustration", 0.45, "Repeated refusal: switch to empathy at the first sign of irritation.",
              ["EV-04", "EV-35"], "R-11")
    return True


def r12_frustration_history(f, b):
    hits = [k for k, v in [("showed frustration on a past call (seller file)", f.get("showed_frustration")),
                           ("frustration in their transcribed words", f.get("hist_sig_frustration")),
                           ("audited gap about frustration", f.get("gap_frustration"))] if _ok(v) and v >= 1]
    if not hits:
        return False
    b.set("voice.pace", min(b.get("voice.pace"), 0.85), "Frustration history: calmer, slower delivery "
          "(slower pitch converts better overall, EV-22p).", ["EV-22p", "EV-35"], "medium", "R-12")
    b.set("tone.empathy", 5, "Seller " + "; ".join(hits) + f". Frustrated sellers hang up far more often "
          f"({stat('EV-35')}).", ["EV-35", "EV-24.frustration"], "medium", "R-12")
    b.thr("frustration", 0.4, "Frustration history: lowest threshold.", ["EV-35"], "R-12")
    return True


def r13_dnc(f, b):
    if not (num(f, "do_not_call_requested") >= 1 or f.get("last_disposition") == "do_not_call"):
        return False
    b.set("conversation_plan.opening_style", "compliance_only",
          "Seller asked not to be called. No pitch: confirm opt-out and end politely.", ["COMPLIANCE"], "high", "R-13")
    b.set("conversation_plan.escalation_rules",
          [{"when": "always", "do": COMPLIANCE["dnc_ack_hi"]}], "Do-not-call request on record.", ["COMPLIANCE"],
          "high", "R-13")
    b.dnc = True
    return True


def r14_asked_bot(f, b):
    if num(f, "asked_if_talking_to_bot") < 1 and "AI Bot" not in " ".join(f.get("q_list") or []):
        return False
    b.set("conversation_plan.opening_style", "disclosure_first",
          "Seller previously asked whether they were talking to a bot. Disclose up front that VANI is IndiaMART's "
          f"AI assistant (compliance + trust). Outcome data for these sellers is thin ({stat('EV-14')}).",
          ["EV-14", "COMPLIANCE"], "medium", "R-14")
    b.thr("confusion", 0.45, "Seller has questioned the caller's identity before.", ["EV-31"], "R-14")
    return True


def r15_exec_contact(f, b):
    ex = num(f, "exec_answered_calls")
    touch = num(f, "already_in_touch_with_executive") >= 1 or _ok(f.get("exec_contact"))
    if not (touch or ex >= 2):
        return False
    why = []
    if touch:
        why.append("already in touch with / met an IndiaMART executive")
    if ex >= 2:
        why.append(f"{int(ex)} answered executive calls in Aug-Sep")
    b.set("conversation_plan.opening_style", "exec_follow_up",
          f"Seller {', '.join(why)}. A fresh sales pitch to them converts worse ({stat('EV-15')}); position the "
          "meeting as a follow-up with their executive.", ["EV-15"], "high", "R-15")
    b.add_escalation({"when": "seller says they already spoke to / met an executive",
                      "do": "Offer a follow-up slot with that same executive; do not restart the pitch."},
                     "R-15", ["EV-15"])
    return True


def r16_new_seller(f, b):
    if f.get("eng_known") or num(f, "business_age", 99) > 1:
        return False
    b.set("tone.warmth", 5, f"New business (GST {int(num(f, 'gst_registration_year'))}) with no engagement history; "
          f"such sellers are the most receptive group ({stat('EV-13')}).", ["EV-13"], "high", "R-16")
    b.set("tone.max_words_per_turn", 38, "New seller: allow one extra sentence explaining what the meeting gives.",
          ["EV-13"], "medium", "R-16")
    return True


def r17_service_business(f, b):
    if f.get("biz_kind") != "service":
        return False
    b.set("tone.warmth", max(b.get("tone.warmth"), 4), f"Service provider: services convert above average "
          f"({stat('EV-16d')}); conversational, relationship tone.", ["EV-16d"], "medium", "R-17")
    b.set("voice.style", "conversational", "Service businesses: conversational rather than sales voice.",
          ["EV-16d"], "low", "R-17")
    return True


def r18_wholesaler(f, b):
    if f.get("biz_kind") != "wholesaler":
        return False
    b.set("tone.assertiveness", 4, f"Wholesalers convert below average ({stat('EV-16c')}); be direct about "
          "volume (buy leads / enquiries) rather than profile cosmetics.", ["EV-16c"], "low", "R-18")
    return True


def r19_personalise(f, b):
    slots = []
    city, cat = f.get("seller_city"), f.get("top_category_1")
    if _ok(city):
        slots.append({"slot": "city", "value": city, "why": "local relevance"})
    if _ok(cat):
        slots.append({"slot": "category", "value": cat, "why": "their top product category"})
    enq = f.get("eng_enq_received_90d")
    if _ok(enq) and enq >= 3:
        slots.append({"slot": "enquiries_90d", "value": int(enq), "why": f"they received {int(enq)} buyer "
                      f"enquiries in 90 days (EV-11: high-enquiry sellers are busy, so mention it briefly)"})
    cqs = f.get("eng_cqs")
    if _ok(cqs) and cqs < 15:
        slots.append({"slot": "catalogue_score", "value": int(cqs), "why": f"catalogue score {int(cqs)}/100: "
                      f"concrete improvement reason ({stat('EV-12')})"})
    pc = f.get("eng_product_count")
    if _ok(pc) and pc > 0:
        slots.append({"slot": "product_count", "value": int(pc), "why": "number of listed products"})
    if not slots:
        return False
    b.set("conversation_plan.personalisation", slots, "Personal details taken from the seller file; no new facts "
          "are invented.", ["EV-11", "EV-12"], "medium", "R-19")
    return True


def r20_busy_high_volume(f, b):
    enq = f.get("eng_enq_received_90d")
    if not (_ok(enq) and enq >= 10):
        return False
    b.set("tone.max_words_per_turn", min(b.get("tone.max_words_per_turn"), 24),
          f"{int(enq)} enquiries in 90 days: an active, busy seller; high-enquiry sellers convert less on long "
          f"pitches ({stat('EV-11')}).", ["EV-11"], "medium", "R-20")
    b.thr("rush", min(b.thr_get("rush"), 0.5), "Busy, high-volume seller.", ["EV-11"], "R-20")
    return True


def r21_callback_history(f, b):
    cl = num(f, "calls_call_later")
    disp = f.get("disp_list") or []
    if cl < 2 and "callback_requested" not in disp:
        return False
    b.add_escalation({"when": "seller is busy or unavailable",
                      "do": "Propose one specific later slot (avoid 11:00-13:00) and confirm it; never just "
                            "'call later'."}, "R-21", ["EV-28b", "EV-10", "EV-03"])
    b.thr("unavailable", 0.45, f"Seller asked for a callback {int(cl)} time(s) before ({stat('EV-03')}).",
          ["EV-03"], "R-21")
    return True


def r22_audited_history(f, b):
    n = f.get("n_gaps")
    if not (_ok(n) and n >= 1):
        return False
    hist = {"audited_gaps": int(n), "example": {
        "call": int(f["gap_call"]) if _ok(f.get("gap_call")) else None,
        "seller_said": f.get("gap_seller_said"), "vani_said": f.get("gap_bot_said"),
        "should_have_said": f.get("gap_should_say")}}
    themes = [k for k in ("rush", "confusion", "frustration", "ignored_or_repeated", "price", "time_offered")
              if num(f, f"gap_{k}") >= 1]
    hist["themes"] = themes
    b.set("live_adaptation.known_history", hist,
          f"The audited evaluator flagged {int(n)} turn(s) VANI mishandled with this seller "
          f"({', '.join(themes) or 'general'}). Calls with a mishandled turn convert worse ({stat('EV-37')}).",
          ["EV-36", "EV-37"], "high", "R-22")
    if "rush" in themes:
        b.thr("rush", 0.4, "VANI ignored this seller's 'busy' before.", ["EV-36"], "R-22")
    if "confusion" in themes:
        b.thr("confusion", 0.4, "This seller was confused by VANI before.", ["EV-36"], "R-22")
    if "frustration" in themes:
        b.thr("frustration", 0.4, "This seller got frustrated with VANI before.", ["EV-36"], "R-22")
    if "ignored_or_repeated" in themes:
        b.add_guardrail("Never repeat the pitch to this seller: the audit shows VANI did that before.", "R-22")
    return True


def r23_objection_playbook(f, b, library):
    seller_objs = [objection_key(c) for c in (f.get("obj_list") or [])]
    seller_objs += [objection_key(c) for c in str(f.get("audited_objections") or "").split("; ") if c]
    if "Pricing Payment" in (f.get("q_list") or []) or num(f, "gap_price") >= 1:
        seller_objs.append("price_question")
    if num(f, "gap_time_offered") >= 1:
        seller_objs.append("seller_gives_time")
    own = [k for k in dict.fromkeys(seller_objs) if k]
    default = ["busy_no_time", "seller_gives_time", "price_question", "not_interested", "out_of_station",
               "who_are_you_or_bot", "already_in_touch", "send_details", "bad_past_experience"]
    order = own + [k for k in default if k not in own]
    pb = [{"situation": k, "approach": library[k]["approach"],
           "example_line": (library[k]["example_lines"] or [""])[0], "evidence": library[k]["evidence"],
           "from_seller_history": k in own} for k in order if k in library]
    quote = f.get("objection_quote")
    reason = ("Ordered by this seller's own past objections first (" + ", ".join(own) + ")" if own else
              "Default order by how often each situation is mishandled today (EV-36)")
    if _ok(quote):
        reason += f'; their own words on a past call: "{str(quote)[:120]}"'
    b.set("conversation_plan.objection_playbook", pb, reason + ". Example lines are the evaluator's suggested "
          "replies from real mishandled calls.", ["EV-30", "EV-36"], "high" if own else "medium", "R-23")
    return bool(own)


RULES = [
    ("R-01", "True call reason sets the opening hook", r01_true_reason),
    ("R-02", "Repeat-called seller: short, acknowledging opening", r02_repeat_called),
    ("R-03", "Short-call history: ultra-short opening", r03_short_call_history),
    ("R-04", "Pace by business size", r04_pace_by_size),
    ("R-05", "Pace for manufacturers / wholesalers", r05_pace_by_kind),
    ("R-06", "Large business: formal, consultative", r06_large_business),
    ("R-07", "Registered company: formal address", r07_formal_entity),
    ("R-08", "Micro proprietor: friendly, simple Hindi", r08_micro_trader),
    ("R-09", "Region sets start language and switch option", r09_region_language),
    ("R-10", "Seller's own spoken language (transcripts)", r10_own_language),
    ("R-11", "Past refusal: empathy, low pressure", r11_prior_refusal),
    ("R-12", "Frustration history: calmer, lower threshold", r12_frustration_history),
    ("R-13", "Do-not-call: compliance only", r13_dnc),
    ("R-14", "Asked if bot: disclose first", r14_asked_bot),
    ("R-15", "Already in touch with executive: follow-up framing", r15_exec_contact),
    ("R-16", "New business: warm, explanatory", r16_new_seller),
    ("R-17", "Service business: conversational", r17_service_business),
    ("R-18", "Wholesaler: direct, volume-led", r18_wholesaler),
    ("R-19", "Personalisation slots from seller data", r19_personalise),
    ("R-20", "High-enquiry seller: brief", r20_busy_high_volume),
    ("R-21", "Callback history: always propose a slot", r21_callback_history),
    ("R-22", "Audited history of this seller's calls", r22_audited_history),
]
