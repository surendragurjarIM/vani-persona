"""Build the configure_agent payloads for a VANI variant (variables, languages, voice, nudges, goal, intro)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from sarvam_agent.to_variables import INPUT_VARIABLE_DOCS, variables  # noqa: E402
from sarvam_agent.variants import LANGUAGES, VARIANTS, tts_config  # noqa: E402

OUTCOMES = ["meeting_fixed", "callback_scheduled", "not_interested", "do_not_call", "wrong_person",
            "already_in_touch", "no_conversation"]
MODES = ["baseline", "rush", "frustration", "confusion", "interest", "language"]


def agent_variables(defaults: dict) -> dict:
    av = {k: {"name": k, "value": defaults.get(k, ""), "description": d} for k, d in INPUT_VARIABLE_DOCS.items()}
    # mid-call: written by the agent's built-in update_variables tool on every persona switch
    av["persona_mode"] = {"name": "persona_mode", "value": "baseline", "type": "enum", "one_of": MODES,
                          "is_agent_updatable": True,
                          "description": "Current live delivery mode; changed by the agent on each persona switch"}
    av["switch_count"] = {"name": "switch_count", "value": 0, "type": "integer", "is_agent_updatable": True,
                          "description": "How many live persona switches happened in this call"}
    av["switch_log"] = {"name": "switch_log", "value": "", "is_agent_updatable": True, "needs_initial_value": False,
                        "description": "One line per live switch: turn, signal, the user's words, change made"}
    # post-call outputs
    av["call_outcome"] = {"name": "call_outcome", "value": "", "type": "enum", "one_of": OUTCOMES,
                          "needs_initial_value": False, "update_post_interaction": True,
                          "description": "How the call ended",
                          "post_interaction_prompt": "Classify the call outcome. meeting_fixed only if the user "
                          "explicitly agreed to a specific day and time for a meeting with the IndiaMART executive. "
                          "callback_scheduled if the user agreed to a specific callback time. do_not_call if the user "
                          "asked not to be called. wrong_person if the business owner was not reached. "
                          "already_in_touch if the user is already working with an IndiaMART executive and declined "
                          "a new meeting. no_conversation if the user never really engaged. Otherwise not_interested."}
    av["meeting_slot"] = {"name": "meeting_slot", "value": "", "needs_initial_value": False,
                          "update_post_interaction": True, "description": "Agreed meeting or callback day and time",
                          "post_interaction_prompt": "The day, time and place (or online) the user agreed to for "
                          "the meeting or callback, in the form: day, time, place. Empty if none was agreed."}
    av["signals_detected"] = {"name": "signals_detected", "value": "", "needs_initial_value": False,
                              "update_post_interaction": True, "description": "Seller signals seen in the call",
                              "post_interaction_prompt": "List each seller signal seen in the call from: rush, "
                              "frustration, confusion, interest, language switch, unavailable, not interested. For "
                              "each, give the turn and the user's words. Empty if none."}
    av["switch_summary"] = {"name": "switch_summary", "value": "", "needs_initial_value": False,
                            "update_post_interaction": True, "description": "Persona switches the agent made",
                            "post_interaction_prompt": "For each time the agent changed its delivery during the call "
                            "(shorter and faster to the point, apologetic and empathetic, simpler words, moved to "
                            "fixing a slot, changed language), write: turn, signal, what changed, and whether the "
                            "change matched what the user needed. Empty if the agent never changed delivery."}
    av["user_language"] = {"name": "user_language", "value": "", "needs_initial_value": False,
                           "update_post_interaction": True, "description": "Language(s) the user spoke",
                           "post_interaction_prompt": "The language or languages the user spoke, in order of use."}
    return av


def base_config(variant_key: str, defaults: dict) -> dict:
    v = VARIANTS[variant_key]
    defaults = dict(defaults, agent_name=v["agent_name"])
    return {
        "channel_type": "v2v",
        "llm_config": {"agent_config": {"agent_variables": agent_variables(defaults),
                                        "initial_state_name": "start", "is_single_prompt_mode": True}},  # mid-call update_variables is on by default
        "language_config": {"initial_language_name": v["initial_language"], "supported_languages": LANGUAGES,
                            "indic_language_style": "classic_colloquial_with_custom_code_mixed_words",
                            "custom_code_mixed_words": ["IndiaMART", "meeting", "executive", "buyer", "enquiry",
                                                        "buy leads", "catalogue", "profile", "online", "premium plan",
                                                        "GST", "category"]},
        "text_to_speech_config": tts_config(variant_key),
        "intro_message_config": {"audio": "Namaste, this is {{agent_name}} calling from IndiaMART. Am I speaking "
                                          "with the person who handles the {{seller_category}} business?"},
        "interaction_config": {"nudge_config": {
            "enable_inactivity_nudge": True, "end_interaction_after_consecutive_nudges": True,
            "user_nudge_message_configs": [
                {"nudge_type": "template", "timeout_seconds": 6,
                 "template_messages": ["Hello, can you hear me? This is IndiaMART calling."]},
                {"nudge_type": "template", "timeout_seconds": 8,
                 "template_messages": ["It seems this is not a good time. IndiaMART will call back later. Thank you."]}]}},
        "evaluation_config": {"criteria": [
            {"name": "Meeting fixed", "description": "The user agreed to a specific day and time for the meeting",
             "config": {"logic": "AND", "conditions": [{"variable": "call_outcome", "operator": "equals",
                                                        "value": "meeting_fixed"}]}}]},
    }


if __name__ == "__main__":
    variant = sys.argv[1]
    sid = int(sys.argv[2])
    spec = json.loads((config.OUT_DIR / "personas" / f"{sid}.json").read_text(encoding="utf-8"))
    _, defaults = variables(spec)
    out = config.OUT_DIR / "sarvam"
    out.mkdir(parents=True, exist_ok=True)
    cfg = base_config(variant, defaults)
    (out / f"config_{variant}.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(cfg, ensure_ascii=False))
