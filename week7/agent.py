"""The agent: a model-driven tool loop with four hard budgets.

    .venv/bin/python week7/agent.py TCK-7004            # one ticket
    .venv/bin/python week7/agent.py                     # all 10
    .venv/bin/python week7/agent.py TCK-7009 --max-tokens 4000

The loop is the textbook one: send the conversation, run whatever tools the
model asks for, append the results, repeat until the model answers in text.
Which tools run, in what order and how many times, is decided by the model
from what the previous tool returned -- that is the only thing that makes it
an agent rather than a workflow.

Budgets
-------
All four are checked BEFORE every model call, and tokens/cost are checked
again right after one, so a call that blows the budget cannot also trigger
more tool calls:

  max_iterations   model calls in this run
  max_tokens       input + output tokens summed over every model call
  max_cost_usd     the same, in dollars
  max_wall_s       wall-clock since the run started

When one fires the loop stops, the ticket is handed to a human with an
[ESCALATED] reply, and `terminated` records which budget, its limit and the
value observed. No exception, no partial tool call, no retry.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app import tracing  # noqa: E402

tracing.load_dotenv()

import model  # noqa: E402
import tools as T  # noqa: E402
from store import TICKET_IDS  # noqa: E402


@dataclass
class Budgets:
    max_iterations: int = 8
    max_tokens: int = 20_000
    max_cost_usd: float = 0.25
    max_wall_s: float = 20.0


class Meter:
    """Running totals and a structured event log for one run."""

    def __init__(self, system: str, ticket_id: str):
        self.system, self.ticket_id = system, ticket_id
        self.t0 = time.perf_counter()
        self.tokens_in = self.tokens_out = self.llm_calls = 0
        self.cost = 0.0
        self.steps: list[dict] = []
        self.log: list[dict] = []

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0

    def event(self, event: str, **fields) -> None:
        self.log.append({"t": round(self.elapsed(), 3), "system": self.system,
                         "ticket_id": self.ticket_id, "event": event, **fields})

    def llm(self, resp: dict) -> None:
        u = resp["usage"]
        c = model.cost_usd(u["input_tokens"], u["output_tokens"])
        self.llm_calls += 1
        self.tokens_in += u["input_tokens"]
        self.tokens_out += u["output_tokens"]
        self.cost += c
        self.steps.append({"kind": "llm", "stop_reason": resp["stop_reason"],
                           "input_tokens": u["input_tokens"],
                           "output_tokens": u["output_tokens"],
                           "cost_usd": c, "latency_s": resp["latency_s"]})
        self.event("model_call", n=self.llm_calls,
                   stop_reason=resp["stop_reason"], tokens_total=self.tokens,
                   cost_usd=round(self.cost, 6))

    def tool(self, name: str, args: dict, result: dict, latency: float) -> None:
        self.steps.append({"kind": "tool", "name": name, "args": args,
                           "result": result, "latency_s": latency})
        self.event("tool_call", tool=name, args=args)

    def summary(self) -> dict:
        return {"llm_calls": self.llm_calls, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "total_tokens": self.tokens,
                "cost_usd": self.cost, "latency_s": self.elapsed(),
                "path": [s["name"] for s in self.steps if s["kind"] == "tool"],
                "steps": self.steps, "log": self.log}


def run_tool(meter: Meter, name: str, args: dict) -> dict:
    t0 = time.perf_counter()
    with tracing.observe(name, as_type="tool", input=args) as span:
        result = T.call(name, args)
        span.update(output=result)
    meter.tool(name, args, result, time.perf_counter() - t0)
    return result


def call_model(meter: Meter, system: str, messages: list[dict],
               tools: list[dict] | None) -> dict:
    with tracing.observe("call-model", as_type="generation",
                         model=model.MODEL,
                         input=messages[-1]["content"]) as gen:
        resp = model.complete(system, messages, tools)
        u = resp["usage"]
        gen.update(output=resp["content"],
                   usage_details={"input": u["input_tokens"],
                                  "output": u["output_tokens"]},
                   cost_details={"total": model.cost_usd(u["input_tokens"],
                                                         u["output_tokens"])},
                   metadata={"stop_reason": resp["stop_reason"],
                             "priced_as": model.PRICED_AS,
                             "tokens": "estimated chars/4"})
    meter.llm(resp)
    return resp


def _breached(meter: Meter, b: Budgets, before_call: bool) -> dict | None:
    """The first budget that is exhausted, or None. Order: wall-clock,
    iterations, tokens, cost -- cheapest to observe first."""
    checks = [("max_wall_s", b.max_wall_s, round(meter.elapsed(), 3)),
              ("max_tokens", b.max_tokens, meter.tokens),
              ("max_cost_usd", b.max_cost_usd, round(meter.cost, 6))]
    if before_call:
        checks.insert(1, ("max_iterations", b.max_iterations, meter.llm_calls))
    for name, limit, observed in checks:
        if observed >= limit:
            return {"budget": name, "limit": limit, "observed": observed}
    return None


def _handoff(ticket_id: str) -> dict:
    """What a budget termination returns: same contract, sent to a human."""
    return {"ticket_id": ticket_id, "decision": None, "refund_order_id": None,
            "refund_amount_usd": None, "escalate": True,
            "reply": (f"Hi, thanks for raising ticket {ticket_id}.\n\n"
                      "I've passed your ticket to a colleague in the billing "
                      "team, who will pick it up from here.\n\n[ESCALATED]\n\n"
                      "Best regards,\nBilling Support")}


def run_agent(ticket_id: str, budgets: Budgets | None = None,
              session_id: str | None = None) -> dict:
    b = budgets or Budgets()
    meter = Meter("agent", ticket_id)
    meter.event("start", budgets=asdict(b))
    messages = [{"role": "user",
                 "content": f"Resolve support ticket {ticket_id}."}]
    output, terminated = None, None

    with tracing.observe("resolve-ticket-agent", as_type="agent",
                         input={"ticket_id": ticket_id, "budgets": asdict(b)}) as root, \
            tracing.trace_attributes(session_id=session_id,
                                    tags=["week7", "system:agent", ticket_id]):
        while True:
            terminated = _breached(meter, b, before_call=True)
            if terminated:
                break
            resp = call_model(meter, model.SYSTEM_AGENT, messages, T.TOOLS)
            messages.append({"role": "assistant", "content": resp["content"]})
            if resp["stop_reason"] != "tool_use":
                output = json.loads(resp["content"][0]["text"])
                break
            # The call that just returned may itself have crossed a budget.
            # Stop before running the tools it asked for.
            terminated = _breached(meter, b, before_call=False)
            if terminated:
                break
            results = []
            for block in resp["content"]:
                if block["type"] != "tool_use":
                    continue
                r = run_tool(meter, block["name"], block["input"])
                results.append({"type": "tool_result",
                                "tool_use_id": block["id"],
                                "content": json.dumps(r)})
            messages.append({"role": "user", "content": results})

        if terminated:
            meter.event("budget_exceeded", **terminated)
            output = _handoff(ticket_id)
            meter.event("terminated_cleanly", handed_off_to="human",
                        llm_calls=meter.llm_calls, tokens_total=meter.tokens,
                        cost_usd=round(meter.cost, 6))
            tracing.score("budget_terminated", terminated["budget"],
                          f"limit {terminated['limit']}, observed "
                          f"{terminated['observed']}")
        else:
            meter.event("finished", decision=output["decision"])
        # The root observation carries the run's input and the full output
        # contract, so an evaluator on this one observation sees everything.
        root.update(input=f"Resolve support ticket {ticket_id}.",
                    output=output, metadata={
            "ticket_id": ticket_id, "budgets": asdict(b),
            "path": [s["name"] for s in meter.steps if s["kind"] == "tool"],
            "llm_calls": meter.llm_calls, "total_tokens": meter.tokens,
            "cost_usd": meter.cost, "terminated": terminated})
        url = tracing.trace_url()

    return {"system": "agent", "ticket_id": ticket_id, "output": output,
            "terminated": terminated, "budgets": asdict(b), "trace_url": url,
            **meter.summary()}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("ticket", nargs="?")
    ap.add_argument("--max-iterations", type=int, default=Budgets.max_iterations)
    ap.add_argument("--max-tokens", type=int, default=Budgets.max_tokens)
    ap.add_argument("--max-cost", type=float, default=Budgets.max_cost_usd)
    ap.add_argument("--max-wall", type=float, default=Budgets.max_wall_s)
    a = ap.parse_args()
    b = Budgets(a.max_iterations, a.max_tokens, a.max_cost, a.max_wall)
    for tid in ([a.ticket] if a.ticket else TICKET_IDS):
        r = run_agent(tid, b)
        stop = (f"TERMINATED by {r['terminated']['budget']}"
                if r["terminated"] else r["output"]["decision"])
        print(f"{tid}  {' -> '.join(r['path']):55} {stop:24} "
              f"{r['total_tokens']:6} tok  ${r['cost_usd']:.4f}  "
              f"{r['latency_s']:.2f}s")
    tracing.flush()


if __name__ == "__main__":
    main()
