"""Hinglish signal lexicon, shared by offline evidence mining and the live fast-tier detector.

Patterns were curated from the most frequent seller n-grams in ps07_call_turns.csv
("busy hoon" 449, "time nahi hai" 445, "baar baar" 180, "hello hello" 370, "kaun bol" 337, ...).
Each pattern carries a weight in [0, 1]: how strongly that phrase alone indicates the signal.
Transcripts are romanised, so patterns are romanised. Live STT (saaras:v4) output is
transliterated to roman before matching.
"""
import re
from dataclasses import dataclass, field

NA = r"(?:nahi|nahin|nai|nhi|na)"
HOON = r"(?:hoon|hun|hu|hai|hain)"

SIGNAL_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "frustration": [
        (r"\bbaar baar\b", 0.8), (r"\bkitni baar\b", 0.85), (r"\broz roz\b", 0.8),
        (r"\b(?:har (?:roz|din)|daily) (?:call|phone)", 0.85),
        (rf"\b(?:call|phone|fone) (?:mat|{NA}) (?:karo|kariye|karna|kijiye|kare)", 0.95),
        (r"\b(?:mat|na) (?:karo|kariye) (?:call|phone)", 0.95), (r"\bdo ?n[o']?t call\b", 0.95),
        (r"\bpareshan\b", 0.75), (r"\bdimag\b", 0.8), (r"\btime waste\b", 0.8), (r"\bbakwas\b", 0.9),
        (r"\bfaltu\b", 0.85), (r"\bpagal\b", 0.9), (r"\birritat", 0.85), (r"\bdisturb", 0.7),
        (r"\bkyun? (?:call|phone) (?:kar|kiya)", 0.6), (r"\bkitne call\b", 0.8),
        (r"\b(?:number|no) (?:hata|block|delete)", 0.9), (r"\bmana (?:kiya|kar diya)\b", 0.8),
        (r"\b(?:bola|bol diya|keh diya|bataya) (?:na|tha na)\b", 0.65), (r"\bsamajh(?:te)? (?:nahi|nahin) (?:aata|ho)", 0.6),
        (r"\bpaa?gal\b", 0.9), (r"\bchutiya|\bbewakoof|\bbakwaas", 0.95), (r"\bfokat\b", 0.8),
        (r"\b(?:ek hazaar|hazaar|sau|kai|bahut|das|dasvi|dusri|teesri) baar\b", 0.8),
        (r"\bhar (?:second|doosre|dusre|char|teesre) din\b", 0.85), (r"\bkitni meeting", 0.7),
        (r"\brehne (?:hi )?do\b", 0.6), (r"\bpareshaa?n", 0.75), (r"\bphone mat\b|\bcall mat\b", 0.9),
        (r"\bheadache\b", 0.8), (r"\bfed up\b", 0.9), (r"\bharass", 0.95), (r"\bcomplaint\b", 0.6),
    ],
    "rush": [
        (rf"\bbusy {HOON}\b", 0.8), (r"\bbusy\b", 0.55), (r"\bjaldi\b", 0.75),
        (rf"\btime {NA}\b", 0.6), (rf"\bfree {NA}\b", 0.6),
        (r"\bseedha\b|\bsidha\b", 0.7), (r"\b(?:short|point) (?:mein|pe|par)\b", 0.8), (r"\bto the point\b", 0.85),
        (r"\b(?:kya|kaun sa) kaam (?:hai|tha)\b", 0.55), (r"\bkaam (?:bataiye|batao|boliye|bolo)\b", 0.7),
        (r"\b(?:bataiye|boliye|bolo) jaldi\b", 0.85), (r"\bdriving\b|\bgaadi chala", 0.75),
        (r"\bmeeting mein {HOON}\b".replace("{HOON}", HOON), 0.7), (r"\bcustomer (?:hai|baithe|aaye)", 0.6),
        (r"\bek minute\b", 0.4), (r"\bdo minute\b", 0.5), (r"\bquickly\b|\bfast\b", 0.6),
        (r"\bprice batai?ye\b|\bseedha price\b", 0.6), (r"\bmudde ki baat\b", 0.85),
        (rf"\b(?:samay|waqt|time) (?:toh |to )?(?:hai )?{NA}\b", 0.6), (r"\bno time\b|\bnot free\b", 0.7),
        (rf"\babhi {NA}\b", 0.45), (rf"\bbaat {NA} karni\b", 0.55),
    ],
    "unavailable": [
        (r"\bbahar {HOON}\b".replace("{HOON}", HOON), 0.8), (r"\bout of (?:station|city|town)\b", 0.9),
        (r"\bbaad mein\b", 0.55), (r"\bkal (?:call|phone|baat)", 0.6), (r"\bnext week\b", 0.6),
        (r"\b(?:shaam|subah) ko\b", 0.35), (r"\bcall back\b", 0.6), (r"\bhospital\b|\bshaadi\b", 0.6),
        (r"\b(?:gaon|village)\b", 0.5), (r"\bthodi der\b", 0.5),
        (rf"\bavailable {NA}\b|\bnot available\b", 0.75), (r"\bagle hafte\b|\bek hafte baad\b|\bdo-?teen din\b", 0.7),
        (rf"\bkal {NA}\b", 0.5), (r"\bbaahar\b", 0.6),
    ],
    "confusion": [
        (r"\bkaun bol\b", 0.35), (r"\baap kaun\b", 0.4), (r"\bkahan se\b", 0.35),
        (r"\bkya (?:bola|kaha|bole|bol rahe)\b", 0.7), (r"\bsamjh?a (?:nahi|nahin)\b", 0.9),
        (r"\bsamajh (?:nahi|nahin) (?:aaya|aa raha|aayi)\b", 0.9), (r"\bkya matlab\b|\bmatlab\b", 0.6),
        (r"\bkis (?:baare|cheez|liye)\b", 0.5), (r"\bkya hai (?:yeh|ye)\b", 0.6),
        (r"\b(?:phir se|dobara|repeat)\b", 0.75), (r"\bhello hello\b", 0.6),
        (r"\b(?:awaaz|awaj|aawaz) (?:nahi|nahin|kat|clear)", 0.8), (r"\bsunai (?:nahi|nahin)\b", 0.85),
        (r"\bclear (?:nahi|nahin)\b", 0.8), (r"\bpardon\b|\bsorry\?|\bwhat\?", 0.7),
        (r"\bkaunsa indiamart\b|\bindiamart kya\b", 0.6), (r"\bkaun si company\b", 0.5),
        (r"\b(?:robot|bot|computer|machine|recording)\b", 0.5), (r"\bai (?:ho|hai|hain)\b", 0.6),
        (r"^\W*(?:kya|kaun|hello|haan|ji)\W*\?\W*$", 0.6), (r"\bkaun ?(?:sa|si|se)\b[^.?!]*\?", 0.5),
        (r"\bkis(?:se|ko) baat\b", 0.55), (r"\bkaise hoga\b", 0.5), (r"\bkya samjh", 0.6),
    ],
    "interest": [
        (r"\bkitne ka\b|\bkitna (?:hai|lagega|padega|charge|paisa)\b", 0.85), (r"\bprice\b|\brate\b|\bcost\b", 0.55),
        (r"\bmonthly\b|\bmahine\b", 0.6), (r"\bpackage\b|\bplan\b", 0.45),
        (r"\bkya (?:milega|benefit|fayda|faida)\b", 0.8), (r"\bkaise (?:kaam|hoga|karte)\b", 0.6),
        (r"\bdetails?\b", 0.45), (r"\bkab (?:aayenge|aaoge|aa sakte|milenge)\b", 0.85), (r"\baddress\b", 0.6),
        (r"\baa (?:jaiye|jao|jaana)\b", 0.8), (r"\bmilte hain\b", 0.7), (r"\binterested\b", 0.6),
        (r"\b(?:theek|thik) hai (?:kal|aaj|aa)", 0.7), (r"\b\d{1,2} baje\b|\b(?:ek|do|teen|chaar|paanch|gyarah|barah) baje\b", 0.55),
        (r"\bchalega\b|\bzaroor\b|\bbilkul\b", 0.5),
        (r"\bcharges?\b|\bamount\b|\bfees?\b", 0.6), (r"\bpaise kitn|\bkitna lag|\bsaal ka kitna|\bpayment kya", 0.85),
        (r"\bonline (?:call|meeting)\b", 0.55), (r"\b\d{1,2} ?o'?clock\b", 0.55), (r"\benquir|\binquir|\bleads?\b|\bbuyers?\b", 0.45),
    ],
    "not_interested": [
        (rf"\b{NA} chahiye\b", 0.85), (rf"\bzaroorat {NA}\b|\bzarurat {NA}\b", 0.85), (r"\bnot interested\b", 0.95),
        (rf"\binterest {NA}\b", 0.9), (rf"\b{NA} karna\b", 0.6), (r"\balready\b", 0.5),
        (r"\b(?:service|subscription) band\b", 0.8), (rf"\b{NA} {NA}\b", 0.45),
    ],
}

COMPILED = {sig: [(re.compile(p, re.I), w) for p, w in pats] for sig, pats in SIGNAL_PATTERNS.items()}

# English words that rarely occur as Hinglish function words (avoid: main, to, do, the-ambiguous forms).
ENGLISH_WORDS = set("""
i am is are was were the a an this that these those it its you your we our they their he she his her
what which who when where why how yes no not please thank thanks sorry okay ok fine good great sure
can could will would should shall may might must have has had do does did done call calling called
meeting meet tomorrow today yesterday time busy free later morning evening afternoon week month year
sir madam maam ma'am hello hi speaking speak talk tell send sending details detail price cost rate
business company office shop factory product products service services interested interest want need
already know understand right now just only also very much more less about with from for into on at
of by as if but or and so then than there here because after before again repeat what's i'm don't
can't won't it's that's let me my mine no-one anyone someone nothing everything number contact
""".split())

SCRIPT_RANGES = {
    "hi": r"[ऀ-ॿ]", "gu": r"[઀-૿]", "ta": r"[஀-௿]", "bn": r"[ঀ-৿]",
    "te": r"[ఀ-౿]", "kn": r"[ಀ-೿]", "ml": r"[ഀ-ൿ]", "pa": r"[਀-੿]",
}

# Bot-side markers (for "how did VANI respond after a signal")
EMPATHY_RE = re.compile(r"\b(?:samajh (?:sakti|rahi|sakta)|maaf|sorry|koi baat nahi|bilkul|aapki baat|zaroor|"
                        r"main samajh|i understand|no problem)\b", re.I)
SLOT_OFFER_RE = re.compile(r"\b(?:\d{1,2} baje|subah|shaam|dopahar|kal|parson|monday|tuesday|wednesday|thursday|"
                           r"friday|saturday|kaun sa time|kis time|tomorrow)\b", re.I)


@dataclass
class FastSignals:
    scores: dict = field(default_factory=dict)   # signal -> 0..1
    matches: dict = field(default_factory=dict)  # signal -> [matched phrases]
    english_share: float = 0.0
    script: str = "latin"
    n_words: int = 0


def english_share(text: str) -> tuple[float, int]:
    toks = re.findall(r"[a-z']+", text.lower())
    if not toks:
        return 0.0, 0
    return sum(t in ENGLISH_WORDS for t in toks) / len(toks), len(toks)


def detect_script(text: str) -> str:
    for lang, rng in SCRIPT_RANGES.items():
        if re.search(rng, text):
            return lang
    return "latin"


def detect(text: str) -> FastSignals:
    """Score one seller utterance. Multiple hits on one signal combine as 1 - prod(1 - w)."""
    out = FastSignals()
    low = text.lower()
    for sig, pats in COMPILED.items():
        hits = [(m.group(0), w) for rx, w in pats for m in [rx.search(low)] if m]
        if hits:
            miss = 1.0
            for _, w in hits:
                miss *= (1 - w)
            out.scores[sig] = round(1 - miss, 3)
            out.matches[sig] = [h for h, _ in hits]
    out.english_share, out.n_words = english_share(text)
    out.script = detect_script(text)
    return out
