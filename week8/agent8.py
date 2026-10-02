"""The Week-8 agent loop: Week 7's loop, same budgets, sampled engine.

    .venv/bin/python week8/agent8.py TCK-7001 --seed 3            # one run
    .venv/bin/python week8/agent8.py TCK-7001 --seed 3 --mitigate

Differences from week7/agent.py, all mechanical:
  * model.complete -> sim_model.complete(seed=...)  (sampled engine)
  * every tool call goes through tools8.call(), which owns per-run state
    (the records fetched so far) and, with validate=True, the mitigation
  * latency is the simulated per-call latency summed, not slept, so the
    wall-clock budget and the latency numbers are repeatable
  * no Langfuse traffic: 300 eval runs should not land in a shared project

Budgets are Week 7's defaults (8 model calls, 20k tokens, $0.25), checked
before every model call and again after one, exactly as Week 7 does.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
WEEK7 = os.path.join(HERE, "..", "week7")
for p in (HERE, WEEK7):
    if p not in sys.path:
        sys.path.insert(0, p)

import model as M7  # noqa: E402
import sim_model  # noqa: E402
import tools8  # noqa: E402


@dataclass
class Budgets:
    max_iterations: int = 8
    max_tokens: int = 20_000
    max_cost_usd: float = 0.25
    max_wall_s: float = 20.0


@dataclass
class Config:
    validate_policy_args: bool = False     # the Week-8 mitigation
    # Chat only: run the ticket with different customer wording (e.g. the
    # Week 7 text, which quotes no figures). Same ticket id, same scoring.
    ticket_message: str | None = None
    # Bonus only (injection.py): extra tools, output sanitiser, guardrail.
    extra_tools: dict = field(default_factory=dict)
    extra_schemas: list = field(default_factory=list)
    sanitize: object = None                # fn(tool_name, result) -> result
    guardrail: object = None               # fn(output, state) -> output


class Meter:
    def __init__(self):
        self.tokens_in = self.tokens_out = self.llm_calls = 0
        # latency is simulated (repeatable); overhead_s is the real time spent
        # in our own code -- validator, sanitiser, guardrail -- kept apart.
        self.cost = self.latency = self.overhead_s = 0.0
        self.steps: list[dict] = []

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


def _breached(m: Meter, b: Budgets, before_call: bool) -> dict | None:
    checks = [("max_wall_s", b.max_wall_s, round(m.latency, 3)),
              ("max_tokens", b.max_tokens, m.tokens),
              ("max_cost_usd", b.max_cost_usd, round(m.cost, 6))]
    if before_call:
        checks.insert(1, ("max_iterations", b.max_iterations, m.llm_calls))
    for name, limit, observed in checks:
        if observed >= limit:
            return {"budget": name, "limit": limit, "observed": observed}
    return None


def _handoff(ticket_id: str) -> dict:
    return {"ticket_id": ticket_id, "decision": None, "refund_order_id": None,
            "refund_amount_usd": None, "escalate": True,
            "reply": (f"Hi, thanks for raising ticket {ticket_id}.\n\nI've "
                      "passed your ticket to a colleague in the billing team, "
                      "who will pick it up from here.\n\n[ESCALATED]\n\n"
                      "Best regards,\nBilling Support")}


def run(ticket_id: str, seed: int, config: Config | None = None,
        budgets: Budgets | None = None) -> dict:
    cfg, b, m = config or Config(), budgets or Budgets(), Meter()
    schemas = tools8.TOOLS + cfg.extra_schemas
    state = {"ticket": None, "orders": {}, "extra_tools": cfg.extra_tools,
             "side_effects": [], "message_override": cfg.ticket_message}
    messages = [{"role": "user", "content": f"Resolve support ticket {ticket_id}."}]
    output = terminated = None

    while True:
        terminated = _breached(m, b, before_call=True)
        if terminated:
            break
        resp = sim_model.complete(M7.SYSTEM_AGENT, messages, schemas, seed)
        u = resp["usage"]
        c = M7.cost_usd(u["input_tokens"], u["output_tokens"])
        m.llm_calls += 1
        m.tokens_in += u["input_tokens"]
        m.tokens_out += u["output_tokens"]
        m.cost += c
        m.latency += resp["latency_s"]
        m.steps.append({"kind": "llm", "stop_reason": resp["stop_reason"],
                        "input_tokens": u["input_tokens"],
                        "output_tokens": u["output_tokens"], "cost_usd": c})
        messages.append({"role": "assistant", "content": resp["content"]})
        if resp["stop_reason"] != "tool_use":
            output = json.loads(resp["content"][0]["text"])
            break
        terminated = _breached(m, b, before_call=False)
        if terminated:
            break
        results = []
        for block in resp["content"]:
            if block["type"] != "tool_use":
                continue
            t0 = time.perf_counter()
            r = tools8.call(block["name"], block["input"], state,
                            cfg.validate_policy_args)
            if cfg.sanitize:
                r = cfg.sanitize(block["name"], r)
            m.overhead_s += time.perf_counter() - t0
            m.latency += tools8.TOOL_LATENCY_S
            m.steps.append({"kind": "tool", "name": block["name"],
                            "args": block["input"], "result": r})
            results.append({"type": "tool_result", "tool_use_id": block["id"],
                            "content": json.dumps(r)})
        messages.append({"role": "user", "content": results})

    if terminated:
        output = _handoff(ticket_id)
    guarded = None
    if cfg.guardrail:
        t0 = time.perf_counter()
        output, guarded = cfg.guardrail(output, state, m.steps)
        m.overhead_s += time.perf_counter() - t0

    tool_steps = [s for s in m.steps if s["kind"] == "tool"]
    return {"ticket_id": ticket_id, "seed": seed, "output": output,
            "terminated": terminated, "guardrail": guarded,
            "budgets": asdict(b), "llm_calls": m.llm_calls,
            "total_tokens": m.tokens, "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out, "cost_usd": m.cost,
            "latency_s": m.latency, "overhead_s": m.overhead_s, "tool_calls": tool_steps,
            "path": [s["name"] for s in tool_steps],
            "side_effects": state["side_effects"]}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("ticket")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mitigate", action="store_true")
    a = ap.parse_args()
    r = run(a.ticket, a.seed, Config(validate_policy_args=a.mitigate))
    for i, s in enumerate(r["tool_calls"], 1):
        res = s["result"]
        brief = res.get("error") or res.get("decision") or res.get("status") \
            or ("found" if res.get("found") else json.dumps(res)[:60])
        print(f"  {i}. {s['name']}({json.dumps(s['args'])}) -> {brief}")
    print(f"decision={r['output']['decision']} refund={r['output']['refund_order_id']}"
          f" {r['total_tokens']} tok ${r['cost_usd']:.4f} {r['latency_s']:.2f}s")


if __name__ == "__main__":
    main()
