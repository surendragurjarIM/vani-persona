"""The Sarvam code tool update_persona_mode, run against the SDK's own context objects."""
import asyncio

import pytest

pytest.importorskip("sarvam_conv_ai_sdk")
from sarvam_conv_ai_sdk import EngagementMetadata, SarvamToolContext  # noqa: E402

from live.lexicon import SIGNAL_PATTERNS  # noqa: E402
from sarvam_agent import build_switch_tool  # noqa: E402

build_switch_tool.build()
from sarvam_agent import update_persona_mode as tool  # noqa: E402


def ctx(attempt="1", log_var=True):
    av = {"attempt_number": attempt}
    if log_var:
        av["live_switch_log"] = ""
    return SarvamToolContext(
        agent_variables=av, engagement_metadata=EngagementMetadata(interaction_id="i", app_id="a", app_version=1),
        language="Hindi", allowed_languages=["Hindi", "English", "Gujarati"], state="start", next_valid_states=[])


def call(c, words, suspected="none", turn=1, lang=None):
    t = tool.UpdatePersonaMode(user_words=words, suspected_signal=suspected, turn_number=turn, user_language=lang)
    return asyncio.run(t.run(c))


def test_generated_file_carries_the_lexicon():
    assert tool.SIGNAL_PATTERNS == SIGNAL_PATTERNS


def test_keywords_alone_confirm_frustration_llm_missed():
    c = ctx()
    out = call(c, "aap log baar baar call karte ho, pareshan kar diya", suspected="none", turn=3)
    st = c.internal_variables["vani_persona_state"]
    assert st["mode"] == "frustration" and st["log"][0]["source"] == "keywords"
    assert "Mode is now frustration" in out.message_to_llm


def test_confusion_needs_llm_unless_strong_phrase():
    c = ctx()
    call(c, "kaun bol raha hai", suspected="none", turn=1)
    assert c.internal_variables["vani_persona_state"]["mode"] == "base"
    call(c, "kaun bol raha hai", suspected="confusion", turn=2)
    assert c.internal_variables["vani_persona_state"]["mode"] == "confusion"


def test_priority_and_cooldown():
    c = ctx()
    call(c, "busy hoon jaldi boliye, kitne ka hai", suspected="rush", turn=2)
    assert c.internal_variables["vani_persona_state"]["mode"] == "rush"   # rush outranks interest
    call(c, "kitne ka hai price", suspected="interest", turn=3)
    call(c, "jaldi bolo", suspected="rush", turn=4)                     # rush again within 2 turns: blocked
    modes = [e["to"] for e in c.internal_variables["vani_persona_state"]["log"]]
    assert modes == ["rush", "interest"]


def test_dnc_always_wins_and_fatigue_lowers_frustration_threshold():
    c = ctx(attempt="5")
    out = call(c, "mujhe call mat karo", suspected="none", turn=2)
    assert c.internal_variables["vani_persona_state"]["mode"] == "do_not_call"
    assert "end_interaction" in out.message_to_llm
    c2 = ctx(attempt="5")
    call(c2, "kitne call aate hain", suspected="none", turn=2)          # 0.8 hit, fires at threshold 0.6
    assert c2.internal_variables["vani_persona_state"]["mode"] == "frustration"


def test_language_switch_is_applied_and_logged():
    c = ctx()
    out = call(c, "મને ગુજરાતીમાં કહો", suspected="language", turn=2)
    assert c.language == "Gujarati" and "Reply in Gujarati" in out.message_to_llm
    assert '"language"' in c.agent_variables["live_switch_log"]


def test_language_switch_logged_when_platform_switched_first():
    c = ctx()
    call(c, "haan ji boliye", turn=1, lang="Hindi")
    c.language = "Gujarati"                     # Sarvam's change_output_language ran before this tool
    call(c, "મને ગુજરાતીમાં કહો", suspected="language", turn=2, lang="Gujarati")
    log = c.internal_variables["vani_persona_state"]["log"]
    assert [(e["signal"], e["from"], e["to"]) for e in log] == [("language", "Hindi", "Gujarati")]
    call(c, "હા બરાબર છે", turn=3, lang="Gujarati")   # staying in Gujarati is not a new switch
    assert len(c.internal_variables["vani_persona_state"]["log"]) == 1


def test_no_signal_keeps_mode_and_works_without_log_variable():
    c = ctx(log_var=False)
    out = call(c, "haan ji boliye", suspected="none", turn=1)
    assert "No mode change" in out.message_to_llm and "live_switch_log" not in c.agent_variables


def test_devanagari_from_phone_stt_matches_the_lexicon():
    # Sarvam's phone STT writes Hindi in Devanagari; these are lines from real test calls on 2026-10-10.
    assert tool.romanise("आप लोग बार-बार कॉल करते हो तो परेशान कर दिया।").strip() == \
        "aap log baar baar call karte ho to pareshaan kar diya"
    assert tool.keyword_scores("अभी बहुत बिजी हूँ दुकान पे कस्टमर है जल्दी बोलिए।")[0]["rush"] > 0.9
    assert tool.keyword_scores("कितने का है प्लान?")[0]["interest"] > 0.8
    c = ctx()
    call(c, "आप लोग बार-बार कॉल करते हो तो परेशान कर दिया।", suspected="frustration", turn=3)
    assert c.internal_variables["vani_persona_state"]["log"][0]["source"] == "llm+keywords"


def test_language_switch_logged_when_first_tool_call_is_the_switch():
    # Seen on Sarvam: the platform switched to Gujarati first, and this was the tool's first call in the call.
    c = ctx()
    c.language = "Gujarati"
    call(c, "મને ગુજરાતીમાં વાત કરો", suspected="language", turn=2, lang="Gujarati")
    log = c.internal_variables["vani_persona_state"]["log"]
    assert [(e["signal"], e["to"]) for e in log] == [("language", "Gujarati")]
