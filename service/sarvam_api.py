"""Minimal Sarvam Voice Agents REST client (docs: docs.sarvam.ai/conversations/api). Auth header X-API-Key."""
import time

import httpx

from service import settings


class SarvamError(RuntimeError):
    pass


class SarvamVA:
    def __init__(self, api_key: str | None = None, base: str | None = None, transport=None):
        self.key = api_key if api_key is not None else settings.SARVAM_VA_API_KEY
        self.base = (base or settings.SARVAM_BASE).rstrip("/")
        self.scope = f"v1/orgs/{settings.SARVAM_ORG_ID}/workspaces/{settings.SARVAM_WORKSPACE_ID}"
        self.http = httpx.Client(timeout=30, transport=transport)

    def _req(self, method: str, path: str, **kw) -> dict:
        if not self.key:
            raise SarvamError("SARVAM_VA_API_KEY is not set (dashboard -> Settings -> API Key)")
        for attempt in range(4):
            r = self.http.request(method, f"{self.base}/{path}", headers={"X-API-Key": self.key}, **kw)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise SarvamError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
            return r.json() if r.content else {}
        raise SarvamError(f"{method} {path} -> rate limited")

    # ---- campaigns & cohorts
    def list_campaigns(self) -> dict:
        return self._req("GET", f"scheduling/{self.scope}/campaigns")

    def create_campaign(self, *, name: str, app_id: str, app_version: int, start: str, end: str,
                        webhook_url: str | None = None, attempts_per_second: float = 0.5,
                        hours=("09:00", "20:00"), max_retries: int = 2) -> dict:
        app_config = {
            "app_id": app_id, "app_type": "agent", "app_version": app_version,
            "attempts_per_second": attempts_per_second,
            "connection_configs": [{"connection_id": settings.SARVAM_CONNECTION_ID,
                                    "phone_numbers": [settings.SARVAM_AGENT_NUMBER], "weight": 1}],
            "retry_config": {"max_retries": max_retries, "retry_interval_minutes": [120] * max_retries,
                             "retry_on": {"busy": {"enabled": True}, "no_answer": {"enabled": True}}},
        }
        if webhook_url:
            app_config["webhook_config"] = {"url": webhook_url, "metadata": {"source": "vani-persona"}}
        body = {"name": name, "app_config": app_config, "start_timestamp": start, "end_timestamp": end,
                "allowed_schedule": {"allowed_start_time": hours[0], "allowed_end_time": hours[1],
                                     "allowed_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                                      "Saturday"], "timezone": "Asia/Kolkata"}}
        return self._req("POST", f"scheduling/{self.scope}/campaigns", json=body)

    def stream_cohort(self, campaign_id: str, name: str, users: list[dict]) -> list[dict]:
        """users: [{user_phone_number, user_identifier, app_variables, app_overrides}] -> one response per 1000."""
        out = []
        for i in range(0, len(users), 1000):
            part = users[i:i + 1000]
            out.append(self._req("POST", f"scheduling/{self.scope}/campaigns/{campaign_id}/cohorts/stream",
                                 json={"name": f"{name}-{i // 1000 + 1}"[:50], "users": part}))
        return out

    # ---- single calls
    def instant_call(self, *, app_id: str, app_version: int, phone: str, variables: dict,
                     initial_language: str | None = None, webhook_url: str | None = None) -> dict:
        body = {"app_config": {"app_id": app_id, "app_version": app_version, "app_type": "agent",
                               "connection_config": {"connection_id": settings.SARVAM_CONNECTION_ID,
                                                     "agent_phone_number": settings.SARVAM_AGENT_NUMBER},
                               "agent_variables": variables},
                "user_config": {"user_phone_number": phone}}
        if initial_language:
            body["app_config"]["app_overrides"] = {"initial_language_name": initial_language}
        if webhook_url:
            body["webhook_config"] = {"url": webhook_url, "metadata": {"source": "vani-persona"}}
        return self._req("POST", f"outbounds/{self.scope}/outbounds", json=body)
