"""Overlay configs for cloning the base VANI agent into each voice variant (one demo seller as defaults)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from sarvam_agent.to_variables import variables  # noqa: E402
from sarvam_agent.variants import VARIANTS, tts_config  # noqa: E402

DEMO_SELLERS = {"warm_hinglish": 331550, "friendly_hinglish": 97898477, "clear_hinglish": 25144509,
                "formal_hinglish": 98255184, "english_led": 2911154, "english_formal": 66773609}

INTRO = {  # platform translations of the English intro; gendered verbs fixed per voice gender
    "female": {
        "English": "Namaste, this is {{agent_name}} calling from IndiaMART. Am I speaking with the person who handles the {{seller_category}} business?",
        "Hindi": "नमस्ते, मैं इंडियामार्ट से {{agent_name}} बोल रही हूँ। क्या मेरी बात {{seller_category}} के बिज़नेस संभालने वाले व्यक्ति से हो रही है?",
        "Gujarati": "નમસ્તે, હું IndiaMART માંથી {{agent_name}} બોલું છું. શું હું એ વ્યક્તિ સાથે વાત કરી રહી છું જે {{seller_category}} નો બિઝનેસ સંભાળે છે?",
        "Punjabi": "ਨਮਸਤੇ, ਮੈਂ IndiaMART ਤੋਂ {{agent_name}} ਬੋਲ ਰਹੀ ਹਾਂ। ਕੀ ਮੇਰੀ ਗੱਲ ਉਸ ਬੰਦੇ ਨਾਲ ਹੋ ਰਹੀ ਹੈ ਜੋ {{seller_category}} ਦਾ ਕੰਮ ਦੇਖਦੇ ਨੇ?",
        "Marathi": "नमस्ते, मी इंडियामार्टमधून {{agent_name}} बोलतेय. मी {{seller_category}} चा व्यवसाय सांभाळणाऱ्या व्यक्तीशी बोलतेय का?",
    },
    "male": {
        "English": "Namaste, this is {{agent_name}} calling from IndiaMART. Am I speaking with the person who handles the {{seller_category}} business?",
        "Hindi": "नमस्ते, मैं इंडियामार्ट से {{agent_name}} बोल रहा हूँ। क्या मेरी बात {{seller_category}} के बिज़नेस संभालने वाले व्यक्ति से हो रही है?",
        "Gujarati": "નમસ્તે, હું IndiaMART માંથી {{agent_name}} બોલું છું. શું હું એ વ્યક્તિ સાથે વાત કરી રહ્યો છું જે {{seller_category}} નો બિઝનેસ સંભાળે છે?",
        "Punjabi": "ਨਮਸਤੇ, ਮੈਂ IndiaMART ਤੋਂ {{agent_name}} ਬੋਲ ਰਿਹਾ ਹਾਂ। ਕੀ ਮੇਰੀ ਗੱਲ ਉਸ ਬੰਦੇ ਨਾਲ ਹੋ ਰਹੀ ਹੈ ਜੋ {{seller_category}} ਦਾ ਕੰਮ ਦੇਖਦੇ ਨੇ?",
        "Marathi": "नमस्ते, मी इंडियामार्टमधून {{agent_name}} बोलतोय. मी {{seller_category}} चा व्यवसाय सांभाळणाऱ्या व्यक्तीशी बोलतोय का?",
    },
}
COMMON_INTRO = {
    "Bengali": "নমস্তে, আমি ইন্ডিয়ামার্ট থেকে {{agent_name}} বলছি। আমি কি {{seller_category}} ব্যবসার দায়িত্বে থাকা ব্যক্তির সাথে কথা বলছি?",
    "Kannada": "ನಮಸ್ತೆ, ನಾನು ಇಂಡಿಯಾಮಾರ್ಟ್‌ನಿಂದ {{agent_name}} ಮಾತಾಡ್ತಿರೋದು. ನಾನು {{seller_category}} ಬಿಸಿನೆಸ್ ನೋಡೋರ ಜೊತೆ ಮಾತಾಡ್ತಿದ್ದೀನಾ?",
    "Malayalam": "നമസ്തേ, ഞാൻ IndiaMART-ൽ നിന്ന് {{agent_name}} ആണ് വിളിക്കുന്നത്. {{seller_category}} ബിസിനസ് നോക്കുന്ന ആളാണോ നിങ്ങൾ?",
    "Tamil": "வணக்கம், நான் IndiaMART-லருந்து {{agent_name}} பேசுறேன். {{seller_category}} பிசினஸை கவனிச்சுக்கிறவங்க நீங்கதானா?",
    "Telugu": "నమస్తే, నేను ఇండియామార్ట్ నుండి {{agent_name}} మాట్లాడుతున్నాను. నేను {{seller_category}} బిజినెస్ చూసుకునే వారితోనే మాట్లాడుతున్నానా?",
    "Odia": "ନମସ୍କାର, ମୁଁ IndiaMART ରୁ {{agent_name}} କହୁଛି। ମୁଁ କ’ଣ {{seller_category}} ବ୍ୟବସାୟ ଦେଖୁଥିବା ବ୍ୟକ୍ତିଙ୍କ ସହ କଥା ହେଉଛି?",
    "Assamese": "নমস্কাৰ, মই IndiaMART-ৰ পৰা {{agent_name}} কথা পাতি আছো। মই {{seller_category}} ব্যৱসায়টো চলোৱা মানুহজনৰ লগতেই কথা পাতিছোঁ নেকি?",
}


def overlay(variant: str) -> dict:
    v = VARIANTS[variant]
    spec = json.loads((config.OUT_DIR / "personas" / f"{DEMO_SELLERS[variant]}.json").read_text(encoding="utf-8"))
    _, vals = variables(spec)
    return {
        "llm_config": {"agent_config": {"agent_variables": {k: {"value": val} for k, val in vals.items()}}},
        "language_config": {"initial_language_name": v["initial_language"]},
        "text_to_speech_config": tts_config(variant),
        "intro_message_config": {"multilingual_audio": {"default_language": "English", "language_text_mapping":
                                                        {**COMMON_INTRO, **INTRO[v["gender"]]}}},
    }


if __name__ == "__main__":
    out = config.OUT_DIR / "sarvam"
    for k in DEMO_SELLERS:
        if k == "warm_hinglish":
            continue
        (out / f"overlay_{k}.json").write_text(json.dumps(overlay(k), ensure_ascii=False), encoding="utf-8")
        print(k, VARIANTS[k]["name"], len(json.dumps(overlay(k))))
