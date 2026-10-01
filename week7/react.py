"""ReAct: the agent loop with its reasoning written down.

    .venv/bin/python week7/react.py TCK-7009       # one ticket, full transcript
    .venv/bin/python week7/react.py                # all 10, one line each

ReAct (Reason + Act) is the agent loop in agent.py with one addition: before
every Action the model writes a Thought, and after it the tool's result comes
back as an Observation. The loop is unchanged --

    Thought  -> why the next step is needed, from what has been observed
    Action   -> one tool call (name + arguments)
    Observation -> the tool result, appended to the conversation
    ... repeat until the Thought is "I have the decision" -> Final Answer

The value is the trace: a reviewer can see WHY the agent fetched a second
order on TCK-7009, not just that it did.

What is real: the Action is chosen by the same model.complete() call the
agent uses, from the same conversation. The Thought text is written by this
file from the observations so far (the offline engine returns tool_use blocks,
not prose) -- with a hosted model the Thought is the text block it emits
before its tool_use block.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from agent import Budgets, Meter, _breached, _handoff, call_model, run_tool  # noqa: E402
import model  # noqa: E402
import tools as T  # noqa: E402
from store import TICKET_IDS  # noqa: E402


def thought(action: dict | None, seen: dict) -> str:
    """The reasoning that justifies the next action, from observations only."""
    ticket = seen.get("get_ticket")
    if action is None:
        return ("I have the policy decision for the right order, so I can "
                "write the final answer.")
    name, args = action["name"], action["input"]
    if name == "get_ticket":
        return (f"I know nothing about {args['ticket_id']} yet. I need the "
                "customer's message, tier and the orders it references.")
    if name == "get_order":
        ids = ticket.get("order_ids", [])
        fetched = [o for o in ids if o in seen.get("orders", {})]
        if fetched:
            return (f"The ticket names {len(ids)} orders and I have only "
                    f"fetched {', '.join(fetched)}. To find the duplicate I "
                    f"must compare charges, so I fetch {args['order_id']}.")
        if len(ids) > 1:
            return (f"The ticket names {len(ids)} orders ({', '.join(ids)}). "
                    f"I start with {args['order_id']}.")
        return (f"The ticket references {args['order_id']}. I need its status, "
                "amount and age before any decision.")
    if name == "lookup_refund_policy":
        if not ticket.get("order_ids"):
            return ("The ticket names no order, so there is nothing to fetch. "
                    "I ask the policy what happens to a missing order.")
        return (f"I have the facts (status={args['order_status']}, "
                f"tier={args['customer_tier']}, "
                f"days={args.get('days_since_purchase')}, "
                f"amount={args.get('amount_usd')}). I must not decide "
                "eligibility myself, so I ask the policy tool.")
    return f"I call {name}."


def run_react(ticket_id: str, budgets: Budgets | None = None,
              verbose: bool = True) -> dict:
    b = budgets or Budgets()
    meter = Meter("react", ticket_id)
    messages = [{"role": "user",
                 "content": f"Resolve support ticket {ticket_id}."}]
    seen: dict = {"orders": {}}
    trace: list[dict] = []
    step = 0

    def say(line: str) -> None:
        if verbose:
            print(line)

    say(f"Question: Resolve support ticket {ticket_id}.")
    while True:
        stop = _breached(meter, b, before_call=True)
        if stop:
            say(f"\n[STOP] budget {stop['budget']} reached "
                f"({stop['observed']} >= {stop['limit']}) -> hand to a human")
            return {"ticket_id": ticket_id, "output": _handoff(ticket_id),
                    "terminated": stop, "trace": trace, **meter.summary()}

        resp = call_model(meter, model.SYSTEM_AGENT, messages, T.TOOLS)
        messages.append({"role": "assistant", "content": resp["content"]})
        actions = [c for c in resp["content"] if c["type"] == "tool_use"]
        step += 1

        if not actions:
            t = thought(None, seen)
            output = json.loads(resp["content"][0]["text"])
            say(f"\nThought {step}: {t}")
            say(f"Final Answer: decision={output['decision']} "
                f"refund={output['refund_order_id']} "
                f"escalate={output['escalate']}")
            trace.append({"step": step, "thought": t, "final": output})
            return {"ticket_id": ticket_id, "output": output,
                    "terminated": None, "trace": trace, **meter.summary()}

        results = []
        for a in actions:
            t = thought(a, seen)
            obs = run_tool(meter, a["name"], a["input"])
            if a["name"] == "get_ticket":
                seen["get_ticket"] = obs
            elif a["name"] == "get_order":
                seen["orders"][obs["order_id"]] = obs
            say(f"\nThought {step}: {t}")
            say(f"Action {step}: {a['name']}({json.dumps(a['input'])})")
            say(f"Observation {step}: {json.dumps(obs)}")
            trace.append({"step": step, "thought": t, "action": a["name"],
                          "args": a["input"], "observation": obs})
            results.append({"type": "tool_result", "tool_use_id": a["id"],
                            "content": json.dumps(obs)})
        messages.append({"role": "user", "content": results})


def main() -> None:
    if len(sys.argv) > 1:
        r = run_react(sys.argv[1])
        print(f"\n{r['llm_calls']} model calls, {r['total_tokens']} tokens, "
              f"${r['cost_usd']:.4f}, {r['latency_s']:.2f}s")
        return
    for tid in TICKET_IDS:
        r = run_react(tid, verbose=False)
        print(f"{tid}  {len(r['trace'])} thought/action steps  "
              f"{' -> '.join(r['path']):55} {r['output']['decision']}")


if __name__ == "__main__":
    main()
