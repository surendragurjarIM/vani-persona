"""SQLite store for pushes (seller -> campaign/call) and call results from Sarvam webhooks."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from service import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS pushes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, phone TEXT, variant TEXT, app_id TEXT,
  app_version INTEGER, campaign_id TEXT, attempt_id TEXT, kind TEXT, persona_label TEXT, pushed_at TEXT);
CREATE TABLE IF NOT EXISTS call_results (
  attempt_id TEXT PRIMARY KEY, seller_id INTEGER, app_id TEXT, app_version INTEGER, campaign_id TEXT,
  interaction_id TEXT, connectivity TEXT, completion TEXT, duration REAL, call_outcome TEXT, meeting_slot TEXT,
  signals_detected TEXT, switch_summary TEXT, user_language TEXT, persona_label TEXT, transcript TEXT,
  raw TEXT, received_at TEXT);
CREATE INDEX IF NOT EXISTS ix_results_seller ON call_results(seller_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def record_push(**row):
    with db() as con:
        con.execute("INSERT INTO pushes (seller_id, phone, variant, app_id, app_version, campaign_id, attempt_id, "
                    "kind, persona_label, pushed_at) VALUES (:seller_id, :phone, :variant, :app_id, :app_version, "
                    ":campaign_id, :attempt_id, :kind, :persona_label, :pushed_at)",
                    {"campaign_id": None, "attempt_id": None, "pushed_at": now(), **row})


def record_result(payload: dict) -> dict:
    """Store one Sarvam call-end webhook (campaign or instant outbound payload)."""
    iv = payload.get("initial_agent_variables") or {}
    fv = payload.get("final_agent_variables") or {}
    ov = payload.get("output_agent_variables") or {}
    merged = {**iv, **fv, **ov}
    sid = merged.get("seller_id") or payload.get("user_identifier")
    row = {
        "attempt_id": payload.get("attempt_id"), "seller_id": int(sid) if str(sid or "").isdigit() else None,
        "app_id": payload.get("app_id"), "app_version": payload.get("app_version"),
        "campaign_id": payload.get("campaign_id"), "interaction_id": payload.get("interaction_id"),
        "connectivity": payload.get("connectivity_status"), "completion": payload.get("completion_status"),
        "duration": payload.get("duration"), "call_outcome": merged.get("call_outcome"),
        "meeting_slot": merged.get("meeting_slot"), "signals_detected": merged.get("signals_detected"),
        "switch_summary": merged.get("switch_summary"), "user_language": merged.get("user_language"),
        "persona_label": merged.get("persona_label"),
        "transcript": json.dumps(payload.get("interaction_transcript") or [], ensure_ascii=False),
        "raw": json.dumps(payload, ensure_ascii=False), "received_at": now(),
    }
    with db() as con:
        con.execute("INSERT OR REPLACE INTO call_results VALUES (:attempt_id, :seller_id, :app_id, :app_version, "
                    ":campaign_id, :interaction_id, :connectivity, :completion, :duration, :call_outcome, "
                    ":meeting_slot, :signals_detected, :switch_summary, :user_language, :persona_label, "
                    ":transcript, :raw, :received_at)", row)
    return row


def summary() -> dict:
    with db() as con:
        rows = con.execute(
            "SELECT p.variant AS variant, COUNT(r.attempt_id) AS calls, "
            "SUM(r.connectivity = 'connected') AS connected, SUM(r.call_outcome = 'meeting_fixed') AS meetings, "
            "SUM(r.call_outcome = 'callback_scheduled') AS callbacks, "
            "SUM(r.switch_summary IS NOT NULL AND r.switch_summary != '') AS calls_with_switches, "
            "AVG(r.duration) AS avg_duration FROM call_results r "
            "LEFT JOIN (SELECT DISTINCT app_id, variant FROM pushes) p ON p.app_id = r.app_id GROUP BY p.variant"
        ).fetchall()
        pushed = con.execute("SELECT variant, COUNT(*) n FROM pushes GROUP BY variant").fetchall()
    return {"by_variant": [dict(r) for r in rows], "pushed": {r["variant"]: r["n"] for r in pushed}}
