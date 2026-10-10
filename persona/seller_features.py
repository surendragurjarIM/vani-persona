"""One feature row per seller: the seller file + that seller's own call history from the audited data.

Sources per seller
  seller file           profile, turnover, categories, engagement, bot-call history, past objections/questions
  bot_calls             latest lead bucket (decides the TRUE reason for calling), last call time
  call_features         what the seller actually said on transcribed calls: English share, signals shown
  evaluator (audited)   gaps on this seller's calls (what VANI mishandled), objections with quotes,
                        executive contact, latest disposition
  executive calls       answered calls from IndiaMART executives (Aug-Sep)

    python -m persona.seller_features   -> data/cache/seller_features.parquet
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from data.loader import load  # noqa: E402
from evidence.features import seller_segments  # noqa: E402

# lead bucket -> true reason for the call (as the real VANI script states it)
BUCKET_REASON = {
    "PIM": "paid_services", "PAM": "paid_services", "PANF": "paid_services", "PNCHF": "paid_services",
    "PUA": "buylead", "OLP": "buylead", "OLPR": "buylead",
    "SCHD": "callback",
}
GAP_THEMES = {"rush": r"busy|no time|time constraint|hurry|driving",
              "ignored_or_repeated": r"repeat|ignor|same pitch",
              "confusion": r"confus|clarif|did not understand|didn't understand|unclear",
              "frustration": r"frustrat|irritat|annoy|angry|upset",
              "price": r"price|pricing|cost|charge",
              "time_offered": r"suggested a time|provided a time|gave a time|specific time|preferred time|available on"}


def parse_counts(s) -> list[tuple[str, int]]:
    """'Cat A (2); Cat B (1)' -> [('Cat A', 2), ('Cat B', 1)]"""
    if not isinstance(s, str) or not s.strip():
        return []
    out = []
    for part in s.split(";"):
        m = re.match(r"\s*(.+?)\s*\((\d+)\)\s*$", part)
        if m:
            out.append((m.group(1), int(m.group(2))))
    return out


def build() -> pd.DataFrame:
    s = load("sellers")
    seg = seller_segments(s)
    f = s.merge(seg, on="fk_glusr_usr_id", how="left")

    bc = load("bot_calls").sort_values("call_start_time")
    last = bc.groupby("fk_glusr_usr_id").agg(last_bucket=("redis_bucket", "last"),
                                             last_version=("lead_bot_version", "last"),
                                             last_call=("call_start_time", "last"),
                                             short_calls=("lead_call_duration", lambda x: int((x < 15).sum())))
    f = f.merge(last, on="fk_glusr_usr_id", how="left")

    cf = pd.read_parquet(config.CACHE_DIR / "call_features.parquet")
    talk = cf[cf.seller_words >= 8]
    lang = talk.groupby("fk_glusr_usr_id").apply(
        lambda g: np.average(g.seller_en_share, weights=g.seller_words), include_groups=False).rename("own_en_share")
    sig_cols = [c for c in cf.columns if c.startswith("sig_") and not c.endswith("_turn")]
    sigs = cf.groupby("fk_glusr_usr_id")[sig_cols].max().add_prefix("hist_")
    ntx = cf.groupby("fk_glusr_usr_id").size().rename("n_transcribed_calls")
    f = f.merge(lang, on="fk_glusr_usr_id", how="left").merge(sigs, on="fk_glusr_usr_id", how="left") \
         .merge(ntx, on="fk_glusr_usr_id", how="left")

    q = load("eval_seller_questions")
    gaps = q[q.category == "gap"].copy()
    reason = gaps.gap_reason.fillna("").str.lower() + " " + gaps.seller_context.fillna("").str.lower()
    for k, rx in GAP_THEMES.items():
        gaps[f"gap_{k}"] = reason.str.contains(rx).astype(int)
    gagg = gaps.groupby("fk_glusr_usr_id").agg(
        n_gaps=("attempt_id", "size"), **{f"gap_{k}": (f"gap_{k}", "max") for k in GAP_THEMES})
    gex = gaps.dropna(subset=["que_dialogue", "suggested_reply"]).groupby("fk_glusr_usr_id").head(1) \
        .set_index("fk_glusr_usr_id")[["attempt_id", "que_dialogue", "ans_dialogue", "suggested_reply"]] \
        .rename(columns={"attempt_id": "gap_call", "que_dialogue": "gap_seller_said", "ans_dialogue": "gap_bot_said",
                         "suggested_reply": "gap_should_say"})
    f = f.merge(gagg, on="fk_glusr_usr_id", how="left").merge(gex, on="fk_glusr_usr_id", how="left")

    ob = load("eval_objections")
    oq = ob.dropna(subset=["quotes"]).groupby("fk_glusr_usr_id").agg(
        audited_objections=("category", lambda x: "; ".join(sorted(set(x)))),
        objection_quote=("quotes", lambda x: x.iloc[0].split(" | ")[0]))
    f = f.merge(oq, on="fk_glusr_usr_id", how="left")

    se = load("eval_se_contact")
    se = se[se.category.isin(["meeting_done", "in_touch_with_se"])].groupby("fk_glusr_usr_id").category.last() \
        .rename("exec_contact")
    disp = load("eval_disposition").merge(bc[["attempt_id", "call_start_time"]], on="attempt_id") \
        .sort_values("call_start_time").groupby("fk_glusr_usr_id").agg(
            last_disposition=("disposition", "last"), last_followup=("followup_when", "last"))
    ex = load("exec_calls")
    exa = ex[ex.status == "Answered"].groupby("fk_glusr_usr_id").size().rename("exec_answered_calls")
    f = f.merge(se, on="fk_glusr_usr_id", how="left").merge(disp, on="fk_glusr_usr_id", how="left") \
         .merge(exa, on="fk_glusr_usr_id", how="left")

    f["true_reason"] = f.last_bucket.map(BUCKET_REASON).fillna("category_demand")
    f["next_attempt"] = f.bot_attempts.fillna(0).astype(int) + 1
    f["business_age"] = 2026 - f.gst_registration_year
    f["obj_list"] = f.past_objections.map(lambda x: [c for c, _ in parse_counts(x)])
    f["q_list"] = f.past_questions_asked.map(lambda x: [c for c, _ in parse_counts(x)])
    f["disp_list"] = f.past_dispositions_detailed.map(lambda x: [c for c, _ in parse_counts(x)])
    f.to_parquet(config.CACHE_DIR / "seller_features.parquet", index=False)
    return f


def load_features() -> pd.DataFrame:
    p = config.CACHE_DIR / "seller_features.parquet"
    return pd.read_parquet(p) if p.exists() else build()


if __name__ == "__main__":
    f = build()
    print(f"{len(f):,} sellers, {f.shape[1]} features")
    for c in ["own_en_share", "n_gaps", "audited_objections", "exec_contact", "exec_answered_calls", "last_bucket"]:
        print(f"  {c:22s} filled for {f[c].notna().sum():>7,} sellers")
    print(f.true_reason.value_counts().to_string())
