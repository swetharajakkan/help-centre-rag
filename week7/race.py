"""Race the agent against the fixed workflow over the same 10 tickets.

    .venv/bin/python week7/race.py

Writes, all under week7/:
  race.csv        one row per (system, ticket) + the 8 headline numbers
  race.json       everything the UI shows: per-ticket steps, paths, the
                  path-variance analysis and the verdict

Grading
-------
A run PASSES when the output contract matches the answer key in store.py on
all four fields (decision, refund_order_id, refund_amount_usd, escalate) AND
the reply passes the four Week-6 SP-001 assertions (week6/assertions.py,
imported, not copied). Same grader for both systems.

The verdict paragraph is generated from the measured results rather than
typed, so it cannot drift from the table: every number in it is read from
the same summary the table prints.
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "week6"))

import assertions as A  # noqa: E402  (week6)
from agent import Budgets, run_agent, tracing  # noqa: E402
import model  # noqa: E402
from store import BRANCH_NOTE, EXPECTED, ORDERS, TICKETS, TICKET_IDS  # noqa: E402
from workflow import run_workflow  # noqa: E402

FIELDS = ["decision", "refund_order_id", "refund_amount_usd", "escalate"]


def grade(ticket_id: str, output: dict) -> dict:
    exp = EXPECTED[ticket_id]
    mismatches = [{"field": f, "expected": exp[f], "got": output.get(f)}
                  for f in FIELDS if output.get(f) != exp[f]]
    # Week-6 assertions read a ticket record with Week-6 field names.
    order = ORDERS.get(exp["refund_order_id"] or "") or next(
        (ORDERS[o] for o in TICKETS[ticket_id]["order_ids"] if o in ORDERS), {})
    w6_ticket = {"ticket_id": ticket_id,
                 "tier": TICKETS[ticket_id]["customer_tier"].capitalize(),
                 "days_since_purchase": order.get("days_since_purchase", 0)}
    checks = A.run(output.get("reply", ""), w6_ticket)
    return {"passed": not mismatches and checks["passed"],
            "mismatches": mismatches, "assertions": checks["checks"],
            "assertions_failed": checks["failed"]}


def summarise(runs: list[dict]) -> dict:
    lat = [r["latency_s"] for r in runs]
    return {"n": len(runs),
            "passed": sum(r["grade"]["passed"] for r in runs),
            "pass_rate": sum(r["grade"]["passed"] for r in runs) / len(runs),
            "p50_latency_s": statistics.median(lat),
            "total_tokens": sum(r["total_tokens"] for r in runs),
            "cost_per_ticket_usd": sum(r["cost_usd"] for r in runs) / len(runs),
            "llm_calls": sum(r["llm_calls"] for r in runs),
            "tool_calls": sum(len(r["path"]) for r in runs)}


def path_analysis(agent: dict, workflow: dict) -> list[dict]:
    rows = []
    for tid in TICKET_IDS:
        a, w = agent[tid], workflow[tid]
        rows.append({
            "ticket_id": tid, "cls": EXPECTED[tid]["cls"],
            "branch_note": BRANCH_NOTE.get(tid, ""),
            "agent_path": a["path"], "workflow_path": w["path"],
            "path_differs": a["path"] != w["path"],
            "agent_decision": a["output"]["decision"],
            "workflow_decision": w["output"]["decision"],
            "outcome_differs": any(a["output"].get(f) != w["output"].get(f)
                                   for f in FIELDS),
            "agent_passed": a["grade"]["passed"],
            "workflow_passed": w["grade"]["passed"],
        })
    return rows


def verdict(sa: dict, sw: dict, paths: list[dict]) -> str:
    # The workflow's path never changes, so "the path varied" means the tools
    # the agent chose differ from the workflow's fixed sequence.
    varied = [p for p in paths if p["path_differs"]]
    broke = [p for p in paths if p["agent_passed"] and not p["workflow_passed"]]
    absorbed = [p for p in paths if p["cls"] == "branch" and not p["path_differs"]]
    tok_x = sa["total_tokens"] / max(1, sw["total_tokens"])
    cost_x = sa["cost_per_ticket_usd"] / max(1e-9, sw["cost_per_ticket_usd"])

    s = [f"Decision rule: does the execution path vary with the input? "
         f"Measured on 10 tickets, the agent's path varied on "
         f"{len(varied)} ({', '.join(p['ticket_id'] for p in varied) or 'none'})."]
    harmless = [p for p in varied if not p["outcome_differs"]]
    if harmless:
        s.append(f"On {', '.join(p['ticket_id'] for p in harmless)} the path "
                 "changed but the output did not.")
    if absorbed:
        s.append(f"The {len(absorbed)} branch tickets "
                 f"({', '.join(p['ticket_id'] for p in absorbed)}) did not need "
                 "it: the enum policy tool turns a missing, refunded, "
                 "charged-back or over-limit order into a decision, so the fixed path "
                 "handled them.")
    if broke:
        names = ", ".join(p["ticket_id"] for p in broke)
        s.append(f"The class that forces a variable path is the multi-order "
                 f"(duplicate-charge) ticket: the workflow fetched one order "
                 f"and refunded the wrong one ({names}).")
    else:
        s.append("No ticket class failed on the fixed path, so none of the "
                 "10 forces an agent.")
    s.append(f"Workflow: {sw['passed']}/10 pass, p50 "
             f"{sw['p50_latency_s']:.2f}s, {sw['total_tokens']:,} tokens, "
             f"${sw['cost_per_ticket_usd']:.4f}/ticket. Agent: "
             f"{sa['passed']}/10, p50 {sa['p50_latency_s']:.2f}s, "
             f"{sa['total_tokens']:,} tokens ({tok_x:.1f}x), "
             f"${sa['cost_per_ticket_usd']:.4f}/ticket ({cost_x:.1f}x).")
    if broke:
        s.append("Verdict: the fixed workflow is sufficient for single-order "
                 "tickets; only multi-order tickets justify the agent's cost.")
    else:
        s.append("Verdict: the fixed workflow is sufficient for every tested "
                 "case.")
    return " ".join(s)


def main() -> None:
    # Construct and auth-check the tracing client before the clock starts, so
    # its one-off startup is not billed to whichever ticket happens to run
    # first.
    tracing.status()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    agent, workflow = {}, {}
    for tid in TICKET_IDS:
        for system, fn, bucket in (("agent", run_agent, agent),
                                   ("workflow", run_workflow, workflow)):
            r = fn(tid)
            r["grade"] = grade(tid, r["output"])
            bucket[tid] = r
            print(f"{system:8} {tid}  {'PASS' if r['grade']['passed'] else 'FAIL'}"
                  f"  {' -> '.join(r['path']):55} {r['total_tokens']:6} tok"
                  f"  ${r['cost_usd']:.4f}  {r['latency_s']:.2f}s")
    tracing.flush()

    sa, sw = summarise(list(agent.values())), summarise(list(workflow.values()))
    paths = path_analysis(agent, workflow)
    text = verdict(sa, sw, paths)

    with open(os.path.join(HERE, "race.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["system", "ticket_id", "class", "passed", "latency_s",
                    "total_tokens", "cost_usd", "llm_calls", "path"])
        for system, bucket in (("agent", agent), ("workflow", workflow)):
            for tid in TICKET_IDS:
                r = bucket[tid]
                w.writerow([system, tid, EXPECTED[tid]["cls"],
                            int(r["grade"]["passed"]), f"{r['latency_s']:.3f}",
                            r["total_tokens"], f"{r['cost_usd']:.6f}",
                            r["llm_calls"], ">".join(r["path"])])
        w.writerow([])
        w.writerow(["system", "pass_rate", "p50_latency_s", "total_tokens",
                    "cost_per_ticket_usd"])
        for system, s in (("agent", sa), ("workflow", sw)):
            w.writerow([system, f"{s['pass_rate']:.2f}",
                        f"{s['p50_latency_s']:.3f}", s["total_tokens"],
                        f"{s['cost_per_ticket_usd']:.6f}"])

    out = {"ran_at": started, "ticket_ids": TICKET_IDS,
           "engine": {"model": model.MODEL, "priced_as": model.PRICED_AS,
                      "price_in_per_mtok": model.PRICE_IN_PER_MTOK,
                      "price_out_per_mtok": model.PRICE_OUT_PER_MTOK,
                      "tokens": "estimated, ceil(chars/4) of the exact payload",
                      "latency": "measured wall-clock; model calls sleep a "
                                 "simulated latency, tools a fixed round trip"},
           "budgets": vars(Budgets()),
           "summary": {"agent": sa, "workflow": sw},
           "runs": {"agent": agent, "workflow": workflow},
           "expected": EXPECTED, "tickets": TICKETS,
           "paths": paths, "verdict": text,
           "verdict_words": len(text.split())}
    json.dump(out, open(os.path.join(HERE, "race.json"), "w"), indent=1,
              default=str)

    print(f"\n{'':10}{'pass rate':>10}{'p50 lat':>10}{'tokens':>10}{'$/ticket':>11}")
    for name, s in (("agent", sa), ("workflow", sw)):
        print(f"{name:10}{s['pass_rate']*100:9.0f}%{s['p50_latency_s']:9.2f}s"
              f"{s['total_tokens']:10}{s['cost_per_ticket_usd']:11.4f}")
    print(f"\nVERDICT ({len(text.split())} words)\n{text}")


if __name__ == "__main__":
    main()
