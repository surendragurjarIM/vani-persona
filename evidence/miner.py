"""Evidence miner: which persona choices go with more meetings, for which sellers, and how sure we are.

    python -m evidence.miner   -> out/evidence.json (registry used by persona rules) + out/evidence_report.md

Every record compares choice A vs choice B on meeting-fix rate (or another stated outcome):
  n_a, n_b, rate_a, rate_b, diff (A-B, percentage points), 95% CI of diff, lift (A/B), strength.
Strength:
  strong    both arms n >= 500 and the 95% CI of the difference excludes 0
  moderate  both arms n >= 100 and the CI excludes 0
  weak      direction only (small n or CI includes 0)
  informed_guess  no direct data; reasoning stated in `note`
Comparisons that could be confounded (lead bucket, bot version) are stratified: per-stratum differences are
pooled with weights n_a*n_b/(n_a+n_b) (Cochran-Mantel-Haenszel style risk difference).
All effects are observational (correlational), not A/B tests. Each record says so in `caveat` where relevant.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from data.loader import load  # noqa: E402
from evidence.features import seller_segments  # noqa: E402

Z = 1.96
RECORDS: list[dict] = []


# ---------------- statistics ----------------

def wilson(k: float, n: int) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return (c - h, c + h)


def _diff_stats(ka, na, kb, nb):
    pa, pb = ka / na, kb / nb
    se = math.sqrt(pa * (1 - pa) / na + pb * (1 - pb) / nb)
    return pa - pb, se


def strength(na, nb, lo, hi) -> str:
    excl = lo > 0 or hi < 0
    if min(na, nb) >= 500 and excl:
        return "strong"
    if min(na, nb) >= 100 and excl:
        return "moderate"
    return "weak"


def compare(df: pd.DataFrame, a: pd.Series, b: pd.Series, *, eid: str, claim: str, choice_a: str, choice_b: str,
            segment: str = "all sellers", outcome: str = "meeting_fixed", strata: list[str] | None = None,
            source: str = "bot_calls", caveat: str = "", used_by: list[str] | None = None) -> dict:
    y = df[outcome].astype(float)
    na, nb = int(a.sum()), int(b.sum())
    ka, kb = float(y[a].sum()), float(y[b].sum())
    if na == 0 or nb == 0:
        rec = {"id": eid, "claim": claim, "strength": "weak", "note": "an arm is empty", "n_a": na, "n_b": nb}
        RECORDS.append(rec)
        return rec
    if strata:
        num = var = wsum = 0.0
        for _, g in df.groupby(strata, observed=True):
            ga, gb = a[g.index], b[g.index]
            n1, n2 = int(ga.sum()), int(gb.sum())
            if n1 < 5 or n2 < 5:
                continue
            d, se = _diff_stats(y[g.index][ga].sum(), n1, y[g.index][gb].sum(), n2)
            w = n1 * n2 / (n1 + n2)
            num += w * d
            var += (w * se) ** 2
            wsum += w
        diff, se = (num / wsum, math.sqrt(var) / wsum) if wsum else _diff_stats(ka, na, kb, nb)
    else:
        diff, se = _diff_stats(ka, na, kb, nb)
    lo, hi = diff - Z * se, diff + Z * se
    rec = {
        "id": eid, "claim": claim, "segment": segment, "choice_a": choice_a, "choice_b": choice_b,
        "outcome": outcome, "n_a": na, "n_b": nb, "rate_a": round(ka / na, 4), "rate_b": round(kb / nb, 4),
        "ci_a": [round(x, 4) for x in wilson(ka, na)], "ci_b": [round(x, 4) for x in wilson(kb, nb)],
        "diff_pp": round(100 * diff, 2), "diff_ci_pp": [round(100 * lo, 2), round(100 * hi, 2)],
        "lift": round((ka / na) / (kb / nb), 3) if kb else None, "stratified_by": strata or [],
        "strength": strength(na, nb, lo, hi), "source": source, "caveat": caveat, "used_by": used_by or [],
    }
    RECORDS.append(rec)
    return rec


def describe(eid: str, claim: str, table: pd.DataFrame, *, source: str, strength_: str, note: str = "",
             used_by: list[str] | None = None) -> dict:
    rec = {"id": eid, "claim": claim, "strength": strength_, "source": source, "note": note,
           "table": json.loads(table.round(4).to_json(orient="records")), "used_by": used_by or []}
    RECORDS.append(rec)
    return rec


def guess(eid: str, claim: str, note: str, used_by: list[str]) -> dict:
    rec = {"id": eid, "claim": claim, "strength": "informed_guess", "note": note, "used_by": used_by}
    RECORDS.append(rec)
    return rec


# ---------------- data prep ----------------

def prior_history(bc: pd.DataFrame) -> pd.DataFrame:
    """For each call, the seller's bot-call history strictly before it (no leakage of the call's own outcome)."""
    bc = bc.sort_values(["fk_glusr_usr_id", "call_start_time", "attempt_id"]).copy()
    lab = bc.disposition_label.fillna("")
    for col, name in [("Meeting Fixed", "mf"), ("Not Interested", "ni"), ("Call Later / Busy", "cl"),
                      ("General (talked)", "gen")]:
        bc[f"_{name}"] = (lab == col).astype(int)
    g = bc.groupby("fk_glusr_usr_id")
    for name in ["mf", "ni", "cl", "gen"]:
        bc[f"prior_{name}"] = g[f"_{name}"].cumsum() - bc[f"_{name}"]
    bc["prior_answered"] = g.cumcount()
    bc["prior_short"] = g["lead_call_duration"].transform(lambda s: (s < 15).astype(int).cumsum()) - \
        (bc.lead_call_duration < 15).astype(int)
    return bc.drop(columns=[c for c in bc.columns if c.startswith("_")])


def calls_with_sellers() -> pd.DataFrame:
    bc = prior_history(load("bot_calls"))
    s = load("sellers")
    seg = seller_segments(s)
    cols = ["fk_glusr_usr_id", "eng_enq_received_90d", "eng_cqs", "eng_pns_answered_90d", "eng_product_count",
            "asked_if_talking_to_bot", "showed_frustration", "already_in_touch_with_executive",
            "do_not_call_requested", "past_objections", "past_questions_asked", "seller_state"]
    df = bc.merge(seg, on="fk_glusr_usr_id", how="left").merge(s[cols], on="fk_glusr_usr_id", how="left")
    df["meeting_fixed"] = df.meeting_fixed.fillna(0).astype(int)
    return df.reset_index(drop=True)


# ---------------- evidence blocks ----------------

def seller_level(df: pd.DataFrame):
    print(f"[seller-level] {len(df):,} answered bot calls")
    base = df.meeting_fixed.mean()
    RECORDS.append({"id": "EV-00", "claim": "Baseline meeting-fix rate on answered bot calls", "strength": "strong",
                    "rate": round(base, 4), "n": len(df), "source": "bot_calls", "used_by": []})
    v = df.lead_bot_version
    compare(df, v.eq("personalis"), v.eq("main_vani"), eid="EV-01",
            claim="Personalised-script trial fixes more meetings than the one-size main_vani script",
            choice_a="personalised script", choice_b="main_vani script", strata=["redis_bucket"],
            caveat="Trial ran on a subset of dates; stratified by lead bucket.", used_by=["persona.overall"])
    att = df.call_attempt_count
    compare(df, att.eq(1), att.ge(4), eid="EV-02", claim="Meeting-fix rate collapses with repeated call attempts",
            choice_a="1st attempt", choice_b="4th+ attempt", strata=["redis_bucket"],
            used_by=["plan.opening", "tone.verbosity", "live.thresholds"])
    compare(df, df.prior_answered.ge(3) & df.prior_cl.ge(1), df.prior_answered.ge(3) & df.prior_cl.eq(0), eid="EV-03",
            claim="Sellers who earlier said 'call later' still convert on later calls at a different rate",
            choice_a="prior call-later", choice_b="no prior call-later", segment="sellers with 3+ prior answered calls",
            strata=["redis_bucket"], used_by=["plan.opening", "plan.escalation"])
    compare(df, df.prior_ni.ge(1), df.prior_answered.ge(1) & df.prior_ni.eq(0), eid="EV-04",
            claim="A prior 'not interested' lowers the chance of a meeting on the next call",
            choice_a="prior not-interested", choice_b="answered before, never NI", strata=["redis_bucket"],
            used_by=["plan.opening", "tone.empathy", "plan.objections"])
    compare(df, df.prior_short.ge(2), df.prior_answered.ge(2) & df.prior_short.eq(0), eid="EV-05",
            claim="Sellers who cut earlier calls short (<15s) rarely fix meetings: a long pitch won't reach them",
            choice_a="2+ prior calls <15s", choice_b="prior calls, none <15s", strata=["redis_bucket"],
            used_by=["plan.opening", "voice.pace", "tone.verbosity"])
    tb = df.turnover_band
    compare(df, tb.eq("large"), tb.eq("micro"), eid="EV-06",
            claim="The generic pitch converts larger businesses (1.5Cr+) worse than micro sellers",
            choice_a="turnover 1.5Cr+", choice_b="turnover 0-40L", strata=["redis_bucket"],
            used_by=["language.formality", "plan.opening", "voice.speaker"])
    compare(df, df.formal_entity.eq(1), df.formal_entity.eq(0), eid="EV-07",
            claim="Limited companies / partnerships respond worse to the default informal pitch",
            choice_a="Ltd/Partnership", choice_b="Proprietorship/other", strata=["redis_bucket"],
            used_by=["language.formality"])
    for i, (reg, label) in enumerate([("south_ta", "Tamil Nadu"), ("east_bn", "West Bengal"),
                                      ("west_gu", "Gujarat"), ("west_mh", "Maharashtra"),
                                      ("south_kn", "Karnataka"), ("south_te", "Telangana/AP")]):
        compare(df, df.region.eq(reg), df.region.eq("hindi_belt"), eid=f"EV-08{chr(97 + i)}",
                claim=f"Hindi-only VANI in {label} vs the Hindi belt",
                choice_a=label, choice_b="Hindi belt", strata=["redis_bucket"],
                caveat="Language mismatch is one of several possible reasons.",
                used_by=["language.primary", "voice.accent"])
    rb = df.redis_bucket
    describe("EV-09", "Meeting-fix rate by lead bucket (drives which opening hook to use)",
             df.groupby("redis_bucket").meeting_fixed.agg(n="size", mf_rate="mean").reset_index()
             .query("n >= 300").sort_values("mf_rate", ascending=False), source="bot_calls", strength_="strong",
             used_by=["plan.opening"])
    hr = df.hour
    compare(df, hr.isin([11, 12]), hr.isin([9, 10, 17, 18, 19]), eid="EV-10",
            claim="Late-morning calls (11-12) fix far fewer meetings than early-morning / evening calls",
            choice_a="11:00-12:59", choice_b="09-10 & 17-19", strata=["redis_bucket"],
            used_by=["plan.escalation"])
    eq = df.eng_enq_received_90d
    compare(df, eq.ge(10), eq.notna() & eq.lt(3), eid="EV-11",
            claim="Sellers receiving many buyer enquiries respond to an enquiry-led opening",
            choice_a="10+ enquiries in 90d", choice_b="<3 enquiries in 90d", strata=["redis_bucket"],
            used_by=["plan.opening", "plan.personalisation"])
    cqs = df.eng_cqs
    compare(df, cqs.lt(40), cqs.ge(70), eid="EV-12",
            claim="Low catalogue-quality sellers have a concrete catalogue-improvement reason to meet",
            choice_a="CQS < 40", choice_b="CQS >= 70", strata=["redis_bucket"],
            used_by=["plan.opening", "plan.personalisation"])
    compare(df, df.eng_known.eq(0), df.eng_known.eq(1), eid="EV-13",
            claim="Sellers with no engagement history (new / dormant)", choice_a="no engagement data",
            choice_b="engagement data", strata=["redis_bucket"], used_by=["confidence"])
    compare(df, df.asked_if_talking_to_bot.eq(1), df.asked_if_talking_to_bot.eq(0), eid="EV-14",
            claim="Sellers who asked 'am I talking to a bot?' convert differently",
            choice_a="asked if bot", choice_b="did not ask", strata=["redis_bucket"],
            caveat="Seller-level flag covers Apr-Sep incl. the call itself (descriptive).",
            used_by=["plan.opening", "guardrails.disclosure"])
    compare(df, df.already_in_touch_with_executive.eq(1), df.already_in_touch_with_executive.eq(0), eid="EV-15",
            claim="Sellers already in touch with an IndiaMART executive", choice_a="in touch with exec",
            choice_b="not in touch", strata=["redis_bucket"], caveat="Seller-level flag (descriptive).",
            used_by=["plan.escalation"])
    nob = df.biz_kind
    for i, kind in enumerate(["retailer", "manufacturer", "wholesaler", "service"]):
        compare(df, nob.eq(kind), ~nob.eq(kind), eid=f"EV-16{chr(97 + i)}", claim=f"{kind.title()}s vs everyone else",
                choice_a=kind, choice_b="others", strata=["redis_bucket"], used_by=["plan.opening", "tone.warmth"])
    # past objections parsed from the seller file
    po = df.past_objections.fillna("")
    for i, (cat, short) in enumerate([("Seller Unavailability", "unavailability"),
                                      ("Explicit Disinterest", "explicit_disinterest"),
                                      ("Existing Engagement", "existing_engagement"),
                                      ("Information / Trust", "trust")]):
        compare(df, po.str.contains(cat, regex=False), po.eq("") & df.prior_answered.ge(1), eid=f"EV-17{chr(97 + i)}",
                claim=f"Sellers whose past objection was '{cat}'", choice_a=f"past objection: {short}",
                choice_b="no recorded objection", strata=["redis_bucket"],
                caveat="Seller-level aggregate (descriptive).", used_by=["plan.objections"])


def call_level(cf: pd.DataFrame, ev: pd.DataFrame):
    print(f"[call-level] {len(cf):,} transcribed calls, {len(ev):,} signal events")
    pitched = cf[cf.opening_hook != "no_pitch"].reset_index(drop=True)
    st = ["redis_bucket", "lead_bot_version"]
    # opening hooks, overall and per segment
    for hook in ["enquiry_count", "enquiry_generic", "paid_services", "buylead", "profile_visibility", "catalogue",
                 "last_met", "demo_booked"]:
        h = pitched.opening_hook
        if h.eq(hook).sum() < 30:
            continue
        compare(pitched, h.eq(hook), ~h.eq(hook), eid=f"EV-20.{hook}", claim=f"Opening hook '{hook}' vs other hooks",
                choice_a=hook, choice_b="other hooks", strata=st, source="call_turns",
                caveat="Only calls where the pitch was delivered; hook partly follows lead type, so stratified.",
                used_by=["plan.opening"])
        for seg_col, seg_vals in [("turnover_band", ["micro", "small", "large"]),
                                  ("biz_kind", ["retailer", "manufacturer", "wholesaler", "service"])]:
            for sv in seg_vals:
                sub = pitched[pitched[seg_col] == sv].reset_index(drop=True)
                hh = sub.opening_hook
                if hh.eq(hook).sum() >= 60 and (~hh.eq(hook)).sum() >= 60:
                    compare(sub, hh.eq(hook), ~hh.eq(hook), eid=f"EV-20.{hook}.{sv}",
                            claim=f"Opening hook '{hook}' for {sv} sellers", choice_a=hook, choice_b="other hooks",
                            segment=f"{seg_col}={sv}", strata=st, source="call_turns", used_by=["plan.opening"])
    # The hook is the TRUE reason for the call and is fixed by lead bucket (PIM/PAM -> paid services,
    # PUA/OLP -> buy leads, UA/NUR -> category demand / catalogue / profile). A persona may only choose the
    # framing *within* a bucket, so compare framings inside each bucket.
    for b in ["UA", "NUR", "PUA", "PIM", "OLP"]:
        sub = pitched[pitched.redis_bucket == b].reset_index(drop=True)
        vc = sub.opening_hook.value_counts()
        for hook in vc[vc >= 60].index:
            if (sub.opening_hook != hook).sum() >= 60:
                compare(sub, sub.opening_hook.eq(hook), ~sub.opening_hook.eq(hook), eid=f"EV-20b.{b}.{hook}",
                        claim=f"Within lead bucket {b}: framing '{hook}' vs other framings", choice_a=hook,
                        choice_b="other framings", segment=f"redis_bucket={b}", strata=["lead_bot_version"],
                        source="call_turns", used_by=["plan.opening_hook"])
    # pitch length
    ps = pitched.pitch_sec
    compare(pitched, ps.le(10), ps.gt(14), eid="EV-21", claim="A short first pitch (<=10s) beats a long one (>14s)",
            choice_a="pitch <= 10s", choice_b="pitch > 14s", strata=st, source="call_turns",
            used_by=["plan.opening", "tone.verbosity"])
    rep = pitched[pitched.call_attempt_count.ge(3)].reset_index(drop=True)
    compare(rep, rep.pitch_sec.le(10), rep.pitch_sec.gt(14), eid="EV-21b",
            claim="Short pitch matters more for repeat-called sellers", segment="attempt >= 3",
            choice_a="pitch <= 10s", choice_b="pitch > 14s", strata=st, source="call_turns",
            used_by=["plan.opening", "tone.verbosity"])
    # bot pace
    w = pitched.bot_wps
    q1, q3 = w.quantile([0.25, 0.75])
    compare(pitched, w.le(q1), w.ge(q3), eid="EV-22", claim=f"Slower bot delivery (<= {q1:.2f} words/s) vs faster (>= {q3:.2f})",
            choice_a="slow pace", choice_b="fast pace", strata=st, source="call_turns",
            caveat="Pace varies little in the current bot (one TTS setting); weak contrast expected.",
            used_by=["voice.pace"])
    for tb in ["micro", "large"]:
        sub = pitched[pitched.turnover_band == tb].reset_index(drop=True)
        compare(sub, sub.bot_wps.le(q1), sub.bot_wps.ge(q3), eid=f"EV-22.{tb}", segment=f"turnover={tb}",
                claim=f"Pace effect for {tb} sellers", choice_a="slow pace", choice_b="fast pace", strata=st,
                source="call_turns", used_by=["voice.pace"])
    # pace on the pitch turn only: complete (not cut off) pitches, so content is comparable and
    # a hang-up cannot shorten the turn. Stratified by hook too (hook fixes the script content).
    turns = load("turns")
    pt = pitched[["attempt_id", "pitch_turn_no"]].merge(
        turns, left_on=["attempt_id", "pitch_turn_no"], right_on=["attempt_id", "turn_no"])
    pt["dur"] = pt.end_sec - pt.start_sec
    pt["words"] = pt.text.str.split().str.len()
    pt = pt[(~pt.text.str.rstrip().str.endswith(("...", "…"))) & (pt.words >= 15) & (pt.dur > 3)]
    pt["pitch_wps"] = pt.words / pt.dur
    pp = pitched.merge(pt[["attempt_id", "pitch_wps"]], on="attempt_id")
    pp = pp[pp.pitch_wps.between(1.5, 5.5)].reset_index(drop=True)
    a1, a3 = pp.pitch_wps.quantile([0.25, 0.75])
    st_h = st + ["opening_hook"]
    compare(pp, pp.pitch_wps.le(a1), pp.pitch_wps.ge(a3), eid="EV-22p",
            claim=f"Pitch delivered slower (<= {a1:.2f} words/s) vs faster (>= {a3:.2f}), complete pitches only",
            choice_a="slower pitch", choice_b="faster pitch", strata=st_h, source="call_turns",
            caveat="Pace differences come from TTS/script variation, not a designed test.", used_by=["voice.pace"])
    for tb in ["micro", "small", "large"]:
        sub = pp[pp.turnover_band == tb].reset_index(drop=True)
        compare(sub, sub.pitch_wps.le(a1), sub.pitch_wps.ge(a3), eid=f"EV-22p.{tb}", segment=f"turnover={tb}",
                claim=f"Pitch pace effect for {tb} sellers", choice_a="slower pitch", choice_b="faster pitch",
                strata=st_h, source="call_turns", used_by=["voice.pace"])
    for kind in ["retailer", "manufacturer", "wholesaler", "service"]:
        sub = pp[pp.biz_kind == kind].reset_index(drop=True)
        compare(sub, sub.pitch_wps.le(a1), sub.pitch_wps.ge(a3), eid=f"EV-22p.{kind}", segment=f"biz_kind={kind}",
                claim=f"Pitch pace effect for {kind}s", choice_a="slower pitch", choice_b="faster pitch",
                strata=st_h, source="call_turns", used_by=["voice.pace"])

    # language: who speaks English
    describe("EV-23", "Seller English share by segment (from what sellers actually said)",
             cf.groupby(["turnover_band", "region"]).agg(n=("attempt_id", "size"),
                                                          seller_en_share=("seller_en_share", "mean"))
             .reset_index().query("n >= 40").sort_values("seller_en_share", ascending=False),
             source="call_turns", strength_="moderate", used_by=["language.hinglish_mix", "language.primary"])
    talk = cf[cf.seller_words >= 8].reset_index(drop=True)
    compare(talk, talk.seller_en_share.ge(0.35), talk.seller_en_share.lt(0.15), eid="EV-23b",
            claim="English-leaning sellers get a Hindi-heavy bot today; their meeting-fix rate",
            choice_a="seller English share >= 35%", choice_b="< 15%", strata=st, source="call_turns",
            used_by=["language.hinglish_mix", "live.language_switch"])
    # signal presence -> outcome
    for s in ["frustration", "rush", "unavailable", "confusion", "interest", "not_interested"]:
        compare(cf, cf[f"sig_{s}"].eq(1), cf[f"sig_{s}"].eq(0), eid=f"EV-24.{s}",
                claim=f"Calls where the seller showed '{s}'", choice_a=f"{s} detected", choice_b=f"no {s}",
                strata=st, source="call_turns", caveat="Signals need seller speech, so they appear in longer calls.",
                used_by=[f"live.{s}"])
    # bot response after a signal -> outcome (the core live-adaptation evidence)
    first = ev.sort_values("turn_no").drop_duplicates(["attempt_id", "signal"]).merge(
        cf[["attempt_id", "redis_bucket", "lead_bot_version"]], on="attempt_id")
    first = first[first.bot_next.notna()].reset_index(drop=True)

    def after(sig, a, b, eid, claim, ca, cb, used):
        sub = first[first.signal == sig].reset_index(drop=True)
        if len(sub):
            compare(sub, a(sub), b(sub), eid=eid, claim=claim, choice_a=ca, choice_b=cb, strata=st,
                    source="call_turns", used_by=used,
                    caveat="Observational: what the bot happened to do next. Shows association, not cause.")

    after("rush", lambda d: d.bot_next_words.le(20), lambda d: d.bot_next_words.gt(35), "EV-25",
          "After the seller signals rush, a short reply (<=20 words) vs a long one (>35)",
          "short reply", "long reply", ["live.rush"])
    after("rush", lambda d: d.bot_next_slot_offer.eq(1), lambda d: d.bot_next_slot_offer.eq(0), "EV-25b",
          "After rush, offering a concrete slot vs not", "offers slot", "no slot", ["live.rush"])
    after("confusion", lambda d: d.bot_next_repeat.lt(0.3), lambda d: d.bot_next_repeat.ge(0.5), "EV-26",
          "After confusion, rephrasing (low overlap with previous turn) vs repeating the same words",
          "rephrase", "repeat", ["live.confusion"])
    after("confusion", lambda d: d.bot_next_words.le(20), lambda d: d.bot_next_words.gt(35), "EV-26b",
          "After confusion, a short simple reply vs a long one", "short reply", "long reply", ["live.confusion"])
    after("frustration", lambda d: d.bot_next_empathy.eq(1), lambda d: d.bot_next_empathy.eq(0), "EV-27",
          "After frustration, acknowledging it (empathy phrase) vs pushing on", "empathy", "no empathy",
          ["live.frustration"])
    after("frustration", lambda d: d.bot_next_words.le(20), lambda d: d.bot_next_words.gt(35), "EV-27b",
          "After frustration, a short reply vs a long one", "short reply", "long reply", ["live.frustration"])
    after("interest", lambda d: d.bot_next_slot_offer.eq(1), lambda d: d.bot_next_slot_offer.eq(0), "EV-28",
          "After interest, moving to a concrete slot vs not", "offers slot", "no slot", ["live.interest"])
    after("unavailable", lambda d: d.bot_next_slot_offer.eq(1), lambda d: d.bot_next_slot_offer.eq(0), "EV-28b",
          "When seller is unavailable, proposing a specific later slot vs not", "offers slot", "no slot",
          ["plan.escalation"])


def evaluator_level(cf: pd.DataFrame):
    bc = load("bot_calls")[["attempt_id", "meeting_fixed", "redis_bucket", "lead_bot_version", "lead_call_duration"]]
    lat = load("eval_latency_repetition").merge(bc, on="attempt_id")
    lat = lat[lat.lat_p50.notna()].reset_index(drop=True)
    print(f"[evaluator] latency calls {len(lat):,}")
    st = ["redis_bucket", "lead_bot_version"]
    compare(lat, lat.lat_p50.le(1.2), lat.lat_p50.ge(2.0), eid="EV-29",
            claim="Fast bot replies (median gap <=1.2s) vs slow (>=2s)", choice_a="fast reply", choice_b="slow reply",
            strata=st, source="eval_latency_repetition", used_by=["live.latency_budget"])
    compare(lat, lat.seller_had_to_repeat.fillna(0).ge(1), lat.seller_had_to_repeat.fillna(0).eq(0), eid="EV-29b",
            claim="Calls where the seller had to repeat themselves", choice_a="seller repeated", choice_b="no repeat",
            strata=st, source="eval_latency_repetition", used_by=["live.confusion"])
    compare(lat, lat.bot_repeat_count.fillna(0).ge(2), lat.bot_repeat_count.fillna(0).eq(0), eid="EV-29c",
            claim="Calls where the bot repeated itself 2+ times", choice_a="bot repeats", choice_b="no repeats",
            strata=st, source="eval_latency_repetition", used_by=["live.confusion", "guardrails.no_loop"])

    ob = load("eval_objections").merge(bc[["attempt_id", "meeting_fixed"]], on="attempt_id")
    describe("EV-30", "Objection category -> share of those calls that still ended in a meeting",
             ob.groupby("category").agg(n=("attempt_id", "nunique"), mf_rate=("meeting_fixed", "mean"))
             .reset_index().sort_values("n", ascending=False), source="eval_objections", strength_="moderate",
             used_by=["plan.objections"])
    q = load("eval_seller_questions").merge(bc, on="attempt_id")
    q = q[q.category != "gap"]
    describe("EV-31", "Question the seller asked -> meeting-fix rate of the call",
             q.groupby("category").agg(n=("attempt_id", "nunique"), mf_rate=("meeting_fixed", "mean")).reset_index()
             .query("n >= 50").sort_values("mf_rate", ascending=False), source="eval_seller_questions",
             strength_="moderate", used_by=["live.interest", "live.confusion"])
    disp = load("eval_disposition")
    d = disp.sub_disposition.value_counts(normalize=True).rename("share").reset_index()
    describe("EV-32", "Where calls are lost: sub-disposition shares (disposition evaluator)", d.head(12),
             source="eval_disposition", strength_="strong",
             note="dropped_after_indiamart_identity + dropped_mid_pitch = the opening is the biggest leak.",
             used_by=["plan.opening"])
    # pitch length -> mid-pitch drop
    dd = cf.merge(disp[["attempt_id", "sub_disposition"]], on="attempt_id")
    dd["drop_mid"] = dd.sub_disposition.isin(["dropped_mid_pitch", "dropped_after_indiamart_identity"]).astype(int)
    dd = dd[dd.opening_hook != "no_pitch"].reset_index(drop=True)
    compare(dd, dd.pitch_sec.gt(14), dd.pitch_sec.le(10), eid="EV-33", outcome="drop_mid",
            claim="Long first pitch (>14s) -> seller hangs up mid-pitch more often", choice_a="pitch > 14s",
            choice_b="pitch <= 10s", strata=st, source="eval_disposition+call_turns",
            used_by=["plan.opening", "tone.verbosity"])
    # where VANI fails to adapt today: evaluator "gaps" = seller turns the bot mishandled
    q_all = load("eval_seller_questions")
    gaps = q_all[q_all.category == "gap"].copy()
    reason = gaps.gap_reason.fillna("").str.lower()
    themes = {"busy / no time (rush)": r"busy|no time|not have time|time constraint|hurry",
              "repeated the pitch / ignored seller": r"repeat|ignor|same pitch|again",
              "confusion / clarification": r"confus|clarif|did not understand|didn't understand|unclear",
              "frustration": r"frustrat|irritat|annoy|angry|upset",
              "price / charges": r"price|pricing|cost|charge",
              "language": r"language|english|hindi|gujarati|tamil|marathi|bengali"}
    tbl = pd.DataFrame([{"theme": k, "gaps": int(reason.str.contains(v).sum()),
                         "share_of_gaps": round(float(reason.str.contains(v).mean()), 4)} for k, v in themes.items()])
    describe("EV-36", f"Where VANI mishandles the seller today ({len(gaps):,} evaluator-flagged turns)", tbl,
             source="eval_seller_questions (gaps)", strength_="strong",
             note="Seller turn types: " + ", ".join(f"{k} {v}" for k, v in
                                                     gaps.seller_turn_type.value_counts().items()),
             used_by=["live.rush", "live.confusion", "live.frustration", "plan.objections"])
    sq_calls = load("eval_seller_questions")[["attempt_id"]].drop_duplicates().merge(bc, on="attempt_id")
    sq_calls["had_gap"] = sq_calls.attempt_id.isin(gaps.attempt_id).astype(int)
    sq_calls = sq_calls.reset_index(drop=True)
    compare(sq_calls, sq_calls.had_gap.eq(1), sq_calls.had_gap.eq(0), eid="EV-37",
            claim="Calls where VANI mishandled a seller turn vs calls handled cleanly",
            choice_a="bot mishandled a turn", choice_b="no gap", strata=st, source="eval_seller_questions",
            caveat="Gaps need seller speech, so they occur in longer calls; read with EV-36.",
            used_by=["live.overall"])
    imf = load("eval_incorrect_mf")
    describe("EV-34", "Meetings marked fixed that the seller actually rejected (pushiness risk)",
             imf.seller_final_stance.value_counts(normalize=True).rename("share").reset_index(),
             source="eval_incorrect_mf", strength_="strong",
             note="Guardrail: never claim a meeting is fixed without explicit seller agreement.",
             used_by=["guardrails.confirmation"])
    ex = load("eval_execdrop").merge(cf[["attempt_id", "sig_frustration", "sig_rush"]], on="attempt_id")
    ex["seller_hung_up"] = ex.who_ended_call.eq("SELLER").astype(int)
    if len(ex) > 200:
        compare(ex, ex.sig_frustration.eq(1), ex.sig_frustration.eq(0), eid="EV-35", outcome="seller_hung_up",
                claim="Frustrated sellers hang up on the bot", choice_a="frustration", choice_b="none",
                source="eval_execdrop", used_by=["live.frustration"])


CONFOUNDED = {
    "EV-21": "Survivorship: a pitch only runs long when the seller lets it finish; hang-ups truncate it.",
    "EV-21b": "Same survivorship as EV-21.",
    "EV-33": "Same survivorship as EV-21 (a drop truncates the pitch).",
    "EV-22": "Whole-call pace mixes pitch with short confirmation turns typical of successful calls; see EV-22p.",
    "EV-22.micro": "See EV-22.", "EV-22.large": "See EV-22.",
    "EV-25": "Short bot replies after rush are mostly give-up closings; see EV-25b (slot offer).",
    "EV-26b": "Short replies after confusion include closings; direction not interpretable.",
    "EV-27b": "Short replies after frustration include closings; direction not interpretable.",
    "EV-29b": "Longer (successful) calls have more chances for a repeat: call-length confound.",
    "EV-29c": "Longer (successful) calls have more chances for bot repeats: call-length confound.",
    "EV-24.confusion": "Identity questions ('kaun bol rahe') occur in engaged calls; descriptive only.",
    "EV-20.demo_booked": "n=52; too small.",
}


def flag_confounded():
    for r in RECORDS:
        if r["id"] in CONFOUNDED:
            r["usable"], r["confound"] = False, CONFOUNDED[r["id"]]
        else:
            r.setdefault("usable", r.get("strength") != "weak")


def informed_guesses():
    guess("EV-G1", "Voice gender per seller type",
          "Every past call used one female voice ('Payal'), so the data cannot compare genders. We default to a warm "
          "female voice (matches the proven baseline) and use a measured male voice only for formal large-company "
          "personas, as a deliberate, low-confidence choice to be A/B tested.", ["voice.speaker"])
    guess("EV-G2", "Regional language for non-Hindi states",
          "Bot spoke Hindi/Hinglish only. EV-08* shows how those regions convert on Hindi; offering the regional "
          "language is an informed guess, so we start in Hinglish/English and switch only when the seller does.",
          ["language.primary", "live.language_switch"])
    guess("EV-G3", "Pitch/pace for confused sellers",
          "Bulbul pace can only be set per persona; past calls had nearly constant pace, so slowing down on "
          "confusion relies on EV-26 (rephrase) and EV-29b (repeat) plus standard call-centre practice.",
          ["live.confusion", "voice.pace"])


def report(path_md: Path):
    lines = ["# Evidence report\n", "Generated by `python -m evidence.miner`. Rates are meeting-fix rates unless stated. "
             "Strength: strong (n>=500 per arm, CI excludes 0), moderate (n>=100, CI excludes 0), weak, informed_guess.\n"]
    for r in RECORDS:
        lines.append(f"## {r['id']} · {r['claim']}  `[{r['strength']}]`")
        if "rate_a" in r:
            lines.append(f"- {r['choice_a']}: **{100 * r['rate_a']:.1f}%** (n={r['n_a']:,}) vs {r['choice_b']}: "
                         f"**{100 * r['rate_b']:.1f}%** (n={r['n_b']:,}) · diff {r['diff_pp']:+.1f} pp "
                         f"[{r['diff_ci_pp'][0]:+.1f}, {r['diff_ci_pp'][1]:+.1f}] · lift {r['lift']}"
                         + (f" · stratified by {', '.join(r['stratified_by'])}" if r.get("stratified_by") else ""))
            if r.get("segment") and r["segment"] != "all sellers":
                lines.append(f"- segment: {r['segment']}")
        if "rate" in r:
            lines.append(f"- rate {100 * r['rate']:.2f}% (n={r['n']:,})")
        if "table" in r:
            tbl = pd.DataFrame(r["table"])
            lines.append(tbl.to_markdown(index=False) if hasattr(tbl, "to_markdown") else tbl.to_string(index=False))
        if r.get("confound"):
            lines.append(f"- **Not used for rules (confounded):** {r['confound']}")
        for k in ("caveat", "note"):
            if r.get(k):
                lines.append(f"- _{r[k]}_")
        lines.append("")
    path_md.write_text("\n".join(lines), encoding="utf-8")


def main():
    df = calls_with_sellers()
    seller_level(df)
    cf = pd.read_parquet(config.CACHE_DIR / "call_features.parquet")
    ev = pd.read_parquet(config.CACHE_DIR / "signal_events.parquet")
    call_level(cf, ev)
    evaluator_level(cf)
    informed_guesses()
    flag_confounded()
    config.OUT_DIR.mkdir(exist_ok=True)
    out = {"generated_from": "PS07 dataset Apr-Sep 2026", "baseline_mf": RECORDS[0]["rate"],
           "strength_rules": __doc__.split("Strength:")[1].split("Comparisons")[0].strip(), "records": RECORDS}
    (config.OUT_DIR / "evidence.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float),
                                                  encoding="utf-8")
    report(config.OUT_DIR / "evidence_report.md")
    by = pd.Series([r["strength"] for r in RECORDS]).value_counts()
    print(f"\n{len(RECORDS)} evidence records -> out/evidence.json, out/evidence_report.md\n{by.to_string()}")
    for r in RECORDS:
        if "rate_a" in r:
            print(f"{r['id']:28s} {r['strength']:9s} {100 * r['rate_a']:5.1f}% vs {100 * r['rate_b']:5.1f}%  "
                  f"diff {r['diff_pp']:+5.1f}pp [{r['diff_ci_pp'][0]:+.1f},{r['diff_ci_pp'][1]:+.1f}] "
                  f"n={r['n_a']:,}/{r['n_b']:,}  {r['claim'][:60]}")


if __name__ == "__main__":
    main()
