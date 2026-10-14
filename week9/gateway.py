"""Bonus: one front door for both servers, with an audit line and token scopes.

    .venv/bin/python week9/gateway.py --port 8766

The agent connects to this one HTTP endpoint (week9/mcp_config.gateway.json).
The gateway is itself an MCP server that proxies to every upstream listed in
week9/mcp_config.json -- the same config the agent uses directly -- and mounts
each under its server name, so tools arrive as e.g.
"ticket-history_get_escalation_history".

Two things happen on every request, in ScopeAndAudit below:

  scope   The caller's bearer token carries scopes. A tool or resource needs
          one (SCOPES); a token without it gets a RECOVERABLE denial -- a tool
          error the model can read, naming what it may do instead -- rather
          than a transport failure it would retry.
  audit   Every tools/call (and every escalation resource read) appends one
          JSON line to week9/evidence/gateway_audit.log: ts, caller, tool,
          ticket id, outcome.

Tokens (GATEWAY_TOKENS, JSON; default below):
  agent-full             kb:read tickets:read tickets:escalations
  agent-no-escalations   kb:read tickets:read
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from fastmcp import FastMCP  # noqa: E402
from fastmcp.client.transports import StreamableHttpTransport  # noqa: E402
from fastmcp.exceptions import ResourceError, ToolError  # noqa: E402
from fastmcp.server import create_proxy  # noqa: E402
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier  # noqa: E402
from fastmcp.server.dependencies import get_access_token  # noqa: E402
from fastmcp.server.middleware import Middleware  # noqa: E402

from week9.agent import config as agent_config  # noqa: E402
from week9.agent.host import _transport  # noqa: E402

AUDIT_LOG = os.environ.get("GATEWAY_AUDIT_LOG",
                           os.path.join(ROOT, "week9", "evidence", "gateway_audit.log"))
TICKET = re.compile(r"TCK-\d{4}", re.I)

DEFAULT_TOKENS = {
    "agent-full": {"client_id": "help-centre-agent",
                   "scopes": ["kb:read", "tickets:read", "tickets:escalations"]},
    "agent-no-escalations": {"client_id": "help-centre-agent-restricted",
                             "scopes": ["kb:read", "tickets:read"]},
}

# Most specific first: the escalation history needs its own scope.
SCOPES = [("escalation", "tickets:escalations"), ("ticket-history", "tickets:read"),
          ("help-centre-rag", "kb:read")]


def required_scope(name: str) -> str | None:
    return next((scope for key, scope in SCOPES if key in name), None)


def audit(caller: str, kind: str, name: str, args, outcome: str) -> None:
    m = TICKET.search(json.dumps(args))
    line = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "caller": caller, kind: name, "ticket_id": m.group(0).upper() if m else None,
            "outcome": outcome}
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, "a") as fh:
        fh.write(json.dumps(line) + "\n")


def _who() -> tuple[str, set[str]]:
    tok = get_access_token()
    return (tok.client_id, set(tok.scopes)) if tok else ("anonymous", set())


class ScopeAndAudit(Middleware):
    async def on_call_tool(self, context, call_next):
        name, args = context.message.name, context.message.arguments or {}
        caller, scopes = _who()
        need = required_scope(name)
        if need and need not in scopes:
            audit(caller, "tool", name, args, f"denied:{need}")
            fallback = name.replace("get_escalation_history", "get_ticket")
            alt = (f" Call {fallback} for the ticket's status and escalation count instead,"
                   if fallback != name else "")
            raise ToolError(
                f"permission denied: this token lacks scope {need}, which {name} needs. "
                f"Not retryable with this token.{alt} or hand the ticket to a colleague "
                "with escalation access.")
        try:
            result = await call_next(context)
        except Exception as exc:
            audit(caller, "tool", name, args, f"error:{str(exc)[:80]}")
            raise
        audit(caller, "tool", name, args, "ok")
        return result

    async def on_read_resource(self, context, call_next):
        uri = str(context.message.uri)
        caller, scopes = _who()
        need = required_scope(uri) if "escalation" in uri else None
        if need and need not in scopes:
            # Same rule as the tool: otherwise attaching the resource would be a
            # way round the denied tool.
            audit(caller, "resource", uri, uri, f"denied:{need}")
            raise ResourceError(f"permission denied: this token lacks scope {need}.")
        result = await call_next(context)
        if need:
            audit(caller, "resource", uri, uri, "ok")
        return result


def build(config_path: str | None = None) -> FastMCP:
    tokens = json.loads(os.environ.get("GATEWAY_TOKENS") or json.dumps(DEFAULT_TOKENS))
    gw = FastMCP(name="support-gateway", version="1.0.0",
                 instructions="One front door for the help-centre KB and Support Ops "
                              "ticket history. Every call is audited.",
                 auth=StaticTokenVerifier(tokens=tokens),
                 middleware=[ScopeAndAudit()])
    for name, spec in agent_config.load(config_path)["servers"].items():
        gw.mount(create_proxy(_upstream(spec)), namespace=name)
    return gw


def _upstream(spec: dict):
    """The proxy forwards the CALLER's request headers upstream, so a bearer
    token in `headers` would be overwritten by the agent's gateway token (and
    the agent's token would leak to the vendor). The gateway's own upstream
    credential is set as httpx auth instead, applied after forwarding."""
    if spec.get("transport") != "http":
        return _transport(spec)
    headers = dict(spec.get("headers") or {})
    bearer = headers.pop("Authorization", "").removeprefix("Bearer ").strip()
    return StreamableHttpTransport(spec["url"], headers=headers or None,
                                   auth=bearer or None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--config", help="upstream servers (default week9/mcp_config.json)")
    a = ap.parse_args()
    build(a.config).run(transport="http", host="127.0.0.1", port=a.port, path="/mcp",
                        show_banner=False)
