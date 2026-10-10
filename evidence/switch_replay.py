"""Switch-timing replay: does the live switch tool change mode on the right turn?

Every audited call is replayed seller turn by seller turn through the exact Sarvam code tool
(sarvam_agent/update_persona_mode.py). The evaluator's reason text labels 2,986 seller turns with the signal it saw
(rush, confusion, frustration, interest, or none). For each labelled turn we check what the tool did:

  on time     the tool switched to (or already held) a labelled signal's mode on that turn
  one late    it switched to it on the seller's next turn
  missed      neither
  false       on a turn labelled with no signal, the tool switched anyway

Two runs:
  keywords   all 2,735 audited calls, no LLM: the tool decides from the lexicon alone (a floor: live, the LLM's guess
             is added on every signal turn)
  llm        the 293 turns that also have a recorded LLM verdict: that verdict is passed as the tool's
             suspected_signal, exactly as Sarvam's LLM does live

The tool is called on every seller turn here. Live it is called only on turns the LLM thinks changed, so false switches
here are an upper bound. Flapping = re-entering a mode inside the two-turn cooldown (must be zero by construction).

    python -m evidence.switch_replay        -> out/switch_timing.json
"""
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from sarvam_agent import build_switch_tool  # noqa: E402

build_switch_tool.build()
from sarvam_agent import update_persona_mode as tool  # noqa: E402
from sarvam_conv_ai_sdk import EngagementMetadata, SarvamToolContext  # noqa: E402

SIGNALS = ["rush", "confusion", "frustration", "interest"]
# The evaluator's "rush" label covers busy and unavailable sellers alike.
MODE_OF = {"rush": {"rush", "unavailable"}, "confusion": {"confusion"}, "frustration": {"frustration", "do_not_call"},
           "interest": {"interest"}}


def _ctx():
    return SarvamToolContext(
        agent_variables={"attempt_number": "1"},
        engagement_metadata=EngagementMetadata(interaction_id="replay", app_id="replay", app_version=0,
                                               interaction_language="Hindi"),
        language="Hindi", allowed_languages=["Hindi", "English"], state="start", next_valid_states=[])


def llm_guess(raw: str | None) -> str:
    if not raw:
        return "none"
    d = json.loads(raw)
    best = max(["frustration", "confusion", "interest", "rush", "unavailable"], key=lambda k: d.get(k) or 0)
    return best if (d.get(best) or 0) >= 0.5 else "none"


def replay_call(turns: pd.DataFrame, guesses: dict) -> list[dict]:
    """Run one call's seller turns through the tool. Returns, per seller turn, the switches it made and the mode."""
    ctx, out = _ctx(), []
    for i, r in enumerate(turns.itertuples(index=False), start=1):
        before = len((ctx.internal_variables.get("vani_persona_state") or {}).get("log", []))
        t = tool.UpdatePersonaMode(user_words=str(r.text)[:400], suspected_signal=guesses.get((r.attempt_id, r.turn_no), "none"),
                                   turn_number=i)
        asyncio.run(t.run(ctx))
        st = ctx.internal_variables["vani_persona_state"]
        out.append({"turn_no": r.turn_no, "switches": [s["to"] for s in st["log"][before:] if s["signal"] != "language"],
                    "mode": st["mode"], "log": st["log"]})
    return out


def score(labels: pd.DataFrame, turns: pd.DataFrame, guesses: dict) -> dict:
    per_sig = {s: Counter() for s in SIGNALS}
    false_sw, unlabelled, flaps, switches_per_call = 0, 0, 0, []
    seller = turns[turns.speaker == "seller"].sort_values(["attempt_id", "turn_no"])
    by_call = dict(tuple(seller.groupby("attempt_id")))
    lab_by_call = defaultdict(dict)
    for r in labels.itertuples(index=False):
        lab_by_call[r.attempt_id][r.turn_no] = [s for s in SIGNALS if getattr(r, f"lab_{s}")]
    for cid, labs in lab_by_call.items():
        if cid not in by_call:
            continue
        res = replay_call(by_call[cid].drop_duplicates("turn_no"), guesses)
        idx = {x["turn_no"]: k for k, x in enumerate(res)}
        log = res[-1]["log"] if res else []
        switches_per_call.append(len([s for s in log if s["signal"] != "language"]))
        last = {}
        for k, s in enumerate(log):  # flapping: same mode re-entered within the cooldown
            if s["to"] in last and s["turn"] - last[s["to"]] <= tool.COOLDOWN_TURNS:
                flaps += 1
            last[s["to"]] = s["turn"]
        for tno, gold in labs.items():
            if tno not in idx:
                continue
            k = idx[tno]
            now = res[k]
            nxt = res[k + 1] if k + 1 < len(res) else None
            if not gold:
                unlabelled += 1
                false_sw += bool(now["switches"])
                continue
            for g in gold:
                modes = MODE_OF[g]
                if now["mode"] in modes:
                    per_sig[g]["on_time"] += 1
                elif nxt and set(nxt["switches"]) & modes:
                    per_sig[g]["one_late"] += 1
                else:
                    per_sig[g]["missed"] += 1
    sig_out = {}
    for s, c in per_sig.items():
        n = sum(c.values())
        sig_out[s] = {"labelled_turns": n, "on_time": c["on_time"], "one_late": c["one_late"], "missed": c["missed"],
                      "on_time_rate": round(c["on_time"] / n, 3) if n else None,
                      "within_one_turn_rate": round((c["on_time"] + c["one_late"]) / n, 3) if n else None}
    tot = {k: sum(v[k] for v in sig_out.values()) for k in ("labelled_turns", "on_time", "one_late", "missed")}
    n = tot["labelled_turns"] or 1
    return {"calls": len(switches_per_call), "by_signal": sig_out,
            "all_signals": {**tot, "on_time_rate": round(tot["on_time"] / n, 3),
                            "within_one_turn_rate": round((tot["on_time"] + tot["one_late"]) / n, 3)},
            "no_signal_turns": unlabelled,
            "false_switch_rate": round(false_sw / unlabelled, 3) if unlabelled else None,
            "flapping_events": flaps,
            "avg_switches_per_call": round(sum(switches_per_call) / max(1, len(switches_per_call)), 2)}


def main():
    labels = pd.read_parquet(config.CACHE_DIR / "gap_turns_labelled.parquet")
    turns = pd.read_parquet(config.CACHE_DIR / "turns.parquet")
    turns = turns[turns.attempt_id.isin(labels.attempt_id)]
    sample = pd.read_parquet(config.CACHE_DIR / "llm_tier_sample.parquet")

    keywords = score(labels, turns, {})
    # LLM run: only the sampled turns are scored, each with its recorded LLM verdict as the tool's suspected_signal.
    guesses = {(r.attempt_id, r.turn_no): llm_guess(r.llm) for r in sample.itertuples(index=False)}
    lab = labels.merge(sample[["attempt_id", "turn_no"]].drop_duplicates(), on=["attempt_id", "turn_no"])
    llm = score(lab, turns[turns.attempt_id.isin(sample.attempt_id)], guesses)

    out = {"method": __doc__.split("\n\n")[1].strip(), "cooldown_turns": tool.COOLDOWN_TURNS,
           "keywords_only": keywords, "with_llm_guess": llm}
    path = config.OUT_DIR / "switch_timing.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for name, r in (("keywords only", keywords), ("with LLM guess", llm)):
        a = r["all_signals"]
        print(f"{name:15s} calls={r['calls']:5d} labelled={a['labelled_turns']:4d} on-time={a['on_time_rate']:.0%} "
              f"within-1={a['within_one_turn_rate']:.0%} false={r['false_switch_rate']} flaps={r['flapping_events']}")
        for s, v in r["by_signal"].items():
            print(f"   {s:12s} n={v['labelled_turns']:4d} on-time={v['on_time_rate']} within-1={v['within_one_turn_rate']}")
    print("->", path)


if __name__ == "__main__":
    main()
