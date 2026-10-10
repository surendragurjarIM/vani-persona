"""Project-wide paths, model ids and the Sarvam key (read from env or .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DATA_ROOT = ROOT.parent
DATASET_1 = DATA_ROOT / "Seller-Fit Adaptive Voice Persona - Dataset 1 of 3"
DATASET_2 = DATA_ROOT / "Seller-Fit Adaptive Voice Persona - Dataset 2 of 3"
DATASET_3 = DATA_ROOT / "Seller-Fit Adaptive Voice Persona - Dataset 3 of 3"
CACHE_DIR = ROOT / "data" / "cache"
OUT_DIR = ROOT / "out"

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")

# Model ids (confirmed against sarvamai SDK 0.1.36; smoke test picks the working ones)
LLM_OFFLINE = os.getenv("LLM_OFFLINE", "sarvam-105b")
LLM_LIVE = os.getenv("LLM_LIVE", "sarvam-105b-conversations")
STT_MODEL = os.getenv("STT_MODEL", "saaras:v4")
TTS_MODEL = os.getenv("TTS_MODEL", "bulbul:v4-flash")  # style voices; bulbul:v3 is the fallback


def require_key() -> str:
    if not SARVAM_API_KEY:
        raise SystemExit(f"SARVAM_API_KEY is not set. Put it in {ROOT / '.env'} as SARVAM_API_KEY=...")
    return SARVAM_API_KEY
