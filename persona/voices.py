"""Bulbul voice catalogue used by personas (all verified to synthesise in the smoke test, 2026-10-09).

Bulbul v3/v4 has no pitch knob, so a persona's "pitch" is realised by choosing a speaker whose natural register
fits (register: bright / mid / deep). Styles come from Sarvam's style-tuned v4-flash voices.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    id: str
    model: str
    gender: str       # female / male
    lang: str         # primary BCP-47 the voice is tuned for
    style: str        # sales / customer-warm / conversational / formal
    register: str     # pitch register: bright / mid / deep
    accent: str       # how it sounds to the seller


VOICES = {v.id: v for v in [
    # Hindi / Hinglish
    Voice("ritu_hi_sales", "bulbul:v4-flash", "female", "hi-IN", "sales", "bright", "neutral North Indian Hinglish"),
    Voice("ritu_hi_customer_warm", "bulbul:v4-flash", "female", "hi-IN", "customer-warm", "mid",
          "soft North Indian Hinglish"),
    Voice("simran_hi_sales", "bulbul:v4-flash", "female", "hi-IN", "sales", "bright", "energetic urban Hinglish"),
    Voice("aditya_hi_sales", "bulbul:v4-flash", "male", "hi-IN", "sales", "mid", "measured North Indian Hinglish"),
    Voice("shubh_hi_customer", "bulbul:v4-flash", "male", "hi-IN", "customer-warm", "deep", "calm Hindi"),
    # English-leaning
    Voice("simran_enhi_customer", "bulbul:v4-flash", "female", "en-IN", "customer-warm", "mid",
          "Indian English with Hindi ease"),
    Voice("shubh_enhi_banking", "bulbul:v4-flash", "male", "en-IN", "formal", "deep", "formal Indian English"),
    Voice("neha_en_customer", "bulbul:v4-flash", "female", "en-IN", "customer-warm", "mid", "neutral Indian English"),
    # Regional
    Voice("pooja_gu_customer", "bulbul:v4-flash", "female", "gu-IN", "customer-warm", "mid", "Gujarati"),
    Voice("bhavik_gu_conversation", "bulbul:v4-flash", "male", "gu-IN", "conversational", "mid", "Gujarati"),
    Voice("kavitha", "bulbul:v3", "female", "ta-IN", "conversational", "mid", "Tamil"),
    Voice("gokul_ta_narration", "bulbul:v4-flash", "male", "ta-IN", "formal", "deep", "Tamil"),
    Voice("roopa_bn_conversational", "bulbul:v4-flash", "female", "bn-IN", "conversational", "mid", "Bengali"),
    Voice("arnab_bn_conversation", "bulbul:v4-flash", "male", "bn-IN", "conversational", "mid", "Bengali"),
    Voice("ishita_mr_conversational", "bulbul:v4-flash", "female", "mr-IN", "conversational", "bright", "Marathi"),
    Voice("nilesh_mr_conversation", "bulbul:v4-flash", "male", "mr-IN", "conversational", "mid", "Marathi"),
    Voice("kavitha_te_conversation", "bulbul:v4-flash", "female", "te-IN", "conversational", "mid", "Telugu"),
    Voice("chaitra_kn_conversation", "bulbul:v4-flash", "female", "kn-IN", "conversational", "mid", "Kannada"),
    Voice("chetan_kn_conversation", "bulbul:v4-flash", "male", "kn-IN", "conversational", "mid", "Kannada"),
    Voice("anand_pa_conversation", "bulbul:v4-flash", "male", "pa-IN", "conversational", "mid", "Punjabi"),
]}

# (language, gender, style preference) -> voice id
REGIONAL = {
    "gu-IN": {"female": "pooja_gu_customer", "male": "bhavik_gu_conversation"},
    "ta-IN": {"female": "kavitha", "male": "gokul_ta_narration"},
    "bn-IN": {"female": "roopa_bn_conversational", "male": "arnab_bn_conversation"},
    "mr-IN": {"female": "ishita_mr_conversational", "male": "nilesh_mr_conversation"},
    "te-IN": {"female": "kavitha_te_conversation", "male": "kavitha_te_conversation"},
    "kn-IN": {"female": "chaitra_kn_conversation", "male": "chetan_kn_conversation"},
    "pa-IN": {"female": "anand_pa_conversation", "male": "anand_pa_conversation"},
}

LANG_NAMES = {"hi-IN": "Hindi/Hinglish", "en-IN": "English", "gu-IN": "Gujarati", "ta-IN": "Tamil", "bn-IN": "Bengali",
              "mr-IN": "Marathi", "te-IN": "Telugu", "kn-IN": "Kannada", "pa-IN": "Punjabi", "ml-IN": "Malayalam"}
