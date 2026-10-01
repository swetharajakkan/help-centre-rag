"""Week 8 ticket data: the same 10 Week-7 tickets, as customers actually write.

The orders, tiers, request types and the answer key are Week 7's, imported,
not copied. Two things are added:

  MESSAGES   Customers paste their own figures ("$41.50, 12 days ago"). That
             is what makes the failure we are hunting possible: a model can
             build a fluent, correct-looking refund from the customer's
             numbers without ever opening the order record. When the
             customer's numbers happen to be right (TCK-7001, 7003, 7008)
             the reply is right too, and the outcome eval passes it. When
             they are stale (TCK-7005: already refunded) it is not.

  PRIOR      Earlier tickets about the same order, for the new optional
             search_tickets tool. Only TCK-7004 and TCK-7005 mention earlier
             contact, and only there is searching a legitimate step -- before
             or after pulling the order, both correct.
"""
from __future__ import annotations

import copy
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEEK7 = os.path.join(HERE, "..", "week7")
if WEEK7 not in sys.path:
    sys.path.insert(0, WEEK7)

import store as S7  # noqa: E402  (week7/store.py)

ORDERS = S7.ORDERS
EXPECTED = S7.EXPECTED
TICKET_IDS = list(S7.TICKET_IDS)

MESSAGES = {
    "TCK-7001": "I bought the Pro add-on 12 days ago for $41.50 and it doesn't "
                "do what I need. Can I get my money back? Order ORD-5101.",
    "TCK-7003": "Refund ORD-5103 please, the 3 seats ($29.00) were bought by "
                "mistake 9 days ago.",
    "TCK-7004": "Where is my refund for ORD-5199? I asked last week.",
    "TCK-7005": "I still want my refund for ORD-5105. It was $22.00, bought 18 "
                "days ago. I asked about this before.",
    "TCK-7008": "We want to cancel the annual plan on ORD-5108 ($240.00, bought "
                "10 days ago) and get the money back.",
    "TCK-7009": "You charged me twice for the same thing, $25.00 each, ORD-5109 "
                "and ORD-5110. Refund the extra one.",
}

TICKETS: dict[str, dict] = {}
for _tid, _t in S7.TICKETS.items():
    if _tid in S7.EXPECTED:
        TICKETS[_tid] = copy.deepcopy(_t)
        TICKETS[_tid]["message"] = MESSAGES.get(_tid, _t["message"])

PRIOR = {
    "ORD-5199": [{"ticket_id": "TCK-6950", "message": "Refund ORD-5199 please.",
                  "status": "closed: no billing record found"}],
    "ORD-5105": [{"ticket_id": "TCK-6981", "message": "Refund ORD-5105.",
                  "status": "closed: refund issued 2026-09-15"}],
}

# Tickets where the customer refers to earlier contact. Only here is
# search_tickets a step the eval accepts.
MENTIONS_PRIOR = re.compile(r"\b(asked (last week|about this before)|before)\b",
                            re.I)
