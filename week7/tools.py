"""The agent's tools: two that existed before Week 7, and the third one added.

TOOLS_BEFORE is the tool list as it stood with two tools. TOOLS is the list
now. Both are kept so the description diff is generated from the real
definitions rather than retyped into a document.

Two things changed besides the new tool, and both were forced by it:

  get_order used to say it "checks whether it can be refunded". With a policy
  tool in the list that is an overlap -- two tools claiming the same job, and
  a model that has to guess which one to trust. get_order now fetches the
  record and says explicitly that it does not decide eligibility.

  Both ids were free strings. They now carry a pattern, so a malformed id is
  rejected by the schema instead of becoming a not_found the model has to
  interpret.

The new tool, lookup_refund_policy, has one job: map facts to the SP-001
decision. Every categorical input is an enum, and its output decision is an
enum too, which is what lets both systems return the same output contract.
"""
from __future__ import annotations

import copy
import time

from store import ORDERS, TICKETS

# Simulated round trip to the helpdesk / billing API. Real sleep, so the
# measured wall-clock includes it; identical for both systems.
TOOL_LATENCY_S = 0.04

MANAGER_APPROVAL_THRESHOLD_USD = 100.0
REFUND_WINDOW_DAYS = 30

ORDER_STATUS = ["paid", "refunded", "chargeback", "not_found"]
CUSTOMER_TIER = ["standard", "priority"]
REQUEST_TYPE = ["refund", "duplicate_charge"]
DECISION = ["refund_approved", "outside_window", "already_refunded",
            "needs_manager_approval", "escalate_missing_order",
            "escalate_chargeback"]

TOOLS_BEFORE = [
    {
        "name": "get_ticket",
        "description": "Look up a support ticket and the customer's details.",
        "input_schema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
        },
    },
    {
        "name": "get_order",
        "description": "Look up an order and check whether it can be refunded.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
]

TOOLS = [
    {
        "name": "get_ticket",
        "description": (
            "Fetch one support ticket by its id. Returns the customer's "
            "message, their tier and the order ids the ticket references. "
            "Reads the helpdesk only; never touches billing."),
        "input_schema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string",
                                         "pattern": r"^TCK-\d{4}$"}},
            "required": ["ticket_id"],
        },
    },
    {
        "name": "get_order",
        "description": (
            "Fetch one billing order by its id. Returns status, amount, "
            "product, charge time and days since purchase, or status "
            "not_found. Does not decide refund eligibility."),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string",
                                        "pattern": r"^ORD-\d{4}$"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "lookup_refund_policy",
        "description": (
            "Apply support policy SP-001 to one order's facts and return the "
            "refund decision and whether the ticket must be escalated. Does "
            "not fetch anything: pass the facts in."),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_status": {"type": "string", "enum": ORDER_STATUS},
                "customer_tier": {"type": "string", "enum": CUSTOMER_TIER},
                "request_type": {"type": "string", "enum": REQUEST_TYPE},
                "days_since_purchase": {"type": ["integer", "null"],
                                        "minimum": 0},
                "amount_usd": {"type": ["number", "null"], "minimum": 0},
            },
            "required": ["order_status", "customer_tier", "request_type"],
        },
    },
]


def get_ticket(ticket_id: str) -> dict:
    time.sleep(TOOL_LATENCY_S)
    t = TICKETS.get(ticket_id)
    if t is None:
        return {"ticket_id": ticket_id, "found": False}
    return {"ticket_id": ticket_id, "found": True, **copy.deepcopy(t)}


def get_order(order_id: str | None) -> dict:
    time.sleep(TOOL_LATENCY_S)
    o = ORDERS.get(order_id or "")
    if o is None:
        return {"order_id": order_id, "status": "not_found"}
    return {"order_id": order_id, **copy.deepcopy(o)}


def lookup_refund_policy(order_status: str, customer_tier: str,
                         request_type: str,
                         days_since_purchase: int | None = None,
                         amount_usd: float | None = None) -> dict:
    time.sleep(TOOL_LATENCY_S)
    for name, value, allowed in (("order_status", order_status, ORDER_STATUS),
                                 ("customer_tier", customer_tier, CUSTOMER_TIER),
                                 ("request_type", request_type, REQUEST_TYPE)):
        if value not in allowed:
            return {"error": f"{name} must be one of {allowed}, got {value!r}"}

    if order_status == "not_found":
        decision, section, escalate = ("escalate_missing_order",
                                       "no billing record: escalate", True)
    elif order_status == "chargeback":
        decision, section, escalate = ("escalate_chargeback",
                                       "open bank dispute: disputes team", True)
    elif order_status == "refunded":
        decision, section, escalate = ("already_refunded",
                                       "one refund per order", False)
    elif request_type == "duplicate_charge":
        decision, section, escalate = ("refund_approved",
                                       "duplicate charges are always refunded",
                                       False)
    elif days_since_purchase is None or days_since_purchase > REFUND_WINDOW_DAYS:
        decision, section, escalate = ("outside_window",
                                       "the refund window is thirty days", False)
    elif (amount_usd or 0) > MANAGER_APPROVAL_THRESHOLD_USD:
        decision, section, escalate = ("needs_manager_approval",
                                       "refunds over USD 100 need a manager",
                                       True)
    else:
        decision, section, escalate = ("refund_approved",
                                       "inside the thirty-day window", False)

    if customer_tier == "priority":
        # SP-001: Priority tier is always escalated, whatever the decision.
        escalate, section = True, section + "; Priority tier is always escalated"
    return {"decision": decision, "escalate": escalate,
            "refund_allowed": decision in ("refund_approved",
                                           "needs_manager_approval"),
            "policy_section": section}


REGISTRY = {"get_ticket": get_ticket, "get_order": get_order,
            "lookup_refund_policy": lookup_refund_policy}


def call(name: str, args: dict) -> dict:
    """Execute one tool call. Unknown tools are an error result, not a crash."""
    fn = REGISTRY.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        return fn(**args)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
