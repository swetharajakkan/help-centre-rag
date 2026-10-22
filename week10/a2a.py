"""The policy-lookup worker behind A2A, and an orchestrator that talks to it.

The race (race.py) calls the policy worker as a Python function, so when it
raised a 500 the orchestrator caught the exception and carried on: nothing in
the call shape forced it to say anything had gone wrong. Here the same worker
is reached over A2A instead, and the difference is the point:

  * the worker publishes an AgentCard (what it does, what it accepts, auth);
  * every request becomes a Task with a state, moved through the A2A task
    lifecycle  submitted -> working -> completed | failed | input-required;
  * the orchestrator's own ticket is a Task too, so when its worker's task
    ends `failed` the ticket goes to `input-required` and waits for the
    ticket owner (retry / route to Billing Review / reply by hand) instead
    of shipping a reply.

Wire format: JSON-RPC 2.0 with the A2A method names (message/send,
tasks/get, tasks/cancel), Message/Part/Task/Artifact objects shaped as the
A2A spec shapes them. The HTTP routes in backend/app/week10.py are a thin
shell over `PolicyWorker.handle`, so the in-process client used here and an
HTTP client get the same bytes back.
"""
from __future__ import annotations

import json
import time
import uuid

from . import race

TERMINAL = {"completed", "failed", "canceled", "rejected"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"


def _msg(role: str, *, text: str | None = None, data=None, task_id=None, context_id=None) -> dict:
    parts = []
    if text is not None:
        parts.append({"kind": "text", "text": text})
    if data is not None:
        parts.append({"kind": "data", "data": data})
    return {"kind": "message", "role": role, "messageId": uuid.uuid4().hex,
            "parts": parts, "taskId": task_id, "contextId": context_id}


class TaskStore:
    """Tasks plus every state transition, so the lifecycle can be shown."""

    def __init__(self):
        self.tasks: dict[str, dict] = {}

    def create(self, context_id: str | None, first: dict) -> dict:
        tid = uuid.uuid4().hex[:12]
        task = {"kind": "task", "id": tid, "contextId": context_id or uuid.uuid4().hex[:12],
                "status": {"state": "submitted", "timestamp": _now()},
                "history": [first], "artifacts": [], "transitions": []}
        task["transitions"].append({"state": "submitted", "at": task["status"]["timestamp"],
                                    "note": None})
        self.tasks[tid] = task
        return task

    def move(self, task: dict, state: str, note: str | None = None, message: dict | None = None):
        if task["status"]["state"] in TERMINAL:
            raise ValueError(f"task {task['id']} is already {task['status']['state']}")
        task["status"] = {"state": state, "timestamp": _now()}
        if message:
            task["status"]["message"] = message
            task["history"].append(message)
        task["transitions"].append({"state": state, "at": task["status"]["timestamp"], "note": note})


# ------------------------------------------------------------------ worker

class PolicyWorker:
    """The policy-lookup worker as an A2A server."""

    def __init__(self, index, url: str = "/api/a2a/policy-worker"):
        self.index, self.url = index, url
        self.store = TaskStore()

    def card(self) -> dict:
        return {
            "name": "Policy-lookup worker",
            "description": "Finds the help-centre fix for a triaged billing ticket and "
                           "applies support policy SP-001. Returns {answered, claims, refusal}.",
            "url": self.url, "version": "0.10.0", "protocolVersion": "0.3.0",
            "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": False, "pushNotifications": False,
                             "stateTransitionHistory": True},
            "securitySchemes": {"session": {"type": "apiKey", "in": "cookie",
                                            "name": "hc_session"}},
            "security": [{"session": []}],
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [{"id": "policy-lookup", "name": "Policy lookup",
                        "description": "Input: {ticket, triage}. Output: {answered, claims, refusal}.",
                        "tags": ["support", "policy", "retrieval"],
                        "inputModes": ["application/json"], "outputModes": ["application/json"]}],
        }

    def handle(self, rpc: dict) -> dict:
        """One JSON-RPC 2.0 request -> one response."""
        rid, method, params = rpc.get("id"), rpc.get("method"), rpc.get("params") or {}
        try:
            if method == "message/send":
                result = self._send(params)
            elif method == "tasks/get":
                result = self._get(params["id"])
            elif method == "tasks/cancel":
                task = self._get(params["id"])
                self.store.move(task, "canceled", "canceled by caller")
                result = task
            else:
                return {"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32601, "message": f"method not found: {method}"}}
        except KeyError as exc:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32001, "message": f"task not found: {exc}"}}
        except ValueError as exc:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32002, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _get(self, tid: str) -> dict:
        return self.store.tasks[tid]

    def _send(self, params: dict) -> dict:
        msg = params["message"]
        data = next(p["data"] for p in msg["parts"] if p.get("kind") == "data")
        task = self.store.create(msg.get("contextId"), msg)
        self.store.move(task, "working")
        if (params.get("metadata") or {}).get("inject_500"):
            # Same injected fault as the race: the worker's backend dies.
            self.store.move(task, "failed", "HTTP 500 from the policy-lookup backend",
                            _msg("agent", text="policy-lookup worker: internal server error (500)",
                                 task_id=task["id"], context_id=task["contextId"]))
            return task
        res, _chunks = race._search(self.index, data["ticket"])
        out = race._final(res)
        task["artifacts"].append({"artifactId": uuid.uuid4().hex[:12], "name": "policy_lookup",
                                  "parts": [{"kind": "data", "data": out}]})
        self.store.move(task, "completed")
        return task


# ------------------------------------------------------------ orchestrator

class Orchestrator:
    """The squad's orchestrator, exposing its own ticket as an A2A task."""

    def __init__(self, worker_rpc, index):
        self.rpc, self.index = worker_rpc, index      # rpc: dict -> dict (JSON-RPC)
        self.store = TaskStore()
        self.calls: list[dict] = []                   # every JSON-RPC exchange
        self._ctx: dict[str, dict] = {}

    def _call(self, method: str, params: dict) -> dict:
        req = {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:8], "method": method, "params": params}
        resp = self.rpc(req)
        self.calls.append({"request": req, "response": resp})
        if "error" in resp:
            raise RuntimeError(resp["error"]["message"])
        return resp["result"]

    def start(self, ticket: dict, inject_500: bool = False) -> dict:
        task = self.store.create(None, _msg("user", data={"ticket": ticket}))
        self._ctx[task["id"]] = {"ticket": ticket, "triage": race._triage(ticket),
                                 "worker_tasks": []}
        self.store.move(task, "working", "triage done; delegating policy lookup over A2A")
        return self._delegate(task, inject_500)

    def _delegate(self, task: dict, inject_500: bool) -> dict:
        ctx = self._ctx[task["id"]]
        send = _msg("user", data={"ticket": ctx["ticket"], "triage": ctx["triage"]},
                    context_id=task["contextId"])
        wt = self._call("message/send", {"message": send,
                                         "metadata": {"inject_500": inject_500}})
        ctx["worker_tasks"].append(wt)
        state = wt["status"]["state"]
        if state == "completed":
            out = wt["artifacts"][0]["parts"][0]["data"]
            reply = race.render(ctx["ticket"], out["answered"], out["claims"], out["refusal"])
            task["artifacts"].append({"artifactId": uuid.uuid4().hex[:12], "name": "draft_reply",
                                      "parts": [{"kind": "text", "text": reply}]})
            self.store.move(task, "completed", "worker completed; reply synthesised")
        else:
            why = (wt["status"].get("message") or {}).get("parts", [{}])[0].get("text", state)
            self.store.move(
                task, "input-required", f"worker task {wt['id']} {state}: {why}",
                _msg("agent", task_id=task["id"], context_id=task["contextId"],
                     text=f"Policy lookup {state} ({why}). No reply was drafted. "
                          "Ticket owner: reply 'retry', 'billing_review' or 'manual'."))
        return task

    def resume(self, task_id: str, decision: str) -> dict:
        """The ticket owner answers an input-required task (same taskId)."""
        task = self.store.tasks[task_id]
        if task["status"]["state"] != "input-required":
            raise ValueError(f"task is {task['status']['state']}, not input-required")
        task["history"].append(_msg("user", text=decision, task_id=task_id,
                                    context_id=task["contextId"]))
        if decision == "retry":
            self.store.move(task, "working", "owner chose retry")
            return self._delegate(task, inject_500=False)
        note = {"billing_review": "routed to Billing Review by the ticket owner",
                "manual": "ticket owner will reply by hand"}.get(decision)
        if note is None:
            raise ValueError(f"unknown decision {decision!r}")
        self.store.move(task, "completed", note)
        return task


def view(task: dict) -> dict:
    """The task as the UI shows it."""
    reply = next((p["text"] for a in task["artifacts"] for p in a["parts"]
                  if p.get("kind") == "text"), None)
    ask = (task["status"].get("message") or {}).get("parts", [{}])[0].get("text")
    return {"id": task["id"], "state": task["status"]["state"],
            "transitions": task["transitions"], "reply": reply,
            "question_for_owner": ask if task["status"]["state"] == "input-required" else None}


def main() -> None:
    """Write week10/a2a_trace.json: healthy, failed, and failed-then-retried."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    cases = {c["case_id"]: c for c in race.load_cases()}
    index = race.D.build_index_with_policy()
    worker = PolicyWorker(index)
    orch = Orchestrator(worker.handle, index)
    t = cases[race.FAIL_CASE]["ticket"]
    healthy = orch.start(t)
    failed = orch.start(t, inject_500=True)
    failed_view = json.loads(json.dumps(view(failed)))
    retried = orch.resume(failed["id"], "retry")
    out = {"card": worker.card(), "case_id": race.FAIL_CASE,
           "healthy": view(healthy), "failed": failed_view, "after_retry": view(retried),
           "worker_tasks": [{"id": w["id"], "state": w["status"]["state"],
                             "transitions": w["transitions"]}
                            for w in worker.store.tasks.values()],
           "rpc_sample": orch.calls[1]}
    json.dump(out, open(os.path.join(here, "a2a_trace.json"), "w"), indent=1)
    for k in ("healthy", "failed", "after_retry"):
        print(f"{k:12} " + " -> ".join(x["state"] for x in out[k]["transitions"]))


if __name__ == "__main__":
    main()
