"""Week 8 tools: Week 7's three, one optional search, and the ONE mitigation.

get_order and lookup_refund_policy are Week 7's functions (week7/tools.py),
called with their simulated sleep switched off -- latency is accounted by
the meter instead, so 200 runs take seconds and the numbers are repeatable.
get_ticket reads the Week-8 ticket text (store8.TICKETS).

The mitigation
--------------
validate_policy_args() -- argument validation on lookup_refund_policy. It is
the whole diff between the "before" and "after" runs (see MITIGATION_DIFF in
trajectory_eval.py). The rule: the order facts passed to the policy tool must
equal an order record that get_order returned earlier IN THIS RUN. Facts
typed from the customer's email, however correct they look, are rejected with
an error that names the order to fetch. A not_found with no record is allowed
only when the ticket names no order at all.

Nothing else changes: same tool descriptions, same schemas, same step limit,
same model. That is what makes the before -> after count attributable.
"""
from __future__ import annotations

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEEK7 = os.path.join(HERE, "..", "week7")
for p in (HERE, WEEK7):
    if p not in sys.path:
        sys.path.insert(0, p)

import tools as T7  # noqa: E402  (week7/tools.py)
from store8 import ORDERS, PRIOR, TICKETS  # noqa: E402

T7.TOOL_LATENCY_S = 0.0          # accounted by the meter, not slept
TOOL_LATENCY_S = 0.04            # the same simulated round trip as Week 7

SEARCH_TICKETS = {
    "name": "search_tickets",
    "description": (
        "Find earlier support tickets that mention one order id. Optional "
        "context only: use it when the customer says they have been in "
        "touch before. Never decides anything."),
    "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string",
                                    "pattern": r"^ORD-\d{4}$"}},
        "required": ["order_id"],
    },
}

TOOLS = copy.deepcopy(T7.TOOLS) + [SEARCH_TICKETS]


def get_ticket(ticket_id: str) -> dict:
    t = TICKETS.get(ticket_id)
    if t is None:
        return {"ticket_id": ticket_id, "found": False}
    return {"ticket_id": ticket_id, "found": True, **copy.deepcopy(t)}


def search_tickets(order_id: str) -> dict:
    return {"order_id": order_id, "tickets": copy.deepcopy(PRIOR.get(order_id, []))}


FACT_KEYS = ("status", "days_since_purchase", "amount_usd")


def record_matches(args: dict, record: dict) -> bool:
    return (args.get("order_status") == record.get("status")
            and args.get("days_since_purchase") == record.get("days_since_purchase")
            and args.get("amount_usd") == record.get("amount_usd"))


def validate_policy_args(args: dict, state: dict) -> str | None:
    """The mitigation. None if the facts came from a fetched record, else an
    error message the model can act on."""
    fetched = state["orders"]
    if any(record_matches(args, r) for r in fetched.values()):
        return None
    ticket = state.get("ticket") or {}
    if (args.get("order_status") == "not_found"
            and not ticket.get("order_ids")
            and args.get("days_since_purchase") is None
            and args.get("amount_usd") is None):
        return None
    wanted = [o for o in ticket.get("order_ids", []) if o not in fetched]
    hint = (f" Call get_order({wanted[0]!r}) first." if wanted else "")
    return ("argument validation failed: the order facts passed to "
            "lookup_refund_policy do not match any order record returned by "
            f"get_order in this run.{hint}")


def call(name: str, args: dict, state: dict, validate: bool) -> dict:
    """Execute one tool call against the run's state."""
    if name == "get_ticket":
        r = get_ticket(**args)
        if r.get("found"):
            state["ticket"] = r
        return r
    if name == "get_order":
        r = T7.get_order(**args)
        state["orders"][args.get("order_id")] = r
        return r
    if name == "search_tickets":
        return search_tickets(**args)
    if name == "lookup_refund_policy":
        if validate:
            err = validate_policy_args(args, state)
            if err:
                return {"error": err}
        return T7.lookup_refund_policy(**args)
    if name == "issue_refund" and "issue_refund" in state.get("extra_tools", {}):
        return state["extra_tools"]["issue_refund"](state, **args)
    return {"error": f"unknown tool {name!r}"}
