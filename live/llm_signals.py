"""LLM tier of the signal detector: reads the last bot turn + the seller's reply and scores the seller's state.

Used live (in parallel with reply generation) and offline to measure accuracy (evidence/signals_eval.py --llm).
Model: sarvam-105b-conversations (~0.3 s, no reasoning tokens).
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

SIGNALS = ["frustration", "confusion", "interest", "rush", "unavailable", "not_interested"]

SYSTEM = """You monitor a live phone call between VANI (an IndiaMART voice agent who wants to book a short meeting \
with a sales executive) and a seller. The seller speaks Hindi, Hinglish, English or a regional language.
Score the SELLER's state in their LAST reply only, each from 0 to 1:
- frustration: annoyed, angry, complains about repeated calls, wants calls to stop
- confusion: did not understand, asks who/what/why, asks to repeat, cannot hear, asks if it is a bot
- interest: asks price/charges/benefits/how it works, agrees to meet, gives a time or address
- rush: wants it quick, says busy / no time right now, asks to come to the point
- unavailable: out of station, not available on the proposed day, asks to call later or next week
- not_interested: refuses, no requirement, already has it
Also give language: the language the seller used in that reply (hi, en, hinglish, gu, ta, bn, mr, te, kn, pa, ml, other),
and quote: the 2-6 words of the seller that most justify the highest score.
Reply with ONLY one JSON object, no code fences:
{"frustration":0,"confusion":0,"interest":0,"rush":0,"unavailable":0,"not_interested":0,"language":"hinglish","quote":""}"""


def _client():
    from sarvamai import SarvamAI
    return SarvamAI(api_subscription_key=config.require_key())


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {s: float(d.get(s, 0) or 0) for s in SIGNALS}
    out["language"] = str(d.get("language", "")).lower()
    out["quote"] = str(d.get("quote", ""))
    return out


def classify(seller_text: str, last_bot: str = "", client=None, model: str | None = None) -> dict:
    c = client or _client()
    user = f'VANI said: "{last_bot[-400:]}"\nSeller replied: "{seller_text}"'
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    for attempt in range(5):
        try:
            r = c.chat.completions(messages=msgs, model=model or config.LLM_LIVE, temperature=0.0, max_tokens=120)
            return _parse(r.choices[0].message.content)
        except Exception as e:  # 429 rate limit -> back off; anything else -> give up, fast tier still works
            if "429" not in str(e) and "rate" not in str(e).lower():
                return {}
            time.sleep(0.5 * 2 ** attempt)
    return {}
