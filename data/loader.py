"""Load the PS07 CSVs once, stack the part files, flatten evaluator JSON, and cache everything as parquet.

    python -m data.loader            # build every cache table
    from data.loader import load     # load("sellers"), load("eval_objections"), ...
"""
import glob
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

config.CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _stack(pattern: str, **kw) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(pattern)
    return pd.concat([pd.read_csv(f, low_memory=False, **kw) for f in files], ignore_index=True)


def _js(s):
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return {}


# ---------- raw tables ----------

def _sellers() -> pd.DataFrame:
    return _stack(str(config.DATASET_1 / "ps07_seller_files_part*.csv")).drop_duplicates("fk_glusr_usr_id")


def _bot_calls() -> pd.DataFrame:
    df = _stack(str(config.DATASET_2 / "ps07_bot_calls_*.csv")).drop_duplicates("attempt_id")
    df["call_start_time"] = pd.to_datetime(df.call_start_time, errors="coerce")
    df["hour"] = df.call_start_time.dt.hour
    df["weekday"] = df.call_start_time.dt.dayofweek
    return df


def _turns() -> pd.DataFrame:
    df = pd.read_csv(config.DATASET_1 / "ps07_call_turns.csv", dtype={"text": str})
    df["text"] = df.text.fillna("")
    return df.sort_values(["attempt_id", "turn_no"]).reset_index(drop=True)


def _exec_calls() -> pd.DataFrame:
    df = pd.read_csv(config.DATASET_1 / "ps07_executive_calls.csv")
    df["call_start_time"] = pd.to_datetime(df.call_start_time, errors="coerce")
    return df


def _recording_sample() -> pd.DataFrame:
    return pd.read_csv(config.DATASET_1 / "ps07_recording_sample_5000.csv")


def _evaluators_raw() -> pd.DataFrame:
    return _stack(str(config.DATASET_3 / "ps07_evaluator_outputs_*.csv"))


# ---------- evaluator flatteners (one row per call, or per item for lists) ----------

def _flat_disposition(ev):
    rows = []
    for a, g, j in ev:
        rows.append({"attempt_id": a, "fk_glusr_usr_id": g, "disposition": j.get("disposition"),
                     "sub_disposition": j.get("sub_disposition"), "confidence": j.get("confidence"),
                     "followup_when": j.get("followup_when"), "reason": j.get("reason")})
    return pd.DataFrame(rows)


def _flat_objections(ev):
    rows = []
    for a, g, j in ev:
        for i, o in enumerate(j.get("objection_analysis") or []):
            rows.append({"attempt_id": a, "fk_glusr_usr_id": g, "obj_idx": i, "category": o.get("category"),
                         "reasons": " | ".join(o.get("reasons") or []),
                         "quotes": " | ".join(o.get("evidence_quotes") or []),
                         "meeting_fixed_eval": j.get("meeting_fixed")})
    return pd.DataFrame(rows)


def _flat_seller_questions(ev):
    rows = []
    for a, g, j in ev:
        for i, q in enumerate(j.get("questions") or []):
            cats = q.get("category") or []
            cats = cats if isinstance(cats, list) else [cats]
            for c in cats:
                rows.append({"attempt_id": a, "fk_glusr_usr_id": g, "q_idx": i, "category": c,
                             "que_dialogue": q.get("que_dialogue"), "ans_dialogue": q.get("ans_dialogue")})
        for i, q in enumerate(j.get("gaps") or []):  # newer schema: turns where the bot failed the seller
            if isinstance(q, dict):
                gt = q.get("gap_type") or []
                rows.append({"attempt_id": a, "fk_glusr_usr_id": g, "q_idx": 100 + i, "category": "gap",
                             "seller_turn_type": q.get("seller_turn_type"),
                             "gap_type": "; ".join(gt) if isinstance(gt, list) else gt,
                             "que_dialogue": q.get("seller_turn_dialogue"),
                             "ans_dialogue": q.get("bot_response_dialogue"), "gap_reason": q.get("reason"),
                             "suggested_reply": q.get("suggested_kb_entry"),
                             "seller_context": q.get("seller_turn_context")})
    return pd.DataFrame(rows)


def _flat_simple(keys):
    def f(ev):
        return pd.DataFrame([{"attempt_id": a, "fk_glusr_usr_id": g, **{k: j.get(k) for k in keys}}
                             for a, g, j in ev])
    return f


def _flat_latency(ev):
    rows = []
    for a, g, j in ev:
        lat, rep = j.get("latency") or {}, j.get("repetition") or {}
        rows.append({"attempt_id": a, "fk_glusr_usr_id": g, "n_turns": j.get("n_turns"),
                     "is_loopy": j.get("is_loopy"), "lat_p50": lat.get("p50_sec"), "lat_p95": lat.get("p95_sec"),
                     "lat_max": lat.get("max_sec"), "overlap_count": lat.get("overlap_count"),
                     "seller_had_to_repeat": lat.get("seller_had_to_repeat_count"),
                     "bot_repeat_count": (rep.get("bot") or {}).get("repeat_count"),
                     "seller_repeat_count": (rep.get("seller") or {}).get("repeat_count"),
                     "bot_back_to_back": (rep.get("bot_back_to_back") or {}).get("count")})
    return pd.DataFrame(rows)


def _flat_topics(ev):
    rows = []
    for a, g, j in ev:
        for t in j.get("discussion_timeline") or []:
            rows.append({"attempt_id": a, "fk_glusr_usr_id": g, "seq": t.get("sequence_number"),
                         "topic_id": t.get("topic_id"), "subtopic": t.get("subtopic")})
    return pd.DataFrame(rows)


EVAL_FLATTENERS = {
    "disposition": _flat_disposition,
    "objections": _flat_objections,
    "seller_questions": _flat_seller_questions,
    "incorrect_mf": _flat_simple(["incorrect_mf", "seller_final_stance"]),
    "execdrop": _flat_simple(["who_ended_call", "seller_tried_after_closure", "explanation"]),
    "se_contact": _flat_simple(["category", "seller_exact_quote"]),
    "ivr": _flat_simple(["category", "severity"]),
    "location_confirmation": _flat_simple(["location_outcome", "call_outcome", "lead_city"]),
    "latency_repetition": _flat_latency,
    "topics": _flat_topics,
}

TABLES = {
    "sellers": _sellers,
    "bot_calls": _bot_calls,
    "turns": _turns,
    "exec_calls": _exec_calls,
    "recording_sample": _recording_sample,
}


def _build_evaluators():
    raw = _evaluators_raw()
    print(f"evaluator rows: {len(raw):,}")
    for agent, fn in EVAL_FLATTENERS.items():
        sub = raw[raw.eval_agent == agent]
        ev = [(a, g, _js(s)) for a, g, s in zip(sub.attempt_id, sub.fk_glusr_usr_id, sub.agent_output)]
        df = fn(ev)
        df.to_parquet(config.CACHE_DIR / f"eval_{agent}.parquet", index=False)
        print(f"  eval_{agent:24s} {len(sub):>7,} calls -> {len(df):>7,} rows")


def load(name: str) -> pd.DataFrame:
    p = config.CACHE_DIR / f"{name}.parquet"
    if not p.exists():
        if name.startswith("eval_"):
            _build_evaluators()
        else:
            TABLES[name]().to_parquet(p, index=False)
    return pd.read_parquet(p)


def build_all():
    for name, fn in TABLES.items():
        df = fn()
        df.to_parquet(config.CACHE_DIR / f"{name}.parquet", index=False)
        print(f"{name:18s} {len(df):>9,} rows")
    _build_evaluators()


if __name__ == "__main__":
    build_all()
