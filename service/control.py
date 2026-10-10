"""Control room: one page that shows every part of the Persona Service and lets you run it.

Served at / (and /control). Read-only views of the data, evidence, detector, personas, routing, call results and
manual feed, plus buttons that run the batch jobs in the background with a live log.

GET  /api/control/overview            pipeline steps with their output files, settings, headline numbers
GET  /api/control/data                cached tables (rows, columns, size); /data/{name} previews the first rows
GET  /api/control/evidence            the evidence registry (145 records) with strength tags
GET  /api/control/signals             detector accuracy on audited turns (keywords, LLM, fused)
POST /api/control/detect              run the live switch tool on seller lines, turn by turn
GET  /api/control/routing             sellers per agent, do-not-call count, distinctness
GET  /api/control/jobs                job status; POST /api/control/jobs/{name} starts one
GET  /api/control/results             stored call results, pushes, review queue
POST /api/control/results/sample      store a sample call-end webhook to see the loop; DELETE removes samples
GET  /api/control/manual              manual feed: templates, inbox, active overrides; POST .../gaps saves a CSV
GET  /api/control/sarvam              Sarvam settings; ?check=true calls Sarvam to test the key
GET  /guide                           GUIDE.md (rendered by the page)
"""
import asyncio
import csv
import io
import json
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from service import feedback, settings, store
from service.engine import engine

router = APIRouter()
ROOT = settings.ROOT
OUT = ROOT / "out"
CACHE = ROOT / "data" / "cache"
MANUAL = ROOT / "manual"
JOB_LOGS = OUT / "jobs"
PAGE = Path(__file__).with_name("control") / "index.html"
GUIDE = Path(__file__).with_name("GUIDE.md")

# What each cached table is, in plain words (shown on the Data tab).
TABLES = {
    "sellers": "Seller master: one row per seller (city, category, turnover, engagement)",
    "bot_calls": "Every VANI bot call with its outcome",
    "turns": "Turn-by-turn transcripts of 12.8k calls",
    "exec_calls": "Calls by IndiaMART executives",
    "seller_features": "Per-seller features the persona generator reads (built from all tables)",
    "call_features": "Per-call features used by the evidence miner (opening, pace, signals)",
    "signal_events": "Seller turns where a signal was detected, and how VANI replied",
    "gap_turns_labelled": "Audited seller turns with the evaluator's label (detector ground truth)",
    "llm_tier_sample": "Turns scored by the LLM detector, used to choose keyword/LLM fusion",
    "recording_sample": "Sample of call recordings considered for tone analysis",
}

STEPS = [
    {"n": 1, "name": "Mine evidence", "job": "weekly-evidence", "when": "Weekly",
     "does": "Meeting-fix rate for each choice VANI can make, with 95% CI and a strength tag.",
     "outputs": ["out/evidence.json", "out/evidence_report.md"]},
    {"n": 2, "name": "Tune signal detector", "job": "weekly-evidence", "when": "Weekly, with step 1",
     "does": "Keyword list and LLM checked against audited seller turns; sets the fusion per signal.",
     "outputs": ["out/signals_eval.json", "out/switch_timing.json"]},
    {"n": 3, "name": "Generate personas", "job": "nightly", "when": "Nightly",
     "does": "23 evidence rules plus manual overrides give every seller a persona with reasons.",
     "outputs": ["data/cache/seller_features.parquet", "out/persona_specs.jsonl.gz", "out/distinctness.json"]},
    {"n": 4, "name": "Route and push", "job": "route-table", "when": "Nightly, then before each campaign",
     "does": "Picks one of six Sarvam agents per seller and the 17 variables it needs.",
     "outputs": ["out/routing.csv", "sarvam_agent/campaigns.json"]},
    {"n": 11, "name": "Store results", "job": None, "when": "After every call (webhook)",
     "does": "Sarvam posts each finished call; results are stored and problem calls queued for review.",
     "outputs": ["out/service.db", "manual/inbox/review_queue.csv"]},
    {"n": 12, "name": "Manual feed", "job": "manual-ingest", "when": "Any time",
     "does": "Your reviewed gaps and recordings become overrides that outrank the automatic rules.",
     "outputs": ["manual/inbox/manual_gaps.csv", "out/manual_overrides.json"]},
]

JOBS = {
    "nightly": ["-m", "service.jobs", "nightly"],
    "weekly-evidence": ["-m", "service.jobs", "weekly-evidence"],
    "route-table": ["-m", "service.jobs", "route-table"],
    "manual-ingest": ["-m", "manual.ingest"],
    "tests": ["-m", "pytest", "-q", "tests"],
}
JOB_NOTES = {
    "nightly": "Rebuilds seller features, applies the manual feed, regenerates all 149,363 personas and the "
               "routing table. Takes a few minutes and about 2 GB of memory.",
    "weekly-evidence": "Re-mines the evidence, re-scores the detector and replays switch timing on the audited calls. "
                       "Takes about 10 minutes.",
    "route-table": "Rewrites out/routing.csv from the current personas. Seconds.",
    "manual-ingest": "Validates manual/inbox/manual_gaps.csv into out/manual_overrides.json. Seconds.",
    "tests": "Runs the 26 automated tests. Seconds.",
}
_jobs: dict = {}
_lock = threading.Lock()


def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:  # e.g. VANI_DB pointing outside the project
        return str(p)


def _file_info(rel: str) -> dict:
    p = ROOT / rel
    if not p.exists():
        return {"path": rel, "exists": False}
    st = p.stat()
    return {"path": rel, "exists": True, "bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")}


def _json(rel: str):
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _clean(v):
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v][:12]
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


# ------------------------------------------------------------------ pages

@router.get("/", response_class=HTMLResponse)
@router.get("/control", response_class=HTMLResponse)
def page():
    return PAGE.read_text(encoding="utf-8")


@router.get("/guide", response_class=PlainTextResponse)
def guide():
    return GUIDE.read_text(encoding="utf-8")


# ------------------------------------------------------------------ overview

@router.get("/api/control/overview")
def overview():
    e = engine()
    ev = _json("out/evidence.json") or {}
    dist = _json("out/distinctness.json") or {}
    steps = []
    for s in STEPS:
        outs = [_file_info(o) for o in s["outputs"]]
        steps.append({**s, "outputs": outs, "ready": all(o["exists"] for o in outs[:1])})
    with store.db() as con:
        n_results = con.execute("SELECT COUNT(*) FROM call_results").fetchone()[0]
        n_pushes = con.execute("SELECT COUNT(*) FROM pushes").fetchone()[0]
    return {
        "numbers": {"sellers": int(len(e.features)), "evidence_records": len(ev.get("records", [])),
                    "baseline_meeting_fix": ev.get("baseline_mf"),
                    "distinct_personas": dist.get("distinct_persona_configurations"),
                    "manual_overrides": len(e.overrides), "agents": len(settings.AGENTS),
                    "call_results": n_results, "pushes": n_pushes},
        "steps": steps,
        "settings": {"sarvam_key_set": bool(settings.SARVAM_VA_API_KEY),
                     "telephony_set": bool(settings.SARVAM_CONNECTION_ID),
                     "public_url": settings.PUBLIC_BASE_URL or None,
                     "webhook_token_set": bool(settings.WEBHOOK_TOKEN),
                     "campaigns": settings.campaigns(), "db": _rel(settings.DB_PATH)},
        "agents": [{"variant": k, **v} for k, v in settings.AGENTS.items()],
    }


# ------------------------------------------------------------------ data

@router.get("/api/control/data")
def data():
    out = []
    for p in sorted(CACHE.glob("*.parquet")):
        md = pq.ParquetFile(p).metadata
        out.append({"name": p.stem, "rows": md.num_rows, "columns": md.num_columns, "bytes": p.stat().st_size,
                    "about": TABLES.get(p.stem, "Audited evaluator output" if p.stem.startswith("eval_") else "")})
    return out


@router.get("/api/control/data/{name}")
def data_preview(name: str, limit: int = 15):
    p = CACHE / f"{name}.parquet"
    if not p.exists() or p.parent != CACHE:
        raise HTTPException(404, "no such table")
    pf = pq.ParquetFile(p)
    batch = next(pf.iter_batches(batch_size=max(1, min(limit, 50))))
    rows = [{k: _clean(v) for k, v in r.items()} for r in batch.to_pylist()]
    return {"name": name, "columns": [f.name for f in pf.schema_arrow], "rows": rows}


# ------------------------------------------------------------------ evidence + detector

@router.get("/api/control/evidence")
def evidence():
    return _json("out/evidence.json") or {"records": []}


@router.get("/api/control/signals")
def signals():
    return {**(_json("out/signals_eval.json") or {}), "switch_timing": _json("out/switch_timing.json")}


@router.post("/api/control/detect")
def detect(body: dict = Body(...)):
    """Run the exact Sarvam switch tool locally. Lines may start with 'rush:' etc. to stand in for the LLM's guess."""
    from sarvam_conv_ai_sdk import EngagementMetadata, SarvamToolContext

    from sarvam_agent import update_persona_mode as tool

    attempt = str(body.get("attempt_number") or 1)
    ctx = SarvamToolContext(
        agent_variables={"attempt_number": attempt, "live_switch_log": ""},
        engagement_metadata=EngagementMetadata(interaction_id="control-room", app_id="local", app_version=0,
                                               interaction_language="Hindi"),
        language="Hindi", allowed_languages=["Hindi", "English", "Gujarati", "Tamil", "Bengali", "Marathi",
                                             "Telugu", "Kannada", "Malayalam", "Punjabi", "Odia"],
        state="start", next_valid_states=[])
    allowed = {"frustration", "rush", "confusion", "interest", "unavailable", "do_not_call", "language"}
    turns = []
    for i, raw in enumerate([ln.strip() for ln in body.get("lines", []) if ln.strip()][:30], start=1):
        guess, words = "none", raw
        head, sep, rest = raw.partition(":")
        if sep and head.strip().lower().replace(" ", "_") in allowed:
            guess, words = head.strip().lower().replace(" ", "_"), rest.strip()
        scores, hits = tool.keyword_scores(words)
        before = len((ctx.internal_variables.get("vani_persona_state") or {}).get("log", []))
        t = tool.UpdatePersonaMode(user_words=words, suspected_signal=guess, turn_number=i)
        out = asyncio.run(t.run(ctx))
        st = ctx.internal_variables["vani_persona_state"]
        turns.append({"turn": i, "words": words, "llm_guess": guess, "keyword_scores": scores, "keyword_hits": hits,
                      "switches": st["log"][before:], "mode": st["mode"], "language": str(ctx.language),
                      "message_to_agent": out.message_to_llm})
    return {"turns": turns, "priority": tool.PRIORITY, "keyword_alone": tool.KEYWORD_ALONE,
            "cooldown_turns": tool.COOLDOWN_TURNS}


# ------------------------------------------------------------------ routing

@router.get("/api/control/routing")
def routing():
    p = OUT / "routing.csv"
    counts, labels = Counter(), Counter()
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                counts["do_not_call" if r["do_not_call"] == "1" else r["variant"]] += 1
                labels[r["persona_label"]] += 1
    return {"by_agent": dict(counts.most_common()), "top_labels": labels.most_common(15),
            "distinctness": _json("out/distinctness.json"), "file": _file_info("out/routing.csv")}


# ------------------------------------------------------------------ jobs

def _run_job(name: str):
    JOB_LOGS.mkdir(parents=True, exist_ok=True)
    log = JOB_LOGS / f"{name}.log"
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(f"$ python {' '.join(JOBS[name])}\n")
        fh.flush()
        proc = subprocess.Popen([sys.executable, *JOBS[name]], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
                                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        with _lock:
            _jobs[name]["pid"] = proc.pid
        code = proc.wait()
    reloaded = False
    if code == 0 and name in ("nightly", "manual-ingest"):
        engine().reload()
        reloaded = True
    with _lock:
        _jobs[name].update(status="done" if code == 0 else "failed", exit_code=code, reloaded=reloaded,
                           finished=time.time())


@router.get("/api/control/jobs")
def jobs():
    out = {}
    for name in JOBS:
        j = dict(_jobs.get(name, {"status": "idle"}))
        log = JOB_LOGS / f"{name}.log"
        if log.exists():
            j["log_tail"] = log.read_text(encoding="utf-8", errors="replace")[-6000:]
        if j.get("started"):
            j["seconds"] = round((j.get("finished") or time.time()) - j["started"])
        out[name] = {**j, "note": JOB_NOTES[name], "command": "python " + " ".join(JOBS[name])}
    return out


@router.post("/api/control/jobs/{name}")
def start_job(name: str):
    if name not in JOBS:
        raise HTTPException(404, "unknown job")
    with _lock:
        if any(j.get("status") == "running" for j in _jobs.values()):
            raise HTTPException(409, "another job is still running")
        _jobs[name] = {"status": "running", "started": time.time()}
    threading.Thread(target=_run_job, args=(name,), daemon=True).start()
    return {"started": name}


# ------------------------------------------------------------------ results

@router.get("/api/control/results")
def results():
    with store.db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT attempt_id, seller_id, app_id, connectivity, duration, call_outcome, meeting_slot, "
            "signals_detected, switch_summary, user_language, persona_label, received_at, raw "
            "FROM call_results ORDER BY received_at DESC LIMIT 50")]
        pushes = [dict(r) for r in con.execute("SELECT * FROM pushes ORDER BY id DESC LIMIT 50")]
    for r in rows:
        raw = json.loads(r.pop("raw") or "{}")
        ov = {**(raw.get("final_agent_variables") or {}), **(raw.get("output_agent_variables") or {})}
        r["live_switch_log"] = ov.get("live_switch_log")
    queue = []
    if settings.REVIEW_QUEUE.exists():
        with open(settings.REVIEW_QUEUE, encoding="utf-8") as fh:
            queue = list(csv.DictReader(fh))[-50:]
    return {"summary": store.summary(), "results": rows, "pushes": pushes, "review_queue": queue,
            "webhook_url": (f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/sarvam?token=…"
                            if settings.PUBLIC_BASE_URL else None)}


SAMPLE = {
    "app_id": "VANI---Warm-26080196-acf0", "app_version": 3, "campaign_id": None, "completion_status": "completed",
    "connectivity_status": "connected", "user_identifier": "331550", "duration": 64.0, "retry_attempt": 0,
    "initial_agent_variables": {"seller_id": "331550", "persona_label": "Calm, friendly Hindi · repeat-called micro service"},
    "output_agent_variables": {
        "call_outcome": "callback_scheduled", "meeting_slot": "",
        "signals_detected": "confusion at turn 2: kya bola? samjha nahi; frustration at turn 3: baar baar call karte ho",
        "switch_summary": "",
        "live_switch_log": json.dumps([
            {"turn": 2, "signal": "confusion", "evidence": "kya bola? samjha nahi", "source": "llm+keywords",
             "from": "base", "to": "confusion"},
            {"turn": 3, "signal": "frustration", "evidence": "baar baar call karte ho", "source": "llm+keywords",
             "from": "confusion", "to": "frustration"}], ensure_ascii=False)},
    "interaction_transcript": [{"role": "user", "en_text": "Why do you keep calling again and again"}],
}


@router.post("/api/control/results/sample")
def add_sample():
    payload = {**SAMPLE, "attempt_id": f"sample-{int(time.time())}", "interaction_id": f"sample/{int(time.time())}"}
    row = store.record_result(payload)
    return {"stored": row["attempt_id"], "queued_for_review": feedback.queue_for_review(row)}


@router.delete("/api/control/results/sample")
def clear_samples():
    with store.db() as con:
        n = con.execute("DELETE FROM call_results WHERE attempt_id LIKE 'sample-%'").rowcount
    if settings.REVIEW_QUEUE.exists():
        with open(settings.REVIEW_QUEUE, encoding="utf-8") as fh:
            keep = [r for r in csv.DictReader(fh) if not (r.get("call_id") or "").startswith("sample-")]
        with open(settings.REVIEW_QUEUE, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=feedback.COLUMNS)
            w.writeheader()
            w.writerows(keep)
    return {"removed": n}


# ------------------------------------------------------------------ manual feed

@router.get("/api/control/manual")
def manual():
    def read(p: Path):
        return p.read_text(encoding="utf-8") if p.exists() else None

    inbox = MANUAL / "inbox"
    files = sorted(_rel(p) for p in inbox.rglob("*") if p.is_file()) if inbox.exists() else []
    return {"template_gaps": read(MANUAL / "templates" / "manual_gaps.csv"),
            "inbox_gaps": read(inbox / "manual_gaps.csv"), "inbox_files": files,
            "overrides": engine().overrides, "readme": read(MANUAL / "README.md")}


@router.post("/api/control/manual/gaps")
def save_gaps(body: dict = Body(...)):
    text = (body.get("csv") or "").strip()
    rows = list(csv.DictReader(io.StringIO(text)))
    need = {"gap_id", "persona_setting", "recommended_value", "applies_to", "priority", "reviewer"}
    if not rows or not need <= set(rows[0]):
        raise HTTPException(400, f"the CSV needs a header with at least: {', '.join(sorted(need))}")
    (MANUAL / "inbox").mkdir(parents=True, exist_ok=True)
    (MANUAL / "inbox" / "manual_gaps.csv").write_text(text + "\n", encoding="utf-8")
    return {"saved_rows": len(rows), "next": "Run 'manual-ingest' on the Jobs tab, then open any affected persona."}


# ------------------------------------------------------------------ sarvam

@router.get("/api/control/sarvam")
def sarvam(check: bool = False):
    out = {"org_id": settings.SARVAM_ORG_ID, "workspace_id": settings.SARVAM_WORKSPACE_ID,
           "key_set": bool(settings.SARVAM_VA_API_KEY), "telephony_set": bool(settings.SARVAM_CONNECTION_ID),
           "campaigns": settings.campaigns(),
           "agents": [{"variant": k, **v} for k, v in settings.AGENTS.items()]}
    if check:
        from service.sarvam_api import SarvamError, SarvamVA
        try:
            camps = SarvamVA().list_campaigns()
            out["check"] = {"ok": True, "campaigns_on_sarvam": len(camps) if isinstance(camps, list)
                            else len(camps.get("items", camps.get("campaigns", [])) if isinstance(camps, dict) else [])}
        except (SarvamError, Exception) as e:  # noqa: BLE001 - show any failure on the page
            out["check"] = {"ok": False, "error": str(e)[:300]}
    return out
