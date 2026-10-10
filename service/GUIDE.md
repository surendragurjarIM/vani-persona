# VANI Persona Service: how it works and how to use it

## What it is

Sarvam runs the phone calls. The Persona Service runs next to it and answers one question for every seller: **who should VANI be on this call?** It does that in four steps before calls and two after:

| # | Step | In one line | Reads | Writes |
|---|---|---|---|---|
| 1 | Mine evidence | Which choices fixed more meetings in 269k past calls | `data/cache/*.parquet` | `out/evidence.json` |
| 2 | Tune signal detector | How well keywords and the LLM spot rush, frustration, confusion, interest | audited seller turns | `out/signals_eval.json` |
| 3 | Generate personas | 23 rules turn each seller's data plus the evidence into a persona with reasons | seller features, evidence, manual overrides | `out/persona_specs.jsonl.gz` |
| 4 | Route and push | Pick one of six Sarvam agents and fill 17 variables | personas | `out/routing.csv`, Sarvam campaigns |
| 11 | Store results | Save each finished call from Sarvam; queue the ones a person should hear | Sarvam webhook | `out/service.db`, `manual/inbox/review_queue.csv` |
| 12 | Manual feed | Your team's corrections, which beat every automatic rule | `manual/inbox/manual_gaps.csv` | `out/manual_overrides.json` |

Steps 5 to 10 (the call itself, the live switch, language switching, call logs, the board) happen on Sarvam.

## Start it

1. Double-click **`start_control_room.bat`** in the `vani-persona` folder. A black window opens and stays open while the service runs.
2. After about 10 seconds the browser opens **http://localhost:8080**. If it doesn't, open that address yourself.
3. To stop the service, close the black window.

From PowerShell instead:

```
cd "...\Persona Files\vani-persona"
.\.venv\Scripts\python.exe -m uvicorn service.app:app --port 8080
```

The service loads all 149,363 sellers into memory at start (about 1 GB). Close other heavy programs if Windows is short of memory.

## A five-minute tour

The page has four views, in the bar at the top. **Guide** (this text) and **API** sit at the top right.

1. **Talk.** Click a demo seller, for example the small **Noida** seller, then the large **Morbi** wholesaler, and compare. Six tiles show what makes the two sound different: voice, pace, language, register, opening and turn length. Hover a tile to read the full reason; the dot is the confidence. **Every setting, reason and evidence** opens the full spec, and **What Sarvam receives** shows the 17 variables. Press **Talk to VANI** to speak to the matching agent through your microphone, and try being busy, annoyed or confused.
2. **Evidence.** The strongest findings from 2,69,455 past calls. Type `attempt` in the filter: first calls fix 16% of meetings, 4th-and-later calls 4%. That is why repeat-called sellers get short, acknowledging openings. The bars show how often the live switch tool changes mode on the right turn. **Try the switch tool** runs the same Python file that is uploaded to Sarvam; Hindi in Devanagari works, and a prefix like `confusion:` stands in for the LLM's guess.
3. **Pipeline.** The six steps from data to call and back, with when each last ran. **Where sellers go** shows how many sellers each Sarvam agent gets. **Run** starts a batch job; its log opens below. **Sarvam agents and settings** lists the six agents and their versions.
4. **Feedback.** Calls that came back, the review queue, and your corrections. **Add a sample call** shows the loop working locally.

## Common tasks

### Why did a seller get this setting?
Talk → choose the seller → hover the tile, or open **Every setting, reason and evidence**. Each line ends with the evidence ids, the confidence and the source: a rule such as `rule:R-02`, `default`, or `manual:<reviewer>`. Evidence ids can be found on the Evidence view.

### Change a persona setting for one seller, a segment, or everyone
1. Open **Feedback**. **Your corrections** shows the template with two example rows.
2. Edit or add a row. The important columns:
   - `persona_setting`, for example `tone.max_words_per_turn` or `live_adaptation.thresholds.rush`.
   - `recommended_value`.
   - `applies_to`: `seller:331550`, `segment:turnover_band=micro&region=west_gu`, or `all`.
   - `priority` from 1 to 5, and `reviewer`.
3. Press **Save**, then on **Pipeline** run **manual-ingest**.
4. Open the seller on **Talk**. The setting now shows `manual:<reviewer>` with high confidence.
5. To update every seller's routing, run **nightly**.

### Refresh everything after new data
Put new files in the dataset folders, then on **Pipeline** run **weekly-evidence** and then **nightly**. The page picks up the new personas when nightly finishes.

### Change how the live switch decides
The logic lives in `sarvam_agent/switch_tool_template.py`. The keywords come from `live/lexicon.py`.
1. Edit, then rebuild with `.\.venv\Scripts\python.exe -m sarvam_agent.build_switch_tool`.
2. Check it on **Evidence → Try the switch tool**, and run the tests with `.\.venv\Scripts\python.exe -m pytest -q tests`.
3. Upload the rebuilt `sarvam_agent/update_persona_mode.py` on each Sarvam agent (Tools → Upload Python file) and commit the agents.

### Place a call or push a campaign
Open **API** (top right, or http://localhost:8080/docs).
- `POST /calls/outbound` with `{"seller_id": 331550, "phone": "+91…"}` rings one number with the routed agent and persona.
- `POST /campaigns/{variant}/push` uploads sellers to an agent's campaign.

Both use Sarvam credits. Campaigns need a telephony connection on Sarvam, plus `SARVAM_CONNECTION_ID` in `.env`. For demos without telephony, use test calls on the Sarvam dashboard or **Talk to VANI** on the Talk view.

## Endpoints

| Endpoint | Who calls it | What it does |
|---|---|---|
| `GET /` | you | This page |
| `GET /persona/{id}` | you, this page | Full persona with reasons and evidence |
| `GET /route/{id}` | you, this page | Agent + 17 variables for that seller |
| `POST /onstart` | Sarvam, when a call starts | Returns the variables for the seller being called |
| `POST /campaigns/{variant}/push` | you, nightly | Sellers into a Sarvam campaign (1,000 per request; do-not-call skipped) |
| `POST /calls/outbound` | you | One call now |
| `POST /webhooks/sarvam?token=` | Sarvam, after each call | Store the result, queue for review |
| `GET /results/summary` | you | Meetings, callbacks and switches per agent |
| `POST /admin/reload` | nightly job | Reload personas without a restart |
| `GET /api/control/...` | this page | Everything the four views show |

## Where things are

| Path | What |
|---|---|
| `data/cache/` | The dataset as fast tables |
| `evidence/` | Step 1 and 2 code |
| `persona/` | Step 3: rules (`rules.py`), generator, voices, facts |
| `sarvam_agent/` | Step 4 mapping, agent prompt, switch tool, `agents.json` |
| `service/` | This service: `app.py` (API), `control.py` + `control/index.html` (this page), `jobs.py` (batch), `store.py` (results DB) |
| `manual/` | Manual feed: templates, inbox, ingest |
| `out/` | Everything the steps write |
| `tests/` | 26 automated tests |

## When something goes wrong

- **PowerShell says "CouldNotAutoLoadModule".** Start the command with `.\` like this: `.\.venv\Scripts\python.exe -m uvicorn ...`, or use the .bat file.
- **"Address already in use".** The service is already running in another window. Close it, or use `--port 8081`.
- **The black window closes, or the page stops answering.** Windows ran short of memory. Close other programs and start again.
- **Sarvam key missing.** Add `SARVAM_VA_API_KEY=` to `.env` (Sarvam dashboard → Settings → API Key) and restart.
- **The guide shows as plain text.** The page loads a small Markdown library from the internet. Offline, the text is still readable.

## Moving it off this machine

The service is one Docker image (`Dockerfile` in this folder) that needs the `data/cache` and `out` folders. In production it belongs in IndiaMART's cloud (see the architecture map). For a free hosted trial, a Hugging Face Space of type Docker can run the same image. That needs a Hugging Face account and the Sarvam key added as a Space secret.
