"""VANI Persona Service settings (env or .env). Sarvam Voice Agents ids come from the dashboard / agents.json."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402  (loads .env)

ROOT = config.ROOT
DB_PATH = Path(os.getenv("VANI_DB", config.OUT_DIR / "service.db"))
REVIEW_QUEUE = ROOT / "manual" / "inbox" / "review_queue.csv"

# Sarvam Voice Agents REST (different key from the speech APIs: dashboard -> Settings -> API Key)
SARVAM_VA_API_KEY = os.getenv("SARVAM_VA_API_KEY", "")
SARVAM_ORG_ID = os.getenv("SARVAM_ORG_ID", "01a110de-7159-7b40-a3eb-00943f7aa055")
SARVAM_WORKSPACE_ID = os.getenv("SARVAM_WORKSPACE_ID", "01a110de-715e-7fa2-9971-d8ed6286574c")
SARVAM_BASE = os.getenv("SARVAM_VA_BASE", "https://apps.sarvam.ai/api")

# Telephony (needed only to place calls): connection id + caller-id number from the dashboard
SARVAM_CONNECTION_ID = os.getenv("SARVAM_CONNECTION_ID", "")
SARVAM_AGENT_NUMBER = os.getenv("SARVAM_AGENT_NUMBER", "")

# Webhooks: Sarvam POSTs call results to {PUBLIC_BASE_URL}/webhooks/sarvam?token=WEBHOOK_TOKEN
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
# Shared secret Sarvam must send (header X-Hook-Token) when calling /onstart
ONSTART_TOKEN = os.getenv("ONSTART_TOKEN", WEBHOOK_TOKEN)

AGENTS = {k: v for k, v in json.loads((ROOT / "sarvam_agent" / "agents.json").read_text(encoding="utf-8")).items()
          if not k.startswith("_")}
# variant -> campaign_id, filled after campaigns are created (campaigns.json written by the service)
CAMPAIGNS_FILE = ROOT / "sarvam_agent" / "campaigns.json"


def campaigns() -> dict:
    return json.loads(CAMPAIGNS_FILE.read_text(encoding="utf-8")) if CAMPAIGNS_FILE.exists() else {}
