"""Small talk: "hi", "thanks", "bye" get a friendly reply, not a refusal.

Runs before the Responder. A message that is ONLY small talk is answered
here, with no tools and nothing to verify (it states no facts). A greeting
in front of a real question ("hi, why was TCK-4403 escalated?") is peeled
off: the question goes to the agents and the reply starts with a greeting.
"""
from __future__ import annotations

import re

CAPABILITIES = ("I can answer questions about the billing migration — phases and "
                "cutover, payment methods, invoices, proration, tax IDs, the API and "
                "webhooks — look up a support ticket if you give me its id "
                "(like TCK-4403), and answer from documents our team has uploaded "
                "(refunds, payments, subscriptions, account security, tax).")

# (kind, pattern for the whole message once punctuation is stripped)
PATTERNS = [
    ("how_are_you", r"(hi |hello |hey )?(how are you( doing)?|how s it going|how are things|"
                    r"how do you do|what s up|whats up|sup)( today)?"),
    ("who", r"(who are you|what are you|what is your name|what s your name|are you a bot|"
            r"are you human|are you real)"),
    ("help", r"(help|help me|i need help|can you help( me)?|what can you do|"
             r"what do you do|how does this work|what can i ask( you)?)"),
    ("thanks", r"((ok |okay |great |cool )?(thanks|thank you|thank u|thx|ty|cheers|"
               r"much appreciated|appreciate it)( so much| a lot| very much)?( for (the|your) help)?)"),
    ("bye", r"(bye|goodbye|good bye|see you|see ya|cya|take care|good night|that s all|"
            r"that is all|nothing else|no thanks|no thank you)( for now| bye)?"),
    ("ack", r"(ok|okay|k|cool|great|nice|got it|understood|alright|all right|perfect|"
            r"awesome|sure|fine|good|sounds good|makes sense)"),
    ("greeting", r"(hi|hello|hey|hiya|howdy|yo|greetings|hi there|hello there|hey there|"
                 r"good (morning|afternoon|evening|day))"),
]
PRIORITY = ["bye", "thanks", "how_are_you", "who", "help", "greeting", "ack"]
GREETING_LEAD = re.compile(
    r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening))( there)?\b[\s,!.:-]*", re.I)

REPLIES = {
    "greeting": "Hi! I'm the Help Centre support agent. " + CAPABILITIES + " What can I do for you?",
    "how_are_you": "I'm doing well, thanks for asking! " + CAPABILITIES + " How can I help?",
    "who": "I'm the Help Centre support agent: one agent writes each answer from the "
           "help centre and the ticket history, and a second agent checks every "
           "statement against the source before you see it. " + CAPABILITIES,
    "help": "Happy to help. " + CAPABILITIES + " For example: “Why was TCK-4403 "
            "escalated?” or “What happens to stored cards during the migration?”",
    "thanks": "You're welcome! Is there anything else I can help with — another "
              "question about the migration, or a ticket?",
    "bye": "Goodbye, and thanks for getting in touch. Come back any time.",
    "ack": "Great. Let me know if there's anything else you'd like to check.",
}


def _clean(text: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("'", " "))
    return re.sub(r"\s+", " ", t).strip()


def classify(text: str) -> dict | None:
    """{"kind", "reply", "rest"}: rest is the real question left after a
    leading greeting, or None when the whole message was small talk."""
    t = _clean(text)
    if not t:
        return None
    # "hi thanks", "ok bye" and the like: every phrase is small talk.
    for kind, pat in PATTERNS:
        if re.fullmatch(rf"({pat})( (please|again|then|mate|buddy|friend|so much))*", t):
            return {"kind": kind, "reply": _timed(REPLIES[kind], t), "rest": None}
    every = "|".join(p for _, p in PATTERNS)
    if re.fullmatch(rf"(?:{every})(?: (?:{every}))+", t):
        # Mixed small talk ("hi thanks", "ok bye"): the most meaningful part wins.
        present = {k for k, p in PATTERNS if re.search(rf"\b(?:{p})\b", t)}
        kind = next(k for k in PRIORITY if k in present)
        return {"kind": kind, "reply": _timed(REPLIES[kind], t), "rest": None}
    m = GREETING_LEAD.match(text)
    if m and len(text[m.end():].strip()) > 3:
        greet = m.group(1).capitalize()
        return {"kind": "greeting+question", "reply": f"{greet}! ", "rest": text[m.end():].strip()}
    return None


def _timed(reply: str, t: str) -> str:
    m = re.match(r"good (morning|afternoon|evening|day)", t)
    return reply.replace("Hi!", f"Good {m.group(1)}!", 1) if m else reply
