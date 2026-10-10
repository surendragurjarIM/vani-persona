"""The VANI persona family on Sarvam Voice Agents.

Voice, speaking speed and pitch are per-agent settings on this workspace's plan, so personas that sound different
are separate agents sharing one prompt. Each seller's persona spec routes it to one variant (by the spec's speaker)
and fills the per-seller variables. Voice ids are workspace `internal_id`s from agents(operation='list_voices').
"""

VOICE_IDS = {  # display name -> internal_id (workspace catalogue, read 2026-10-09)
    "Ritu - Warm Support Agent": "01a0cf16-d7da-7f22-b00b-b454c7a709ba",
    "Simran - Hindi Sales Agent": "01a0cf16-c494-7231-b33d-fc186090959f",
    "Ritu - Sales Agent": "01a0cf16-dd5f-77fa-8a45-4a6c01663eb1",
    "Aditya - Sales Agent": "01a0cf16-fd75-7f65-ad57-d0ca08ad4d7a",
    "Simran - English Support Agent": "01a0cf16-ba80-7ea3-9e61-8e5a0381560b",
    "Shubh - Expressive Banking Agent": "01a0cf16-a571-7451-a420-be5f97e71f71",
    # regional voices used when the call switches language
    "Pooja - Gujarati Conversational Voice": "01a0cf17-07ec-7e82-976c-1115f36dda1b",
    "Bhavik - Conversational Voice": "01a0cf16-c5bd-7063-969f-2962475c911a",
    "Kavitha - Conversational Voice": "01a0cf16-897b-76f8-8de9-34f27e861df6",
    "Gokul - Narrator": "01a0e8fc-8c09-7a4f-91dc-e8eb812b88e7",
    "Roopa - Bengali Conversational Voice": "01a0cf16-e562-7c39-a3fb-24ec65422292",
    "Arnab - Conversational Voice": "01a0cf16-91b2-7d4a-9565-165855db219c",
    "Ritu - Marathi Insurance Agent": "01a0cf16-de84-785d-b91b-7b47965d373d",
    "Nilesh - Conversational Voice": "01a0cf16-f342-7d26-8a95-9944e6556c3c",
    "Pooja - Telugu Conversational Voice": "01a0cf16-aee5-7a59-981c-e4e7b8b148a0",
    "Chaitra - Kannada Mix Support": "01a0cf16-955f-71e1-b1b6-68bf2fcf2172",
    "Chetan - Conversational Voice": "01a0cf16-a424-75e1-8419-e1a0a756fc42",
    "Harpreet - Narrator": "01a0cf16-e790-7000-86d5-2d57a740bb3a",
}

REGIONAL_VOICES = {
    "female": {"Gujarati": "Pooja - Gujarati Conversational Voice", "Tamil": "Kavitha - Conversational Voice",
               "Bengali": "Roopa - Bengali Conversational Voice", "Marathi": "Ritu - Marathi Insurance Agent",
               "Telugu": "Pooja - Telugu Conversational Voice", "Kannada": "Chaitra - Kannada Mix Support",
               "Punjabi": "Harpreet - Narrator"},
    "male": {"Gujarati": "Bhavik - Conversational Voice", "Tamil": "Gokul - Narrator",
             "Bengali": "Arnab - Conversational Voice", "Marathi": "Nilesh - Conversational Voice",
             "Telugu": "Pooja - Telugu Conversational Voice", "Kannada": "Chetan - Conversational Voice",
             "Punjabi": "Harpreet - Narrator"},
}
LANGUAGES = ["Hindi", "English", "Gujarati", "Tamil", "Bengali", "Marathi", "Telugu", "Kannada", "Punjabi"]

VARIANTS = {
    "warm_hinglish": {"name": "VANI · Warm Hinglish", "voice": "Ritu - Warm Support Agent", "gender": "female",
                      "pace": 0.9, "initial_language": "Hindi", "agent_name": "Payal",
                      "for": "sellers who refused before or need empathy; micro traders"},
    "friendly_hinglish": {"name": "VANI · Friendly Hinglish", "voice": "Simran - Hindi Sales Agent",
                          "gender": "female", "pace": 0.9, "initial_language": "Hindi", "agent_name": "Payal",
                          "for": "micro proprietors, informal shop talk"},
    "clear_hinglish": {"name": "VANI · Clear Hinglish", "voice": "Ritu - Sales Agent", "gender": "female",
                       "pace": 1.0, "initial_language": "Hindi", "agent_name": "Payal",
                       "for": "standard sellers, short-call histories"},
    "formal_hinglish": {"name": "VANI · Formal Hinglish", "voice": "Aditya - Sales Agent", "gender": "male",
                        "pace": 1.0, "initial_language": "Hindi", "agent_name": "Aditya",
                        "for": "large businesses, registered companies"},
    "english_led": {"name": "VANI · English-led", "voice": "Simran - English Support Agent", "gender": "female",
                    "pace": 1.0, "initial_language": "English", "agent_name": "Payal",
                    "for": "South India and English-speaking sellers"},
    "english_formal": {"name": "VANI · English Formal", "voice": "Shubh - Expressive Banking Agent",
                       "gender": "male", "pace": 1.0, "initial_language": "English", "agent_name": "Aditya",
                       "for": "large English-speaking businesses"},
}

SPEAKER_TO_VARIANT = {  # persona spec voice.speaker -> variant
    "ritu_hi_customer_warm": "warm_hinglish", "simran_hi_sales": "friendly_hinglish",
    "ritu_hi_sales": "clear_hinglish", "aditya_hi_sales": "formal_hinglish", "shubh_hi_customer": "formal_hinglish",
    "neha_en_customer": "english_led", "simran_enhi_customer": "english_led", "shubh_enhi_banking": "english_formal",
}


def tts_config(variant_key: str) -> dict:
    v = VARIANTS[variant_key]
    mixed = [{"language_name": lang, "internal_id": VOICE_IDS[name]}
             for lang, name in REGIONAL_VOICES[v["gender"]].items()]
    mixed += [{"language_name": "Hindi", "internal_id": VOICE_IDS[v["voice"]]},
              {"language_name": "English", "internal_id": VOICE_IDS[v["voice"]]}]
    # v2 config takes either one internal_id or a per-language list; the list covers Hindi/English too
    # internal_id: None deletes the template's single voice in the merge
    return {"config_version": "2.0", "internal_id": None, "enable_mixed_speaker_settings": True,
            "mixed_speaker_config": mixed,
            "speech_settings": {"pace": v["pace"], "pitch": None, "volume": None}}
