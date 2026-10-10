"""Locked fact sheet. Personas change delivery only: every fact, price and compliance line comes from here verbatim.

Prices are what the current VANI script quotes (ps07_call_turns: "premium plan 30,200 rupaye plus GST saalana ...
4,000 plus GST mahine"). The bot has also said "32,000" in ~135 calls, i.e. it quotes inconsistent prices today.
CONFIRM WITH INDIAMART before the demo; change only this file.
"""

FACTS = {
    "company": "IndiaMART",
    "agent_name": {"female": "Payal", "male": "Aditya"},
    "purpose": "a short 15-20 minute meeting with an IndiaMART sales executive",
    "meeting_options": ["in person at the seller's shop/office", "online video call"],
    "price_annual": "₹30,200 plus GST per year (premium plan)",
    "price_monthly": "about ₹4,000 plus GST per month",
    "price_line_hi": "Premium plan saalana 30,200 rupaye plus GST hai, yaani lagbhag 4,000 rupaye plus GST mahina.",
    "price_line_en": "The premium plan is ₹30,200 plus GST a year, which is about ₹4,000 plus GST a month.",
    "meeting_is_free": True,
    "free_meeting_line_hi": "Meeting bilkul free hai, koi commitment nahi hai.",
    "free_meeting_line_en": "The meeting is free and there is no obligation to buy anything.",
}

COMPLIANCE = {
    "ai_disclosure_hi": "Main IndiaMART ki AI assistant hoon, aapki meeting schedule karne mein madad karti hoon.",
    "ai_disclosure_en": "I'm IndiaMART's AI assistant, and I help schedule meetings with our team.",
    "dnc_ack_hi": "Bilkul, main aapka number abhi do-not-call list mein daal deti hoon. Maaf kijiye, dhanyavaad.",
    "dnc_ack_en": "Of course, I'll add your number to our do-not-call list right away. Sorry for the trouble.",
    "no_false_confirmation": "Never say a meeting is fixed unless the seller explicitly agreed to a day and time.",
}

ALLOWED_NUMBERS = {"30,200", "30200", "4,000", "4000", "15", "20", "15-20"}
