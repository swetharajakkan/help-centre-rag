"""Run one ticket under a budget tight enough to fire, and save the log.

    .venv/bin/python week7/budget_demo.py
    .venv/bin/python week7/budget_demo.py TCK-7001 --budget max_iterations --limit 2

Default: TCK-7009 (the longest path, 5 model calls) with max_tokens=2500,
which it needs ~3,800 to finish. The other three budgets stay at their
defaults, so the log shows exactly one budget firing.

Writes week7/budget_termination.log: a header naming the ticket, the budget
that fired and its configured limit, then the run's JSON-lines event log,
ending in `terminated_cleanly`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from agent import Budgets, run_agent, tracing  # noqa: E402

LOG = os.path.join(HERE, "budget_termination.log")
KINDS = {"max_iterations": int, "max_tokens": int,
         "max_cost_usd": float, "max_wall_s": float}


def run_demo(ticket_id: str, budget: str, limit: float,
             write: bool = True) -> dict:
    b = Budgets()
    setattr(b, budget, KINDS[budget](limit))
    r = run_agent(ticket_id, b)
    t = r["terminated"]
    lines = [
        "# week7 budget termination log",
        f"# ticket:          {ticket_id}",
        f"# budgets:         {json.dumps(asdict(b))}",
        (f"# budget reached:  {t['budget']}  (configured limit {t['limit']}, "
         f"observed {t['observed']})") if t else
        "# budget reached:  none -- the run finished inside every budget",
        f"# outcome:         {'terminated cleanly, handed to a human' if t else r['output']['decision']}",
        f"# model calls:     {r['llm_calls']}   tokens: {r['total_tokens']}   "
        f"cost: ${r['cost_usd']:.5f}   wall: {r['latency_s']:.2f}s",
        f"# langfuse trace:  {r['trace_url'] or 'tracing off'}",
        "",
        *(json.dumps(e) for e in r["log"]),
    ]
    text = "\n".join(lines) + "\n"
    if write:
        with open(LOG, "w") as fh:
            fh.write(text)
    return {**r, "log_text": text}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticket", nargs="?", default="TCK-7009")
    ap.add_argument("--budget", default="max_tokens", choices=list(KINDS))
    ap.add_argument("--limit", type=float, default=2500)
    a = ap.parse_args()
    r = run_demo(a.ticket, a.budget, a.limit)
    tracing.flush()
    print(r["log_text"])
    print(f"wrote {LOG}")


if __name__ == "__main__":
    main()
