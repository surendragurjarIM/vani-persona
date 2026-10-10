"""VANI Persona Service: the brain next to Sarvam Voice Agents.

    uvicorn service.app:app --port 8080      then open http://localhost:8080 (control room)

GET  /                                  control room (service/control.py): every step, runnable, with the guide
GET  /health
GET  /persona/{seller_id}               full persona spec (reasons, evidence, confidence); ?enrich=true adds LLM rationale
GET  /route/{seller_id}                 which VANI agent + the 17 variables Sarvam needs for this seller
POST /onstart                           Sarvam on-start hook: {seller_id | user_phone_number} -> flat variables
POST /campaigns/{variant}/push          [{seller_id, phone}] -> stream into that variant's Sarvam campaign
POST /calls/outbound                    {seller_id, phone} -> instant Sarvam call with the routed agent + persona
POST /webhooks/sarvam?token=...         Sarvam call-end webhook -> store + review queue
GET  /results/summary                   meetings / callbacks / switches per persona agent
POST /admin/reload                      reload features, playbook and manual overrides (after the nightly job)
"""
import csv
import re

import httpx
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from service import control, feedback, settings, store
from service.engine import engine
from service.sarvam_api import SarvamError, SarvamVA

app = FastAPI(title="VANI Persona Service", version="1.0")
app.include_router(control.router)

# Exposed publicly (PUBLIC_BASE_URL set) without secrets would let anyone read personas or inject call results.
if settings.PUBLIC_BASE_URL and not (settings.WEBHOOK_TOKEN and settings.ONSTART_TOKEN):
    raise RuntimeError("PUBLIC_BASE_URL is set: WEBHOOK_TOKEN (and ONSTART_TOKEN) must be set too")
PHONES_FILE = settings.ROOT / "data" / "phones.csv"  # seller_id,phone supplied by IndiaMART (not in the dataset)


def _phone_index() -> dict:
    if not PHONES_FILE.exists():
        return {}
    with open(PHONES_FILE, encoding="utf-8") as fh:
        return {r["phone"][-10:]: int(r["seller_id"]) for r in csv.DictReader(fh)}


def _seller_or_404(seller_id: int):
    if not engine().has(seller_id):
        raise HTTPException(404, f"seller {seller_id} is not in the seller file")


def _webhook_url() -> str | None:
    if not settings.PUBLIC_BASE_URL:
        return None
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/sarvam?token={settings.WEBHOOK_TOKEN}"


@app.get("/health")
def health():
    e = engine()
    return {"ok": True, "sellers": int(len(e.features)), "agents": list(settings.AGENTS),
            "campaigns": settings.campaigns(), "manual_overrides": len(e.overrides),
            "sarvam_key_set": bool(settings.SARVAM_VA_API_KEY), "telephony_set": bool(settings.SARVAM_CONNECTION_ID)}


@app.get("/persona/{seller_id}")
def persona(seller_id: int, enrich: bool = False):
    _seller_or_404(seller_id)
    spec = engine().spec(seller_id)
    if enrich:
        from persona.llm_enrich import enrich as _enrich
        spec = _enrich(spec)
    return spec


@app.get("/route/{seller_id}")
def route(seller_id: int):
    _seller_or_404(seller_id)
    return engine().route(seller_id)


@app.post("/onstart")
def onstart(payload: dict = Body(...), x_hook_token: str | None = Header(default=None)):
    """Sarvam on-start hook: returns the persona variables as a flat JSON object for response mapping."""
    if settings.ONSTART_TOKEN and x_hook_token != settings.ONSTART_TOKEN:
        raise HTTPException(401, "bad hook token")
    sid = payload.get("seller_id")
    if not sid and payload.get("user_phone_number"):
        sid = _phone_index().get(str(payload["user_phone_number"])[-10:])
    if not sid or not engine().has(int(sid)):
        raise HTTPException(404, "unknown seller")
    r = engine().route(int(sid))
    return {**r["variables"], "persona_variant": r["variant"]}


@app.post("/campaigns/{variant}/push")
def push(variant: str, sellers: list[dict] = Body(...), cohort_name: str = Query("vani-batch")):
    """Stream sellers into the variant's campaign. Sellers routed to a different variant are returned, not pushed."""
    camp = settings.campaigns().get(variant)
    if not camp:
        raise HTTPException(400, f"no campaign registered for {variant}; create one with python -m service.jobs "
                                 f"create-campaigns")
    users, skipped = [], []
    for s in sellers:
        sid = int(s["seller_id"])
        if not engine().has(sid):
            skipped.append({"seller_id": sid, "reason": "unknown seller"})
            continue
        r = engine().route(sid)
        if r["do_not_call"]:
            skipped.append({"seller_id": sid, "reason": "do-not-call"})
            continue
        if r["variant"] != variant:
            skipped.append({"seller_id": sid, "reason": f"routes to {r['variant']}"})
            continue
        users.append({"user_phone_number": s["phone"], "user_identifier": str(sid), "app_variables": r["variables"],
                      "app_overrides": {"initial_language_name": r["initial_language"]}})
        store.record_push(seller_id=sid, phone=s["phone"], variant=variant, app_id=r["app_id"],
                          app_version=r["app_version"], campaign_id=camp, kind="campaign",
                          persona_label=r["persona_label"])
    resp = SarvamVA().stream_cohort(camp, cohort_name, users) if users else []
    return {"pushed": len(users), "skipped": skipped, "sarvam": resp}


@app.post("/calls/outbound")
def outbound(body: dict = Body(...)):
    sid = int(body["seller_id"])
    _seller_or_404(sid)
    r = engine().route(sid)
    if r["do_not_call"]:
        raise HTTPException(409, "seller asked not to be called")
    try:
        resp = SarvamVA().instant_call(app_id=r["app_id"], app_version=r["app_version"], phone=body["phone"],
                                       variables=r["variables"], initial_language=r["initial_language"],
                                       webhook_url=_webhook_url())
    except SarvamError as e:
        raise HTTPException(502, str(e))
    store.record_push(seller_id=sid, phone=body["phone"], variant=r["variant"], app_id=r["app_id"],
                      app_version=r["app_version"], attempt_id=resp.get("attempt_id"), kind="instant",
                      persona_label=r["persona_label"])
    return {"route": {k: r[k] for k in ("variant", "agent_name", "persona_label")}, "sarvam": resp}


@app.post("/webhooks/sarvam")
def webhook(payload: dict = Body(...), token: str = Query("")):
    if settings.WEBHOOK_TOKEN and token != settings.WEBHOOK_TOKEN:
        raise HTTPException(401, "bad token")
    row = store.record_result(payload)
    queued = feedback.queue_for_review(row)
    return {"stored": row["attempt_id"], "queued_for_review": queued}


@app.get("/results/summary")
def results():
    return store.summary()


@app.post("/admin/reload")
def reload():
    engine().reload()
    return {"reloaded": True, "manual_overrides": len(engine().overrides)}


# ---------------------------------------------------------------- Talk view data (browser voice on Sarvam)

DEMO = [("331550", "Noida micro service, 6th attempt"), ("97898477", "Sambhal jewellery wholesaler, rush-prone"),
        ("25144509", "Jaipur, short-call history"), ("98255184", "Morbi large wholesaler, Gujarati option"),
        ("2911154", "Chennai, speaks English"), ("66773609", "Chennai large firm, formal English")]


@app.get("/console")
def console_page():
    """The old console now lives in the single page at / (Talk view)."""
    return RedirectResponse("/#talk")


@app.get("/api/console/config")
def console_config():
    return {"org_id": settings.SARVAM_ORG_ID, "workspace_id": settings.SARVAM_WORKSPACE_ID,
            "voice_ready": bool(settings.SARVAM_VA_API_KEY), "demo_sellers": [
                {"seller_id": int(s), "note": n, "variant": engine().route(int(s))["variant"]} for s, n in DEMO]}


@app.get("/api/sellers/search")
def search(q: str = Query(..., min_length=2), limit: int = 20):
    f = engine().features
    if q.isdigit():
        hit = f[f.fk_glusr_usr_id.astype(str).str.startswith(q)]
    else:
        ql = q.lower()
        hit = f[f.seller_city.fillna("").str.lower().str.contains(ql, regex=False)
                | f.top_category_1.fillna("").str.lower().str.contains(ql, regex=False)]
    cols = ["fk_glusr_usr_id", "seller_city", "seller_state", "top_category_1", "annual_turnover", "business_type"]
    return [{k: (None if v != v else v) for k, v in r.items()} for r in hit[cols].head(limit).to_dict("records")]


_RUNTIME = "https://apps.sarvam.ai/api/app-runtime/"
_URL_PATH = re.compile(r"^orgs/([\w-]+)/workspaces/([\w-]+)/apps/([\w.-]+)/url$")


@app.get("/sarvam-runtime/{path:path}")
def runtime_proxy(path: str, request: Request):
    """The browser SDK fetches its signed WebSocket URL through here, so the API key stays on this server.
    Only the signed-URL route of our own VANI agents is forwarded."""
    m = _URL_PATH.match(path)
    allowed = {a["app_id"] for a in settings.AGENTS.values()}
    if not m or m.group(1) != settings.SARVAM_ORG_ID or m.group(2) != settings.SARVAM_WORKSPACE_ID \
            or m.group(3) not in allowed:
        raise HTTPException(403, "only VANI agent session URLs are proxied")
    if not settings.SARVAM_VA_API_KEY:
        raise HTTPException(503, "SARVAM_VA_API_KEY is not set (dashboard -> Settings -> API Key)")
    r = httpx.get(_RUNTIME + path, params=dict(request.query_params),
                  headers={"X-API-Key": settings.SARVAM_VA_API_KEY}, timeout=20)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")
