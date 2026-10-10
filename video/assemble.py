"""Mux frames + narration (+ quiet sea ambience) into MP4s.

    python assemble.py   ->  out/VANI_full_with_demo_slot.mp4      the whole film, demo slot as a title card
                             out/1_opening.mp4                      open, problem, idea
                             out/2_demo_slot_card.mp4               the card shown before/over your call recordings
                             out/3_solution_and_close.mp4           how it works ... closing
"""
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"
FPS = 25
LEAD = 0.5


def run(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main():
    OUT.mkdir(exist_ok=True)
    tl = json.loads((HERE / "timeline.json").read_text(encoding="utf-8"))
    total = tl[-1]["start"] + tl[-1]["dur"]
    voiced = [s for s in tl if s["voice"]]

    # Narration placed at each scene's start + lead, mixed with a low brown-noise "sea" bed.
    ins, filt = [], []
    for i, s in enumerate(voiced):
        ins += ["-i", str(HERE / "audio" / f"{s['id']}.wav")]
        ms = int((s["start"] + LEAD) * 1000)
        filt.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
    n = len(voiced)
    ins += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anoisesrc=color=brown:sample_rate=44100:amplitude=0.5"]
    filt.append(f"[{n}:a]lowpass=f=420,volume=0.05,tremolo=f=0.12:d=0.6,aformat=channel_layouts=stereo[sea]")
    filt.append("".join(f"[v{i}]" for i in range(n)) + f"[sea]amix=inputs={n + 1}:normalize=0:duration=longest,"
                f"atrim=0:{total:.2f}[a]")
    audio = OUT / "mix.m4a"
    run([*ins, "-filter_complex", ";".join(filt), "-map", "[a]", "-c:a", "aac", "-b:a", "192k", str(audio)])

    full = OUT / "VANI_full_with_demo_slot.mp4"
    run(["-framerate", str(FPS), "-i", str(HERE / "frames" / "%06d.jpg"), "-i", str(audio),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
         "-shortest", "-movflags", "+faststart", str(full)])

    def cut(name, first, last):
        a = next(s for s in tl if s["id"] == first)["start"]
        b = next(s for s in tl if s["id"] == last)
        run(["-ss", f"{a:.3f}", "-to", f"{b['start'] + b['dur']:.3f}", "-i", str(full), "-c:v", "libx264", "-crf", "18",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUT / name)])

    cut("1_opening.mp4", "open", "idea")
    cut("2_demo_slot_card.mp4", "demos", "demos")
    cut("3_solution_and_close.mp4", "how", "close")
    for p in sorted(OUT.glob("*.mp4")):
        d = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)])
        print(f"{p.name:32s} {float(d):6.1f}s  {p.stat().st_size / 1e6:5.1f} MB")


if __name__ == "__main__":
    main()
