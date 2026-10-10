"""How good is the fast-tier signal detector? Measured against the evaluator labels, at call and turn level.

    python -m evidence.signals_eval   -> out/signals_eval.json, printed table

Call level : detector fired anywhere in the call vs the evaluator's label for that call.
Turn level : the evaluator quotes the seller's words (seller_questions.que_dialogue). We locate that turn in the
             transcript and check whether the detector fires on it (or the next seller turn). This measures
             whether a switch would happen at the right moment.
Labels are weak (another model's judgement), so these numbers are a lower bound on true precision.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from data.loader import load  # noqa: E402
from live.lexicon import detect  # noqa: E402

THRESHOLDS = [0.4, 0.6, 0.8]
GAP_LABELS = {  # evaluator reason text -> seller state on that turn
    "rush": r"busy|no time|not have time|don't have time|time constraint|in a hurry|hurry|driving|"
            r"in a meeting|currently occupied|call later|later time|not available",
    "confusion": r"confus|clarif|did not understand|didn't understand|unclear|asked who|asked what|"
                 r"identity|who is calling|could not hear|couldn't hear",
    "frustration": r"frustrat|irritat|annoy|angry|rude|upset|repeated calls|multiple calls|stop calling|harass",
    "interest": r"price|pricing|cost|charges|how much|fee|benefit|package details|plan details",
}
QUESTION_TO_SIGNAL = {
    "Frustrated User": "frustration",
    "Clarification": "confusion", "Identity Confirmation": "confusion", "AI Bot Confirmation": "confusion",
    "Pricing Payment": "interest", "Benefit Value": "interest", "Service Product Info": "interest",
    "Meeting Visit": "interest", "Location Confirmation": "interest",
}


def call_labels(call_ids: pd.Index) -> pd.DataFrame:
    lab = pd.DataFrame(index=call_ids)
    q = load("eval_seller_questions")
    disp = load("eval_disposition").set_index("attempt_id")
    ob = load("eval_objections")
    lat = load("eval_latency_repetition").set_index("attempt_id")

    def has_q(cats):
        return set(q[q.category.isin(cats)].attempt_id)

    def has_ob(cat):
        return set(ob[ob.category == cat].attempt_id)

    covered_q = set(q.attempt_id) | set(load("eval_seller_questions").attempt_id)
    lab["frustration"] = lab.index.isin(has_q(["Frustrated User"]) |
                                        set(disp[disp.disposition == "do_not_call"].index))
    lab["confusion"] = lab.index.isin(has_q(["Clarification", "Identity Confirmation", "AI Bot Confirmation"]) |
                                      set(lat[lat.seller_had_to_repeat.fillna(0) >= 1].index))
    lab["interest"] = lab.index.isin(has_q(["Pricing Payment", "Benefit Value", "Service Product Info",
                                            "Meeting Visit"]))
    lab["rush"] = lab.index.isin(has_ob("Seller Unavailability & Scheduling Constraints") |
                                 set(disp[disp.disposition == "callback_requested"].index))
    lab["not_interested"] = lab.index.isin(has_ob("Explicit Disinterest / Refusal") |
                                           set(disp[disp.disposition.isin(["not_interested", "do_not_call"])].index))
    lab["_covered"] = lab.index.isin(covered_q | set(disp.index) | set(ob.attempt_id))
    return lab


def prf(pred: pd.Series, gold: pd.Series) -> dict:
    tp = int((pred & gold).sum())
    fp = int((pred & ~gold).sum())
    fn = int((~pred & gold).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "support": int(gold.sum())}


def _toks(s):
    return set(re.findall(r"[a-z]+", str(s).lower()))


def main():
    turns = load("turns")
    sel = turns[turns.speaker == "seller"].copy()
    scores = sel.text.map(lambda t: detect(t).scores)
    for s in ["frustration", "confusion", "interest", "rush", "unavailable", "not_interested"]:
        sel[s] = scores.map(lambda d: d.get(s, 0.0))
    sel["rush_any"] = sel[["rush", "unavailable"]].max(axis=1)  # evaluator label merges the two

    # ---- call level ----
    per_call = sel.groupby("attempt_id")[["frustration", "confusion", "interest", "rush_any", "not_interested"]].max()
    lab = call_labels(per_call.index)
    per_call, lab = per_call[lab._covered], lab[lab._covered]
    results = {"call_level": {}, "turn_level": {}, "n_calls": int(len(per_call))}
    print(f"Call level: {len(per_call):,} transcribed calls with evaluator coverage")
    print(f"{'signal':15s} {'thr':>4s} {'prec':>6s} {'recall':>6s} {'f1':>6s} {'support':>8s}")
    for sig, col in [("frustration", "frustration"), ("confusion", "confusion"), ("interest", "interest"),
                     ("rush", "rush_any"), ("not_interested", "not_interested")]:
        results["call_level"][sig] = {}
        for th in THRESHOLDS:
            m = prf(per_call[col] >= th, lab[sig])
            results["call_level"][sig][str(th)] = m
            print(f"{sig:15s} {th:4.1f} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} {m['support']:8d}")

    # ---- turn level: the evaluator's "gaps" quote the exact seller turn the bot mishandled, with a reason.
    # The reason text (written by a separate model) names the seller's state -> an independent turn label.
    q = load("eval_seller_questions")
    q = q[(q.category == "gap") & q.que_dialogue.notna() & q.attempt_id.isin(sel.attempt_id)]
    reason = (q.gap_reason.fillna("") + " " + q.seller_context.fillna("")).str.lower()
    for sig, rx in GAP_LABELS.items():
        q[f"lab_{sig}"] = reason.str.contains(rx, regex=True)
    by_call = {a: g.reset_index(drop=True) for a, g in sel.groupby("attempt_id")}
    rows = []
    for r in q.itertuples():
        g = by_call.get(r.attempt_id)
        qt = _toks(r.que_dialogue)
        if g is None or not qt:
            continue
        sims = g.text.map(lambda t: len(qt & _toks(t)) / max(1, len(qt | _toks(t))))
        i = int(sims.idxmax())
        if sims[i] < 0.5:
            continue
        row = {"attempt_id": r.attempt_id, "turn_no": int(g.loc[i, "turn_no"])}
        for sig in GAP_LABELS:
            col = "rush_any" if sig == "rush" else sig
            row[f"lab_{sig}"] = bool(getattr(r, f"lab_{sig}"))
            row[f"det_{sig}"] = float(g.loc[i, col])
        rows.append(row)
    h = pd.DataFrame(rows).drop_duplicates(["attempt_id", "turn_no"])
    print(f"\nTurn level: {len(h):,} mishandled seller turns (evaluator 'gaps') located in transcripts")
    print(f"{'signal':13s} {'thr':>4s} {'prec':>6s} {'recall':>6s} {'f1':>6s} {'support':>8s}")
    for sig in GAP_LABELS:
        results["turn_level"][sig] = {}
        for th in THRESHOLDS:
            m = prf(h[f"det_{sig}"] >= th, h[f"lab_{sig}"])
            results["turn_level"][sig][str(th)] = m
            print(f"{sig:13s} {th:4.1f} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} {m['support']:8d}")
    h.to_parquet(config.CACHE_DIR / "gap_turns_labelled.parquet", index=False)
    (config.OUT_DIR / "signals_eval.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print("\n-> out/signals_eval.json")


if __name__ == "__main__" and "--llm" not in sys.argv:
    main()


def llm_tier(n_per_label: int = 60, seed: int = 7):
    """Compare fast tier, LLM tier and the fused detector on a stratified sample of labelled gap turns."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    from live.llm_signals import _client, classify
    h = pd.read_parquet(config.CACHE_DIR / "gap_turns_labelled.parquet")
    turns = load("turns")
    labs = [f"lab_{s}" for s in GAP_LABELS]
    parts = [h[h[c]].sample(min(n_per_label, int(h[c].sum())), random_state=seed) for c in labs]
    parts.append(h[~h[labs].any(axis=1)].sample(n_per_label, random_state=seed))
    smp = pd.concat(parts).drop_duplicates(["attempt_id", "turn_no"]).reset_index(drop=True)
    tt = turns.set_index(["attempt_id", "turn_no"]).text
    bot = turns[turns.speaker == "bot"]

    def ctx(r):
        prev = bot[(bot.attempt_id == r.attempt_id) & (bot.turn_no < r.turn_no)]
        return tt.get((r.attempt_id, r.turn_no), ""), (prev.text.iloc[-1] if len(prev) else "")

    c = _client()
    pairs = [ctx(r) for r in smp.itertuples()]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as ex:
        out = list(ex.map(lambda p: classify(p[0], p[1], client=c), pairs))
    print(f"LLM tier: {len(out)} turns in {time.perf_counter() - t0:.1f}s")
    res = {}
    print(f"{'signal':13s} {'tier':6s} {'prec':>6s} {'recall':>6s} {'f1':>6s} {'support':>8s}")
    for sig in GAP_LABELS:
        gold = smp[f"lab_{sig}"].astype(bool)
        fast = smp[f"det_{sig}"]
        llm_col = pd.Series([max(o.get(sig, 0), o.get("unavailable", 0)) if sig == "rush" else o.get(sig, 0)
                             for o in out])
        fused = pd.concat([fast.where(fast >= 0.8, 0), llm_col], axis=1).max(axis=1)  # strong lexical hit OR llm
        res[sig] = {}
        for name, sc, th in [("fast", fast, 0.6), ("llm", llm_col, 0.5), ("fused", fused, 0.5)]:
            m = prf(sc >= th, gold)
            res[sig][name] = m
            print(f"{sig:13s} {name:6s} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f} {m['support']:8d}")
    smp["llm"] = [json.dumps(o, ensure_ascii=False) for o in out]
    smp.to_parquet(config.CACHE_DIR / "llm_tier_sample.parquet", index=False)
    p = config.OUT_DIR / "signals_eval.json"
    allres = json.loads(p.read_text(encoding="utf-8"))
    allres["llm_tier_sample"] = {"n": int(len(smp)), "results": res}
    p.write_text(json.dumps(allres, indent=1), encoding="utf-8")


if __name__ == "__main__" and "--llm" in sys.argv:
    llm_tier()
