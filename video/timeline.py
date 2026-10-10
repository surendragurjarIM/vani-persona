"""Scene timeline from the narration lengths: each voiced scene gets 0.5 s before and 0.7 s after its line."""
import json
from pathlib import Path

HERE = Path(__file__).parent
LEAD, TAIL = 0.5, 0.7


def build():
    script = json.loads((HERE / "script.json").read_text(encoding="utf-8"))
    dur = json.loads((HERE / "durations.json").read_text(encoding="utf-8"))
    t, tl = 0.0, []
    for s in script:
        d = dur[s["id"]] + (LEAD + TAIL if s["kind"] == "voice" else 0)
        tl.append({"id": s["id"], "start": round(t, 3), "dur": round(d, 3), "voice": s["kind"] == "voice"})
        t += d
    (HERE / "timeline.json").write_text(json.dumps(tl, indent=1), encoding="utf-8")
    return tl


if __name__ == "__main__":
    for x in build():
        print(f"{x['id']:10s} {x['start']:7.2f}  {x['dur']:5.2f}")
