"""The one model both systems call. Offline, deterministic, metered.

There is no ANTHROPIC_API_KEY on this checkout, so -- exactly as week6/judge.py
does -- the "LLM" is an offline engine with the Messages API's shape:
`complete(system, messages, tools)` takes Anthropic-format messages (text,
tool_use and tool_result blocks) and returns either tool_use blocks
(stop_reason "tool_use") or a final text block (stop_reason "end_turn").

What is real and what is not, stated once so the UI can repeat it:

  decisions   Real. The engine only sees the conversation it is handed. It
              reads tool results out of the messages and decides the next
              call from them; it cannot peek at store.py or the answer key.
  tokens      Estimated. ceil(chars / 4) over the exact JSON payload that
              would be sent (system + tool schemas + every message) and the
              exact JSON returned. The agent resends its whole history each
              turn and pays for that, as a real agent does.
  cost        Derived from those tokens at claude-opus-5 list price.
  latency     Measured wall-clock. Each call sleeps a simulated model latency
              (fixed + per-token), so latency tracks tokens the way it does
              with a hosted model; tool calls sleep a fixed round trip.

The final-answer step (draft) is shared code, so both systems produce the
same output contract from the same facts. A difference in the contract can
only come from a difference in which facts reached it.
"""
from __future__ import annotations

import json
import math
import re
import time

MODEL = "offline-policy-engine"
PRICED_AS = "claude-opus-5"
PRICE_IN_PER_MTOK = 5.00
PRICE_OUT_PER_MTOK = 25.00

# Simulated model latency: time-to-first-token plus prefill and decode rates.
LAT_BASE_S = 0.12
LAT_PER_IN_TOKEN_S = 0.00002
LAT_PER_OUT_TOKEN_S = 0.003

SYSTEM_AGENT = (
    "You resolve refund-chase support tickets. Use the tools to read the "
    "ticket, fetch every order it references, and ask lookup_refund_policy "
    "for the decision. Never decide eligibility yourself. When you have the "
    "policy decision, reply with ONLY a JSON object with keys ticket_id, "
    "decision, refund_order_id, refund_amount_usd, escalate, reply. The "
    "reply must name the ticket id, state any refund as a USD figure, and "
    "end with [ESCALATED] when escalate is true.")

SYSTEM_DRAFT = (
    "You draft the customer reply for a refund-chase ticket from the facts "
    "given. Reply with ONLY a JSON object with keys ticket_id, decision, "
    "refund_order_id, refund_amount_usd, escalate, reply. The reply must name "
    "the ticket id, state any refund as a USD figure, and end with "
    "[ESCALATED] when escalate is true.")

TICKET_RE = re.compile(r"TCK-\d{4}")


def estimate_tokens(obj) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True)
    return max(1, math.ceil(len(text) / 4))


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * PRICE_IN_PER_MTOK
            + output_tokens * PRICE_OUT_PER_MTOK) / 1_000_000


# ------------------------------------------------------------- the response

def complete(system: str, messages: list[dict],
             tools: list[dict] | None = None) -> dict:
    """One model call. Returns {content, stop_reason, usage, latency_s}."""
    t0 = time.perf_counter()
    if tools:
        content = _agent_step(messages)
    else:
        content = [{"type": "text", "text": json.dumps(_draft_from_facts(
            json.loads(messages[-1]["content"])))}]
    stop = "tool_use" if any(b["type"] == "tool_use" for b in content) \
        else "end_turn"

    usage = {"input_tokens": estimate_tokens(
                 {"system": system, "tools": tools or [], "messages": messages}),
             "output_tokens": estimate_tokens(content)}
    time.sleep(LAT_BASE_S + usage["input_tokens"] * LAT_PER_IN_TOKEN_S
               + usage["output_tokens"] * LAT_PER_OUT_TOKEN_S)
    return {"content": content, "stop_reason": stop, "usage": usage,
            "latency_s": time.perf_counter() - t0}


# ------------------------------------------------- agent mode: pick next step

def _observations(messages: list[dict]) -> tuple[str | None, list[tuple[dict, dict]]]:
    """The ticket id the user asked about, and every (tool_use, result) pair
    so far, in order. This is everything the engine is allowed to know."""
    first = messages[0]["content"]
    first = first if isinstance(first, str) else json.dumps(first)
    m = TICKET_RE.search(first)
    calls: dict[str, dict] = {}
    pairs = []
    for msg in messages:
        if not isinstance(msg["content"], list):
            continue
        for b in msg["content"]:
            if b["type"] == "tool_use":
                calls[b["id"]] = b
            elif b["type"] == "tool_result":
                pairs.append((calls[b["tool_use_id"]], json.loads(b["content"])))
    return (m.group(0) if m else None), pairs


def _tool_use(n: int, name: str, args: dict) -> list[dict]:
    return [{"type": "tool_use", "id": f"call_{n}", "name": name, "input": args}]


def _agent_step(messages: list[dict]) -> list[dict]:
    ticket_id, pairs = _observations(messages)
    n = len(pairs) + 1
    by_tool: dict[str, list[tuple[dict, dict]]] = {}
    for call, result in pairs:
        by_tool.setdefault(call["name"], []).append((call, result))

    if "get_ticket" not in by_tool:
        return _tool_use(n, "get_ticket", {"ticket_id": ticket_id})
    ticket = by_tool["get_ticket"][-1][1]

    fetched = {r["order_id"]: r for _, r in by_tool.get("get_order", [])}
    for oid in ticket.get("order_ids", []):
        if oid not in fetched:
            return _tool_use(n, "get_order", {"order_id": oid})

    target = pick_target_order(ticket, [fetched[o] for o in
                                        ticket.get("order_ids", [])])
    if "lookup_refund_policy" not in by_tool:
        return _tool_use(n, "lookup_refund_policy",
                         policy_args(ticket, target))
    policy = by_tool["lookup_refund_policy"][-1][1]
    return [{"type": "text", "text": json.dumps(
        _draft_from_facts({"ticket": ticket, "order": target,
                           "policy": policy}))}]


def pick_target_order(ticket: dict, orders: list[dict]) -> dict:
    """Which order the decision is about.

    A duplicate-charge ticket is about the LATER of two identical charges;
    finding it needs both orders in hand. Everything else is about the one
    order named, or a not_found stand-in when none was named.
    """
    if not orders:
        return {"order_id": None, "status": "not_found"}
    if ticket.get("request_type") == "duplicate_charge" and len(orders) >= 2:
        paid = [o for o in orders if o.get("status") == "paid"]
        for a in paid:
            for b in paid:
                if (a is not b and a["product"] == b["product"]
                        and a["amount_usd"] == b["amount_usd"]
                        and b["charged_at"] > a["charged_at"]):
                    return b
    return orders[0]


def policy_args(ticket: dict, order: dict) -> dict:
    return {"order_status": order.get("status", "not_found"),
            "customer_tier": ticket.get("customer_tier", "standard"),
            "request_type": ticket.get("request_type", "refund"),
            "days_since_purchase": order.get("days_since_purchase"),
            "amount_usd": order.get("amount_usd")}


# ------------------------------------------------ final answer: the contract

def _draft_from_facts(facts: dict) -> dict:
    ticket, order, policy = facts["ticket"], facts["order"], facts["policy"]
    tid = ticket["ticket_id"]
    decision = policy.get("decision", "escalate_missing_order")
    escalate = bool(policy.get("escalate", True))
    oid = order.get("order_id")
    amount = order.get("amount_usd")
    refund = decision in ("refund_approved", "needs_manager_approval")

    if decision == "refund_approved":
        body = (f"We have approved a refund of USD {amount:.2f} for order "
                f"{oid} ({order.get('product')}). It will reach your original "
                "payment method within 5-10 business days.")
    elif decision == "needs_manager_approval":
        body = (f"Your request for USD {amount:.2f} back on order {oid} is "
                "above what support can approve directly, so it has gone to a "
                "billing manager for sign-off. You will hear back within one "
                "business day.")
    elif decision == "outside_window":
        body = (f"Order {oid} was purchased {order.get('days_since_purchase')} "
                "days ago, which is outside our 30-day window, so it is not "
                "eligible for a refund.")
    elif decision == "already_refunded":
        body = (f"Our records show order {oid} was already refunded in full, "
                "so there is nothing further to process. Bank transfers can "
                "take up to 10 business days to appear.")
    elif decision == "escalate_chargeback":
        body = (f"Order {oid} has an open dispute with your bank, so it is "
                "handled by our disputes team rather than as a refund. I have "
                "passed your ticket to them.")
    elif oid:
        body = (f"I could not find order {oid} in our billing system. I have "
                "passed your ticket to the billing team, who will confirm the "
                "order details with you.")
    else:
        body = ("Your message does not include an order number, so I cannot "
                "look up the charge. I have passed your ticket to the billing "
                "team, who will confirm the order details with you.")

    parts = [f"Hi, thanks for raising ticket {tid}.", body]
    if escalate:
        parts.append("[ESCALATED]")
    parts.append("Best regards,\nBilling Support")
    return {"ticket_id": tid, "decision": decision,
            "refund_order_id": oid if refund else None,
            "refund_amount_usd": amount if refund else None,
            "escalate": escalate, "reply": "\n\n".join(parts)}
