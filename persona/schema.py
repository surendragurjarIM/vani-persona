"""Persona spec schema. Every setting carries its value, a reason tied to seller data, the evidence ids behind it,
a confidence level, and where it came from (rule / default / manual review)."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


class Setting(BaseModel):
    value: Any
    reason: str
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = "low"
    source: str = "default"          # "default" | "rule:R-xx" | "manual:<reviewer>"


class Voice(BaseModel):
    speaker: Setting                 # Bulbul voice id
    gender: Setting
    accent: Setting
    pitch: Setting                   # realised through speaker register (Bulbul has no pitch control)
    pace: Setting                    # Bulbul pace 0.5-2.0
    style: Setting                   # sales / customer-warm / conversational / formal
    tts_model: Setting


class Language(BaseModel):
    primary: Setting                 # BCP-47 code used for TTS + LLM output
    english_share: Setting           # % English words in Hinglish output (0-100)
    formality: Setting               # low / medium / high
    address_form: Setting            # how VANI addresses the seller
    switch_option: Setting           # language VANI may switch to when the seller does


class Tone(BaseModel):
    warmth: Setting                  # 1-5
    empathy: Setting                 # 1-5
    assertiveness: Setting           # 1-5
    max_words_per_turn: Setting


class Plan(BaseModel):
    opening_hook: Setting
    opening_style: Setting           # standard / short-acknowledging / disclosure-first / exec-follow-up
    opening_line: Setting            # template rendered with personalisation slots
    personalisation: Setting         # list of {slot, value, why}
    objection_playbook: Setting      # ordered list of {objection, approach, example_line, evidence}
    escalation_rules: Setting        # list of {when, do}
    guardrails: Setting              # list of rules
    best_call_window: Setting


class LiveAdaptation(BaseModel):
    thresholds: Setting              # signal -> score needed to switch
    priority: Setting
    cooldown_turns: Setting
    language_switch_confirm_utterances: Setting
    known_history: Setting           # what happened on this seller's past calls (audited data)


class PersonaSpec(BaseModel):
    seller_id: int
    persona_label: str               # short human-readable name for the persona
    seller_snapshot: dict            # the seller facts the persona was built from
    voice: Voice
    language: Language
    tone: Tone
    conversation_plan: Plan
    live_adaptation: LiveAdaptation
    rules_fired: list[str]
    manual_overrides: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    overall_confidence: Confidence = "low"
    generator_version: str = "2026-10-09"
