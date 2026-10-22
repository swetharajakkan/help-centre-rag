"""Week 10 in the app: the triage-squad vs single-agent race (admin only).

  GET  /api/week10      the race as week10/race.py last wrote it, plus the
                        A2A AgentCard.
  POST /api/w10/ask     one typed question through both arms, live, with
                        each arm's hand-offs and token bill.
"""
from __future__ import annotations

import json
import os
import sys

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
W10 = os.path.join(ROOT, "week10")

router = APIRouter()


def _race():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from week10 import race  # noqa: PLC0415  (pulls in week6 + the index code)
    return race


@router.get("/api/week10")
def overview() -> dict:
    path = os.path.join(W10, "race.json")
    if not os.path.exists(path):
        raise HTTPException(404, "race not run yet")
    out = json.load(open(path))
    card = os.path.join(W10, "agent_card.json")
    out["agent_card"] = json.load(open(card)) if os.path.exists(card) else None
    fan = os.path.join(W10, "fanout.json")
    if os.path.exists(fan):
        f = json.load(open(fan))
        f["md"] = open(os.path.join(W10, "fanout.md")).read()
        for r in f["rows"]:
            r.pop("handoffs", None)
        out["fanout"] = f
    return out


ARMS = ("single", "single_par", "squad")


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    tier: str = "Standard"
    session_id: str | None = None
    arms: list[str] | None = None       # which arms to run; default all three
    auto: bool = False                  # run only the arm the user's screen would pick


def _ticket(question: str, tier: str = "Standard") -> dict:
    return {"ticket_id": "TCK-0000", "case_id": "live", "tier": tier,
            "days_since_purchase": 0, "refund_requested": False,
            "refund_amount_usd": None, "question": question.strip(), "product_area": None}


def _run_race1(name: str, ticket: dict, index) -> dict:
    """A race-1 arm on a ticket with at most one issue, in race 2's shape."""
    race = _race()
    fn = {"single": race.run_single, "single_par": race.run_single_par,
          "squad": race.run_squad}[name]
    r = fn(ticket, index)
    per_agent: dict[str, int] = {}
    for h in r["handoffs"]:
        per_agent[h["to"]] = per_agent.get(h["to"], 0) + h["tokens"]
    return {"reply": r["reply"], "answered": r["final"]["answered"], "terminated": None,
            "tokens": r["tokens"], "max_agent_tokens": max(per_agent.values()),
            "cost_usd": r["cost_usd"], "latency_s": r["latency_s"],
            "calls": len(r["handoffs"]), "agents": len(per_agent), "handoffs": r["handoffs"]}


def _arms(ticket: dict, index, arms) -> dict:
    """Run the chosen arms on one ticket and grade each reply like race 1."""
    race = _race()
    from week10 import fanout

    case = {"case_id": ticket.get("case_id", "live"), "judged": True, "ticket": ticket}
    k = len(set(race.CODE.findall(ticket["question"])))
    out = {}
    for name in [a for a in ARMS if a in arms]:
        if k >= 2:        # several independent issues: race 2's arms
            fn = {"single": lambda t: fanout.run_single(t, index),
                  "single_par": lambda t: fanout.run_single(t, index, parallel=True),
                  "squad": lambda t: fanout.run_squad(t, index)}[name]
            r = fn(ticket)
            r = {k2: r[k2] for k2 in ("reply", "answered", "terminated", "tokens",
                                      "max_agent_tokens", "cost_usd", "latency_s", "calls",
                                      "agents", "handoffs")}
        else:
            r = _run_race1(name, ticket, index)
        g = race.grade(case, r["reply"])
        out[name] = {**r, "passed": g["passed"], "verdict": g["verdict"],
                     "assertions_failed": g["assertions_failed"], "why": g["why"]}
    return {"n_codes": k, "budget": {"max_calls": fanout.MAX_CALLS,
                                     "max_tokens": fanout.MAX_TOKENS}, "arms": out}


@router.post("/api/w10/ask")
def ask(req: Ask) -> dict:
    from .main import _week6_live

    _race()
    from week10 import fanout

    ticket = _ticket(req.question, req.tier)
    r = fanout.route(ticket["question"])
    if req.auto:
        if r["arm"] == "crew":
            return {"question": ticket["question"], "route": r, "n_codes": 0, "arms": {},
                    "budget": {"max_calls": fanout.MAX_CALLS, "max_tokens": fanout.MAX_TOKENS}}
        arms = [r["arm"]]
    else:
        arms = [a for a in (req.arms or ARMS) if a in ARMS]
        if not arms:
            raise HTTPException(400, "pick at least one of single, single_par, squad")
    return {"question": ticket["question"], "route": r,
            **_arms(ticket, _week6_live()["index"], arms)}


@router.post("/api/w10/auto")
async def auto(req: Ask, request: Request) -> dict:
    """The user's screen: the router picks the arm; no-code questions go to the crew."""
    import time

    from . import track, week9
    from .main import _week6_live

    _race()
    from week10 import fanout

    question = req.question.strip()
    r = fanout.route(question)
    if r["arm"] == "crew":
        data = await week9.ask(week9.Ask(question=question), request)
        return {"route": r, "crew": data}
    t0 = time.perf_counter()
    res = _arms(_ticket(question), _week6_live()["index"], [r["arm"]])
    a = res["arms"][r["arm"]]
    who = getattr(request.state, "user", None) or {}
    rec = track.build(who, question, ms=round((time.perf_counter() - t0) * 1000, 1))
    rec.update(kind=f"auto:{r['arm']}", answer=a["reply"], error=None,
               approved=a["passed"], agents=[{"name": r["arm"], "runs": a["agents"],
                                              "did": r["reason"], "tokens": a["tokens"]}])
    track.append(rec)
    return {"route": r, "reply": a["reply"], "answered": a["answered"], "calls": a["calls"],
            "agents": a["agents"], "tokens": a["tokens"], "latency_s": a["latency_s"]}


# ------------------------------------------------------------ race 2 (live)

class FanoutRun(BaseModel):
    case_id: str | None = None          # F-01..F-04
    k: int | None = Field(default=None, ge=2, le=10)   # or a sweep ticket naming K codes
    arms: list[str] | None = None


@router.post("/api/w10/fanout")
def fanout_run(req: FanoutRun) -> dict:
    from .main import _week6_live

    _race()
    from week10 import fanout

    if req.case_id:
        case = next((c for c in fanout.CASES if c["case_id"] == req.case_id), None)
        if case is None:
            raise HTTPException(404, "unknown case")
    elif req.k:
        case = fanout.sweep_ticket(req.k)
    else:
        raise HTTPException(400, "give case_id or k")
    arms = [a for a in (req.arms or ARMS) if a in ARMS] or list(ARMS)
    return {"case_id": case["case_id"], "question": case["ticket"]["question"],
            "route": fanout.route(case["ticket"]["question"]),
            **_arms({**case["ticket"], "case_id": case["case_id"]},
                    _week6_live()["index"], arms)}


# ---------------------------------------------------------------- A2A
#
#   GET  /api/a2a/policy-worker/.well-known/agent.json   the worker's AgentCard
#   POST /api/a2a/policy-worker                           JSON-RPC 2.0 (message/send,
#                                                         tasks/get, tasks/cancel)
#   POST /api/w10/a2a/run      {case_id, inject_500}  the orchestrator's ticket task
#   POST /api/w10/a2a/resume   {task_id, decision}    the ticket owner's answer

_A2A: dict = {}


def _a2a():
    if not _A2A:
        from .main import _week6_live

        _race()
        from week10 import a2a

        index = _week6_live()["index"]
        worker = a2a.PolicyWorker(index)
        _A2A.update(mod=a2a, worker=worker, orch=a2a.Orchestrator(worker.handle, index))
    return _A2A


@router.get("/api/a2a/policy-worker/.well-known/agent.json")
def worker_card() -> dict:
    return _a2a()["worker"].card()


@router.post("/api/a2a/policy-worker")
def worker_rpc(rpc: dict) -> dict:
    return _a2a()["worker"].handle(rpc)


class A2ARun(BaseModel):
    case_id: str
    inject_500: bool = False


def _a2a_out(task: dict) -> dict:
    a = _a2a()
    ctx = a["orch"]._ctx.get(task["id"], {})
    return {"task": a["mod"].view(task),
            "worker_tasks": [{"id": w["id"], "state": w["status"]["state"],
                              "transitions": w["transitions"]}
                             for w in ctx.get("worker_tasks", [])],
            "rpc": a["orch"].calls[-1] if a["orch"].calls else None}


@router.post("/api/w10/a2a/run")
def a2a_run(req: A2ARun) -> dict:
    race = _race()
    cases = {c["case_id"]: c for c in race.load_cases()}
    if req.case_id not in cases:
        raise HTTPException(404, "unknown case")
    return _a2a_out(_a2a()["orch"].start(cases[req.case_id]["ticket"], req.inject_500))


class A2AResume(BaseModel):
    task_id: str
    decision: str


@router.post("/api/w10/a2a/resume")
def a2a_resume(req: A2AResume) -> dict:
    try:
        return _a2a_out(_a2a()["orch"].resume(req.task_id, req.decision))
    except KeyError:
        raise HTTPException(404, "no such task")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
