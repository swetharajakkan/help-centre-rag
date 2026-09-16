"""Deterministic assertions on a drafted ticket reply.

These four criteria used to sit in the judge prompt (week6/judge_v0.txt,
criteria 2-5). Each one is decidable by reading the reply and the ticket
record -- no taste, no tone, no judgement -- so paying a model to score them
buys nothing but variance and latency. They were deleted from the judge prompt
in judge_v1.txt and re-implemented here.

Each rule is in one of three states for a given case:
  PASS       the rule applies and the reply satisfies it
  FAIL       the rule applies and the reply violates it
  n/a        the rule's precondition is not met (no refund offered, not
             Priority tier), so there is nothing to check

Assertion 4 is the one that can be wrong in the expensive direction, so its
refund detector is deliberately literal: it fires on explicit offer/approval
wording, not on the word "refund" appearing anywhere. A reply that says "this
is not eligible for a refund" does not promise one.
"""
from __future__ import annotations

import re

# An explicit commitment to refund, in the drafter's voice. "Refund" as a noun
# in an explanation ("the credit note behaves like a refund") is not one.
OFFER = re.compile(
    r"\b(?:we\s+(?:have|'ve|will|can)\s+(?:approved?|issued?|process(?:ed)?|"
    r"refund(?:ed)?)|approved?\s+a\s+(?:full\s+)?refund|"
    r"refund\s+(?:of|has\s+been|will\s+be)|issuing\s+a\s+refund)\b",
    re.I)
NEGATED = re.compile(r"\b(?:not|cannot|can't|unable\s+to|no)\b[^.]{0,40}\brefund\b",
                     re.I)
# A currency figure the finance export can parse.
FIGURE = re.compile(r"\b(?:USD|\$)\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b")
ESCALATION_TAG = "[ESCALATED]"
REFUND_WINDOW_DAYS = 30


def promises_refund(reply: str) -> bool:
    """True when the reply commits to a refund."""
    for sentence in re.split(r"(?<=[.!?])\s+", reply):
        if OFFER.search(sentence) and not NEGATED.search(sentence):
            return True
    return False


def a1_ticket_id_echoed(reply: str, ticket: dict) -> tuple[str, str]:
    """SP-001: every reply names the ticket it answers."""
    ok = ticket["ticket_id"] in reply
    return ("PASS" if ok else "FAIL",
            "" if ok else f"{ticket['ticket_id']} does not appear in the reply")


def a2_refund_amount_numeric(reply: str, ticket: dict) -> tuple[str, str]:
    """SP-001: a refund offer states the amount as a currency figure."""
    if not promises_refund(reply):
        return "n/a", "no refund offered"
    ok = bool(FIGURE.search(reply))
    return ("PASS" if ok else "FAIL",
            "" if ok else "refund promised with no parseable currency figure")


def a3_escalation_tag_when_priority(reply: str, ticket: dict) -> tuple[str, str]:
    """SP-001: every Priority-tier reply carries the escalation tag."""
    if ticket["tier"] != "Priority":
        return "n/a", "tier is not Priority"
    ok = ESCALATION_TAG in reply
    return ("PASS" if ok else "FAIL",
            "" if ok else "Priority ticket with no [ESCALATED] tag")


def a4_no_refund_outside_window(reply: str, ticket: dict) -> tuple[str, str]:
    """SP-001: no refund is offered past day 30. Day 30 is inside."""
    days = ticket["days_since_purchase"]
    if days <= REFUND_WINDOW_DAYS:
        return "n/a", f"day {days} is inside the {REFUND_WINDOW_DAYS}-day window"
    ok = not promises_refund(reply)
    return ("PASS" if ok else "FAIL",
            "" if ok else f"refund promised on day {days}, "
                          f"{days - REFUND_WINDOW_DAYS} days past the window")


ASSERTIONS = [
    ("ticket_id_echoed", a1_ticket_id_echoed),
    ("refund_amount_numeric", a2_refund_amount_numeric),
    ("escalation_tag_when_priority", a3_escalation_tag_when_priority),
    ("no_refund_outside_window", a4_no_refund_outside_window),
]


def run(reply: str, ticket: dict) -> dict:
    """All four rules on one reply. `passed` is True when none FAILed."""
    out = {}
    for name, fn in ASSERTIONS:
        status, detail = fn(reply, ticket)
        out[name] = {"status": status, "detail": detail}
    return {"checks": out,
            "failed": [n for n, r in out.items() if r["status"] == "FAIL"],
            "passed": not any(r["status"] == "FAIL" for r in out.values())}
