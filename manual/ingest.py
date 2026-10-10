"""Ingest the manual feed (manual/inbox) -> out/manual_overrides.json (+ manual few-shot examples).

    python -m manual.ingest [--transcribe]

Manual rows outrank automatic evidence: persona.generator applies them after all rules (higher `priority` wins),
and the live detector uses manual gaps as few-shot examples.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

INBOX = config.ROOT / "manual" / "inbox"
SIGNALS = {"frustration", "confusion", "interest", "rush", "unavailable", "not_interested", "language", "other", ""}
SETTING_PREFIXES = ("voice.", "language.", "tone.", "conversation_plan.", "live_adaptation.thresholds.")


def _num(v):
    try:
        x = float(v)
        return int(x) if x.is_integer() else x
    except (TypeError, ValueError):
        return v


def load_gaps() -> tuple[list[dict], list[dict], list[str]]:
    p = INBOX / "manual_gaps.csv"
    if not p.exists():
        return [], [], [f"{p} not found (copy templates/manual_gaps.csv to start)"]
    df = pd.read_csv(p, dtype=str).fillna("")
    overrides, examples, errors = [], [], []
    for i, r in df.iterrows():
        rid = r.get("gap_id") or f"MG-row{i + 2}"
        if r.get("signal", "") not in SIGNALS:
            errors.append(f"{rid}: unknown signal '{r['signal']}'")
            continue
        if r.get("seller_said") and r.get("should_have_said"):
            examples.append({"id": rid, "signal": r["signal"], "seller_said": r["seller_said"],
                             "vani_said": r.get("vani_said", ""), "should_have_said": r["should_have_said"],
                             "tone_heard": r.get("tone_heard", ""), "call_id": r.get("call_id", "")})
        if not r.get("persona_setting"):
            continue
        if not r["persona_setting"].startswith(SETTING_PREFIXES):
            errors.append(f"{rid}: persona_setting '{r['persona_setting']}' is not a known spec path")
            continue
        scope = r.get("applies_to") or (f"seller:{r['fk_glusr_usr_id']}" if r.get("fk_glusr_usr_id") else "all")
        if not scope.startswith(("seller:", "segment:", "all")):
            errors.append(f"{rid}: applies_to must be seller:<id>, segment:<k>=<v>[&...] or all")
            continue
        overrides.append({
            "id": rid, "setting": r["persona_setting"], "value": _num(r["recommended_value"]),
            "applies_to": scope, "priority": int(_num(r.get("priority") or 3)), "reviewer": r.get("reviewer", ""),
            "reason": (r.get("notes") or r.get("should_have_said") or "manual review").strip(),
            "when": r.get("seller_said", ""), "signal": r.get("signal", ""), "tone_heard": r.get("tone_heard", ""),
            "evidence": [f"manual_call:{r['call_id']}"] if r.get("call_id") else [],
        })
    return overrides, examples, errors


def load_calls(transcribe: bool) -> tuple[list[dict], list[str]]:
    p = INBOX / "manual_calls.csv"
    if not p.exists():
        return [], []
    df = pd.read_csv(p, dtype=str).fillna("")
    calls, errors = [], []
    for _, r in df.iterrows():
        cid = r["call_id"]
        tf = config.ROOT / r["transcript_file"] if r.get("transcript_file") else INBOX / "transcripts" / f"{cid}.csv"
        if r["source"] == "recording" and not tf.exists():
            if transcribe:
                try:
                    transcribe_recording(cid, r["recording_url_or_file"], tf)
                except Exception as e:  # keep going; report
                    errors.append(f"{cid}: transcription failed: {e}")
                    continue
            else:
                errors.append(f"{cid}: recording not transcribed yet (run with --transcribe)")
                continue
        if not tf.exists():
            errors.append(f"{cid}: transcript file {tf} missing")
            continue
        t = pd.read_csv(tf)
        missing = {"turn_no", "speaker", "text"} - set(t.columns)
        if missing:
            errors.append(f"{cid}: transcript missing columns {missing}")
            continue
        calls.append({"call_id": cid, "fk_glusr_usr_id": r.get("fk_glusr_usr_id"), "outcome": r.get("outcome"),
                      "n_turns": int(len(t)), "transcript_file": str(tf)})
    return calls, errors


def transcribe_recording(call_id: str, src: str, out_csv: Path):
    """Sarvam batch STT with diarization -> turn CSV (bot = speaker who talks first)."""
    import time

    import httpx
    from sarvamai import SarvamAI
    c = SarvamAI(api_subscription_key=config.require_key())
    local = INBOX / "recordings" / f"{call_id}.mp3"
    if src.startswith("http") and not local.exists():
        local.write_bytes(httpx.get(src, timeout=60).content)
    elif not src.startswith("http"):
        local = config.ROOT / src
    job = c.speech_to_text_job.create_job(model="saaras:v4", mode="codemix", with_diarization=True,
                                          with_timestamps=True, language_code="unknown", num_speakers=2)
    job.upload_files(file_paths=[str(local)])
    job.start()
    job.wait_until_complete()
    out_dir = INBOX / "transcripts" / f"_{call_id}_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    job.download_outputs(output_dir=str(out_dir))
    raw = json.loads(next(out_dir.glob("*.json")).read_text(encoding="utf-8"))
    entries = (raw.get("diarized_transcript") or {}).get("entries") or []
    first = entries[0]["speaker_id"] if entries else None
    rows = [{"turn_no": i + 1, "speaker": "bot" if e["speaker_id"] == first else "seller",
             "start_sec": e.get("start_time_seconds"), "end_sec": e.get("end_time_seconds"),
             "text": e.get("transcript", "")} for i, e in enumerate(entries)]
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    time.sleep(0.1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcribe", action="store_true")
    args = ap.parse_args()
    (INBOX / "transcripts").mkdir(parents=True, exist_ok=True)
    overrides, examples, e1 = load_gaps()
    calls, e2 = load_calls(args.transcribe)
    out = {"overrides": overrides, "examples": examples, "calls": calls}
    (config.OUT_DIR / "manual_overrides.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    print(f"manual calls: {len(calls)} · overrides: {len(overrides)} · detector examples: {len(examples)}")
    for e in e1 + e2:
        print("  !", e)
    print(f"-> {config.OUT_DIR / 'manual_overrides.json'}  (regenerate personas: python -m persona.cli --all)")


if __name__ == "__main__":
    main()
