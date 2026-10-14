"""Two agents on one task: a Responder writes the answer, a Verifier checks it.

  Responder  loop.run_agent: discovers tools, calls them, drafts JSON claims.
  Verifier   independent of the Responder's trace. For every claim it routes
             the cited source id to a lookup tool by itself, RE-FETCHES the
             record over MCP, and checks
               - the quote is verbatim in the re-fetched record,
               - every stated field ("facts") equals the record's value,
               - every number in the claim text appears in the record,
             and, when Claude is available, asks a second model call whether
             the quote actually supports the claim.
  Supervisor this function. Approved -> ship. Rejected -> one revision round
             with the Verifier's reasons (Claude rewrites; offline, the
             failing claims are dropped). Still rejected -> refuse and hand
             to a human rather than ship an unverified answer.

The Verifier deliberately does not trust the Responder's tool results: a
Responder that mis-copied a figure from a correct tool result, or invented
one, is exactly what it exists to catch.
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from . import loop, smalltalk
from .model import ClaudeModel, id_param, route_id

NUM = re.compile(r"\d+(?:\.\d+)?")
WS = re.compile(r"\s+")

VERIFY_SYSTEM = """\
You are the Verifier. Given a claim and the source text it cites, decide if
the source supports the claim exactly (same figures, same status, nothing
added). Reply with ONLY {"supported": true|false, "reason": "<short>"}."""


def _norm(s: str) -> str:
    return WS.sub(" ", str(s)).strip().lower()


def _strings(obj) -> list[str]:
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return [str(obj)]


class Verifier:
    def __init__(self, host, model=None):
        self.host, self.model = host, model
        self._cache: dict[str, dict] = {}
        self.calls: list[dict] = []        # every re-fetch, for the admin track view

    async def evidence(self, source_id: str) -> dict:
        """Re-fetch the cited record through a lookup tool of the Verifier's
        own choosing (routed from tools/list, like any other caller)."""
        sid = (source_id or "").strip().upper()
        if sid in self._cache:
            return self._cache[sid]
        tools = self.host.tool_specs()
        ranked = route_id(sid, tools)
        ev = {"source_id": sid, "ok": False, "via": None, "record": None, "text": ""}
        if ranked:
            t = ranked[0][1]
            out = await self.host.call_tool(t["name"], {id_param(t): sid})
            self.calls.append({k: out[k] for k in ("qualified", "server", "tool", "args",
                                                   "is_error", "ms")})
            ev["via"] = t["name"]
            if not out["is_error"]:
                try:
                    rec = json.loads(out["text"])
                except ValueError:
                    rec = {"text": out["text"]}
                ev |= {"ok": True, "record": rec, "text": " ".join(_strings(rec))}
            else:
                ev["error"] = out["text"]
        # Attached resources for the same id count as evidence too.
        for ctx in await self.host.attach(sid):
            self.calls.append({"resource": ctx["uri"], "server": ctx["server"],
                               "is_error": not ctx["ok"]})
            if ctx["ok"]:
                ev["text"] += " " + ctx["text"] + " " + " ".join(_strings(_loads(ctx["text"])))
                ev["ok"] = True
        self._cache[sid] = ev
        return ev

    async def check(self, claim: dict) -> dict:
        reasons = []
        ev = await self.evidence(claim.get("source_id", ""))
        hay = _norm(ev["text"])
        if not ev["ok"]:
            reasons.append(f"could not re-fetch {claim.get('source_id')!r}"
                           + (f": {ev.get('error')}" if ev.get("error") else ""))
        else:
            q = _norm(claim.get("quote", ""))
            if not q:
                reasons.append("no quote given")
            elif q not in hay:
                reasons.append("quote is not verbatim in the re-fetched source")
            rec = ev["record"] or {}
            for k, v in (claim.get("facts") or {}).items():
                if k in rec and _norm(rec[k]) != _norm(v):
                    reasons.append(f"{k} is {rec[k]!r} in the source, claim says {v!r}")
            # Whole numbers, not substrings: "7" must not pass because a date
            # in the source happens to contain a 7.
            known = {x.lstrip("0") or "0" for x in NUM.findall(hay + " " + claim.get("source_id", ""))}
            for n in NUM.findall(claim.get("text", "")):
                if (n.lstrip("0") or "0") not in known:
                    reasons.append(f"figure {n} does not appear in the source")
        semantic = None
        if not reasons and isinstance(self.model, ClaudeModel):
            semantic = await asyncio.to_thread(self._semantic, claim, ev["text"][:6000])
            if semantic and not semantic.get("supported", True):
                reasons.append(f"semantic: {semantic.get('reason')}")
        return {"claim": claim, "ok": not reasons, "reasons": reasons,
                "refetched_via": ev["via"], "semantic": semantic}

    def _semantic(self, claim: dict, source: str) -> dict | None:
        msg = json.dumps({"claim": claim.get("text"), "source": source})
        r = self.model.complete(VERIFY_SYSTEM, [{"role": "user", "content": msg}], [])
        text = "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")
        try:
            return json.loads(text[text.find("{"): text.rfind("}") + 1])
        except ValueError:
            return None

    async def verify(self, draft: dict) -> dict:
        claims = draft.get("claims") or []
        if not claims:
            ok = draft.get("kind") == "refusal"
            return {"approved": ok, "checks": [],
                    "summary": "refusal: nothing asserted" if ok
                    else "rejected: the answer makes no cited claims"}
        checks = [await self.check(c) for c in claims]
        passed = sum(c["ok"] for c in checks)
        return {"approved": passed == len(checks), "checks": checks,
                "summary": f"{passed}/{len(checks)} claims verified"}


def _loads(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return {}


def _prune(draft: dict, verdict: dict) -> dict:
    keep = [c["claim"] for c in verdict["checks"] if c["ok"]]
    if not keep:
        return {"kind": "refusal", "claims": [],
                "answer": "I couldn't verify an answer from the connected sources, so I've "
                          "passed this to a human colleague."}
    return {"kind": "answer", "claims": keep,
            "answer": " ".join(f"{c['text']} [{c['source_id']}]" for c in keep)}


def _smalltalk_result(question: str, talk: dict, t0: float, model) -> dict:
    """A message that was only small talk: answered by the router, no tools."""
    return {"question": question, "answer": talk["reply"], "kind": "smalltalk",
            "approved": True, "verified_claims": 0, "rounds": [],
            "responder": {"steps": [], "context": [], "model_turns": 0, "tool_calls": [],
                          "tool_errors": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0},
            "agents": {"Router": {"runs": 1, "kind": talk["kind"]}},
            "model": getattr(model, "name", "?"),
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


async def run_crew(host, model, question: str, max_rounds: int = 2) -> dict:
    t0 = time.perf_counter()
    talk = smalltalk.classify(question)
    if talk and talk["rest"] is None:
        return _smalltalk_result(question, talk, t0, model)
    greeting = ""
    if talk:                       # "hi, <real question>": answer the question
        greeting, question = talk["reply"], talk["rest"]
    resp = await loop.run_agent(host, model, question)
    verifier = Verifier(host, model)
    draft, rounds, responder_runs = resp["final"], [], 1
    for rnd in range(1, max_rounds + 1):
        verdict = await verifier.verify(draft)
        rounds.append({"round": rnd, "draft": draft, "verdict": verdict})
        if verdict["approved"] or rnd == max_rounds:
            break
        if isinstance(model, ClaudeModel):
            feedback = "Verifier rejected your answer:\n" + "\n".join(
                f"- claim {i + 1}: {'; '.join(c['reasons'])}"
                for i, c in enumerate(verdict["checks"]) if not c["ok"]) + \
                "\nRewrite the JSON keeping only claims the sources support verbatim."
            msgs = resp["messages"] + [{"role": "user", "content": feedback}]
            again = await loop.run_agent(host, model, question, messages=msgs, max_turns=4)
            resp["steps"] += again["steps"]
            responder_runs += 1
            draft = again["final"]
        else:
            draft = _prune(draft, verdict)
    last = rounds[-1]
    approved = last["verdict"]["approved"]
    final = last["draft"] if approved else _prune(last["draft"], last["verdict"])
    if not approved and final["kind"] == "answer":
        # Round budget spent: ship only what passed, and say it was trimmed.
        final["answer"] += " (Some statements were removed because they could not be verified.)"
    return {"question": question, "answer": greeting + final["answer"], "kind": final["kind"],
            "approved": approved, "verified_claims": len(final.get("claims", [])),
            "rounds": rounds, "responder": {k: resp[k] for k in (
                "steps", "context", "model_turns", "tool_calls", "tool_errors",
                "tokens_in", "tokens_out", "cost_usd")},
            "agents": {**({"Router": {"runs": 1, "kind": talk["kind"]}} if talk else {}),
                       "Responder": {"runs": responder_runs},
                       "Verifier": {"runs": len(rounds), "calls": verifier.calls}},
            "model": getattr(model, "name", "?"),
            "ms": round((time.perf_counter() - t0) * 1000, 1)}
