"""Close the loop: finished calls that need a human look go to manual/inbox/review_queue.csv.

Reviewers listen to the call (Sarvam Call Logs, interaction_id), fill the persona_setting / recommended_value
columns where the persona or a switch was wrong, and move the row into manual_gaps.csv. The next ingest
(python -m manual.ingest) then outranks automatic evidence for that seller, segment or everyone.
"""
import csv

from service import settings

COLUMNS = ["gap_id", "call_id", "interaction_id", "fk_glusr_usr_id", "persona_label", "call_outcome", "signal",
           "seller_said", "vani_said", "should_have_said", "tone_heard", "persona_setting", "recommended_value",
           "applies_to", "priority", "reviewer", "date", "notes"]

SIGNAL_WORDS = ["frustration", "rush", "confusion", "interest", "language", "unavailable", "not interested"]


def needs_review(row: dict) -> str | None:
    """Return why a call should be reviewed, or None."""
    outcome, sig, sw = row.get("call_outcome"), row.get("signals_detected") or "", row.get("switch_summary") or ""
    if row.get("connectivity") != "connected":
        return None
    if outcome == "do_not_call":
        return "do-not-call: confirm the persona did not provoke it"
    if "frustration" in sig.lower() and outcome != "meeting_fixed":
        return "frustration and no meeting: check the switch timing"
    if "not match" in sw.lower() or "did not" in sw.lower():
        return "switch judged not to match the user's need"
    if sig and not sw:
        return "signals seen but no persona switch logged"
    return None


def queue_for_review(row: dict) -> bool:
    why = needs_review(row)
    if not why:
        return False
    settings.REVIEW_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    new = not settings.REVIEW_QUEUE.exists()
    sig = next((w for w in SIGNAL_WORDS if w in (row.get("signals_detected") or "").lower()), "other")
    with open(settings.REVIEW_QUEUE, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow({"gap_id": f"RQ-{row['attempt_id']}", "call_id": row["attempt_id"],
                    "interaction_id": row.get("interaction_id"), "fk_glusr_usr_id": row.get("seller_id"),
                    "persona_label": row.get("persona_label"), "call_outcome": row.get("call_outcome"),
                    "signal": sig.replace("not interested", "not_interested"), "priority": 3,
                    "applies_to": f"seller:{row.get('seller_id')}" if row.get("seller_id") else "all",
                    "notes": why})
    return True
