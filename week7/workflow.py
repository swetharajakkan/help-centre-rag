"""The fixed workflow: the same task in four hard-coded steps. No loop.

    .venv/bin/python week7/workflow.py TCK-7004         # one ticket
    .venv/bin/python week7/workflow.py                  # all 10

    1. get_ticket(ticket_id)
    2. get_order(first order id on the ticket)
    3. lookup_refund_policy(facts from 1 and 2)
    4. one model call: draft the reply from those facts

Same tools (tools.py), same model (model.complete), same output contract, same
Meter and tracing as the agent. There is no `while`, no `for` over tool
calls, and the model is never shown a tool schema, so it cannot choose a
step. Every ticket takes exactly these four steps, whatever step 2 returns.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from agent import Meter, call_model, run_tool, tracing  # noqa: E402
import model  # noqa: E402
from store import TICKET_IDS  # noqa: E402


def run_workflow(ticket_id: str, session_id: str | None = None) -> dict:
    meter = Meter("workflow", ticket_id)
    meter.event("start")
    with tracing.observe("resolve-ticket-workflow", as_type="chain",
                         input={"ticket_id": ticket_id}) as root, \
            tracing.trace_attributes(session_id=session_id,
                                    tags=["week7", "system:workflow", ticket_id]):

        # Step 1 -- the ticket.
        ticket = run_tool(meter, "get_ticket", {"ticket_id": ticket_id})

        # Step 2 -- the order. Always exactly one call: the first id named, or
        # None, which the billing system answers with not_found.
        order_ids = ticket.get("order_ids") or [None]
        order = run_tool(meter, "get_order", {"order_id": order_ids[0]})

        # Step 3 -- the policy decision, from whatever steps 1 and 2 found.
        policy = run_tool(meter, "lookup_refund_policy", {
            "order_status": order.get("status", "not_found"),
            "customer_tier": ticket.get("customer_tier", "standard"),
            "request_type": ticket.get("request_type", "refund"),
            "days_since_purchase": order.get("days_since_purchase"),
            "amount_usd": order.get("amount_usd"),
        })

        # Step 4 -- one model call, no tools offered, drafts the contract.
        facts = {"ticket": ticket, "order": order, "policy": policy}
        resp = call_model(meter, model.SYSTEM_DRAFT,
                          [{"role": "user", "content": json.dumps(facts)}],
                          tools=None)
        output = json.loads(resp["content"][0]["text"])

        meter.event("finished", decision=output["decision"])
        root.update(input=f"Resolve support ticket {ticket_id}.",
                    output=output, metadata={
            "ticket_id": ticket_id,
            "path": [s["name"] for s in meter.steps if s["kind"] == "tool"],
            "llm_calls": meter.llm_calls, "total_tokens": meter.tokens,
            "cost_usd": meter.cost})
        url = tracing.trace_url()

    return {"system": "workflow", "ticket_id": ticket_id, "output": output,
            "terminated": None, "trace_url": url, **meter.summary()}


def main() -> None:
    ids = sys.argv[1:] or TICKET_IDS
    for tid in ids:
        r = run_workflow(tid)
        print(f"{tid}  {' -> '.join(r['path']):55} "
              f"{r['output']['decision']:24} {r['total_tokens']:6} tok  "
              f"${r['cost_usd']:.4f}  {r['latency_s']:.2f}s")
    tracing.flush()


if __name__ == "__main__":
    main()
