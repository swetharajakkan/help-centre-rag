"""The admin's Track view: one record per question asked through /api/w9/ask.

Each record says who asked what, what the host attached, every tools/call
the Responder made (server, tool, arguments, result, timing), every record the
Verifier re-fetched, each claim's verdict, and the answer the asker saw.

Records are appended to a JSONL file (HELP_CENTRE_TRACK_LOG, default
backend/data/track.jsonl) so they survive a restart. It holds the users'
own questions, so it is gitignored and only readable by `admin`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import uuid

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "track.jsonl")
_LOCK = threading.Lock()
RESULT_CHARS = 1500        # tool results are trimmed; the full text is on the server


def path() -> str:
    return os.environ.get("HELP_CENTRE_TRACK_LOG") or DEFAULT_PATH


def _step(s: dict) -> dict:
    if s["kind"] == "model":
        return {k: s.get(k) for k in ("kind", "turn", "model", "stop_reason", "tool_uses",
                                      "input_tokens", "output_tokens")}
    return {**{k: s.get(k) for k in ("kind", "turn", "qualified", "server", "tool", "args",
                                     "is_error", "ms")},
            "result": (s.get("text") or "")[:RESULT_CHARS]}


def build(who: dict | None, question: str, run: dict | None = None,
          error: str | None = None, ms: float | None = None) -> dict:
    who = who or {}
    rec = {"id": uuid.uuid4().hex[:12],
           "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "username": who.get("username", "anonymous"), "role": who.get("role", "?"),
           "question": question, "error": error}
    if run is None:
        return rec | {"answer": None, "kind": "error", "approved": False, "ms": ms,
                      "agents": [], "steps": [], "context": [], "rounds": [],
                      "tools_called": []}
    r = run["responder"]
    tool_steps = [s for s in r["steps"] if s["kind"] == "tool"]
    v = run.get("agents", {}).get("Verifier", {})
    rounds = [{"round": x["round"], "approved": x["verdict"]["approved"],
               "summary": x["verdict"]["summary"],
               "checks": [{"text": c["claim"].get("text"), "source_id": c["claim"].get("source_id"),
                           "quote": c["claim"].get("quote"), "ok": c["ok"],
                           "reasons": c["reasons"], "refetched_via": c["refetched_via"]}
                          for c in x["verdict"]["checks"]]}
              for x in run["rounds"]]
    return rec | {
        "answer": run["answer"], "kind": run["kind"], "approved": run["approved"],
        "verified_claims": run["verified_claims"], "model": run["model"], "ms": run["ms"],
        "context": [c["uri"] for c in r["context"]],
        "agents": ([{"name": "Router", "runs": 1,
                     "did": (f"recognised small talk ({run['agents']['Router']['kind']}) and "
                             "replied directly: no tools, nothing to verify")
                     if run["kind"] == "smalltalk" else
                     "peeled the greeting off and passed the question on"}]
                   if "Router" in run.get("agents", {}) else []) + ([] if run["kind"] == "smalltalk" else [
            {"name": "Responder", "runs": run.get("agents", {}).get("Responder", {}).get("runs", 1),
             "did": f"{r['model_turns']} model turns, {len(tool_steps)} tools/call "
                    f"({r['tool_errors']} failed)",
             "tokens": r["tokens_in"] + r["tokens_out"]},
            {"name": "Verifier", "runs": v.get("runs", len(rounds)),
             "did": "; ".join(x["summary"] for x in rounds),
             "calls": v.get("calls", [])},
        ]),
        "steps": [_step(s) for s in r["steps"]],
        "tools_called": list(dict.fromkeys(s["qualified"] for s in tool_steps)),
        "rounds": rounds,
    }


def append(rec: dict) -> None:
    p = path()
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with _LOCK, open(p, "a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def _all() -> list[dict]:
    p = path()
    if not os.path.exists(p):
        return []
    with _LOCK, open(p) as fh:
        out = []
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue                      # a torn last line must not hide the rest
        return out


def summary(rec: dict) -> dict:
    return {k: rec.get(k) for k in ("id", "ts", "username", "role", "question", "kind",
                                    "approved", "verified_claims", "ms", "error",
                                    "tools_called")} | {
        "n_tool_calls": sum(1 for s in rec.get("steps", []) if s["kind"] == "tool"),
        "n_agents": len(rec.get("agents", [])),
        "agent_runs": sum(a.get("runs", 1) for a in rec.get("agents", []))}


def recent(limit: int = 200, role: str | None = None) -> dict:
    recs = _all()
    if role:
        recs = [r for r in recs if r.get("role") == role]
    return {"total": len(recs), "items": [summary(r) for r in reversed(recs[-limit:])]}


def get(rec_id: str) -> dict | None:
    return next((r for r in _all() if r.get("id") == rec_id), None)
