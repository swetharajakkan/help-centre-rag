"""Week 8 trajectory eval: score the path, not just the answer.

    .venv/bin/python week8/trajectory_eval.py            # before + after
    .venv/bin/python week8/trajectory_eval.py --seeds 20 # more samples

For each of the 10 tickets x N seeds (default 10 -> 100 runs per condition)
the agent runs twice, with the same seeds: BEFORE (Week-7 tools as they are)
and AFTER (the one mitigation: argument validation on lookup_refund_policy).

Two evals over every run:
  outcome     Week 7's grader, imported: output contract == answer key AND
              the four Week-6 SP-001 reply assertions pass.
  trajectory  the tool-call sequence (name + the argument that identifies
              WHAT it was called on) is one of the accepted sequences in
              EXPECTED_PATHS below, every argument is valid, and the run was
              not cut off by a budget.

Writes week8/trajectory_results.json and week8/trajectory_report.md. Every
number in the report is printed from the same structures, never retyped.
"""
from __future__ import annotations

import inspect
import json
import os
import statistics
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WEEK7 = os.path.join(ROOT, "week7")
for p in (HERE, WEEK7, os.path.join(ROOT, "week6")):
    if p not in sys.path:
        sys.path.insert(0, p)

import agent8  # noqa: E402
import sim_model  # noqa: E402
import tools8  # noqa: E402
from race import grade as outcome_grade  # noqa: E402  (week7 grader)
from store8 import TICKETS, TICKET_IDS  # noqa: E402

# ---------------------------------------------------------------------------
# 1. The 10 expected tool sequences.
#
# A step is (tool, what it was called on). For lookup_refund_policy "what it
# was called on" is the order whose fetched record the facts came from --
# "NO_ORDER" when the ticket names none, "UNGROUNDED" when the facts match no
# record fetched in this run (typed from the customer's email, or invented).
#
# Cases with MORE THAN ONE valid path list every accepted sequence and are
# asserted as a set (ALTERNATE_PATH_CASES says why). Everything else has
# exactly one.
# ---------------------------------------------------------------------------

def T(t): return ("get_ticket", t)
def O(o): return ("get_order", o)
def S(o): return ("search_tickets", o)
def P(o): return ("lookup_refund_policy", o)


def _one(tid, oid):
    return [[T(tid), O(oid), P(oid)]]


def _search_optional(tid, oid):
    return [[T(tid), O(oid), P(oid)],
            [T(tid), S(oid), O(oid), P(oid)],
            [T(tid), O(oid), S(oid), P(oid)]]


EXPECTED_PATHS: dict[str, list[list[tuple[str, str]]]] = {
    "TCK-7001": _one("TCK-7001", "ORD-5101"),
    "TCK-7002": _one("TCK-7002", "ORD-5102"),
    "TCK-7003": _one("TCK-7003", "ORD-5103"),
    "TCK-7004": _search_optional("TCK-7004", "ORD-5199"),
    "TCK-7005": _search_optional("TCK-7005", "ORD-5105"),
    "TCK-7006": _one("TCK-7006", "ORD-5106"),
    "TCK-7007": _one("TCK-7007", "ORD-5107"),
    "TCK-7008": _one("TCK-7008", "ORD-5108"),
    "TCK-7009": [[T("TCK-7009"), O("ORD-5109"), O("ORD-5110"), P("ORD-5110")],
                 [T("TCK-7009"), O("ORD-5110"), O("ORD-5109"), P("ORD-5110")]],
    "TCK-7010": [[T("TCK-7010"), P("NO_ORDER")]],
}

ALTERNATE_PATH_CASES = {
    "TCK-7004": "customer says 'I asked last week': searching prior tickets is "
                "optional, and before or after pulling the order are both "
                "correct (3 accepted sequences)",
    "TCK-7005": "customer says 'I asked about this before': same as TCK-7004 "
                "(3 accepted sequences)",
    "TCK-7009": "two orders must both be fetched before deciding; which one "
                "is fetched first does not matter (2 accepted sequences)",
}

MODES = {
    "skipped_order_record": "a policy decision was made on facts that match "
                            "no order record fetched in this run",
    "invented_id": "a tool was called on an order id the ticket never named",
    "premature_decision": "policy asked before every order the ticket names "
                          "was fetched",
    "redundant_loop": "the identical call re-issued right after it succeeded",
    "error_retry_loop": "the identical call re-issued right after it failed",
    "budget_exhausted": "a Week-7 budget cut the run off (handed to a human)",
    "unneeded_tool": "search_tickets on a ticket with no earlier contact",
}

# How bad one occurrence is. The top mode is chosen by count x weight, not by
# count alone: a redundant call costs tokens and is already capped by the
# Week-7 step budget; a decision made on unread or invented facts can send
# money to the wrong place and still pass the outcome eval.
SEVERITY = {
    "skipped_order_record": (3, "decision on unverified facts"),
    "invented_id": (3, "decision on a fabricated id"),
    "premature_decision": (3, "decision on partial facts"),
    "budget_exhausted": (2, "no decision; human picks it up"),
    "redundant_loop": (1, "cost only"),
    "error_retry_loop": (1, "cost only"),
    "unneeded_tool": (1, "cost only"),
}


def top_mode(summary: dict) -> str:
    return max(MODES, key=lambda m: (summary["modes"][m] * SEVERITY[m][0],
                                     summary["modes"][m]))

# ---------------------------------------------------------------- scoring


def keyed_calls(run: dict) -> list[dict]:
    """Each tool call with its step key and argument validity."""
    ticket = TICKETS[run["ticket_id"]]
    named = set(ticket["order_ids"])
    fetched: dict[str, dict] = {}
    out = []
    for c in run["tool_calls"]:
        name, args, res = c["name"], c["args"], c["result"]
        err = "error" in res
        if name == "get_ticket":
            on = args.get("ticket_id")
            valid = on == run["ticket_id"] and on in TICKETS
        elif name in ("get_order", "search_tickets", "issue_refund"):
            on = args.get("order_id")
            valid = on in named
        elif name == "lookup_refund_policy":
            on = next((oid for oid, r in fetched.items()
                       if tools8.record_matches(args, r)), None)
            if on is None:
                on = ("NO_ORDER" if args.get("order_status") == "not_found"
                      and args.get("amount_usd") is None
                      and args.get("days_since_purchase") is None
                      else "UNGROUNDED")
            valid = ((on in named or (on == "NO_ORDER" and not named))
                     and args.get("customer_tier") == ticket["customer_tier"]
                     and args.get("request_type") == ticket["request_type"])
        else:
            on, valid = "?", False
        if name == "get_order" and not err:
            fetched[args.get("order_id")] = res
        out.append({"key": (name, on), "valid": valid, "error": err,
                    "fetched_before": set(fetched) - ({on} if name == "get_order" else set())})
    return out


def lcs(a: list, b: list) -> int:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            dp[i + 1][j + 1] = dp[i][j] + 1 if x == y else max(dp[i][j + 1], dp[i + 1][j])
    return dp[-1][-1]


def failure_modes(run: dict, calls: list[dict]) -> list[str]:
    ticket = TICKETS[run["ticket_id"]]
    named = set(ticket["order_ids"])
    modes = set()
    for i, c in enumerate(calls):
        name, on = c["key"]
        if name == "lookup_refund_policy" and not c["error"]:
            if on == "UNGROUNDED":
                modes.add("skipped_order_record")
            elif named - c["fetched_before"]:
                modes.add("premature_decision")
        if name in ("get_order", "search_tickets", "issue_refund") and on not in named:
            modes.add("invented_id")
        if name == "search_tickets" and run["ticket_id"] not in ALTERNATE_PATH_CASES:
            modes.add("unneeded_tool")
        if i and run["tool_calls"][i]["name"] == run["tool_calls"][i - 1]["name"] \
                and run["tool_calls"][i]["args"] == run["tool_calls"][i - 1]["args"]:
            modes.add("error_retry_loop" if calls[i - 1]["error"] else "redundant_loop")
    if run["terminated"]:
        modes.add("budget_exhausted")
    return sorted(modes)


def score(run: dict) -> dict:
    tid = run["ticket_id"]
    calls = keyed_calls(run)
    keys = [c["key"] for c in calls]
    accepted = EXPECTED_PATHS[tid]
    names = [k[0] for k in keys]
    best = max(accepted, key=lambda seq: lcs(names, [s[0] for s in seq]))
    matched = lcs(names, [s[0] for s in best])
    needed = min(len(s) for s in accepted)
    traj_ok = (keys in [list(s) for s in accepted]
               and all(c["valid"] for c in calls) and not run["terminated"])
    naive_ok = (keys == list(accepted[0])
                and all(c["valid"] for c in calls) and not run["terminated"])
    og = outcome_grade(tid, run["output"])
    return {"outcome_pass": og["passed"], "outcome_mismatches": og["mismatches"],
            "trajectory_pass": traj_ok, "naive_trajectory_pass": naive_ok,
            "keys": keys, "valid_args": sum(c["valid"] for c in calls),
            "n_calls": len(calls), "tool_errors": sum(c["error"] for c in calls),
            "choice_matched": matched, "choice_denominator": max(len(names), len(best)),
            "steps_taken": len(calls), "steps_needed": needed,
            "modes": failure_modes(run, calls)}


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def evaluate(config: agent8.Config, seeds: int) -> dict:
    runs = []
    for tid in TICKET_IDS:
        for seed in range(seeds):
            r = agent8.run(tid, seed, config)
            r["score"] = score(r)
            runs.append(r)
    return {"runs": runs, "summary": summarise(runs)}


def summarise(runs: list[dict]) -> dict:
    sc = [r["score"] for r in runs]
    n = len(runs)
    cost = [r["cost_usd"] for r in runs]
    tok = [r["total_tokens"] for r in runs]
    lat = [r["latency_s"] for r in runs]
    eff = [s["steps_taken"] / s["steps_needed"] for s in sc]
    outcome = sum(s["outcome_pass"] for s in sc) / n
    traj = sum(s["trajectory_pass"] for s in sc) / n
    naive = sum(s["naive_trajectory_pass"] for s in sc) / n
    modes = Counter(m for s in sc for m in s["modes"])
    return {
        "runs": n,
        "outcome_pass_rate": outcome,
        "trajectory_pass_rate": traj,
        "gap": outcome - traj,
        "naive_trajectory_pass_rate": naive,
        "naive_gap": outcome - naive,
        "right_answer_wrong_path": sum(s["outcome_pass"] and not s["trajectory_pass"]
                                       for s in sc),
        "tool_choice_accuracy": sum(s["choice_matched"] for s in sc)
                                / sum(s["choice_denominator"] for s in sc),
        "argument_validity": sum(s["valid_args"] for s in sc)
                             / sum(s["n_calls"] for s in sc),
        "step_efficiency": sum(s["steps_taken"] for s in sc)
                           / sum(s["steps_needed"] for s in sc),
        "step_efficiency_p50": statistics.median(eff),
        "step_efficiency_max": max(eff),
        "tool_errors": sum(s["tool_errors"] for s in sc),
        "cost_p50": statistics.median(cost), "cost_max": max(cost),
        "cost_mean": statistics.mean(cost),
        "tokens_p50": statistics.median(tok), "tokens_max": max(tok),
        "tokens_mean": statistics.mean(tok),
        "latency_p50": statistics.median(lat), "latency_max": max(lat),
        "latency_mean": statistics.mean(lat),
        "modes": {m: modes.get(m, 0) for m in MODES},
        "per_ticket": {
            tid: {"outcome": sum(r["score"]["outcome_pass"] for r in runs if r["ticket_id"] == tid),
                  "trajectory": sum(r["score"]["trajectory_pass"] for r in runs if r["ticket_id"] == tid),
                  "n": sum(r["ticket_id"] == tid for r in runs)}
            for tid in TICKET_IDS},
    }


# ---------------------------------------------------------------- report

def fmt_path(run: dict) -> str:
    lines = []
    for i, c in enumerate(run["tool_calls"], 1):
        res = c["result"]
        brief = (res.get("error", "")[:70] + "...") if "error" in res else \
            res.get("decision") or res.get("status") or \
            ("found" if res.get("found") else f"{len(res.get('tickets', []))} prior tickets")
        lines.append(f"  {i}. {c['name']}({json.dumps(c['args'])})\n       -> {brief}")
    return "\n".join(lines)


def pick_example(runs: list[dict]) -> dict | None:
    """A ticket that passes the outcome eval and fails the trajectory eval,
    preferring the brief's exact bug: right refund, order never opened."""
    hits = [r for r in runs if r["score"]["outcome_pass"]
            and not r["score"]["trajectory_pass"]]
    hits.sort(key=lambda r: ("skipped_order_record" not in r["score"]["modes"],
                             r["output"].get("decision") != "refund_approved",
                             r["ticket_id"], r["seed"]))
    return hits[0] if hits else None


def regression_rows(b: dict, a: dict, top: str) -> list[dict]:
    rows = []
    for m in MODES:
        x, y = b["modes"][m], a["modes"][m]
        if m == top:
            v = "TARGET: reduced" if y < x else "TARGET: not reduced"
        elif x == 0 and y > 0:
            v = "NEW: created by the mitigation"
        elif y > x:
            v = "WORSE"
        elif y < x:
            v = "better (side effect)"
        else:
            v = "unchanged"
        rows.append({"mode": m, "before": x, "after": y, "delta": y - x,
                     "verdict": v})
    return rows


def report(before: dict, after: dict, seeds: int) -> str:
    b, a = before["summary"], after["summary"]
    top = top_mode(b)
    by_count = max(MODES, key=lambda m: b["modes"][m])
    ex = pick_example(before["runs"])
    reg = regression_rows(b, a, top)
    L = []
    L.append("# Week 8 — trajectory eval results (generated)\n")
    L.append(f"Generated by `week8/trajectory_eval.py` at "
             f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}. "
             f"{len(TICKET_IDS)} tickets x {seeds} seeds = {b['runs']} runs per "
             f"condition; BEFORE and AFTER use the same seeds.\n")

    L.append("## 1. Expected tool sequences\n")
    L.append("| Ticket | Accepted sequence(s) | Alternate paths? |\n|---|---|---|")
    for tid in TICKET_IDS:
        seqs = "<br>".join(" → ".join(f"{t}({o})" for t, o in s)
                           for s in EXPECTED_PATHS[tid])
        L.append(f"| {tid} | {seqs} | {ALTERNATE_PATH_CASES.get(tid, 'no — one path')} |")

    L.append("\n## 2. Trajectory numbers\n")
    L.append("| Metric | BEFORE | AFTER |\n|---|---:|---:|")
    rows = [("Outcome pass rate", pct(b["outcome_pass_rate"]), pct(a["outcome_pass_rate"])),
            ("Trajectory pass rate (set-asserted)", pct(b["trajectory_pass_rate"]), pct(a["trajectory_pass_rate"])),
            ("**Gap (outcome − trajectory)**", f"**{b['gap']*100:+.1f} pts**", f"**{a['gap']*100:+.1f} pts**"),
            ("Right answer, wrong path (runs)", b["right_answer_wrong_path"], a["right_answer_wrong_path"]),
            ("Tool-choice accuracy", pct(b["tool_choice_accuracy"]), pct(a["tool_choice_accuracy"])),
            ("Argument validity rate", pct(b["argument_validity"]), pct(a["argument_validity"])),
            ("Step efficiency (taken / needed), all runs", f"{b['step_efficiency']:.3f}", f"{a['step_efficiency']:.3f}"),
            ("Step efficiency p50 / max (per run)", f"{b['step_efficiency_p50']:.2f} / {b['step_efficiency_max']:.2f}",
             f"{a['step_efficiency_p50']:.2f} / {a['step_efficiency_max']:.2f}"),
            ("Cost per ticket p50", f"${b['cost_p50']:.4f}", f"${a['cost_p50']:.4f}"),
            ("Cost per ticket **max**", f"${b['cost_max']:.4f}", f"${a['cost_max']:.4f}"),
            ("Cost per ticket mean (for reference only)", f"${b['cost_mean']:.4f}", f"${a['cost_mean']:.4f}"),
            ("Tokens per ticket p50 / max", f"{b['tokens_p50']:.0f} / {b['tokens_max']}", f"{a['tokens_p50']:.0f} / {a['tokens_max']}"),
            ("Latency per ticket p50 / max (simulated)", f"{b['latency_p50']:.2f}s / {b['latency_max']:.2f}s",
             f"{a['latency_p50']:.2f}s / {a['latency_max']:.2f}s"),
            ("Tool calls rejected with an error", b["tool_errors"], a["tool_errors"])]
    for r in rows:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} |")
    L.append(f"\nOver-assertion check: asserting ONE exact sequence per ticket "
             f"(the first listed) would give a trajectory pass rate of "
             f"{pct(b['naive_trajectory_pass_rate'])} and a gap of "
             f"{b['naive_gap']*100:+.1f} pts BEFORE — "
             f"{(b['naive_gap']-b['gap'])*100:.1f} pts of the gap would be correct "
             f"alternate paths scored as failures.\n")

    L.append("### Per ticket (passes out of runs)\n")
    L.append("| Ticket | Outcome BEFORE | Trajectory BEFORE | Outcome AFTER | Trajectory AFTER |\n|---|---:|---:|---:|---:|")
    for tid in TICKET_IDS:
        pb, pa = b["per_ticket"][tid], a["per_ticket"][tid]
        L.append(f"| {tid} | {pb['outcome']}/{pb['n']} | {pb['trajectory']}/{pb['n']} "
                 f"| {pa['outcome']}/{pa['n']} | {pa['trajectory']}/{pa['n']} |")

    L.append("\n## 3. Right answer, wrong path\n")
    if ex:
        exp = " → ".join(f"{t}({o})" for t, o in EXPECTED_PATHS[ex["ticket_id"]][0])
        L.append(f"**{ex['ticket_id']}, seed {ex['seed']}** — outcome PASS "
                 f"(decision `{ex['output']['decision']}`, refund "
                 f"`{ex['output']['refund_order_id']}` USD "
                 f"{ex['output']['refund_amount_usd']}), trajectory FAIL "
                 f"(modes: {', '.join(ex['score']['modes'])}).\n")
        L.append(f"Expected: `{exp}`\n\nTaken:\n```text\n{fmt_path(ex)}\n```\n")
        L.append("Reply it sent:\n```text\n" + ex["output"]["reply"] + "\n```\n")

    L.append(f"## 4. Mitigation — top mode `{top}`\n")
    L.append("Ranking the BEFORE modes (top = count x severity weight):\n")
    L.append("| Mode | Runs | Severity | Weight | Score |\n|---|---:|---|---:|---:|")
    for m in sorted(MODES, key=lambda m: -b["modes"][m] * SEVERITY[m][0]):
        w, why = SEVERITY[m]
        L.append(f"| `{m}` | {b['modes'][m]} | {why} | {w} | {b['modes'][m] * w} |")
    if by_count != top:
        L.append(f"\nBy raw count alone the top mode would be `{by_count}` "
                 f"({b['modes'][by_count]} runs vs {b['modes'][top]}). It is "
                 f"not chosen: it changes no decision, and its cost tail is "
                 f"already capped by the Week-7 step budget.\n")
    touched = [i for i, r in enumerate(after["runs"]) if r["score"]["tool_errors"]]
    if touched:
        dc = statistics.mean(after["runs"][i]["cost_usd"] - before["runs"][i]["cost_usd"] for i in touched)
        dt = statistics.mean(after["runs"][i]["total_tokens"] - before["runs"][i]["total_tokens"] for i in touched)
        dl = statistics.mean(after["runs"][i]["latency_s"] - before["runs"][i]["latency_s"] for i in touched)
        fixed = sum(after["runs"][i]["score"]["outcome_pass"] and not before["runs"][i]["score"]["outcome_pass"]
                    for i in touched)
        L.append(f"\nThe validator fired on {len(touched)} of {a['runs']} runs. On "
                 f"those runs the price was +${dc:.4f}, +{dt:.0f} tokens and "
                 f"+{dl:.3f}s per ticket (same seed, before vs after); "
                 f"{fixed} of them went from a WRONG outcome to a right one.\n")
    L.append(f"Exactly one change: `Config(validate_policy_args=True)`, which "
             f"switches on this function in `week8/tools8.py`:\n")
    L.append("```python\n" + inspect.getsource(tools8.validate_policy_args) + "```\n")
    L.append("| | BEFORE | AFTER | Price |\n|---|---:|---:|---:|")
    L.append(f"| `{top}` runs | {b['modes'][top]} | {a['modes'][top]} | |")
    for label, k, f in (("Cost / ticket p50", "cost_p50", "${:.4f}"),
                        ("Cost / ticket max", "cost_max", "${:.4f}"),
                        ("Cost / ticket mean", "cost_mean", "${:.4f}"),
                        ("Tokens / ticket mean", "tokens_mean", "{:.0f}"),
                        ("Latency / ticket p50", "latency_p50", "{:.3f}s"),
                        ("Latency / ticket max", "latency_max", "{:.3f}s")):
        d = a[k] - b[k]
        L.append(f"| {label} | {f.format(b[k])} | {f.format(a[k])} | "
                 f"{'+' if d >= 0 else '−'}{f.format(abs(d))} ({d / b[k] * 100:+.1f}%) |")
    total_b = sum(r["cost_usd"] for r in before["runs"])
    total_a = sum(r["cost_usd"] for r in after["runs"])
    L.append(f"\nTotal over {b['runs']} runs: ${total_b:.4f} → ${total_a:.4f} "
             f"(+${total_a - total_b:.4f}).\n")

    L.append("## 5. Regression check — every mode in the taxonomy\n")
    L.append("| Mode | Definition | BEFORE | AFTER | Δ | Verdict |\n|---|---|---:|---:|---:|---|")
    for r in reg:
        L.append(f"| `{r['mode']}` | {MODES[r['mode']]} | {r['before']} | "
                 f"{r['after']} | {r['delta']:+d} | {r['verdict']} |")
    worse = [r["mode"] for r in reg if r["verdict"].startswith(("NEW", "WORSE"))]
    L.append("\nModes that got worse or appeared: "
             + (", ".join(f"`{m}`" for m in worse) if worse else
                "none. Modes checked: " + ", ".join(f"`{m}`" for m in MODES)) + ".\n")
    L.append("## Engine rates (the dial, not a measurement)\n")
    L.append("| Rate | Value |\n|---|---:|")
    for k, v in sim_model.RATES.items():
        L.append(f"| `{k}` | {v} |")
    return "\n".join(L) + "\n"


def strip(run: dict) -> dict:
    r = dict(run)
    r["score"] = {**r["score"], "keys": [list(k) for k in r["score"]["keys"]]}
    return r


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    a = ap.parse_args()
    before = evaluate(agent8.Config(validate_policy_args=False), a.seeds)
    after = evaluate(agent8.Config(validate_policy_args=True), a.seeds)
    text = report(before, after, a.seeds)
    with open(os.path.join(HERE, "trajectory_report.md"), "w") as fh:
        fh.write(text)
    json.dump({"seeds": a.seeds, "rates": sim_model.RATES,
               "expected_paths": {k: [[list(s) for s in seq] for seq in v]
                                  for k, v in EXPECTED_PATHS.items()},
               "alternate_path_cases": ALTERNATE_PATH_CASES, "modes": MODES,
               "before": {"summary": before["summary"],
                          "runs": [strip(r) for r in before["runs"]]},
               "after": {"summary": after["summary"],
                         "runs": [strip(r) for r in after["runs"]]}},
              open(os.path.join(HERE, "trajectory_results.json"), "w"),
              indent=1, default=str)
    print(text)


if __name__ == "__main__":
    main()
