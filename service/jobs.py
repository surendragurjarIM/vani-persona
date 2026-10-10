"""Batch jobs for the VANI Persona Service.

    python -m service.jobs nightly            refresh features -> manual overrides -> all personas -> routing table
    python -m service.jobs route-table        routing table only (variant per seller) -> out/routing.csv
    python -m service.jobs create-campaigns --start 2026-10-12T03:30:00Z --end 2026-10-19T14:30:00Z
                                              one Sarvam campaign per persona agent -> sarvam_agent/campaigns.json
    python -m service.jobs push --phones data/phones.csv [--variant formal_hinglish] [--limit 1000]
                                              stream routed sellers (with phone numbers) into their campaigns
    python -m service.jobs weekly-evidence    rerun the evidence miner (adds Sarvam call results when present)
"""
import argparse
import csv
import gzip
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from sarvam_agent.to_variables import variables  # noqa: E402
from sarvam_agent.variants import VARIANTS  # noqa: E402
from service import settings, store  # noqa: E402
from service.sarvam_api import SarvamVA  # noqa: E402

PY = sys.executable


def run(*args):
    print("$", " ".join(args), flush=True)
    subprocess.run([PY, "-m", *args], check=True, cwd=settings.ROOT)


def route_table():
    """Variant + agent for every seller, from the latest persona specs."""
    counts, path = Counter(), config.OUT_DIR / "routing.csv"
    with gzip.open(config.OUT_DIR / "persona_specs.jsonl.gz", "rt", encoding="utf-8") as fh, \
            open(path, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["seller_id", "variant", "app_id", "app_version", "initial_language", "persona_label",
                    "do_not_call"])
        for line in fh:
            spec = json.loads(line)
            variant, _ = variables(spec)
            dnc = spec["conversation_plan"]["opening_style"]["value"] == "compliance_only"
            a = settings.AGENTS[variant]
            w.writerow([spec["seller_id"], variant, a["app_id"], a["committed_version"],
                        VARIANTS[variant]["initial_language"], spec["persona_label"], int(dnc)])
            counts["do_not_call" if dnc else variant] += 1
    print(f"routing table -> {path}\n" + "\n".join(f"  {k:18s} {v:>7,}" for k, v in counts.most_common()))


def nightly():
    t = time.time()
    run("persona.seller_features")                 # refresh per-seller features (new calls, audits)
    if (settings.ROOT / "manual" / "inbox" / "manual_gaps.csv").exists():
        run("manual.ingest")                       # reviewer overrides outrank automatic rules
    run("persona.cli", "--all")                    # all personas + distinctness
    route_table()
    print(f"nightly done in {time.time() - t:.0f}s. Running service picks it up via POST /admin/reload")


def create_campaigns(start: str, end: str):
    api, out = SarvamVA(), settings.campaigns()
    hook = (f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/sarvam?token={settings.WEBHOOK_TOKEN}"
            if settings.PUBLIC_BASE_URL else None)
    for variant, a in settings.AGENTS.items():
        if variant in out:
            continue
        r = api.create_campaign(name=f"VANI {variant} {start[:10]}", app_id=a["app_id"],
                                app_version=a["committed_version"], start=start, end=end, webhook_url=hook)
        out[variant] = r["campaign_id"]
        print(variant, "->", r["campaign_id"], r.get("status"))
    settings.CAMPAIGNS_FILE.write_text(json.dumps(out, indent=1), encoding="utf-8")


def push(phones_file: str, variant: str | None, limit: int):
    phones = {}
    with open(phones_file, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            phones[int(r["seller_id"])] = r["phone"]
    camps, groups = settings.campaigns(), defaultdict(list)
    with gzip.open(config.OUT_DIR / "persona_specs.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            spec = json.loads(line)
            sid = spec["seller_id"]
            if sid not in phones or spec["conversation_plan"]["opening_style"]["value"] == "compliance_only":
                continue
            v, vars_ = variables(spec)
            if variant and v != variant:
                continue
            groups[v].append({"user_phone_number": phones[sid], "user_identifier": str(sid),
                              "app_variables": vars_,
                              "app_overrides": {"initial_language_name": VARIANTS[v]["initial_language"]},
                              "_label": spec["persona_label"]})
    api = SarvamVA()
    for v, users in groups.items():
        users = users[:limit]
        if v not in camps:
            print(f"skip {v}: no campaign (run create-campaigns)")
            continue
        for u in users:
            store.record_push(seller_id=int(u["user_identifier"]), phone=u["user_phone_number"], variant=v,
                              app_id=settings.AGENTS[v]["app_id"], app_version=settings.AGENTS[v]["committed_version"],
                              campaign_id=camps[v], kind="campaign", persona_label=u.pop("_label"))
        res = api.stream_cohort(camps[v], f"vani-{v}-{time.strftime('%m%d%H%M')}", users)
        print(v, len(users), "->", [x.get("status") for x in res])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=["nightly", "route-table", "create-campaigns", "push", "weekly-evidence"])
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--phones")
    ap.add_argument("--variant")
    ap.add_argument("--limit", type=int, default=100000)
    a = ap.parse_args()
    if a.job == "nightly":
        nightly()
    elif a.job == "route-table":
        route_table()
    elif a.job == "create-campaigns":
        create_campaigns(a.start, a.end)
    elif a.job == "push":
        push(a.phones, a.variant, a.limit)
    elif a.job == "weekly-evidence":
        run("evidence.features")
        run("evidence.miner")
        run("evidence.signals_eval")
        run("evidence.switch_replay")


if __name__ == "__main__":
    main()
