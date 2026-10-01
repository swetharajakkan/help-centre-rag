"""The ticket and order systems the tools read from, plus the 10 race tickets.

Stands in for the helpdesk and the billing database. It is plain data on
purpose: both systems under test read exactly these records through exactly
the same three tool functions, so any difference between them is a difference
in control flow, never in what they could see.

Each ticket carries its EXPECTED output contract. That is the grader's answer
key, written from SP-001 (week6/policy) before either system was run. Neither
system can read it -- the tools never return it.

Ticket classes
--------------
  straight      one order found, the answer follows from the policy table
  branch        what step 3 must do depends on what step 2 found (order
                missing, already refunded, charged back, over the approval
                threshold, no order referenced). At least 3 are required;
                there are 5.
  multi_order   the customer names two orders. How many get_order calls the
                ticket needs is not known until the ticket has been read.
"""
from __future__ import annotations

TICKETS: dict[str, dict] = {
    "TCK-7001": {"customer_tier": "standard", "order_ids": ["ORD-5101"],
                 "request_type": "refund",
                 "message": "I bought the Pro add-on 12 days ago and it doesn't "
                            "do what I need. Can I get my money back? Order "
                            "ORD-5101."},
    "TCK-7002": {"customer_tier": "standard", "order_ids": ["ORD-5102"],
                 "request_type": "refund",
                 "message": "Please refund order ORD-5102, I stopped using it."},
    "TCK-7003": {"customer_tier": "priority", "order_ids": ["ORD-5103"],
                 "request_type": "refund",
                 "message": "Refund ORD-5103 please, the seats were bought by "
                            "mistake."},
    "TCK-7004": {"customer_tier": "standard", "order_ids": ["ORD-5199"],
                 "request_type": "refund",
                 "message": "Where is my refund for ORD-5199? I asked last week."},
    "TCK-7005": {"customer_tier": "standard", "order_ids": ["ORD-5105"],
                 "request_type": "refund",
                 "message": "I still want my refund for ORD-5105."},
    "TCK-7006": {"customer_tier": "standard", "order_ids": ["ORD-5106"],
                 "request_type": "refund",
                 "message": "Refund ORD-5106 or I'll keep the dispute open with "
                            "my bank."},
    "TCK-7007": {"customer_tier": "standard", "order_ids": ["ORD-5107"],
                 "request_type": "refund",
                 "message": "Can I still get a refund on ORD-5107? It has been "
                            "exactly a month."},
    "TCK-7008": {"customer_tier": "standard", "order_ids": ["ORD-5108"],
                 "request_type": "refund",
                 "message": "We want to cancel the annual plan on ORD-5108 and "
                            "get the money back."},
    "TCK-7009": {"customer_tier": "standard",
                 "order_ids": ["ORD-5109", "ORD-5110"],
                 "request_type": "duplicate_charge",
                 "message": "You charged me twice for the same thing, "
                            "ORD-5109 and ORD-5110. Refund the extra one."},
    "TCK-7010": {"customer_tier": "standard", "order_ids": [],
                 "request_type": "refund",
                 "message": "I want a refund for my last purchase."},
}

# days_since_purchase is relative to the ticket date, as in SP-001.
ORDERS: dict[str, dict] = {
    "ORD-5101": {"status": "paid", "amount_usd": 41.50, "days_since_purchase": 12,
                 "product": "Pro add-on", "charged_at": "2026-09-16T10:02:00Z"},
    "ORD-5102": {"status": "paid", "amount_usd": 18.00, "days_since_purchase": 44,
                 "product": "Starter", "charged_at": "2026-08-15T08:40:00Z"},
    "ORD-5103": {"status": "paid", "amount_usd": 29.00, "days_since_purchase": 9,
                 "product": "3 seats", "charged_at": "2026-09-19T14:11:00Z"},
    # ORD-5199 does not exist: TCK-7004 quotes an order the billing system
    # has no record of.
    "ORD-5105": {"status": "refunded", "amount_usd": 22.00, "days_since_purchase": 18,
                 "product": "Starter", "charged_at": "2026-09-10T09:00:00Z"},
    "ORD-5106": {"status": "chargeback", "amount_usd": 35.00, "days_since_purchase": 15,
                 "product": "Pro add-on", "charged_at": "2026-09-13T16:25:00Z"},
    "ORD-5107": {"status": "paid", "amount_usd": 60.00, "days_since_purchase": 30,
                 "product": "Team plan (monthly)", "charged_at": "2026-08-29T12:00:00Z"},
    "ORD-5108": {"status": "paid", "amount_usd": 240.00, "days_since_purchase": 10,
                 "product": "Team plan (annual)", "charged_at": "2026-09-18T11:30:00Z"},
    # The duplicate pair: same product, same amount, 40 seconds apart. The
    # second charge is the duplicate.
    "ORD-5109": {"status": "paid", "amount_usd": 25.00, "days_since_purchase": 5,
                 "product": "Pro add-on", "charged_at": "2026-09-23T09:14:02Z"},
    "ORD-5110": {"status": "paid", "amount_usd": 25.00, "days_since_purchase": 5,
                 "product": "Pro add-on", "charged_at": "2026-09-23T09:14:42Z"},
}

# The answer key. Fields are the output contract both systems must return.
EXPECTED: dict[str, dict] = {
    "TCK-7001": {"cls": "straight", "decision": "refund_approved",
                 "refund_order_id": "ORD-5101", "refund_amount_usd": 41.50,
                 "escalate": False},
    "TCK-7002": {"cls": "straight", "decision": "outside_window",
                 "refund_order_id": None, "refund_amount_usd": None,
                 "escalate": False},
    "TCK-7003": {"cls": "straight", "decision": "refund_approved",
                 "refund_order_id": "ORD-5103", "refund_amount_usd": 29.00,
                 "escalate": True},
    "TCK-7004": {"cls": "branch", "decision": "escalate_missing_order",
                 "refund_order_id": None, "refund_amount_usd": None,
                 "escalate": True},
    "TCK-7005": {"cls": "branch", "decision": "already_refunded",
                 "refund_order_id": None, "refund_amount_usd": None,
                 "escalate": False},
    "TCK-7006": {"cls": "branch", "decision": "escalate_chargeback",
                 "refund_order_id": None, "refund_amount_usd": None,
                 "escalate": True},
    "TCK-7007": {"cls": "straight", "decision": "refund_approved",
                 "refund_order_id": "ORD-5107", "refund_amount_usd": 60.00,
                 "escalate": False},
    "TCK-7008": {"cls": "branch", "decision": "needs_manager_approval",
                 "refund_order_id": "ORD-5108", "refund_amount_usd": 240.00,
                 "escalate": True},
    "TCK-7009": {"cls": "multi_order", "decision": "refund_approved",
                 "refund_order_id": "ORD-5110", "refund_amount_usd": 25.00,
                 "escalate": False},
    "TCK-7010": {"cls": "branch", "decision": "escalate_missing_order",
                 "refund_order_id": None, "refund_amount_usd": None,
                 "escalate": True},
}

# What makes each branch ticket a branch: the step-2 result step 3 turns on.
BRANCH_NOTE = {
    "TCK-7004": "get_order returns not_found -> escalation path opens",
    "TCK-7005": "order already refunded -> no second refund",
    "TCK-7006": "order under chargeback -> disputes team, not a refund",
    "TCK-7008": "amount over USD 100 -> manager approval path",
    "TCK-7009": "two orders named -> must compare charges to find the duplicate",
    "TCK-7010": "no order referenced -> nothing to fetch, escalate for details",
}

TICKET_IDS = list(TICKETS)


# ------------------------------------------------------- live chat tickets

import itertools
import re

_ADHOC_IDS = itertools.count(9001)
_ORDER_RE = re.compile(r"\bORD-\d{4}\b")
_DUPLICATE_RE = re.compile(r"\b(twice|double[- ]?charged|duplicate|charged two)\b", re.I)


def resolve_ticket(text: str) -> tuple[str, bool]:
    """Turn what someone typed into the chat into a ticket id.

    Returns (ticket_id, known). A ticket id in the text, or the exact message
    of one of the 10 race tickets, selects that ticket. Anything else is filed
    as a new ticket -- the order ids it names, standard tier, a duplicate-charge
    request when it says so -- so the agent and the workflow can be tried on a
    message nobody wrote an answer key for. New tickets live in memory only
    and never join TICKET_IDS, so they cannot leak into the race.
    """
    text = text.strip()
    m = re.search(r"\bTCK-\d{4}\b", text)
    if m and m.group(0) in TICKETS:
        return m.group(0), m.group(0) in EXPECTED
    for tid, t in TICKETS.items():
        if t["message"].strip() == text:
            return tid, tid in EXPECTED
    tid = f"TCK-{next(_ADHOC_IDS)}"
    TICKETS[tid] = {
        "customer_tier": "standard",
        "order_ids": list(dict.fromkeys(_ORDER_RE.findall(text))),
        "request_type": ("duplicate_charge" if _DUPLICATE_RE.search(text)
                         else "refund"),
        "message": text,
    }
    return tid, False
