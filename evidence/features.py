"""Per-call conversational features from ps07_call_turns, joined to outcomes and seller profile.

    python -m evidence.features    -> data/cache/call_features.parquet, data/cache/signal_events.parquet

call_features: one row per transcribed call (opening hook, pitch length, bot pace, seller language mix,
               which signals fired and when, how the bot responded) + outcome + seller segment.
signal_events: one row per seller turn that fired a signal, with the bot's next turn characteristics.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from data.loader import load  # noqa: E402
from live.lexicon import EMPATHY_RE, SLOT_OFFER_RE, detect  # noqa: E402

SIGNALS = ["frustration", "rush", "unavailable", "confusion", "interest", "not_interested"]
FIRE = 0.6  # fast-tier score at which a signal counts as present

HOOKS = [  # first match wins; order = specificity
    ("last_met", r"pichhli baar|pichli baar|pehle baat|last time|aapse mile|mulaqat|meeting hui thi"),
    ("enquiry_count", r"\d+\s*(?:se zyada|se jyada|\+)?\s*(?:buyer )?(?:enquir|inquir)"),
    ("demo_booked", r"demo book|demo liya|demo request"),
    ("paid_services", r"paid (?:service|package|plan)|premium|subscription"),
    ("buylead", r"buy ?lead|buylead"),
    ("catalogue", r"catalog|catalogue|product(?:s)? (?:list|photo|update)"),
    ("profile_visibility", r"profile|visibility|ranking|listing"),
    ("enquiry_generic", r"enquir|inquir|buyer"),
]
HOOK_RX = [(h, re.compile(p, re.I)) for h, p in HOOKS]


def _words(s: str) -> int:
    return len(s.split())


def _jaccard(a: str, b: str) -> float:
    A, B = set(re.findall(r"[a-z]+", a.lower())), set(re.findall(r"[a-z]+", b.lower()))
    return len(A & B) / max(1, len(A | B))


def _hook(text: str) -> str:
    for h, rx in HOOK_RX:
        if rx.search(text):
            return h
    return "no_pitch"  # call ended before any proposition was made


def call_features(turns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, events = [], []
    for aid, g in turns.groupby("attempt_id", sort=False):
        g = g[g.speaker.isin(["bot", "seller"])]
        bot, sel = g[g.speaker == "bot"], g[g.speaker == "seller"]
        if bot.empty:
            continue
        # pitch = first bot turn with >= 15 words (the main proposition)
        long_bot = bot[bot.text.map(_words) >= 15]
        pitch = long_bot.iloc[0] if len(long_bot) else bot.iloc[0]
        opening_text = " ".join(bot.text.head(3))
        dur = (bot.end_sec - bot.start_sec).clip(lower=0.1)
        wps = (bot.text.map(_words) / dur)
        wps = wps[(dur > 1.5) & (wps < 6)]  # drop truncated turns / bad timestamps
        sel_txt = " ".join(sel.text)
        en_share, n_sel_words = 0.0, 0
        if len(sel):
            d_all = detect(sel_txt)
            en_share, n_sel_words = d_all.english_share, d_all.n_words

        r = {"attempt_id": aid, "n_turns": len(g), "n_seller_turns": len(sel),
             "opening_hook": _hook(opening_text), "pitch_words": _words(pitch.text),
             "pitch_sec": float(pitch.end_sec - pitch.start_sec), "pitch_turn_no": int(pitch.turn_no),
             "bot_wps": float(wps.median()) if len(wps) else np.nan,
             "bot_words_per_turn": float(bot.text.map(_words).mean()),
             "seller_words_per_turn": float(sel.text.map(_words).mean()) if len(sel) else 0.0,
             "seller_en_share": en_share, "seller_words": n_sel_words,
             "first_seller_reply": sel.text.iloc[0] if len(sel) else "",
             "call_sec": float(g.end_sec.max())}
        for s in SIGNALS:
            r[f"sig_{s}"] = 0
            r[f"sig_{s}_turn"] = np.nan

        # walk seller turns -> signals -> bot's next turn
        g = g.reset_index(drop=True)
        prev_bot = ""
        for i, t in g.iterrows():
            if t.speaker == "bot":
                prev_bot = t.text
                continue
            d = detect(t.text)
            fired = [s for s, v in d.scores.items() if v >= FIRE]
            if not fired:
                continue
            nxt = g.iloc[i + 1:]
            nxt = nxt[nxt.speaker == "bot"]
            nb = nxt.iloc[0].text if len(nxt) else None
            for s in fired:
                if not r[f"sig_{s}"]:
                    r[f"sig_{s}"], r[f"sig_{s}_turn"] = 1, int(t.turn_no)
                events.append({
                    "attempt_id": aid, "turn_no": int(t.turn_no), "t_sec": float(t.start_sec), "signal": s,
                    "score": d.scores[s], "matched": "; ".join(d.matches[s]), "seller_text": t.text,
                    "bot_next": nb, "bot_next_words": _words(nb) if nb else np.nan,
                    "bot_next_empathy": int(bool(nb and EMPATHY_RE.search(nb))),
                    "bot_next_slot_offer": int(bool(nb and SLOT_OFFER_RE.search(nb))),
                    "bot_next_repeat": float(_jaccard(nb, prev_bot)) if nb and prev_bot else np.nan,
                    "call_ended_after": int(nb is None),
                })
        rows.append(r)
    return pd.DataFrame(rows), pd.DataFrame(events)


def seller_segments(s: pd.DataFrame) -> pd.DataFrame:
    """Coarse, explainable seller segments used by both evidence and the persona rules."""
    out = s[["fk_glusr_usr_id"]].copy()
    big = {"1.5 - 5 Cr", "5 - 25 Cr", "25 - 100 Cr", "100 - 500 Cr", "> 500 Cr"}
    out["turnover_band"] = np.select(
        [s.annual_turnover.isin(["0 - 40 L"]), s.annual_turnover.isin(["40 L - 1.5 Cr"]), s.annual_turnover.isin(big)],
        ["micro", "small", "large"], "unknown")
    nob = s.nature_of_business.fillna("")
    out["biz_kind"] = np.select(
        [nob.str.contains("Manufacturer"), nob.str.contains("Retail"), nob.str.contains("Wholesal|Distribut"),
         nob.str.contains("Service|Exporter|Importer")], ["manufacturer", "retailer", "wholesaler", "service"], "other")
    out["formal_entity"] = s.business_type.isin(["Limited Company", "Partnership"]).astype(int)
    region = {"Gujarat": "west_gu", "Maharashtra": "west_mh", "Goa": "west_mh",
              "Tamil Nadu": "south_ta", "Puducherry": "south_ta", "Karnataka": "south_kn", "Kerala": "south_ml",
              "Telangana": "south_te", "Andhra Pradesh": "south_te", "West Bengal": "east_bn",
              "Odisha": "east_od", "Assam": "east_as", "Punjab": "north_pa", "Chandigarh": "north_pa"}
    out["region"] = s.seller_state.map(region).fillna("hindi_belt")
    out["eng_known"] = s.eng_call_attempts_90d.notna().astype(int)
    return out


def build():
    turns, bc, sellers = load("turns"), load("bot_calls"), load("sellers")
    print(f"turns: {len(turns):,} rows, {turns.attempt_id.nunique():,} calls")
    cf, ev = call_features(turns)
    seg = seller_segments(sellers)
    keep = ["attempt_id", "fk_glusr_usr_id", "lead_bot_version", "redis_bucket", "call_attempt_count", "hour",
            "lead_call_duration", "disposition_label", "meeting_fixed"]
    cf = cf.merge(bc[keep], on="attempt_id", how="inner").merge(seg, on="fk_glusr_usr_id", how="left")
    ev = ev.merge(cf[["attempt_id", "meeting_fixed", "disposition_label"]], on="attempt_id", how="inner")
    cf.to_parquet(config.CACHE_DIR / "call_features.parquet", index=False)
    ev.to_parquet(config.CACHE_DIR / "signal_events.parquet", index=False)
    print(f"call_features: {len(cf):,} calls · signal_events: {len(ev):,}")
    print(cf.opening_hook.value_counts().to_string())
    print(cf[[f"sig_{s}" for s in SIGNALS]].mean().round(3).to_string())
    print(cf[["pitch_sec", "pitch_words", "bot_wps", "seller_en_share"]].describe().round(2).to_string())


if __name__ == "__main__":
    build()
