"""Persona generator CLI.

    python -m persona.cli --seller-id 127142815           # print one spec (JSON) and save out/personas/<id>.json
    python -m persona.cli --seller-file my_sellers.csv    # specs for sellers in any CSV with the seller-file columns
    python -m persona.cli --all                           # every seller -> out/persona_specs.jsonl.gz
                                                          #   + out/persona_specs_flat.csv + out/distinctness.json
"""
import argparse
import gzip
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from persona.generator import generate, load_manual_overrides  # noqa: E402
from persona.playbook import load_library  # noqa: E402
from persona.schema import PersonaSpec  # noqa: E402
from persona.seller_features import load_features  # noqa: E402

FLAT = {  # column -> path in spec
    "speaker": ("voice", "speaker"), "gender": ("voice", "gender"), "pace": ("voice", "pace"),
    "voice_style": ("voice", "style"), "language": ("language", "primary"),
    "english_share": ("language", "english_share"), "formality": ("language", "formality"),
    "switch_option": ("language", "switch_option"), "warmth": ("tone", "warmth"), "empathy": ("tone", "empathy"),
    "assertiveness": ("tone", "assertiveness"), "max_words": ("tone", "max_words_per_turn"),
    "opening_hook": ("conversation_plan", "opening_hook"), "opening_style": ("conversation_plan", "opening_style"),
}
DISTINCT_KEYS = ["speaker", "pace", "language", "english_band", "formality", "warmth", "empathy", "assertiveness",
                 "words_band", "opening_hook", "opening_style", "thr_profile"]


def flatten(spec: dict) -> dict:
    row = {"seller_id": spec["seller_id"], "persona_label": spec["persona_label"],
           "overall_confidence": spec["overall_confidence"], "n_rules": len(spec["rules_fired"]),
           "rules_fired": " ".join(spec["rules_fired"]), "manual": " ".join(spec["manual_overrides"])}
    for col, (sec, key) in FLAT.items():
        row[col] = spec[sec][key]["value"]
    thr = spec["live_adaptation"]["thresholds"]["value"]
    for s in ("frustration", "rush", "confusion", "unavailable"):
        row[f"thr_{s}"] = thr[s]
    for k in ("turnover_band", "biz_kind", "region"):
        row[k] = spec["seller_snapshot"][k]
    return row


def distinctness(flat: pd.DataFrame) -> dict:
    d = flat.copy()
    d["english_band"] = pd.cut(d.english_share, [-1, 15, 30, 50, 100], labels=["hindi", "hinglish", "mixed", "english"])
    d["words_band"] = pd.cut(d.max_words, [0, 18, 24, 32, 100], labels=["xs", "s", "m", "l"])
    d["thr_profile"] = d[["thr_frustration", "thr_rush", "thr_confusion", "thr_unavailable"]].astype(str).agg("|".join,
                                                                                                             axis=1)
    sig = d[DISTINCT_KEYS].astype(str).agg("|".join, axis=1)
    counts = Counter(sig)
    p = np.array(list(counts.values())) / len(sig)
    seg = d.turnover_band.astype(str) + "/" + d.biz_kind.astype(str) + "/" + d.region.astype(str)
    rng = np.random.default_rng(0)
    idx_a, idx_b = rng.integers(0, len(d), 20000), rng.integers(0, len(d), 20000)
    diff_seg = seg.values[idx_a] != seg.values[idx_b]
    vals = d[DISTINCT_KEYS].astype(str).values
    n_diff = (vals[idx_a] != vals[idx_b]).sum(axis=1)
    per_setting = {k: int(d[k].astype(str).nunique()) for k in DISTINCT_KEYS}
    return {
        "sellers": int(len(d)),
        "distinct_persona_configurations": int(len(counts)),
        "largest_configuration_share": round(float(p.max()), 4),
        "top10_configurations_share": round(float(np.sort(p)[::-1][:10].sum()), 4),
        "normalised_entropy": round(float(-(p * np.log(p)).sum() / np.log(len(p))), 3) if len(p) > 1 else 0.0,
        "settings_compared": DISTINCT_KEYS,
        "avg_settings_different_between_two_sellers_of_different_segments":
            round(float(n_diff[diff_seg].mean()), 2),
        "avg_settings_different_within_same_segment": round(float(n_diff[~diff_seg].mean()), 2),
        "distinct_values_per_setting": per_setting,
        "speaker_mix": d.speaker.value_counts().to_dict(),
        "label_mix_top15": d.persona_label.value_counts().head(15).to_dict(),
        "rule_fire_rates": {r: round(float(d.rules_fired.str.contains(rf"\b{r}\b").mean()), 4)
                            for r in [f"R-{i:02d}" for i in range(1, 24)]},
        "confidence_mix": d.overall_confidence.value_counts(normalize=True).round(4).to_dict(),
    }


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seller-id", type=int)
    g.add_argument("--seller-file")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--validate-every", type=int, default=500, help="pydantic-validate every Nth spec in batch")
    args = ap.parse_args()

    feats = load_features()
    lib, ov = load_library(), load_manual_overrides()
    (config.OUT_DIR / "personas").mkdir(parents=True, exist_ok=True)

    if args.seller_id:
        row = feats[feats.fk_glusr_usr_id == args.seller_id]
        if row.empty:
            raise SystemExit(f"seller {args.seller_id} not in the seller file")
        spec = generate(row.iloc[0].to_dict(), lib, ov)
        PersonaSpec.model_validate(spec)
        out = config.OUT_DIR / "personas" / f"{args.seller_id}.json"
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(spec, ensure_ascii=False, indent=1))
        print(f"\n-> {out}", file=sys.stderr)
        return

    if args.seller_file:
        ids = pd.read_csv(args.seller_file, usecols=["fk_glusr_usr_id"]).fk_glusr_usr_id
        feats = feats[feats.fk_glusr_usr_id.isin(ids)]
        print(f"{len(feats):,} of {len(ids):,} sellers found in the feature table")

    t0 = time.perf_counter()
    flat, n = [], 0
    path = config.OUT_DIR / ("persona_specs.jsonl.gz" if args.all else "persona_specs_subset.jsonl.gz")
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in feats.to_dict("records"):
            spec = generate(row, lib, ov)
            if n % args.validate_every == 0:
                PersonaSpec.model_validate(spec)
            fh.write(json.dumps(spec, ensure_ascii=False) + "\n")
            flat.append(flatten(spec))
            n += 1
            if n % 20000 == 0:
                print(f"  {n:,} specs  ({time.perf_counter() - t0:.0f}s)")
    fl = pd.DataFrame(flat)
    fl.to_csv(config.OUT_DIR / "persona_specs_flat.csv", index=False)
    dist = distinctness(fl)
    (config.OUT_DIR / "distinctness.json").write_text(json.dumps(dist, indent=1, default=str), encoding="utf-8")
    print(f"{n:,} specs in {time.perf_counter() - t0:.0f}s -> {path}")
    print(json.dumps({k: v for k, v in dist.items() if not isinstance(v, dict)}, indent=1))


if __name__ == "__main__":
    main()
