"""Persona generator contract tests.   .venv/Scripts/python -m pytest tests -q"""
import re

import pytest

from persona.facts import ALLOWED_NUMBERS
from persona.generator import generate
from persona.rules import EVIDENCE
from persona.schema import PersonaSpec
from persona.seller_features import load_features

NON_EVIDENCE = {"COMPLIANCE", "signals_eval", "smoke_test"}


@pytest.fixture(scope="module")
def sample():
    f = load_features()
    picks = [f.sample(300, random_state=1),
             f[f.do_not_call_requested == 1].head(5), f[f.n_gaps >= 1].head(20), f[f.region == "south_ta"].head(20),
             f[f.turnover_band == "large"].head(20), f[f.bot_answered == 0].head(20)]
    import pandas as pd
    rows = pd.concat(picks).drop_duplicates("fk_glusr_usr_id").to_dict("records")
    return [generate(r, overrides=[]) for r in rows]


def _settings(spec):
    for sec in ("voice", "language", "tone", "conversation_plan", "live_adaptation"):
        for k, s in spec[sec].items():
            yield f"{sec}.{k}", s


def test_schema_valid(sample):
    for s in sample:
        PersonaSpec.model_validate(s)


def test_every_setting_has_reason_and_confidence(sample):
    for s in sample:
        for path, st in _settings(s):
            assert st["reason"].strip(), path
            assert st["confidence"] in ("high", "medium", "low"), path


def test_cited_evidence_exists_and_weak_evidence_is_low_confidence(sample):
    ev = EVIDENCE()
    for s in sample:
        for path, st in _settings(s):
            for e in st["evidence"]:
                if e in NON_EVIDENCE or e.startswith(("MG-", "manual_call:")):
                    continue
                assert e in ev, f"{path} cites unknown {e}"
            cited = [ev[e] for e in st["evidence"] if e in ev]
            if cited and st["confidence"] == "high" and st["source"].startswith("rule:"):
                assert any(c["strength"] == "strong" or c.get("usable") for c in cited), \
                    f"{path}: high confidence on unusable evidence {st['evidence']}"


def test_opening_line_adds_no_numbers(sample):
    for s in sample:
        line = s["conversation_plan"]["opening_line"]["value"]
        snap = s["seller_snapshot"]
        allowed = set(ALLOWED_NUMBERS) | {"10", "5"} | {str(snap.get("eng_enq_received_90d") or "")}
        for n in re.findall(r"\d+(?:,\d{3})*", line):
            assert n in allowed or n in str(snap.get("top_category_1")) or n in str(snap.get("seller_city")), \
                f"seller {s['seller_id']}: unexpected number {n} in opening"


def test_dnc_is_compliance_only(sample):
    for s in sample:
        if s["seller_snapshot"]["do_not_call_requested"] == 1:
            assert s["conversation_plan"]["opening_style"]["value"] == "compliance_only"


def test_missing_data_lowers_confidence(sample):
    for s in sample:
        if "annual_turnover" in s["missing_fields"] and "R-04" not in s["rules_fired"]:
            assert s["voice"]["pace"]["confidence"] in ("low", "medium")
