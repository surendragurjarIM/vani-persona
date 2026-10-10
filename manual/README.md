# Manual feed: your reviewed calls and gaps (highest priority)

Use this folder to teach VANI from calls **your team has listened to**. Anything here outranks the automatic
evidence: manual overrides are applied after every rule, are marked `source: manual:<reviewer>`, and get
`confidence: high` in the persona spec. They also feed live switching (thresholds, guardrails, escalation, and
example turns for the signal detector).

## What to drop in

| File | One row per | Required columns |
|---|---|---|
| `inbox/manual_calls.csv` | call you reviewed | `call_id`, `source` (`transcript` or `recording`), and `transcript_file` or `recording_url_or_file` |
| `inbox/manual_gaps.csv` | moment VANI got wrong (or a rule you want) | `gap_id`, `persona_setting`, `recommended_value`, `applies_to`, `priority`, `reviewer` |
| `inbox/transcripts/<call_id>.csv` | turn of a call | `turn_no, speaker (bot/seller), start_sec, end_sec, text` |
| `inbox/recordings/<call_id>.mp3` | your own recording (optional) | listed in `manual_calls.csv` with `source=recording` |

Copy the examples from `templates/` to start.

### `manual_gaps.csv` columns
- `seller_said`, `vani_said`, `should_have_said`: what happened and what VANI should say. These become examples
  for the objection playbook and few-shot examples for the live signal detector.
- `signal`: `frustration | confusion | interest | rush | unavailable | not_interested | language | other`.
- `tone_heard`: what you heard in the voice (e.g. "irritated, fast"). Text transcripts can't capture tone, so this
  is where listening adds value.
- `persona_setting`: the setting to change. Any spec path works, e.g. `voice.pace`, `voice.gender`,
  `language.primary`, `language.english_share`, `tone.max_words_per_turn`, `tone.empathy`,
  `conversation_plan.opening_style`, `conversation_plan.guardrails`, `conversation_plan.escalation_rules`,
  `live_adaptation.thresholds.<signal>`.
- `recommended_value`: the new value (number or text).
- `applies_to`: `seller:<glid>` (one seller), `segment:<feature>=<value>&<feature>=<value>` (e.g.
  `segment:turnover_band=micro&region=west_gu`), or `all`.
- `priority`: 1-5. Higher wins when two manual rows touch the same setting. All manual rows beat automatic rules.

## Run

```
.venv/Scripts/python -m manual.ingest              # validate + build out/manual_overrides.json
.venv/Scripts/python -m manual.ingest --transcribe # also transcribe recordings via Sarvam batch STT (diarized)
.venv/Scripts/python -m persona.cli --all          # regenerate personas with the overrides applied
```

`manual.ingest` reports every row it rejected and why. Transcribed recordings are saved as
`inbox/transcripts/<call_id>.csv` in the same turn format, so they also join the signal-detector evaluation.
