"""Sarvam smoke test: which models work with our key, how fast they are, and voice samples to listen to.

Run:  .venv/Scripts/python scripts/smoke_test.py [--only chat,tts,stt,stream]
Outputs: out/smoke/results.json and out/voice_samples/*.wav
"""
import argparse
import asyncio
import base64
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

from sarvamai import AsyncSarvamAI, SarvamAI  # noqa: E402

SMOKE_DIR = config.OUT_DIR / "smoke"
VOICE_DIR = config.OUT_DIR / "voice_samples"
SMOKE_DIR.mkdir(parents=True, exist_ok=True)
VOICE_DIR.mkdir(parents=True, exist_ok=True)

# Same meeting-fix pitch in each language/script, so differences come from the voice only.
LINES = {
    "hi_deva": ("hi-IN", "नमस्ते, मैं IndiaMART से बोल रही हूँ। आपकी category में इस हफ्ते काफी buyer enquiries आई हैं। "
                         "क्या कल आप हमारे sales executive के साथ पंद्रह मिनट की meeting के लिए time निकाल सकते हैं?"),
    "hi_roman": ("hi-IN", "Namaste, main IndiaMART se bol rahi hoon. Aapki category mein is hafte kaafi buyer enquiries aayi hain. "
                          "Kya kal aap hamare sales executive ke saath pandrah minute ki meeting ke liye time nikaal sakte hain?"),
    "en": ("en-IN", "Hello, I'm calling from IndiaMART. Your category has received quite a few buyer enquiries this week. "
                    "Could you spare fifteen minutes tomorrow for a short meeting with our sales executive?"),
    "gu": ("gu-IN", "નમસ્તે, હું IndiaMART માંથી બોલું છું. આ અઠવાડિયે તમારી category માં ઘણી buyer enquiries આવી છે. "
                    "શું કાલે તમે અમારા sales executive સાથે પંદર મિનિટની meeting માટે સમય કાઢી શકો?"),
    "ta": ("ta-IN", "வணக்கம், நான் IndiaMART இலிருந்து பேசுகிறேன். இந்த வாரம் உங்கள் category-க்கு நிறைய buyer enquiries வந்துள்ளன. "
                    "நாளை எங்கள் sales executive உடன் பதினைந்து நிமிட meeting-க்கு நேரம் ஒதுக்க முடியுமா?"),
}

# (model, speaker, line_key, pace)
TTS_JOBS = (
    [("bulbul:v3", s, "hi_deva", 1.0) for s in ["ritu", "priya", "simran", "kavya", "aditya", "rahul", "shubh", "rohan"]]
    + [("bulbul:v3", s, "hi_roman", 1.0) for s in ["ritu", "aditya"]]
    + [("bulbul:v3", "ritu", "hi_deva", p) for p in (0.85, 1.2)]
    + [("bulbul:v3", s, "en", 1.0) for s in ["ritu", "aditya"]]
    + [("bulbul:v3", s, "gu", 1.0) for s in ["ritu", "aditya"]]
    + [("bulbul:v3", s, "ta", 1.0) for s in ["kavitha", "vijay"]]
    + [("bulbul:v4-flash", s, "hi_deva", 1.0) for s in [
        "ritu_hi_sales", "ritu_hi_customer_warm", "simran_hi_sales", "ishita_enhi_customer",
        "aditya_hi_sales", "tarun_hi_sales", "shubh_hi_customer", "ratan_hi_customer_expressive"]]
    + [("bulbul:v4-flash", s, "en", 1.0) for s in ["simran_en_sales", "neha_en_customer", "shubh_en_narration"]]
    + [("bulbul:v4-flash", s, "gu", 1.0) for s in ["pooja_gu_customer", "bhavik_gu_conversation"]]
    + [("bulbul:v4-flash", s, "ta", 1.0) for s in ["aravind_ta_ads", "gokul_ta_narration"]]
)

CHAT_PROBE = [
    {"role": "system", "content": "You classify a seller's utterance on an IndiaMART sales call. "
     "Reply ONLY with JSON: {\"frustration\":0-1,\"confusion\":0-1,\"interest\":0-1,\"rush\":0-1,\"language\":\"hi|en|gu|ta|mixed\"}"},
    {"role": "user", "content": "Madam baat bataiye main filhaal thoda busy hoon, price bataiye. Monthly kitne ka hai?"},
]


def client() -> SarvamAI:
    return SarvamAI(api_subscription_key=config.require_key())


def timed(fn):
    t = time.perf_counter()
    try:
        out = fn()
        return out, round(time.perf_counter() - t, 3), None
    except Exception as e:  # report every failure, keep going
        return None, round(time.perf_counter() - t, 3), f"{type(e).__name__}: {str(e)[:300]}"


def test_chat(c: SarvamAI) -> list[dict]:
    rows = []
    variants = [
        ("completions", "sarvam-30b"), ("completions", "sarvam-105b"),
        ("completions", "sarvam-105b-conversations"), ("completions_v2", "sarvam-105b"),
    ]
    for api, model in variants:
        fn = getattr(c.chat, api)
        resp, sec, err = timed(lambda: fn(messages=CHAT_PROBE, model=model, temperature=0.1,
                                          max_tokens=300, reasoning_effort="low"))
        text = None
        if resp is not None:
            msg = resp.choices[0].message
            text = (msg.content or "")[:300]
        rows.append({"api": api, "model": model, "sec": sec, "ok": err is None, "error": err, "reply": text})
        print(f"[chat] {api:15s} {model:28s} {sec:6.2f}s {'OK' if not err else err[:120]}")
        if text:
            print("        ->", text.replace("\n", " ")[:200])
    return rows


def _tts_job(c: SarvamAI, job):
    model, speaker, key, pace = job
    lang, text = LINES[key]
    resp, sec, err = timed(lambda: c.text_to_speech.convert(
        text=text, language_code=lang, speaker=speaker, model=model, pace=pace,
        speech_sample_rate=24000, output_audio_codec="wav"))
    fname = None
    if resp is not None:
        fname = f"{model.replace(':', '-')}__{speaker}__{key}__p{pace}.wav"
        (VOICE_DIR / fname).write_bytes(base64.b64decode("".join(resp.audios)))
    return {"model": model, "speaker": speaker, "line": key, "lang": lang, "pace": pace,
            "sec": sec, "ok": err is None, "error": err, "file": fname}


def test_tts(c: SarvamAI) -> list[dict]:
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(lambda j: _tts_job(c, j), TTS_JOBS))
    for r in rows:
        print(f"[tts] {r['model']:15s} {r['speaker']:30s} {r['line']:8s} p{r['pace']:<4} {r['sec']:5.2f}s "
              f"{'OK' if r['ok'] else r['error'][:100]}")
    return rows


def test_stt(c: SarvamAI) -> list[dict]:
    """Round-trip our own TTS samples, then a real phone recording that has a reference transcript."""
    rows = []
    samples = [("bulbul-v3__ritu__hi_deva__p1.0.wav", "hi-IN"), ("bulbul-v3__aditya__gu__p1.0.wav", "gu-IN"),
               ("bulbul-v3__ritu__en__p1.0.wav", "en-IN")]
    for fname, _lang in samples:
        p = VOICE_DIR / fname
        if not p.exists():
            continue
        for model, mode in [("saaras:v3", "codemix"), ("saaras:v3", "transcribe"), ("saaras:v4", "codemix")]:
            resp, sec, err = timed(lambda: c.speech_to_text.transcribe(
                file=open(p, "rb"), model=model, mode=mode, language_code="unknown"))
            rows.append({"src": fname, "model": model, "mode": mode, "sec": sec, "ok": err is None, "error": err,
                         "transcript": getattr(resp, "transcript", None),
                         "lang": getattr(resp, "language_code", None)})
            print(f"[stt] {fname[:34]:34s} {model:10s} {mode:10s} {sec:5.2f}s lang={rows[-1]['lang']} "
                  f"{(rows[-1]['transcript'] or err or '')[:110]}")
    rows += _stt_real_call(c)
    return rows


def _stt_real_call(c: SarvamAI) -> list[dict]:
    import httpx
    import pandas as pd
    rec = pd.read_csv(config.DATASET_1 / "ps07_recording_sample_5000.csv")
    turns = pd.read_csv(config.DATASET_1 / "ps07_call_turns.csv")
    rec = rec[(rec.has_turn_transcript == 1) & rec.lead_call_duration.between(30, 60)].head(2)
    rows = []
    real_dir = SMOKE_DIR / "real_calls"
    real_dir.mkdir(exist_ok=True)
    for _, r in rec.iterrows():
        mp3 = real_dir / f"{r.attempt_id}.mp3"
        if not mp3.exists():
            mp3.write_bytes(httpx.get(r.call_recording_url, timeout=30).content)
        ref = " ".join(turns[turns.attempt_id == r.attempt_id].sort_values("turn_no").text.astype(str))
        resp, sec, err = timed(lambda: c.speech_to_text.transcribe(
            file=open(mp3, "rb"), model="saaras:v3", mode="codemix", language_code="unknown"))
        hyp = getattr(resp, "transcript", None)
        rows.append({"src": f"real:{r.attempt_id}", "model": "saaras:v3", "mode": "codemix", "sec": sec,
                     "ok": err is None, "error": err, "transcript": hyp, "reference": ref[:600],
                     "lang": getattr(resp, "language_code", None)})
        print(f"[stt-real] {r.attempt_id} {sec:5.2f}s lang={rows[-1]['lang']}\n   HYP: {(hyp or err or '')[:220]}\n   REF: {ref[:220]}")
    return rows


async def test_stream_tts() -> dict:
    """Time to first audio chunk, and a mid-session config change (the live persona switch)."""
    ac = AsyncSarvamAI(api_subscription_key=config.require_key())
    result = {"ok": False}
    t0 = time.perf_counter()
    try:
        async with ac.text_to_speech_streaming.connect(model="bulbul:v3", send_completion_event="true") as ws:
            await ws.configure(target_language_code="hi-IN", speaker="ritu", pace=1.0, output_audio_codec="mp3")
            await ws.convert(LINES["hi_deva"][1])
            await ws.flush()
            chunks, first = [], None
            async for msg in ws:
                kind = type(msg).__name__
                if kind == "AudioOutput":
                    first = first or round(time.perf_counter() - t0, 3)
                    chunks.append(base64.b64decode(msg.data.audio))
                elif kind == "EventResponse":
                    break
                elif kind == "ErrorResponse":
                    raise RuntimeError(str(msg))
            (VOICE_DIR / "stream_before_switch.mp3").write_bytes(b"".join(chunks))
            # Live switch: same socket, new persona settings (rush -> faster pace; frustration -> calmer voice)
            t1 = time.perf_counter()
            await ws.configure(target_language_code="hi-IN", speaker="ritu", pace=1.25, output_audio_codec="mp3")
            await ws.convert("जी, सीधे बात करती हूँ। कल सुबह दस बजे या शाम पाँच बजे, कौन सा time ठीक रहेगा?")
            await ws.flush()
            chunks2, first2 = [], None
            async for msg in ws:
                kind = type(msg).__name__
                if kind == "AudioOutput":
                    first2 = first2 or round(time.perf_counter() - t1, 3)
                    chunks2.append(base64.b64decode(msg.data.audio))
                elif kind in ("EventResponse", "ErrorResponse"):
                    break
            (VOICE_DIR / "stream_after_switch_rush.mp3").write_bytes(b"".join(chunks2))
            result = {"ok": True, "first_chunk_sec": first, "first_chunk_after_switch_sec": first2,
                      "chunks": len(chunks), "chunks_after_switch": len(chunks2)}
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    print("[tts-stream]", result)
    return result


def _to_pcm16k(src: Path, seconds: float = 25.0) -> bytes:
    import subprocess
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-t", str(seconds), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        check=True, capture_output=True).stdout


async def test_stream_stt() -> list[dict]:
    """Stream audio in 100 ms chunks at real-time speed, the way the browser mic will, and log every event."""
    ac = AsyncSarvamAI(api_subscription_key=config.require_key())
    sources = sorted((SMOKE_DIR / "real_calls").glob("*.mp3"))[:1] + [VOICE_DIR / "bulbul-v3__ritu__hi_deva__p1.0.wav"]
    out = []
    for src, model in [(s, m) for s in sources for m in ("saaras:v3", "saaras:v4")]:
        pcm = _to_pcm16k(src)
        events, t0 = [], time.perf_counter()
        try:
            async with ac.speech_to_text_streaming.connect(
                    language_code="unknown", model=model, mode="codemix", sample_rate="16000",
                    input_audio_codec="pcm_s16le", vad_signals="true", high_vad_sensitivity="true") as ws:

                async def reader():
                    async for msg in ws:
                        d = msg.model_dump() if hasattr(msg, "model_dump") else dict(msg)
                        d["t"] = round(time.perf_counter() - t0, 2)
                        events.append(d)

                rtask = asyncio.create_task(reader())
                step = 3200  # 100 ms of 16 kHz s16le
                for i in range(0, len(pcm), step):
                    await ws.transcribe(audio=base64.b64encode(pcm[i:i + step]).decode(),
                                        encoding="audio/wav", sample_rate=16000)
                    await asyncio.sleep(0.1)
                await ws.flush()
                await asyncio.sleep(3)
                rtask.cancel()
            row = {"src": src.name, "model": model, "ok": True, "events": events}
        except Exception as e:
            row = {"src": src.name, "model": model, "ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}",
                   "events": events}
        out.append(row)
        print(f"\n[stt-stream] {src.name} {model} ok={row['ok']} {row.get('error', '')}")
        for ev in events:
            data = ev.get("data") or {}
            txt = data.get("transcript") or data.get("signal_type") or ""
            print(f"   t={ev['t']:5.2f}s {ev.get('type')}: lang={data.get('language_code')} {str(txt)[:120]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="chat,tts,stt,stream,sttstream")
    which = set(ap.parse_args().only.split(","))
    c = client()
    res_path = SMOKE_DIR / "results.json"
    results = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    if "chat" in which:
        results["chat"] = test_chat(c)
    if "tts" in which:
        results["tts"] = test_tts(c)
    if "stt" in which:
        results["stt"] = test_stt(c)
    if "stream" in which:
        results["stream_tts"] = asyncio.run(test_stream_tts())
    if "sttstream" in which:
        results["stream_stt"] = asyncio.run(test_stream_stt())
    res_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {res_path}  ·  voice samples in {VOICE_DIR}")


if __name__ == "__main__":
    main()
