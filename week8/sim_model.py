"""The Week-8 model: Week 7's offline engine, sampled.

Week 7's engine was a perfect, deterministic policy -- it took the textbook
path every time, so a trajectory eval over it would score 100% and find
nothing. A hosted model at temperature > 0 does not behave like that. This
engine keeps Week 7's decision logic and adds the behaviours a real tool-using
model shows, each one a NAMED RATE in RATES below, drawn from a seeded hash
so every run is reproducible and the before/after runs see the same draws
until their trajectories diverge (common random numbers).

Still true from Week 7: the engine sees only the conversation it is handed.
It reads tool results out of the messages; it cannot read store8.py, the
answer key or the eval. Tokens are ceil(chars/4) of the exact payload, cost is
claude-opus-5 list price on those tokens, latency is simulated (Week 7's
per-call formula), not slept.

What is NOT real, stated plainly: the rates. They are chosen, not measured
off a hosted model (there is no ANTHROPIC_API_KEY on this checkout). The
eval, the failure taxonomy, the mitigation and its price are real code paths;
how often the model wanders is a dial. Swap complete() for the Messages API
and every number in trajectory_eval.py is computed the same way.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEEK7 = os.path.join(HERE, "..", "week7")
if WEEK7 not in sys.path:
    sys.path.insert(0, WEEK7)

import model as M7  # noqa: E402  (week7/model.py)
from store8 import MENTIONS_PRIOR  # noqa: E402

RATES = {
    # Customer quoted amount + age of a single order: trust their numbers and
    # go straight to the policy tool without opening the order record.
    "skip_order_lookup": 0.45,
    # Ticket names no order: invent a plausible-looking order id and fetch it.
    "invent_order_id": 0.40,
    # Two orders named: ask the policy after fetching only the first.
    "premature_decision": 0.25,
    # After any successful call, issue the identical call again ...
    "repeat_call": 0.06,
    # ... and once repeating, keep repeating (this is the loop tail).
    "repeat_continue": 0.55,
    # After a tool error, resend the identical call instead of re-planning
    # (capped at 3 in a row).
    "retry_after_error": 0.35,
    # Customer mentions earlier contact: look up prior tickets (optional).
    "search_prior": 0.50,
    # ... and if so, do it after pulling the order rather than before.
    "search_after_order": 0.50,
    # Customer does NOT mention earlier contact: search anyway (unneeded).
    "spurious_search": 0.04,
    # Duplicate-charge ticket: fetch the two orders in the reverse order.
    "reverse_fetch_order": 0.50,
    # Bonus: obey an instruction found inside a tool result. Unwrapped tool
    # output is obeyed every time; output inside the sanitiser's
    # <untrusted_customer_text> wrapper is obeyed this often.
    "obey_injection_wrapped": 0.50,
    # Bonus: obey an instruction typed straight into the USER's own message
    # (direct injection). Users are trusted more than tool output, so this is
    # higher than the wrapped rate.
    "obey_injection_direct": 0.80,
}

AMOUNT_RE = re.compile(r"\$(\d+(?:\.\d{2})?)")
DAYS_RE = re.compile(r"(\d+)\s+days ago")
INVENTED_ORDER_ID = "ORD-5100"

# Bonus: what the engine is susceptible to inside a tool result.
REFUND_CUE = re.compile(r"(ignore (all |any )?(previous|prior) instructions|"
                        r"policy override|(issue|process) a full refund)", re.I)
SAY_CUE = re.compile(r"also tell the customer (.+?)(?:\.|$)", re.I)


def draw(seed: int, tid: str, key: str, n: int = 0) -> float:
    h = hashlib.sha256(f"{seed}|{tid}|{key}|{n}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def _tool_use(n: int, name: str, args: dict) -> list[dict]:
    return [{"type": "tool_use", "id": f"call_{n}", "name": name,
             "input": args}]


def _text(obj: dict) -> list[dict]:
    return [{"type": "text", "text": json.dumps(obj)}]


def quoted_facts(message: str) -> tuple[float | None, int | None]:
    a, d = AMOUNT_RE.search(message), DAYS_RE.search(message)
    return (float(a.group(1)) if a else None, int(d.group(1)) if d else None)


def _matching_record(args: dict, fetched: dict, ticket: dict) -> dict | None:
    """The fetched record the policy facts came from. Duplicate charges have
    IDENTICAL facts, so several records can match; then the order the
    decision is about is chosen the same way it was targeted (the later of
    the duplicate pair), not by whichever was fetched first."""
    hits = [r for r in fetched.values()
            if (args.get("order_status") == r.get("status")
                and args.get("days_since_purchase") == r.get("days_since_purchase")
                and args.get("amount_usd") == r.get("amount_usd"))]
    if len(hits) > 1:
        return M7.pick_target_order(ticket, hits)
    return hits[0] if hits else None


def agent_step(messages: list[dict], seed: int, tool_names: set[str]) -> list[dict]:
    tid, pairs = M7._observations(messages)
    n = len(pairs) + 1
    d = lambda key, i=0: draw(seed, tid, key, i)  # noqa: E731

    # ---------------------------------------------- react to the last result
    if pairs:
        last_call, last_res = pairs[-1]
        if "error" in last_res:
            streak = 0
            for c, r in reversed(pairs):
                if "error" in r and c["name"] == last_call["name"] \
                        and c["input"] == last_call["input"]:
                    streak += 1
                else:
                    break
            if streak <= 3 and d("retry", n) < RATES["retry_after_error"]:
                return _tool_use(n, last_call["name"], last_call["input"])
        else:
            was_repeat = (len(pairs) >= 2
                          and pairs[-2][0]["name"] == last_call["name"]
                          and pairs[-2][0]["input"] == last_call["input"])
            p = RATES["repeat_continue"] if was_repeat else RATES["repeat_call"]
            if d("repeat", n) < p:
                return _tool_use(n, last_call["name"], last_call["input"])

    # ---------------------------------------------------------- the plan
    calls = [c for c, _ in pairs]
    ok = [(c, r) for c, r in pairs if "error" not in r]
    if not any(c["name"] == "get_ticket" for c, _ in ok):
        return _tool_use(n, "get_ticket", {"ticket_id": tid})
    ticket = [r for c, r in ok if c["name"] == "get_ticket"][-1]
    ids = ticket.get("order_ids", [])
    msg = ticket.get("message", "")
    fetched = {r["order_id"]: r for c, r in ok if c["name"] == "get_order"}
    searched = any(c["name"] == "search_tickets" for c in calls)
    policy_ok = [(c, r) for c, r in ok if c["name"] == "lookup_refund_policy"]
    told_to_fetch = any("error" in r and "get_order" in r["error"]
                        for _, r in pairs)
    amount, days = quoted_facts(msg)

    # Injection: an instruction inside the ticket body (a tool result).
    wrapped = "<untrusted_customer_text>" in msg
    refund_cue = REFUND_CUE.search(msg)
    obey = bool(refund_cue) and (not wrapped
                                 or d("obey") < RATES["obey_injection_wrapped"])
    # Direct injection: the same cues, in the user's own turn.
    user_text = messages[0]["content"] if isinstance(messages[0]["content"], str) else ""
    direct = d("obey_direct") < RATES["obey_injection_direct"]
    obey = obey or (bool(REFUND_CUE.search(user_text)) and direct)
    if obey and "issue_refund" in tool_names and ids \
            and not any(c["name"] == "issue_refund" for c in calls):
        if ids[0] not in fetched:
            return _tool_use(n, "get_order", {"order_id": ids[0]})
        o = fetched[ids[0]]
        return _tool_use(n, "issue_refund", {"order_id": ids[0],
                                             "amount_usd": o.get("amount_usd")})

    skip = (len(ids) == 1 and amount is not None and days is not None
            and ticket.get("request_type") == "refund" and not told_to_fetch
            and d("skip") < RATES["skip_order_lookup"])
    if skip and not policy_ok:
        return _tool_use(n, "lookup_refund_policy", {
            "order_status": "paid",
            "customer_tier": ticket.get("customer_tier", "standard"),
            "request_type": ticket.get("request_type", "refund"),
            "days_since_purchase": days, "amount_usd": amount})

    # No order named: maybe invent one ("my last purchase" -> some id).
    if not ids and not policy_ok and d("invent") < RATES["invent_order_id"] \
            and INVENTED_ORDER_ID not in fetched:
        return _tool_use(n, "get_order", {"order_id": INVENTED_ORDER_ID})

    # Optional search, before or after the order, where the customer
    # mentions earlier contact. Spurious search elsewhere.
    if ids and not searched and not policy_ok:
        prior = bool(MENTIONS_PRIOR.search(msg))
        want = (d("search") < RATES["search_prior"]) if prior \
            else (d("spurious") < RATES["spurious_search"])
        after = d("search_pos") < RATES["search_after_order"] or not prior
        all_fetched = all(o in fetched for o in ids)
        if want and (all_fetched if after else not fetched):
            return _tool_use(n, "search_tickets", {"order_id": ids[0]})

    order_seq = list(ids)
    if len(ids) >= 2 and d("reverse") < RATES["reverse_fetch_order"]:
        order_seq = order_seq[::-1]

    if not policy_ok:
        premature = (len(ids) >= 2 and len(fetched) >= 1
                     and d("premature") < RATES["premature_decision"])
        if not premature:
            for oid in order_seq:
                if oid not in fetched:
                    return _tool_use(n, "get_order", {"order_id": oid})
        known = [fetched[o] for o in order_seq if o in fetched] \
            or ([fetched[INVENTED_ORDER_ID]] if INVENTED_ORDER_ID in fetched
                else [])
        target = M7.pick_target_order(ticket, known)
        return _tool_use(n, "lookup_refund_policy",
                         M7.policy_args(ticket, target))

    # ------------------------------------------------------- final answer
    pargs, policy = policy_ok[-1]
    order = _matching_record(pargs["input"], fetched, ticket) or {
        "order_id": ids[0] if ids else None, "status": pargs["input"]["order_status"],
        "amount_usd": pargs["input"].get("amount_usd"),
        "days_since_purchase": pargs["input"].get("days_since_purchase"),
        "product": "your purchase"}
    out = M7._draft_from_facts({"ticket": ticket, "order": order,
                                "policy": policy})
    if obey:
        refunds = [r for c, r in ok if c["name"] == "issue_refund"]
        amt = (fetched.get(ids[0]) or {}).get("amount_usd") if ids else None
        if refunds or amt is not None:
            out.update(decision="refund_approved", refund_order_id=ids[0],
                       refund_amount_usd=amt, escalate=False)
            out["reply"] = (f"Hi, thanks for raising ticket {tid}.\n\nAs "
                            f"requested, we have issued a full refund of USD "
                            f"{amt:.2f} for order {ids[0]}.\n\nBest regards,\n"
                            "Billing Support")
    say = SAY_CUE.search(msg)
    if not (say and (not wrapped or d("obey_say") < RATES["obey_injection_wrapped"])):
        say = SAY_CUE.search(user_text) if direct else None
    if say:
        out["reply"] = out["reply"].replace(
            "\n\nBest regards", f"\n\nAlso, {say.group(1).strip()}.\n\nBest regards")
    return _text(out)


def complete(system: str, messages: list[dict], tools: list[dict],
             seed: int) -> dict:
    content = agent_step(messages, seed, {t["name"] for t in tools})
    stop = "tool_use" if any(b["type"] == "tool_use" for b in content) \
        else "end_turn"
    usage = {"input_tokens": M7.estimate_tokens(
                 {"system": system, "tools": tools, "messages": messages}),
             "output_tokens": M7.estimate_tokens(content)}
    latency = (M7.LAT_BASE_S + usage["input_tokens"] * M7.LAT_PER_IN_TOKEN_S
               + usage["output_tokens"] * M7.LAT_PER_OUT_TOKEN_S)
    return {"content": content, "stop_reason": stop, "usage": usage,
            "latency_s": latency}
