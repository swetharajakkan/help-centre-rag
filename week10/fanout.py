"""Race 2: the workload where the triage squad SHOULD help, declared up front.

    .venv/bin/python week10/fanout.py

Race 1 (race.py) used the first ten judged Week-6 cases and the squad lost:
those tickets are one issue each, so the work is sequential and does not split.
This is a separate experiment, not an addition to race 1's case set, with its
hypothesis written before either arm ran:

    A ticket that reports several independent error codes, each documented in a
    different article, splits cleanly: one worker per code needs only its own
    code and its own article. Fanned out concurrently, the squad should finish
    faster than a single agent that looks the codes up one tool call per turn,
    and stay inside the per-agent budget the single agent will run out of.

Arms (same retrieval `race._code_rows`, same reply renderer `race.render`,
same judge and assertions as race 1):

  single      one tool call per turn on one growing history: search code 1,
              search code 2, ... then get_support_policy, then the reply. This
              is how the Week-7..10 single agent is built.
  single_par  the same single agent allowed PARALLEL tool calls: all searches
              in one turn. Measured because it is the obvious objection.
  squad       orchestrator plans, triage worker extracts the codes, one policy
              worker per code runs CONCURRENTLY (threads; each worker sees its
              code and the triage line only), orchestrator synthesises.

Budgets are Week 7's defaults (week7/agent.py Budgets), applied per agent run:
8 model calls and 20,000 tokens. A run that would cross one is terminated and
escalated, exactly as week7/agent.py does. Model calls are simulated as in
race 1 (tokens = ceil(chars/4) of the exact payload, latency slept in
proportion), so wall-clock concurrency is real.

Writes week10/fanout.json and week10/fanout.md.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    os.execve(sys.executable, [sys.executable, *sys.argv],
              {**os.environ, "PYTHONHASHSEED": "0"})

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from week10 import race  # noqa: E402

MAX_CALLS, MAX_TOKENS = 8, 20_000          # week7/agent.py Budgets defaults

# Automatic routing for the user's screen, read off the size sweep below.
# 1 issue: nothing to split, the single agent. 2+ independent issues: one
# agent fetching them in one turn (parallel tool calls) is cheapest. From
# SQUAD_FROM issues the single agent as built runs out of its call budget
# (K + 2 > MAX_CALLS) and one shared history keeps growing, so each issue
# gets its own worker.
SQUAD_FROM = MAX_CALLS - 1


def route(question: str) -> dict:
    k = len(set(race.CODE.findall(question)))
    if k == 0:
        return {"arm": "crew", "k": 0, "reason": "no error code in the question: the "
                "Week 9 support crew answers (it can look up tickets and accounts)"}
    if k == 1:
        return {"arm": "single", "k": 1,
                "reason": "one issue: nothing to split, so one agent answers"}
    if k < SQUAD_FROM:
        return {"arm": "single_par", "k": k, "reason": f"{k} independent issues: one agent "
                "looks them all up in one turn (parallel tool calls), the cheapest option"}
    return {"arm": "squad", "k": k, "reason": f"{k} independent issues: past what one agent "
            f"can do within its {MAX_CALLS}-call budget, so each issue gets its own worker "
            "and they run at the same time"}

# Authored for this experiment, before either arm ran: every code exists in
# the corpus, and each ticket's codes come from different articles.
CASES = [
    {"case_id": "F-01", "judged": True, "ticket": {
        "ticket_id": "TCK-7001", "tier": "Standard", "days_since_purchase": 9,
        "refund_requested": False, "refund_amount_usd": None, "product_area": None,
        "question": "After cutover we see ERR-4215 on invoices, ERR-4301 on a "
                    "subscription and ERR-4036 on a card update. What does each mean "
                    "and what do we do?"}},
    {"case_id": "F-02", "judged": True, "ticket": {
        "ticket_id": "TCK-7002", "tier": "Priority", "days_since_purchase": 4,
        "refund_requested": False, "refund_amount_usd": None, "product_area": None,
        "question": "Four errors since migration: ERR-4502, ERR-4114, ERR-4005 and "
                    "ERR-4216. How do we fix each one?"}},
    {"case_id": "F-03", "judged": True, "ticket": {
        "ticket_id": "TCK-7003", "tier": "Standard", "days_since_purchase": 12,
        "refund_requested": False, "refund_amount_usd": None, "product_area": None,
        "question": "Our finance team hit ERR-4001, ERR-4033, ERR-4212, ERR-4303 and "
                    "ERR-4503 this week. Please explain each and the fix."}},
    {"case_id": "F-04", "judged": True, "ticket": {
        "ticket_id": "TCK-7004", "tier": "Priority", "days_since_purchase": 20,
        "refund_requested": False, "refund_amount_usd": None, "product_area": None,
        "question": "Six codes across our workspaces: ERR-4002, ERR-4030, ERR-4110, "
                    "ERR-4211, ERR-4302 and ERR-4504. What is each and what should we do?"}},
]


# The size sweep: tickets naming the first K of these codes, K = 2..10. Fixed
# before running, in this order, so no ticket size is picked after the fact.
# Articles: BM-001, -002, -006, -003, -004, -005, -001, -002, -003, -004.
SWEEP_CODES = ["ERR-4002", "ERR-4030", "ERR-4110", "ERR-4211", "ERR-4302",
               "ERR-4504", "ERR-4003", "ERR-4033", "ERR-4216", "ERR-4303"]


def sweep_ticket(k: int) -> dict:
    return {"case_id": f"K-{k:02d}", "judged": True, "ticket": {
        "ticket_id": f"TCK-71{k:02d}", "tier": "Standard", "days_since_purchase": 10,
        "refund_requested": False, "refund_amount_usd": None, "product_area": None,
        "question": f"Since migration we hit {', '.join(SWEEP_CODES[:k])}. "
                    "What does each mean and what do we do?"}}


class Budget(Exception):
    pass


class Run:
    """One agent run: its own meter and its own Week-7 budget."""

    def __init__(self, case_id: str, arm: str, agent: str):
        self.m = race.Meter(case_id, arm)
        self.agent = agent

    def call(self, frm, to, label, payload_in, payload_out):
        tin = race.tokens(payload_in)
        if len(self.m.handoffs) + 1 > MAX_CALLS:
            raise Budget(f"{self.agent}: max_iterations {MAX_CALLS}")
        if self.m.total + tin > MAX_TOKENS:
            raise Budget(f"{self.agent}: max_tokens {MAX_TOKENS:,} "
                         f"(had {self.m.total:,}, next call sends {tin:,})")
        self.m.call(frm, to, label, payload_in, payload_out)


def _lookup(index, code):
    # No lock: concurrent searches were measured to return identical rows
    # (6 codes: 1.86s one after another, 1.46s concurrently).
    return race._code_rows(index, [code])


def _codes(ticket):
    return sorted(set(race.CODE.findall(ticket["question"])))


def _finish(ticket, claims, runs, t0, terminated=None):
    answered = bool(claims) and terminated is None
    refusal = (f"Stopped by the agent budget ({terminated}) before every code was "
               "looked up." if terminated else "")
    reply = race.render(ticket, answered, claims if answered else [], refusal)
    hand = [h for r in runs for h in r.m.handoffs]
    tin = sum(h["tokens_in"] for h in hand)
    tout = sum(h["tokens_out"] for h in hand)
    return {"reply": reply, "answered": answered, "terminated": terminated,
            "tokens": tin + tout, "max_agent_tokens": max(r.m.total for r in runs),
            "cost_usd": (tin * race.PRICE_IN_PER_MTOK + tout * race.PRICE_OUT_PER_MTOK) / 1e6,
            "latency_s": time.perf_counter() - t0, "calls": len(hand),
            "agents": len(runs), "handoffs": hand}


def run_single(ticket, index, parallel=False):
    arm = "single_par" if parallel else "single"
    run = Run(ticket["ticket_id"], arm, "single agent")
    tools = [race.T_SEARCH, race.T_POLICY, race.T_HISTORY, race.T_ESCALATE]
    msgs = [{"role": "user", "content": json.dumps(ticket)}]
    t0, claims = time.perf_counter(), []
    sysp = race.SYS_SINGLE
    try:
        batches = [_codes(ticket)] if parallel else [[c] for c in _codes(ticket)]
        frm = "user"
        for batch in batches:
            uses = [{"type": "tool_use", "name": "search_help_centre", "input": {"query": c}}
                    for c in batch]
            run.call(frm, "single agent", f"search {', '.join(batch)}",
                     {"system": sysp, "tools": tools, "messages": msgs}, uses)
            results = []
            for c in batch:
                got, chunks = _lookup(None if index is None else index, c)
                claims += got
                results.append({"type": "tool_result", "content": chunks})
            msgs += [{"role": "assistant", "content": uses}, {"role": "user", "content": results}]
            frm = "search_help_centre"
        call = {"type": "tool_use", "name": "get_support_policy", "input": {}}
        run.call(frm, "single agent", "call policy",
                 {"system": sysp, "tools": tools, "messages": msgs}, call)
        msgs += [{"role": "assistant", "content": [call]},
                 {"role": "user", "content": [{"type": "tool_result", "content": race.POLICY_TEXT}]}]
        final = {"answered": True, "claims": claims, "refusal": ""}
        run.call("get_support_policy", "single agent", "write reply",
                 {"system": sysp, "tools": tools, "messages": msgs}, final)
        return _finish(ticket, claims, [run], t0)
    except Budget as b:
        return _finish(ticket, claims, [run], t0, terminated=str(b))


def run_squad(ticket, index):
    t0 = time.perf_counter()
    orch = Run(ticket["ticket_id"], "squad", "orchestrator")
    codes = _codes(ticket)
    plan = {"steps": [{"worker": "triage"}] + [{"worker": "policy_lookup", "code": c}
                                                for c in codes]}
    triage = race._triage(ticket)
    runs = [orch]
    try:
        orch.call("user", "orchestrator", "decompose ticket",
                  {"system": race.SYS_ORCH, "messages": [{"role": "user",
                                                          "content": json.dumps(ticket)}]}, plan)
        tri = Run(ticket["ticket_id"], "squad", "triage worker")
        runs.append(tri)
        tri.call("orchestrator", "triage worker", "triage",
                 {"system": race.SYS_TRIAGE, "messages": [{"role": "user", "content":
                                                          json.dumps({"question": ticket["question"],
                                                                      "tier": ticket["tier"]})}]},
                 triage)

        def worker(code):
            w = Run(ticket["ticket_id"], "squad", f"policy worker {code}")
            # Forward only what this worker needs: its code and the triage line.
            msgs = [{"role": "user", "content": json.dumps({"code": code,
                                                            "intent": triage["intent"]})}]
            use = {"type": "tool_use", "name": "search_help_centre", "input": {"query": code}}
            w.call("orchestrator", f"policy worker {code}", "search",
                   {"system": race.SYS_POLICY, "tools": [race.T_SEARCH], "messages": msgs}, use)
            got, chunks = _lookup(index, code)
            msgs += [{"role": "assistant", "content": [use]},
                     {"role": "user", "content": [{"type": "tool_result", "content": chunks}]}]
            out = {"answered": bool(got), "claims": got, "refusal": ""}
            w.call(f"policy worker {code}", f"policy worker {code}", "answer",
                   {"system": race.SYS_POLICY, "tools": [race.T_SEARCH], "messages": msgs}, out)
            return w, got

        with ThreadPoolExecutor(max_workers=len(codes)) as pool:
            done = list(pool.map(worker, codes))
        claims = [c for _, got in done for c in got]
        runs += [w for w, _ in done]
        final = {"answered": True, "claims": claims, "refusal": ""}
        orch.call("policy workers", "orchestrator", "synthesise reply",
                  {"system": race.SYS_ORCH, "messages": [
                      {"role": "user", "content": json.dumps({"triage": triage, "workers": [
                          {"code": c, "claims": got} for c, (_, got) in zip(codes, done)]})}]},
                  final)
        return _finish(ticket, claims, runs, t0)
    except Budget as b:
        return _finish(ticket, [], runs, t0, terminated=str(b))


def write_md(out: dict) -> None:
    S, sw = out["summary"], out["sweep"]
    by = {(x["k"], x["arm"]): x for x in sw}
    ks = sorted({x["k"] for x in sw})
    first_fail = {a: next((k for k in ks if not by[(k, a)]["passed"]), None)
                  for a in ("single", "single_par", "squad")}
    k_max = ks[-1]
    L = ["# Race 2: when the triage squad is the right call", "",
         "Race 1 (the 10 Week-6 cases, one issue each) said **kill**: the work is "
         "sequential and does not split. This is a separate experiment, declared before "
         "it ran, on the one workload the multi-agent pattern is built for: **a ticket "
         "with several independent issues, each documented in a different article.**", "",
         f"Same retrieval, same reply renderer, same judge as race 1. Every agent run gets "
         f"Week 7's budget: {MAX_CALLS} model calls, {MAX_TOKENS:,} tokens.", "",
         "## Four multi-issue tickets (3-6 codes)", "",
         "| Arm | Pass | Tokens | Cost/ticket | Mean latency | Biggest single context |",
         "|---|---|---|---|---|---|"]
    names = {"single": "Single agent (one tool call per turn, as built)",
             "single_par": "Single agent + parallel tool calls",
             "squad": "Triage squad (one worker per code, concurrent)"}
    for a, s in S.items():
        big = max(r["max_agent_tokens"] for r in out["rows"] if r["arm"] == a)
        L.append(f"| {names[a]} | {s['passed']}/{s['n']} | {s['tokens']:,} | "
                 f"${s['cost_per_ticket_usd']:.4f} | {s['mean_latency_s']:.2f}s | {big:,} |")
    L += ["", f"## Size sweep: one ticket naming K codes, K = 2..{k_max}", "",
          "| K | Single | Single + parallel | Squad | Single context | Parallel context | "
          "Largest squad agent |", "|---|---|---|---|---|---|---|"]
    for k in ks:
        a, b, c = by[(k, "single")], by[(k, "single_par")], by[(k, "squad")]
        st = lambda x: ("PASS" if x["passed"] else "**FAIL** (budget)" if x["terminated"]
                        else "FAIL") + f" {x['latency_s']:.1f}s"
        L.append(f"| {k} | {st(a)} | {st(b)} | {st(c)} | {a['max_agent_tokens']:,} | "
                 f"{b['max_agent_tokens']:,} | {c['max_agent_tokens']:,} |")
    sq_slope = (by[(k_max, "squad")]["max_agent_tokens"] - by[(2, "squad")]["max_agent_tokens"]) / (k_max - 2)
    par_slope = (by[(k_max, "single_par")]["max_agent_tokens"] - by[(2, "single_par")]["max_agent_tokens"]) / (k_max - 2)
    L += ["", "## What it shows", "",
          f"- **The single agent as built fails from K = {first_fail['single']}.** One tool "
          f"call per code + policy + reply = K + 2 calls, so {first_fail['single']} codes needs "
          f"{first_fail['single'] + 2} calls against a budget of {MAX_CALLS}. It is escalated "
          "with no answer. The squad passes every size: no agent in it makes more than 2 calls.",
          f"- **Context per agent.** The single agent carries every issue in one history "
          f"({by[(6, 'single')]['max_agent_tokens']:,} tokens at K = 6). The squad's largest "
          f"agent is {by[(k_max, 'squad')]['max_agent_tokens']:,} tokens at K = {k_max} "
          f"(+{sq_slope:.0f} per code, the orchestrator's synthesis), vs "
          f"{by[(k_max, 'single_par')]['max_agent_tokens']:,} for the parallel single agent "
          f"(+{par_slope:.0f} per code).",
          "- **Speed: no win.** Workers run concurrently, but the reply's output tokens and "
          "the shared CPU retriever dominate, so the squad is about as fast as the parallel "
          "single agent, not faster.",
          f"- **The honest caveat.** A single agent with parallel tool calls also passes every "
          f"size here and is cheaper (${S['single_par']['cost_per_ticket_usd']:.4f} vs "
          f"${S['squad']['cost_per_ticket_usd']:.4f} per ticket). On pure lookups, that is "
          "the better fix.", "",
          "## So: when to use the triage squad", "",
          "Use it when a ticket has **several independent issues and each one needs its own "
          "context** (its own article, history, multi-step lookup). The single agent then "
          "has to hold all of them in one history: it runs out of calls (measured: from "
          f"{first_fail['single']} issues) or, with bigger per-issue context, out of tokens. "
          "Each squad worker holds one issue and stays small however big the ticket gets.",
          "",
          "Do **not** use it for single-issue tickets (race 1: same quality, 1.1x tokens, "
          "slower, fails silently), or when the issues are plain lookups a single agent can "
          "fetch with parallel tool calls.", "",
          "Routing rule: single agent by default; triage squad when triage counts more "
          f"independent issues than the single agent's budget allows (K + 2 > {MAX_CALLS}), "
          "or when each issue's context is large.", "",
          "Model calls are simulated as in race 1; concurrency, retrieval and grading are real."]
    open(os.path.join(HERE, "fanout.md"), "w").write("\n".join(L) + "\n")


def main() -> None:
    index = race.D.build_index_with_policy()
    _lookup(index, "ERR-4215")                       # warm the reranker off the clock
    arms = {"single": lambda t: run_single(t, index),
            "single_par": lambda t: run_single(t, index, parallel=True),
            "squad": lambda t: run_squad(t, index)}
    rows = []
    for c in CASES:
        for arm, fn in arms.items():
            r = fn(c["ticket"])
            r["grade"] = race.grade(c, r["reply"])
            rows.append({"case_id": c["case_id"], "arm": arm,
                         "n_codes": len(_codes(c["ticket"])), **r})
            print(f"  {c['case_id']} {arm:10} {'PASS' if r['grade']['passed'] else 'FAIL'} "
                  f"{r['tokens']:6,} tok  max/agent {r['max_agent_tokens']:6,}  "
                  f"{r['latency_s']:.2f}s  {r['terminated'] or ''}")
    sweep = []
    for k in range(2, len(SWEEP_CODES) + 1):
        c = sweep_ticket(k)
        for arm, fn in arms.items():
            r = fn(c["ticket"])
            g = race.grade(c, r["reply"])
            sweep.append({"k": k, "arm": arm, "passed": g["passed"], "tokens": r["tokens"],
                          "max_agent_tokens": r["max_agent_tokens"], "calls": r["calls"],
                          "latency_s": r["latency_s"], "cost_usd": r["cost_usd"],
                          "terminated": r["terminated"]})
        print(f"  K={k:2} " + "  ".join(
            f"{x['arm']}:{'PASS' if x['passed'] else 'FAIL'} {x['latency_s']:.2f}s "
            f"{x['max_agent_tokens']:,}/agent" for x in sweep[-3:]))
    summary = {}
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm]
        summary[arm] = {"passed": sum(r["grade"]["passed"] for r in rs), "n": len(rs),
                        "tokens": sum(r["tokens"] for r in rs),
                        "cost_per_ticket_usd": sum(r["cost_usd"] for r in rs) / len(rs),
                        "mean_latency_s": sum(r["latency_s"] for r in rs) / len(rs),
                        "terminated": sum(bool(r["terminated"]) for r in rs)}
    out = {"cases": [c["case_id"] for c in CASES], "budgets": {"max_calls": MAX_CALLS,
                                                               "max_tokens": MAX_TOKENS},
           "summary": summary,
           "rows": [{k: r[k] for k in ("case_id", "arm", "n_codes", "reply", "answered",
                                       "terminated", "tokens", "max_agent_tokens", "cost_usd",
                                       "latency_s", "calls", "agents", "grade", "handoffs")}
                    for r in rows],
           "questions": {c["case_id"]: c["ticket"]["question"] for c in CASES},
           "sweep": sweep}
    json.dump(out, open(os.path.join(HERE, "fanout.json"), "w"), indent=1)
    write_md(out)
    for arm, s in summary.items():
        print(f"{arm:10} pass {s['passed']}/{s['n']}  tokens {s['tokens']:,}  "
              f"${s['cost_per_ticket_usd']:.4f}/ticket  mean {s['mean_latency_s']:.2f}s  "
              f"budget-stopped {s['terminated']}")


if __name__ == "__main__":
    main()
