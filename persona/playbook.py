"""Objection playbook library, built from the audited evaluator data.

Each situation (busy, not interested, price, already in touch, ...) gets:
  approach      - what VANI should do (delivery only, facts from the fact sheet)
  example_lines - what VANI *should* have said, taken from the evaluator's `suggested_kb_entry` on real calls where
                  the bot mishandled exactly this situation (seller_questions "gaps")
  failure_seen  - what VANI actually did wrong in those calls (most common gap type)
  evidence      - evidence ids + count of audited gaps behind it
Manual gaps (manual/) are merged in with priority by persona.generator.

    python -m persona.playbook   -> out/playbook_library.json
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from data.loader import load  # noqa: E402

SITUATIONS = {
    "busy_no_time": {
        "match": r"\bbusy\b|no time|not have time|time nahi|samay nahi|driving|gaadi chala|in a meeting|occupied",
        "approach": "Acknowledge in one line, do not repeat the pitch, offer two concrete slots (not 11am-1pm).",
        "evidence": ["EV-25b", "EV-36", "EV-24.rush"]},
    "out_of_station": {
        "match": r"out of station|out of town|\bbahar\b|not available|travell?ing|next week|agle hafte|agle week",
        "approach": "Accept, propose a specific day after their return, or an online meeting.",
        "evidence": ["EV-28b", "EV-24.unavailable"]},
    "seller_gives_time": {
        "match": r"\d+ ?baje|\bbaje\b|monday|tuesday|wednesday|thursday|friday|saturday|sunday|somvar|mangal|budh|"
                 r"guruvar|shukra|shani|ravivar|evening|morning|afternoon|subah|shaam|dopahar|parson|o.?clock",
        "approach": "Accept the seller's time at once, confirm day + time + place in one sentence; never re-ask.",
        "evidence": ["EV-28", "EV-36"]},
    "not_interested": {
        "match": r"not interested|no requirement|no need|nahi chahiye|nahin chahiye|zaroorat nahi|zarurat nahi|"
                 r"interest nahi|nahi karna",
        "approach": "One empathetic line + one value reason tied to their data; if refused again, close politely.",
        "evidence": ["EV-04", "EV-17b", "EV-24.not_interested"]},
    "price_question": {
        "match": r"\bprice|\bcost|charge|kitne ka|kitna (?:hai|lag|pad)|\bfees?\b|monthly|paise",
        "approach": "Quote the fact-sheet price exactly once, then bridge to the free meeting for details.",
        "evidence": ["EV-31", "EV-28"]},
    "already_in_touch": {
        "match": r"already (?:met|spoken|talked|in touch|has|have|using)|pehle (?:se|hi) (?:baat|meeting|le)|"
                 r"meeting ho (?:chuki|gayi|gaya)|executive (?:aaye|aa chuke|aaya tha)|baat ho chuki",
        "approach": "Acknowledge the existing contact; offer a follow-up with the same executive instead of a new pitch.",
        "evidence": ["EV-15"]},
    "who_are_you_or_bot": {
        "match": r"\bkaun\b|who is (?:this|calling|speaking)|asks? who|caller.s identity|\bbot\b|robot|"
                 r"are you (?:an )?ai|\bai ho\b|computer|recording|kya naam",
        "approach": "Answer plainly (name, IndiaMART, AI assistant if asked), then the one-line reason for the call.",
        "evidence": ["EV-31"]},
    "bad_past_experience": {
        "match": r"no result|no (?:enquir|inquir|leads)|koi (?:inquiry|enquiry|lead) nahi|faltu|waste|not useful|"
                 r"bad experience|fayda nahi|complain",
        "approach": "Validate the complaint, do not argue; offer the meeting as a review of what went wrong.",
        "evidence": ["EV-30", "EV-36"]},
    "send_details": {
        "match": r"whatsapp|send (?:the )?details|bhej (?:do|dijiye|dena)|details bhej|e-?mail",
        "approach": "Agree to send details AND ask for a 15-minute slot; details alone rarely convert.",
        "evidence": ["EV-28"]},
}
PRIORITY = ["who_are_you_or_bot", "price_question", "already_in_touch", "bad_past_experience", "not_interested",
            "out_of_station", "busy_no_time", "send_details", "seller_gives_time"]


def build() -> dict:
    q = load("eval_seller_questions")
    g = q[(q.category == "gap") & q.suggested_reply.notna()].copy()
    # match on the seller's own words + the evaluator's description of the seller turn (not the gap reason,
    # which talks about the bot); each gap goes to exactly one situation, in PRIORITY order
    text = (g.que_dialogue.fillna("") + " " + g.seller_context.fillna("")).str.lower()
    g["situation"] = None
    for name in PRIORITY:
        free = g.situation.isna() & text.str.contains(SITUATIONS[name]["match"], regex=True)
        g.loc[free, "situation"] = name
    lib = {}
    for name, cfg in SITUATIONS.items():
        m = g[g.situation == name]
        words = m.suggested_reply.str.split().str.len()
        good = m[(words >= 12) & (words <= 45) & ~m.suggested_reply.str.contains(r"\d{2},?\d{3}", regex=True)]
        # prefer replies that move to a concrete next step
        good = good.assign(slot=good.suggested_reply.str.contains(
            r"tomorrow|time|slot|kal|when|day|meeting", case=False, regex=True))
        picks = good.sort_values(["slot"], ascending=False).drop_duplicates("suggested_reply").head(40)
        picks = picks.sample(min(3, len(picks)), random_state=3) if len(picks) else picks
        lib[name] = {
            "approach": cfg["approach"],
            "example_lines": picks.suggested_reply.tolist(),
            "seller_examples": picks.que_dialogue.tolist(),
            "failure_seen": (m.gap_type.fillna("").str.split("; ").explode().value_counts().head(1).index.tolist()
                             or [""])[0],
            "n_audited_gaps": int(len(m)),
            "evidence": cfg["evidence"] + ["EV-36"],
            "source": "evaluator seller_questions.gaps (suggested_kb_entry)",
        }
    return lib


def load_library() -> dict:
    p = config.OUT_DIR / "playbook_library.json"
    if not p.exists():
        p.write_text(json.dumps(build(), ensure_ascii=False, indent=1), encoding="utf-8")
    return json.loads(p.read_text(encoding="utf-8"))


def objection_key(category: str) -> str | None:
    """Map evaluator objection categories (seller file `past_objections`) to playbook situations."""
    c = category.lower()
    if "unavailab" in c or "scheduling" in c:
        return "busy_no_time"
    if "callback" in c or "deferred" in c or "not ready" in c:
        return "out_of_station"
    if "disinterest" in c or "refusal" in c or "mismatch" in c:
        return "not_interested"
    if "existing engagement" in c or "past experience" in c:
        return "already_in_touch"
    if "trust" in c or "privacy" in c:
        return "who_are_you_or_bot"
    if "handling" in c or "executive gaps" in c:
        return "bad_past_experience"
    return None


if __name__ == "__main__":
    lib = build()
    (config.OUT_DIR / "playbook_library.json").write_text(json.dumps(lib, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    for k, v in lib.items():
        print(f"\n## {k}  (audited gaps: {v['n_audited_gaps']}, typical failure: {v['failure_seen']})")
        for s, e in zip(v["seller_examples"], v["example_lines"]):
            print(f"   seller: {str(s)[:90]}\n   should: {e[:200]}")
