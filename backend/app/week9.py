"""Week 9 in the app: the MCP crew behind the chat, and the admin MCP view.

One long-lived MCP host per backend process. It is owned by a background task
(connect -> wait -> close all in the same task, which is what anyio wants);
requests borrow it. A server that failed to connect is retried on the next
request after RETRY_S, so starting the ticket-history server after the
backend is fine.

  POST /api/w9/ask   user + admin. Responder + Verifier answer one question.
                     A user gets the answer and whether it was verified; an
                     admin also gets the full trace.
  GET  /api/week9    admin. tools/list per server, config, evidence files.
  POST /api/week9/reconnect  admin. Re-run discovery now.
  GET  /api/w9/questions     user + admin. Quick questions by week (text only).
  GET  /api/track[/{id}]     admin. Every question asked, and what the agents did.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import track

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

EVIDENCE = os.path.join(ROOT, "week9", "evidence")
RETRY_S = 30

router = APIRouter()


class _HostOwner:
    def __init__(self):
        self.host = None
        self.task: asyncio.Task | None = None
        self.stop: asyncio.Event | None = None
        self.ready: asyncio.Event | None = None
        self.started_at = 0.0
        self.lock = asyncio.Lock()

    async def _own(self):
        from week9.agent.host import Host

        try:
            async with Host() as h:
                self.host = h
                self.ready.set()
                await self.stop.wait()
        finally:
            self.host = None
            self.ready.set()

    async def get(self, force: bool = False):
        async with self.lock:
            stale = self.host is not None and any(
                c.error for c in self.host.conns.values()) and time.time() - self.started_at > RETRY_S
            if force or stale:
                await self.close()
            if self.host is None:
                self.stop, self.ready = asyncio.Event(), asyncio.Event()
                self.started_at = time.time()
                self.task = asyncio.create_task(self._own())
                await self.ready.wait()
            if self.host is None:
                raise HTTPException(503, "MCP host failed to start")
            return self.host

    async def close(self):
        if self.task:
            self.stop.set()
            try:
                await asyncio.wait_for(self.task, 10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001 -- shutting down
                self.task.cancel()
            self.task, self.host = None, None


OWNER = _HostOwner()


async def shutdown() -> None:
    await OWNER.close()


def _model():
    from week9.agent.model import default_model

    return default_model()


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


def _public(r: dict) -> dict:
    """What a `user` sees: the reply and whether it passed verification."""
    claims = r["rounds"][-1]["draft"].get("claims", []) if r["approved"] and r["rounds"] else []
    return {"answer": r["answer"], "kind": r["kind"], "approved": r["approved"],
            "verified_claims": r["verified_claims"], "rounds": len(r["rounds"]),
            "sources": sorted({c.get("source_id") for c in claims if c.get("source_id")}),
            "ms": r["ms"]}


@router.post("/api/w9/ask")
async def ask(req: Ask, request: Request) -> dict:
    from week9.agent import crew

    who = getattr(request.state, "user", None) or {}
    question = req.question.strip()
    t0 = time.perf_counter()
    try:
        host = await OWNER.get()
        r = await crew.run_crew(host, _model(), question)
    except Exception as exc:
        # A failed question is tracked too: that is when an admin most needs it.
        track.append(track.build(who, question, error=f"{type(exc).__name__}: {exc}"[:500],
                                 ms=round((time.perf_counter() - t0) * 1000, 1)))
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, "the agent failed on this question") from exc
    rec = track.build(who, question, r)
    track.append(rec)
    out = {**_public(r), "track_id": rec["id"]}
    if who.get("role") == "admin":
        return {**out, "full": r, "discovery": host.discovery()}
    return out


@router.get("/api/w9/questions")
def questions() -> dict:
    """The quick questions, by week, for the user's screen: text only, no
    labels, answer keys or traces."""
    from . import main

    ex = main.examples()
    plain = lambda xs: [{"id": x.get("id"), "question": x.get("question")}  # noqa: E731
                        for x in xs or [] if x.get("question")]
    groups = {"golden": plain(ex.get("examples")), "week5": plain(ex.get("sampled")),
              "week6": plain(ex.get("week6")), "week7": plain(ex.get("week7")),
              "week8": plain(ex.get("week8"))}
    return {"groups": groups}


@router.get("/api/track")
def track_list(limit: int = 200, role: str | None = None) -> dict:
    return track.recent(limit=max(1, min(limit, 1000)), role=role or None)


@router.get("/api/track/{rec_id}")
def track_get(rec_id: str) -> dict:
    rec = track.get(rec_id)
    if rec is None:
        raise HTTPException(404, "no such track record")
    return rec


def _read(name: str) -> str | None:
    p = os.path.join(EVIDENCE, name)
    return open(p).read() if os.path.exists(p) else None


@router.get("/api/week9")
async def overview() -> dict:
    host = await OWNER.get()
    with open(host.cfg["path"]) as fh:
        config_text = fh.read()
    model = _model()
    audit = _read("gateway_audit.log")
    return {"discovery": host.discovery(), "config_text": config_text,
            "model": getattr(model, "name", "?"),
            "evidence": {n: _read(n) for n in (
                "tool_counts.txt", "agent_diff.txt", "config_diff.txt",
                "error_before_after.md", "bonus_gateway.md")},
            "wire": _read("wire.json"),
            "risk_note": open(os.path.join(ROOT, "week9", "risk_note.md")).read()
            if os.path.exists(os.path.join(ROOT, "week9", "risk_note.md")) else None,
            "audit_tail": audit.splitlines()[-20:] if audit else []}


@router.post("/api/week9/reconnect")
async def reconnect() -> dict:
    host = await OWNER.get(force=True)
    return host.discovery()
