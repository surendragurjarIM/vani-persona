"""Narration for the VANI video: one Sarvam Bulbul clip per scene -> audio/<id>.wav, plus durations.json."""
import base64
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import config  # noqa: E402
from sarvamai import SarvamAI  # noqa: E402

SPEAKER, MODEL, PACE = (sys.argv[1] if len(sys.argv) > 1 else "shubh_enhi_banking"), "bulbul:v4-flash", 1.0


def main():
    client = SarvamAI(api_subscription_key=config.require_key())
    out, durations = HERE / "audio", {}
    out.mkdir(exist_ok=True)
    for scene in json.loads((HERE / "script.json").read_text(encoding="utf-8")):
        if scene["kind"] != "voice":
            durations[scene["id"]] = scene["seconds"]
            continue
        r = client.text_to_speech.convert(text=scene["text"], language_code="en-IN", speaker=SPEAKER,
                                          model=MODEL, pace=PACE)
        wav = out / f"{scene['id']}.wav"
        wav.write_bytes(base64.b64decode("".join(r.audios)))
        sec = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", str(wav)]).strip())
        durations[scene["id"]] = round(sec, 2)
        print(f"{scene['id']:10s} {sec:5.1f}s")
    (HERE / "durations.json").write_text(json.dumps(durations, indent=1), encoding="utf-8")
    print("total", round(sum(durations.values()), 1), "s")


if __name__ == "__main__":
    main()
