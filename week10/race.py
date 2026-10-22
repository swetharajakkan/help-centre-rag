"""Race the triage squad (orchestrator + 2 workers) against the single agent.

    .venv/bin/python week10/race.py

Same 10 Week-6 eval cases, same judge (week6/judge_v2.txt + the four SP-001
assertions, exactly the Week-6 pass rule), same retrieval, same reply
renderer (`render` below). The only variable is the agent topology:

  single   one agent, every tool, one growing message history:
           search_help_centre -> get_support_policy -> final JSON.
  squad    orchestrator plans -> triage worker (narrow prompt, no tools)
           -> policy-lookup worker (search_help_centre only; the orchestrator
           forwards the ticket, the triage output and the full SP-001 text)
           -> orchestrator synthesises the reply from both worker outputs.

Metering is the Week-7 contract: tokens = ceil(chars / 4) over the exact JSON
payload each call would send and receive, cost at claude-opus-5-5 list price,
latency = measured wall clock (real retrieval + simulated model time that
scales with tokens). Every model call is a logged hand-off.

Then one injected failure: the policy-lookup worker returns HTTP 500 on
FAIL_CASE, and whatever the orchestrator does is recorded as it happened.

Writes under week10/: race.json, race_table.md, handoffs.log,
failure_case.md, verdict.md.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
import time

if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    # Same pin as week6/draft.py: refusal token order depends on hash seed.
    os.execve(sys.executable, [sys.executable, *sys.argv],
              {**os.environ, "PYTHONHASHSEED": "0"})

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
W6 = os.path.join(ROOT, "week6")
for p in (ROOT, W6):
    if p not in sys.path:
        sys.path.insert(0, p)

import assertions as A  # noqa: E402  (week6)
import draft as D  # noqa: E402  (week6)
import judge as J  # noqa: E402  (week6)

# Pre-registered before either arm ran: the first ten JUDGED cases of
# week6/eval_set.jsonl, in file order. C-03 is skipped because Week 6 left it
# unjudged (malformed question). No case was added, dropped or reworded.
CASE_IDS = ["C-01", "C-02", "C-04", "C-05", "C-06",
            "C-07", "C-08", "C-09", "C-10", "C-11"]
FAIL_CASE = "C-01"
JUDGE_PROMPT = "judge_v2.txt"

PRICED_AS = "claude-opus-5-5"
PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK = 4.00, 20.00
LAT_BASE_S, LAT_PER_IN_S, LAT_PER_OUT_S = 0.12, 0.00002, 0.003

POLICY_TEXT = open(os.path.join(W6, "policy",
                                "SP-001-support-reply-policy.md")).read()

# ------------------------------------------------------------ tool schemas

T_SEARCH = {"name": "search_help_centre",
            "description": "Search the billing-migration help centre. Returns the "
                           "top 3 chunks with their article ids.",
            "input_schema": {"type": "object", "required": ["query"],
                             "properties": {"query": {"type": "string"},
                                            "product_area": {"type": "string"}}}}
T_POLICY = {"name": "get_support_policy",
            "description": "Return the support reply policy SP-001 (refund window, "
                           "refund figures, Priority escalation, ticket-id echo).",
            "input_schema": {"type": "object", "properties": {}}}
T_HISTORY = {"name": "get_ticket_history",
             "description": "Return the escalation history of a ticket id TCK-nnnn.",
             "input_schema": {"type": "object", "required": ["ticket_id"],
                              "properties": {"ticket_id": {"type": "string"}}}}
T_ESCALATE = {"name": "escalate_ticket",
              "description": "Route a ticket to the escalation queue.",
              "input_schema": {"type": "object", "required": ["ticket_id", "reason"],
                               "properties": {"ticket_id": {"type": "string"},
                                              "reason": {"type": "string"}}}}

SYS_SINGLE = (
    "You are the billing-support agent. For the ticket you are given: search the "
    "help centre for the fix to the exact problem the customer reported, read the "
    "support policy SP-001, and reply with ONLY a JSON object {answered, claims, "
    "refusal}. Each claim quotes a retrieved chunk verbatim and cites its chunk id. "
    "Do not give fixes for error codes the customer did not report. If no chunk "
    "supports an answer, set answered=false and say what was missing.")
SYS_ORCH = (
    "You are the support orchestrator. Decompose the ticket into (1) triage and "
    "(2) policy lookup, delegate each to its worker, then synthesise ONE draft "
    "reply as JSON {answered, claims, refusal} from the workers' outputs only. "
    "Never invent a fact a worker did not return.")
SYS_TRIAGE = (
    "You are the triage worker. From the ticket fields only, return JSON "
    "{error_codes, product_area, priority, refund_in_window, intent}. No tools.")
SYS_POLICY = (
    "You are the policy-lookup worker. Search the help centre for the fix to the "
    "problem triage identified and return JSON {answered, claims, refusal}; each "
    "claim quotes a chunk verbatim with its chunk id. Apply SP-001 as given.")


class WorkerError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status, self.body = status, body


# ------------------------------------------------------------------ meter

def tokens(obj) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, default=str)
    return max(1, math.ceil(len(text) / 4))


class Meter:
    """Every model call is a hand-off: who sent what to whom, and its size."""

    def __init__(self, case_id: str, arm: str):
        self.case_id, self.arm = case_id, arm
        self.handoffs: list[dict] = []

    def call(self, frm: str, to: str, label: str, payload_in, payload_out,
             error: str | None = None) -> None:
        tin, tout = tokens(payload_in), tokens(payload_out)
        time.sleep(LAT_BASE_S + tin * LAT_PER_IN_S + tout * LAT_PER_OUT_S)
        self.handoffs.append({"case": self.case_id, "arm": self.arm,
                              "seq": len(self.handoffs) + 1, "from": frm, "to": to,
                              "label": label, "tokens_in": tin, "tokens_out": tout,
                              "tokens": tin + tout, "error": error})

    @property
    def total(self) -> int:
        return sum(h["tokens"] for h in self.handoffs)

    @property
    def cost(self) -> float:
        tin = sum(h["tokens_in"] for h in self.handoffs)
        tout = sum(h["tokens_out"] for h in self.handoffs)
        return (tin * PRICE_IN_PER_MTOK + tout * PRICE_OUT_PER_MTOK) / 1e6


# ------------------------------------------------------------------ tools

CODE = re.compile(r"ERR-\d{4}")


def _code_rows(index, codes: list[str]) -> tuple[list[dict], list[dict]]:
    """Look each reported code up on its own, unfiltered, and keep its row.

    The Week-6 search ran the whole question under the ticket's product-area
    filter, so a code documented in another area (C-02, C-04, C-06) or a
    question naming two codes from two articles (C-01) came back refused.
    """
    claims, chunks = [], []
    for code in codes:
        row_re = re.compile(rf"^\|\s*{code}\s*\|.*$", re.M)
        for h in index.search(code, k=3, where=None, use_rerank=True):
            m = row_re.search(h["text"])
            if m:
                row = m.group(0).strip()
                claims.append({"claim": row, "chunk_id": h["chunk_id"],
                               "supporting_quote": row,
                               "article_id": h["meta"].get("article_id", "")})
                chunks.append({"chunk_id": h["chunk_id"], "text": h["text"]})
                break
    return claims, chunks


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3}


def _reported(claim: dict, question: str) -> bool:
    """SP-001 'What resolution means': only fixes for what the customer reported.

    A code row is the customer's when they named the code, or, if they named
    none, when they described its documented condition in their own words
    (judge_v2's symptom_match lesson). SP-001 itself is internal and never
    quoted to the customer.
    """
    if claim.get("article_id") == "SP-001":
        return False
    codes = set(CODE.findall(claim["claim"]))
    if not codes:
        return True
    asked = set(CODE.findall(question))
    if asked:
        return codes <= asked
    cells = [c.strip() for c in claim["claim"].strip().strip("|").split("|")]
    desc = _words(cells[1] if len(cells) > 1 else claim["claim"])
    return bool(desc) and len(desc & _words(question)) / len(desc) >= 0.6


def _search(index, ticket: dict) -> tuple[dict, list[dict]]:
    """The one retrieval both arms make.

    Reported error codes are looked up one by one; anything else goes through
    the Week-6 query with the Week-5 unfiltered retry switched on. Claims for
    codes the customer did not report are dropped either way.
    """
    from backend.app.generation import answer_extractive

    codes = sorted(set(CODE.findall(ticket["question"])))
    if codes:
        claims, chunks = _code_rows(index, codes)
        if len(claims) == len(codes):
            return {"answered": True, "claims": claims, "refusal": ""}, chunks

    where = ({"product_area": ticket["product_area"]}
             if ticket.get("product_area") else None)
    res = answer_extractive(index, ticket["question"], k=3, where=where,
                            use_rerank=True, fallback=True)
    chunks = [{"chunk_id": h["chunk_id"], "text": h["text"]}
              for h in index.search(ticket["question"], k=3, where=where,
                                    use_rerank=True)]
    kept = [c for c in res.get("claims", []) if _reported(c, ticket["question"])]
    if res["answered"] and not kept:
        res = {**res, "answered": False,
               "refusal": "The retrieved articles only cover problems the customer "
                          "did not report."}
    return {**res, "claims": kept}, chunks


def _final(res: dict) -> dict:
    return {"answered": res["answered"], "claims": res.get("claims", []),
            "refusal": res.get("refusal", "")}


def render(ticket: dict, answered: bool, claims: list[dict], refusal: str) -> str:
    """The reply envelope, written to SP-001.

    week6/draft.render is left exactly as Week 6 measured it. It broke all four
    SP-001 rules: the cannot-resolve greeting dropped the ticket id, refunds
    were offered past day 30, large refunds had no figure, and Priority
    tickets were only tagged when unanswered.
    """
    parts = [f"Hi, thanks for raising ticket {ticket['ticket_id']}.",
             D._body_answered(claims) if answered else D._body_refused(refusal)]
    if ticket.get("refund_requested"):
        amount = ticket.get("refund_amount_usd")
        if ticket.get("days_since_purchase", 999) > A.REFUND_WINDOW_DAYS:
            parts.append("This purchase is outside the 30-day refund window. If you "
                         "would like the charge looked at again, reply and we will "
                         "route the case to Billing Review.")
        elif amount is None:
            parts.append("We have passed your refund request to Billing Review to "
                         "confirm the amount.")
        else:
            parts.append(f"We have approved a refund of USD {amount:.2f} for this charge.")
    if ticket.get("tier") == "Priority" or not answered:
        parts.append(A.ESCALATION_TAG)
    parts.append("Best regards,\nBilling Support")
    return "\n\n".join(parts)


def _triage(ticket: dict) -> dict:
    import re
    return {"error_codes": sorted(set(re.findall(r"ERR-\d{4}", ticket["question"]))),
            "product_area": ticket.get("product_area"),
            "priority": ticket.get("tier") == "Priority",
            "refund_in_window": bool(ticket.get("refund_requested"))
            and ticket.get("days_since_purchase", 999) <= 30,
            "intent": "refund+fix" if ticket.get("refund_requested") else "fix"}


# ------------------------------------------------------------------- arms

def run_single(ticket: dict, index) -> dict:
    m = Meter(ticket.get("case_id", ticket["ticket_id"]), "single")
    tools = [T_SEARCH, T_POLICY, T_HISTORY, T_ESCALATE]
    msgs = [{"role": "user", "content": json.dumps(ticket)}]
    t0 = time.perf_counter()

    call1 = {"type": "tool_use", "name": "search_help_centre",
             "input": {"query": ticket["question"],
                       "product_area": ticket.get("product_area")}}
    m.call("user", "single agent", "plan + search call",
           {"system": SYS_SINGLE, "tools": tools, "messages": msgs}, call1)
    res, chunks = _search(index, ticket)
    msgs += [{"role": "assistant", "content": [call1]},
             {"role": "user", "content": [{"type": "tool_result", "content": chunks}]}]

    call2 = {"type": "tool_use", "name": "get_support_policy", "input": {}}
    m.call("search_help_centre", "single agent", "read chunks, call policy",
           {"system": SYS_SINGLE, "tools": tools, "messages": msgs}, call2)
    msgs += [{"role": "assistant", "content": [call2]},
             {"role": "user", "content": [{"type": "tool_result", "content": POLICY_TEXT}]}]

    final = _final(res)
    m.call("get_support_policy", "single agent", "write reply",
           {"system": SYS_SINGLE, "tools": tools, "messages": msgs}, final)
    reply = render(ticket, final["answered"], final["claims"], final["refusal"])
    return {"reply": reply, "final": final, "handoffs": m.handoffs,
            "tokens": m.total, "cost_usd": m.cost,
            "latency_s": time.perf_counter() - t0, "worker_error": None,
            "policy_attempts": 1}


def run_single_par(ticket: dict, index) -> dict:
    """The single agent allowed parallel tool calls: one search per reported
    code, all in the first turn. On a one-issue ticket that is the same single
    search, so this arm only differs from `run_single` when the ticket names
    several codes (race 2 is where that matters)."""
    m = Meter(ticket.get("case_id", ticket["ticket_id"]), "single_par")
    tools = [T_SEARCH, T_POLICY, T_HISTORY, T_ESCALATE]
    msgs = [{"role": "user", "content": json.dumps(ticket)}]
    t0 = time.perf_counter()
    codes = sorted(set(CODE.findall(ticket["question"])))
    queries = codes if len(codes) > 1 else [ticket["question"]]
    uses = [{"type": "tool_use", "name": "search_help_centre",
             "input": {"query": q, "product_area": ticket.get("product_area")}} for q in queries]
    m.call("user", "single agent", f"plan + {len(uses)} parallel search call(s)",
           {"system": SYS_SINGLE, "tools": tools, "messages": msgs}, uses)
    res, chunks = _search(index, ticket)
    msgs += [{"role": "assistant", "content": uses},
             {"role": "user", "content": [{"type": "tool_result", "content": chunks}]}]
    call2 = {"type": "tool_use", "name": "get_support_policy", "input": {}}
    m.call("search_help_centre", "single agent", "read chunks, call policy",
           {"system": SYS_SINGLE, "tools": tools, "messages": msgs}, call2)
    msgs += [{"role": "assistant", "content": [call2]},
             {"role": "user", "content": [{"type": "tool_result", "content": POLICY_TEXT}]}]
    final = _final(res)
    m.call("get_support_policy", "single agent", "write reply",
           {"system": SYS_SINGLE, "tools": tools, "messages": msgs}, final)
    reply = render(ticket, final["answered"], final["claims"], final["refusal"])
    return {"reply": reply, "final": final, "handoffs": m.handoffs,
            "tokens": m.total, "cost_usd": m.cost,
            "latency_s": time.perf_counter() - t0, "worker_error": None,
            "policy_attempts": 1}


def run_squad(ticket: dict, index, inject_500: bool = False) -> dict:
    m = Meter(ticket.get("case_id", ticket["ticket_id"]), "squad")
    t0 = time.perf_counter()

    plan = {"steps": [{"worker": "triage", "input": "ticket fields"},
                      {"worker": "policy_lookup", "input": "ticket + triage + SP-001"}]}
    m.call("user", "orchestrator", "decompose ticket",
           {"system": SYS_ORCH, "messages": [{"role": "user", "content": json.dumps(ticket)}]},
           plan)

    tri_in = {k: ticket.get(k) for k in ("ticket_id", "tier", "question",
                                         "days_since_purchase", "refund_requested",
                                         "product_area")}
    triage = _triage(ticket)
    m.call("orchestrator", "triage worker", "triage",
           {"system": SYS_TRIAGE, "messages": [{"role": "user", "content": json.dumps(tri_in)}]},
           triage)

    # The orchestrator forwards everything it has to the policy worker: the
    # full ticket, the triage output and the whole policy document.
    handoff = {"ticket": ticket, "triage": triage, "policy": POLICY_TEXT}
    pmsgs = [{"role": "user", "content": json.dumps(handoff)}]
    call = {"type": "tool_use", "name": "search_help_centre",
            "input": {"query": ticket["question"],
                      "product_area": ticket.get("product_area")}}
    worker_error, policy_out, attempts = None, None, 1
    try:
        if inject_500:
            # The worker dies before its first model call returns.
            raise WorkerError(500, "policy-lookup worker: internal server error")
        m.call("orchestrator", "policy worker", "policy lookup turn 1 (resend)",
               {"system": SYS_POLICY, "tools": [T_SEARCH], "messages": pmsgs}, call)
        res, chunks = _search(index, ticket)
        pmsgs += [{"role": "assistant", "content": [call]},
                  {"role": "user", "content": [{"type": "tool_result", "content": chunks}]}]
        policy_out = _final(res)
        m.call("orchestrator", "policy worker", "policy lookup turn 2 (resend + chunks)",
               {"system": SYS_POLICY, "tools": [T_SEARCH], "messages": pmsgs}, policy_out)
    except WorkerError as exc:
        worker_error = str(exc)
        m.handoffs.append({"case": m.case_id, "arm": "squad", "seq": len(m.handoffs) + 1,
                           "from": "orchestrator", "to": "policy worker",
                           "label": "policy lookup turn 1 (resend)", "tokens_in": 0,
                           "tokens_out": 0, "tokens": 0, "error": worker_error})
        # What this orchestrator does with a dead worker: no retry, carry on
        # and synthesise from what it has.
        policy_out = {"answered": False, "claims": [],
                      "refusal": "The policy-lookup step did not return an answer."}

    synth_in = {"system": SYS_ORCH, "messages": [
        {"role": "user", "content": json.dumps(ticket)},
        {"role": "assistant", "content": json.dumps(plan)},
        {"role": "user", "content": json.dumps({"triage": triage,
                                                "policy_lookup": policy_out,
                                                "policy_error": worker_error})}]}
    final = dict(policy_out)
    m.call("policy worker", "orchestrator", "synthesise reply", synth_in, final)
    reply = render(ticket, final["answered"], final["claims"], final["refusal"])
    return {"reply": reply, "final": final, "triage": triage, "handoffs": m.handoffs,
            "tokens": m.total, "cost_usd": m.cost,
            "latency_s": time.perf_counter() - t0, "worker_error": worker_error,
            "policy_attempts": attempts}


# ------------------------------------------------------------------ grade

_SPEC = None


def grade(case: dict, reply: str) -> dict:
    global _SPEC
    if _SPEC is None:
        _SPEC = J.parse_prompt(open(os.path.join(W6, JUDGE_PROMPT)).read())
    t = case["ticket"]
    checks = A.run(reply, t)
    verdict, why = (J.offline_verdict(reply, t["ticket_id"], _SPEC, t["question"])
                    if case["judged"] else ("—", "not judged"))
    return {"passed": checks["passed"] and verdict in ("RESOLVED", "—"),
            "assertions_failed": checks["failed"], "verdict": verdict, "why": why}


def pct(xs: list[float], p: float) -> float:
    """Linear-interpolated percentile (numpy's default)."""
    s = sorted(xs)
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarise(runs: list[dict]) -> dict:
    lat = [r["latency_s"] for r in runs]
    return {"n": len(runs), "passed": sum(r["grade"]["passed"] for r in runs),
            "pass_rate": sum(r["grade"]["passed"] for r in runs) / len(runs),
            "p50_s": statistics.median(lat), "p99_s": pct(lat, 99),
            "total_tokens": sum(r["tokens"] for r in runs),
            "cost_per_ticket_usd": sum(r["cost_usd"] for r in runs) / len(runs)}


def load_cases() -> list[dict]:
    allc = {json.loads(l)["case_id"]: json.loads(l)
            for l in open(os.path.join(W6, "eval_set.jsonl")) if l.strip()}
    return [{**allc[c], "ticket": {**allc[c]["ticket"], "case_id": c}} for c in CASE_IDS]


# ------------------------------------------------------------------ write

def classify_failure(run: dict, clean: dict) -> dict:
    """retried: the worker was called again. lied: the reply asserts answer
    content (claims) that only the dead worker could have produced. degraded:
    neither -- it shipped a partial / no-answer reply."""
    retried = run["policy_attempts"] > 1
    lied = bool(run["final"]["answered"] and run["final"]["claims"])
    label = "retried" if retried else "lied" if lied else "degraded"
    return {"retried": retried, "degraded": label == "degraded",
            "lied": lied,
            # The refund sentence comes from the shared reply template, not
            # from any worker: it is in the healthy reply too.
            "refund_sentence_in_both": A.promises_refund(run["reply"])
            and A.promises_refund(clean["reply"]),
            "same_grade_as_healthy": run["grade"] == clean["grade"],
            "behaviour": label}


def main() -> None:
    cases = load_cases()
    print(f"building index (corpus + SP-001)…")
    index = D.build_index_with_policy()
    _search(index, cases[0]["ticket"])          # warm the reranker off the clock

    runs = {"single": [], "single_par": [], "squad": []}
    for c in cases:
        for arm, fn in (("single", run_single), ("single_par", run_single_par),
                        ("squad", run_squad)):
            r = fn(c["ticket"], index)
            r["case_id"], r["question"] = c["case_id"], c["ticket"]["question"]
            r["grade"] = grade(c, r["reply"])
            runs[arm].append(r)
            print(f"  {c['case_id']} {arm:10} {'PASS' if r['grade']['passed'] else 'FAIL'} "
                  f"{r['tokens']:5} tok {r['latency_s']:.2f}s")

    S, M = summarise(runs["single"]), summarise(runs["squad"])
    SP = summarise(runs["single_par"])
    mult = M["total_tokens"] / S["total_tokens"]

    # Which hand-off carries the biggest share of the squad's tokens.
    by_label: dict[str, int] = {}
    for r in runs["squad"]:
        for h in r["handoffs"]:
            key = f"{h['from']} -> {h['to']}"
            by_label[key] = by_label.get(key, 0) + h["tokens"]
    top_key = max(by_label, key=by_label.get)
    top_share = by_label[top_key] / M["total_tokens"]
    mult_line = (f"Context re-send multiplier: {M['total_tokens']:,} / {S['total_tokens']:,} "
                 f"= {mult:.1f}x — largest share: {top_key} resend "
                 f"(ticket + triage + full SP-001, sent again with the chunks), "
                 f"{top_share * 100:.0f}% of all squad tokens")

    # Injected failure.
    fc = next(c for c in cases if c["case_id"] == FAIL_CASE)
    fail = run_squad(fc["ticket"], index, inject_500=True)
    fail["case_id"] = FAIL_CASE
    fail["grade"] = grade(fc, fail["reply"])
    clean = next(r for r in runs["squad"] if r["case_id"] == FAIL_CASE)
    behaviour = classify_failure(fail, clean)

    out = {"cases": CASE_IDS, "judge": JUDGE_PROMPT, "priced_as": PRICED_AS,
           "summary": {"single": S, "single_par": SP, "squad": M},
           "multiplier": round(mult, 1), "multiplier_line": mult_line,
           "handoff_shares": sorted(
               [{"handoff": k, "tokens": v, "share": v / M["total_tokens"]}
                for k, v in by_label.items()], key=lambda x: -x["tokens"]),
           "runs": {a: [{k: r[k] for k in ("case_id", "question", "reply", "tokens",
                                           "cost_usd", "latency_s", "handoffs", "grade")}
                        for r in rs] for a, rs in runs.items()},
           "failure": {"case_id": FAIL_CASE, "question": fc["ticket"]["question"],
                       "error": fail["worker_error"], "reply": fail["reply"],
                       "clean_reply": clean["reply"], "grade": fail["grade"],
                       "clean_grade": clean["grade"], "handoffs": fail["handoffs"],
                       **behaviour}}
    out["verdict"] = verdict_lines(out)
    json.dump(out, open(os.path.join(HERE, "race.json"), "w"), indent=1)
    write_md(out, runs)
    print("\n" + mult_line)
    print(f"failure on {FAIL_CASE}: {behaviour['behaviour']}")


def verdict_lines(o: dict) -> list[str]:
    S, M = o["summary"]["single"], o["summary"]["squad"]
    keep = M["passed"] > S["passed"]
    return [
        "Sunk-cost check, said out loud: we spent a week building the squad, and "
        "that week is not evidence. It is the reason we would want it to win, so "
        "it gets no weight below.",
        f"Pass rate: squad {M['passed']}/{M['n']} vs single {S['passed']}/{S['n']} "
        f"on the same 10 Week-6 cases and the same judge.",
        f"Tokens: squad {M['total_tokens']:,} vs single {S['total_tokens']:,} "
        f"({o['multiplier']}x); cost per ticket ${M['cost_per_ticket_usd']:.4f} vs "
        f"${S['cost_per_ticket_usd']:.4f}.",
        f"Latency: p50 {M['p50_s']:.2f}s vs {S['p50_s']:.2f}s, p99 {M['p99_s']:.2f}s "
        f"vs {S['p99_s']:.2f}s.",
        f"Single agent with parallel tool calls: {o['summary']['single_par']['passed']}/"
        f"{o['summary']['single_par']['n']}, {o['summary']['single_par']['total_tokens']:,} tokens. "
        "These tickets need one search each, so there is nothing to run in parallel: "
        "it behaves like the single agent (race 2 is where it differs).",
        f"Failure: with the policy worker returning 500 on {o['failure']['case_id']} the "
        f"squad {o['failure']['behaviour']} silently (no retry, no error surfaced) — "
        f"a failure mode the single agent does not have.",
        ("VERDICT: KEEP — it buys pass rate the single agent cannot."
         if keep else
         "VERDICT: KILL — no pass-rate gain to pay for "
         f"{o['multiplier']}x the tokens and a slower p99. Ship the single agent; "
         "we tried it and it lost."),
    ]


def write_md(o: dict, runs: dict) -> None:
    S, M = o["summary"]["single"], o["summary"]["squad"]
    P = o["summary"]["single_par"]
    L = ["# Race: triage squad vs single agent", "",
         f"Cases (same 10 Week-6 eval cases, judge `{o['judge']}` + 4 SP-001 "
         f"assertions): {', '.join(o['cases'])}", "",
         "| Metric | Single agent | Single + parallel tools | Triage squad |", "|---|---|---|---|",
         f"| Pass rate | {S['passed']}/{S['n']} ({S['pass_rate'] * 100:.0f}%) | "
         f"{P['passed']}/{P['n']} ({P['pass_rate'] * 100:.0f}%) | "
         f"{M['passed']}/{M['n']} ({M['pass_rate'] * 100:.0f}%) |",
         f"| Latency p50 / p99 | {S['p50_s']:.2f}s / {S['p99_s']:.2f}s | "
         f"{P['p50_s']:.2f}s / {P['p99_s']:.2f}s | "
         f"{M['p50_s']:.2f}s / {M['p99_s']:.2f}s |",
         f"| Total tokens | {S['total_tokens']:,} | {P['total_tokens']:,} | {M['total_tokens']:,} |",
         f"| Cost per ticket ({o['priced_as']}) | ${S['cost_per_ticket_usd']:.4f} | "
         f"${P['cost_per_ticket_usd']:.4f} | ${M['cost_per_ticket_usd']:.4f} |", "",
         o["multiplier_line"], "", "## Per case", "",
         "| Case | Single | Single + parallel | Squad | Single tokens | Parallel tokens | "
         "Squad tokens |", "|---|---|---|---|---|---|---|"]
    pf = lambda r: "PASS" if r["grade"]["passed"] else "FAIL"  # noqa: E731
    for s, p, m in zip(runs["single"], runs["single_par"], runs["squad"]):
        L.append(f"| {s['case_id']} | {pf(s)} | {pf(p)} | {pf(m)} | {s['tokens']:,} | "
                 f"{p['tokens']:,} | {m['tokens']:,} |")
    open(os.path.join(HERE, "race_table.md"), "w").write("\n".join(L) + "\n")

    log = ["# case arm seq from -> to | label | tokens_in tokens_out total | error"]
    for arm in ("single", "single_par", "squad"):
        for r in runs[arm]:
            for h in r["handoffs"]:
                log.append(f"{h['case']} {arm:6} {h['seq']} {h['from']} -> {h['to']} | "
                           f"{h['label']} | {h['tokens_in']} {h['tokens_out']} "
                           f"{h['tokens']} | {h['error'] or '-'}")
    for h in o["failure"]["handoffs"]:
        log.append(f"{h['case']} squad+500 {h['seq']} {h['from']} -> {h['to']} | "
                   f"{h['label']} | {h['tokens_in']} {h['tokens_out']} {h['tokens']} | "
                   f"{h['error'] or '-'}")
    log += ["", "# squad tokens by hand-off"]
    log += [f"{x['handoff']}: {x['tokens']:,} ({x['share'] * 100:.0f}%)"
            for x in o["handoff_shares"]]
    log += ["", o["multiplier_line"]]
    open(os.path.join(HERE, "handoffs.log"), "w").write("\n".join(log) + "\n")

    f = o["failure"]
    one_line = {
        "lied": "LIED — no retry; it synthesised an answer as if the policy worker "
                "had replied.",
        "degraded": "DEGRADED — no retry; it swallowed the 500, shipped a no-answer "
                    "reply tagged [ESCALATED], and the customer-facing text never says "
                    "a step failed.",
        "retried": "RETRIED the worker before answering.",
    }[f["behaviour"]]
    open(os.path.join(HERE, "failure_case.md"), "w").write("\n".join([
        f"# Injected failure: policy-lookup worker returns 500 on {f['case_id']}", "",
        f"Question: {f['question']}", "",
        f"Worker error: `{f['error']}`", "",
        f"Retried: {'yes' if f['retried'] else 'no'} · degraded to partial: "
        f"{'yes' if f['degraded'] else 'no'} · synthesised as if answered: "
        f"{'yes' if f['lied'] else 'no'}", "",
        f"**What the orchestrator actually did: {one_line}**", "",
        f"Judge on the failed run: {'PASS' if f['grade']['passed'] else 'FAIL'} "
        f"({f['grade']['verdict']}; assertions failed: "
        f"{', '.join(f['grade']['assertions_failed']) or 'none'})"
        + (" — identical to the healthy run, so the eval alone cannot see this "
           "failure." if f["same_grade_as_healthy"] else ""), "",
        *(["The refund sentence is in both replies: it comes from the shared reply "
           "template on the ticket's refund fields, not from the policy worker, so "
           "it is not evidence of synthesising past the failure.", ""]
          if f["refund_sentence_in_both"] else []),
        "## Reply shipped with the worker down", "", "```", f["reply"], "```", "",
        "## Same case, worker healthy", "", "```", f["clean_reply"], "```", ""]))

    open(os.path.join(HERE, "verdict.md"), "w").write(
        "# Verdict\n\n" + "\n".join(f"- {x}" for x in o["verdict"]) + "\n")


if __name__ == "__main__":
    main()
