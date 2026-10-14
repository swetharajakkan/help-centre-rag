"""Server two: ticket-history MCP server (written by Support Ops, not by us).

This is the third-party server in the Week 9 Task Set A brief. It exposes the
ticket record behind an id and the escalation history behind that ticket. It is
deliberately a separate process with its own auth, its own data and its own
log, so the agent reaches it exactly the way it would reach a remote vendor
server: over HTTP, with a bearer token, and nothing shared but the protocol.

    # remote (the way the agent config uses it)
    TICKET_HISTORY_TOKENS='{"dev-ticket-token": {"client_id": "help-centre-agent",
                            "scopes": ["tickets:read", "tickets:escalations"]}}' \\
    .venv/bin/python week9/servers/ticket_history/server.py --transport http --port 8765

    # local stdio (no auth: stdio trusts whoever spawned it)
    .venv/bin/python week9/servers/ticket_history/server.py --transport stdio

What it exposes, and why each primitive is the primitive it is:

  tool      get_ticket(ticket_id)              model-invoked lookup by id
  tool      get_escalation_history(ticket_id)  Support Ops ship it as a tool too
  resource  tickets://{ticket_id}/escalations  the same history, app-attached
  prompt    handover_note(ticket_id)           a user-picked template

Our host attaches the resource when a ticket id is in the user's message (see
week9/mcp_config.json "attach"), so the model normally never has to spend a
turn calling get_escalation_history. The tool stays for callers that do not
attach context -- and is the one the bonus gateway denies by token scope.

No model runs in here. The server returns records; the host runs the model.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "tickets.json")
# Support Ops log every call, arguments included, to a file next to the
# server. The risk note (week9/risk_note.md) is about exactly this.
ACCESS_LOG = os.environ.get("TICKET_HISTORY_LOG", os.path.join(HERE, "access.log"))

TICKET_ID = re.compile(r"^TCK-\d{4}$")

with open(DATA) as fh:
    TICKETS: dict[str, dict] = json.load(fh)


def _caller() -> str:
    """The authenticated client id, or 'stdio' when there is no HTTP auth."""
    try:
        from fastmcp.server.dependencies import get_access_token
        tok = get_access_token()
        return tok.client_id if tok else "stdio"
    except Exception:
        return "stdio"


def _log(tool: str, args: dict, outcome: str) -> None:
    line = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "caller": _caller(), "tool": tool, "args": args, "outcome": outcome}
    try:
        with open(ACCESS_LOG, "a") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        pass


def _lookup(ticket_id: str, tool: str) -> dict:
    """Shared not-found handling. The error says which of the two failures it
    is -- a malformed id or an id that does not exist -- so the caller can tell
    them apart from a dead server and not resend the same call."""
    tid = (ticket_id or "").strip().upper()
    if not TICKET_ID.match(tid):
        _log(tool, {"ticket_id": ticket_id}, "malformed")
        raise ToolError(
            f"ticket id {ticket_id!r} is malformed: ticket ids look like "
            "TCK-nnnn (TCK- then four digits, e.g. TCK-4401). Re-read the id "
            "from the customer's message; do not retry this exact value.")
    t = TICKETS.get(tid)
    if t is None:
        _log(tool, {"ticket_id": tid}, "not_found")
        raise ToolError(
            f"ticket {tid} not found: the id is well-formed but no ticket has "
            "it. Ask the customer to confirm the id; retrying will not help.")
    _log(tool, {"ticket_id": tid}, "ok")
    return copy.deepcopy(t) | {"ticket_id": tid}


mcp = FastMCP(
    name="ticket-history",
    version="1.3.0",
    instructions=("Support Ops ticket history. Look tickets up by id "
                  "(TCK-nnnn). Records are read-only."),
)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_ticket(ticket_id: str) -> dict:
    """Fetch one support ticket by id: subject, status, priority, product area,
    the customer's own message and how many times it was escalated.

    Use it whenever the user names a ticket id (ids look like TCK-nnnn, e.g.
    TCK-4403). It does not search: if you only have a description of the
    problem, do not guess an id.
    """
    t = _lookup(ticket_id, "get_ticket")
    escalations = t.pop("escalations")
    t["escalation_count"] = len(escalations)
    t["latest_escalation"] = escalations[-1] if escalations else None
    return t


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_escalation_history(ticket_id: str) -> dict:
    """Every escalation behind a ticket (TCK-nnnn), oldest first: when, from
    which tier to which, who moved it and why.

    The host usually attaches this as context already (resource
    tickets://{ticket_id}/escalations); only call it when that context is not
    in the conversation.
    """
    t = _lookup(ticket_id, "get_escalation_history")
    return {"ticket_id": t["ticket_id"], "status": t["status"],
            "escalations": t["escalations"]}


@mcp.resource("tickets://{ticket_id}/escalations", mime_type="application/json",
              description="Escalation history for one ticket, for the host to "
                          "attach as context (app-controlled, not model-invoked).")
def escalations_resource(ticket_id: str) -> str:
    try:
        t = _lookup(ticket_id, "resource:escalations")
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc
    return json.dumps({"ticket_id": t["ticket_id"], "status": t["status"],
                       "escalations": t["escalations"]}, indent=1)


@mcp.prompt
def handover_note(ticket_id: str) -> str:
    """Shift-handover template for one ticket (user-selected, not automatic)."""
    return (f"Write a shift-handover note for {ticket_id}: current status, who "
            "holds it now, what the customer is waiting for, and the next "
            "action. Use only the ticket record and its escalation history.")


def _auth():
    """Bearer-token auth for the HTTP transport. Tokens and their scopes come
    from TICKET_HISTORY_TOKENS (JSON); the default is one local dev token."""
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    raw = os.environ.get("TICKET_HISTORY_TOKENS") or json.dumps({
        os.environ.get("TICKET_HISTORY_TOKEN", "dev-ticket-token"): {
            "client_id": "help-centre-agent",
            "scopes": ["tickets:read", "tickets:escalations"]}})
    return StaticTokenVerifier(tokens=json.loads(raw), required_scopes=["tickets:read"])


def build(transport: str) -> FastMCP:
    if transport == "http":
        mcp.auth = _auth()
    return mcp


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    server = build(a.transport)
    if a.transport == "http":
        server.run(transport="http", host=a.host, port=a.port, path="/mcp",
                   show_banner=False)
    else:
        server.run(transport="stdio", show_banner=False)
