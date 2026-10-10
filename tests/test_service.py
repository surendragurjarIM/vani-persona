"""Persona Service tests. Sarvam REST is mocked; nothing leaves the machine."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from service import settings


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    settings.DB_PATH = tmp_path_factory.mktemp("db") / "t.db"
    settings.REVIEW_QUEUE = tmp_path_factory.mktemp("rq") / "review_queue.csv"
    settings.WEBHOOK_TOKEN = "t0k"
    settings.ONSTART_TOKEN = "t0k"
    from service.app import app
    return TestClient(app)


def test_health(client):
    h = client.get("/health").json()
    assert h["ok"] and h["sellers"] == 149363 and len(h["agents"]) == 6


def test_route_demo_sellers(client):
    expect = {331550: "warm_hinglish", 98255184: "formal_hinglish", 2911154: "english_led"}
    for sid, variant in expect.items():
        r = client.get(f"/route/{sid}").json()
        assert r["variant"] == variant
        assert r["app_id"] == settings.AGENTS[variant]["app_id"]
        assert set(r["variables"]) >= {"call_reason", "language_style", "objection_priorities", "seller_history"}


def test_persona_has_reasons(client):
    s = client.get("/persona/331550").json()
    assert s["voice"]["pace"]["reason"] and s["rules_fired"]


def test_unknown_seller_404(client):
    assert client.get("/route/1").status_code == 404


def test_onstart_requires_token(client):
    assert client.post("/onstart", json={"seller_id": 331550}).status_code == 401
    r = client.post("/onstart", json={"seller_id": 331550}, headers={"X-Hook-Token": "t0k"})
    assert r.status_code == 200 and r.json()["persona_variant"] == "warm_hinglish"


def test_webhook_store_and_review_queue(client):
    payload = {"app_id": settings.AGENTS["warm_hinglish"]["app_id"], "app_version": 1, "attempt_id": "att-1",
               "campaign_id": "c1", "completion_status": "completed", "connectivity_status": "connected",
               "user_identifier": "331550", "user_phone_number": "+919800000000", "duration": 41.0,
               "interaction_id": "20261010/x", "retry_attempt": 0,
               "initial_agent_variables": {"seller_id": "331550", "persona_label": "Calm, friendly Hindi"},
               "output_agent_variables": {"call_outcome": "not_interested",
                                          "signals_detected": "frustration at turn 3: baar baar call",
                                          "switch_summary": ""},
               "interaction_transcript": [{"role": "user", "en_text": "Why do you keep calling"}]}
    assert client.post("/webhooks/sarvam?token=bad", json=payload).status_code == 401
    r = client.post("/webhooks/sarvam?token=t0k", json=payload).json()
    assert r["stored"] == "att-1" and r["queued_for_review"] is True
    assert "frustration" in settings.REVIEW_QUEUE.read_text(encoding="utf-8")


def test_stream_cohort_chunks_and_payload(monkeypatch):
    from service.sarvam_api import SarvamVA
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, json.loads(req.content), req.headers["X-API-Key"]))
        return httpx.Response(200, json={"cohort_id": "c", "status": "processing"})

    api = SarvamVA(api_key="k", transport=httpx.MockTransport(handler))
    users = [{"user_phone_number": f"98000{i:05d}", "app_variables": {"seller_id": str(i)}} for i in range(2500)]
    res = api.stream_cohort("camp-1", "vani", users)
    assert len(res) == 3 and [len(b["users"]) for _, b, _ in seen] == [1000, 1000, 500]
    assert seen[0][0].endswith("/campaigns/camp-1/cohorts/stream") and seen[0][2] == "k"


def test_console_and_search(client):
    r = client.get("/console", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/#talk"
    c = client.get("/api/console/config").json()
    assert len(c["demo_sellers"]) == 6 and c["org_id"]
    assert any(r["seller_city"] == "Morbi" for r in client.get("/api/sellers/search?q=Morbi").json())


def test_runtime_proxy_only_forwards_vani_agents(client):
    org, ws = settings.SARVAM_ORG_ID, settings.SARVAM_WORKSPACE_ID
    assert client.get(f"/sarvam-runtime/orgs/{org}/workspaces/{ws}/apps/someone-else/url").status_code == 403
    assert client.get("/sarvam-runtime/orgs/x/workspaces/y/campaigns").status_code == 403


def test_control_room_views(client):
    assert "<title>VANI</title>" in client.get("/").text
    o = client.get("/api/control/overview").json()
    assert o["numbers"]["sellers"] == 149363 and [s["n"] for s in o["steps"]] == [1, 2, 3, 4, 11, 12]
    tables = {t["name"]: t for t in client.get("/api/control/data").json()}
    assert tables["sellers"]["rows"] > 0 and client.get("/api/control/data/sellers?limit=3").json()["rows"]
    assert client.get("/api/control/data/..%2Fsecrets").status_code == 404
    assert len(client.get("/api/control/evidence").json()["records"]) == 145
    assert sum(client.get("/api/control/routing").json()["by_agent"].values()) == 149363
    assert "# VANI Persona Service" in client.get("/guide").text


def test_control_room_runs_the_switch_tool(client):
    r = client.post("/api/control/detect", json={"lines": ["haan ji", "confusion: kya bola? samjha nahi",
                                                           "busy hoon jaldi bolo"]}).json()
    assert [t["mode"] for t in r["turns"]] == ["base", "confusion", "rush"]
    assert r["turns"][1]["switches"][0]["source"] == "llm+keywords"


def test_control_room_sample_call_loop(client):
    assert client.post("/api/control/results/sample").json()["queued_for_review"] is True
    res = client.get("/api/control/results").json()
    assert res["results"][0]["attempt_id"].startswith("sample-") and res["review_queue"]
    assert client.delete("/api/control/results/sample").json()["removed"] >= 1
    assert client.post("/api/control/manual/gaps", json={"csv": "a,b\n1,2"}).status_code == 400
