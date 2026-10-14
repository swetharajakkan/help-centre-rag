"""Requirement 4: the raw JSON-RPC exchange with the ticket-history server.

    .venv/bin/python week9/wire_capture.py

Speaks MCP by hand over Streamable HTTP with plain httpx -- no MCP SDK -- so
every byte on the wire is visible:

  0. POST without a token              -> 401 (remote MCP auth)
  1. initialize                        -> server capabilities + session id
  2. notifications/initialized         -> 202, no body (a notification)
  3. tools/list                        -> the discovered tools
  4. tools/call get_ticket TCK-4403    -> a result
  5. tools/call get_ticket TCK-44      -> a recoverable tool error (isError)

Writes week9/evidence/wire.raw.json (exactly what was sent and received) and
week9/evidence/wire.json (the same messages, each top-level field annotated
by hand -- the notes live in ANNOTATIONS below and were written after reading
the raw capture, not generated from it).
"""
from __future__ import annotations

import json
import os
import sys

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runtime  # noqa: E402

URL = os.environ.get("TICKET_HISTORY_URL", "http://127.0.0.1:8765/mcp")
TOKEN = os.environ.get("TICKET_HISTORY_TOKEN", "dev-ticket-token")
PROTOCOL = "2025-11-25"

MODEL_CALL = ("The model call happens in the host, in week9/agent/loop.py "
              "(model.complete), after tools/list returns and before tools/call "
              "is sent; it never happens on this wire or inside the "
              "ticket-history server, which only lists tools and executes them.")

# ---------------------------------------------------------------- hand notes

ANNOTATIONS = {
    "unauthenticated": {
        "request": {
            "jsonrpc": "Always the string \"2.0\": this is JSON-RPC 2.0 framing.",
            "id": "Request id chosen by the client; would be echoed in the response.",
            "method": "initialize -- but it never reaches MCP: the HTTP layer rejects it first.",
            "params": "Same params as step 1. Irrelevant here; auth is checked before parsing.",
        },
        "response": {
            "(empty body)": "No JSON-RPC response at all: no token, no session, no id echoed.",
        },
        "http": "401 + WWW-Authenticate: Bearer. Remote MCP auth sits in HTTP, under "
                "JSON-RPC: the request is refused before any MCP method runs.",
    },
    "initialize": {
        "request": {
            "jsonrpc": "JSON-RPC version, fixed \"2.0\".",
            "id": "1 -- the first request of the session; the response carries the same id.",
            "method": "initialize: the handshake. Nothing else may be sent before it.",
            "params": "protocolVersion the client speaks, the client's capabilities "
                      "(none offered: no sampling, no roots), and clientInfo (who is calling).",
        },
        "response": {
            "jsonrpc": "\"2.0\" again.",
            "id": "1 -- matches the request, which is how the client pairs them.",
            "result": "The server's half of the handshake (fields below).",
            "result.protocolVersion": "The version the server agreed to; both sides now speak it.",
            "result.capabilities": "What this server offers: tools, resources and prompts "
                                   "(each with listChanged notifications), logging, plus "
                                   "experimental/extensions slots. The host only asks for "
                                   "what is listed here.",
            "result.serverInfo": "Name and version of the server -- ticket-history 1.3.0. "
                                 "This is the third-party identity the risk note is about.",
            "result.instructions": "Free text the server wants the host to show its model. "
                                   "Untrusted input from a third party, like any tool description.",
        },
        "http": "The response header mcp-session-id names this session; every later "
                "request must send it back.",
    },
    "initialized": {
        "request": {
            "jsonrpc": "\"2.0\".",
            "method": "notifications/initialized: the client confirms the handshake is done.",
            "(no id)": "No id field at all -- that is what makes it a notification: no reply.",
        },
        "response": {},
        "http": "202 Accepted with an empty body. Only now may the client send requests.",
    },
    "tools_list": {
        "request": {
            "jsonrpc": "\"2.0\".",
            "id": "2.",
            "method": "tools/list: discovery. The answer is the ONLY source of the "
                      "agent's tool list for this server.",
            "params": "Empty: no pagination cursor on the first page.",
        },
        "response": {
            "jsonrpc": "\"2.0\".",
            "id": "2 -- pairs with the request.",
            "result": "The discovered tools (field below).",
            "result.tools": "One entry per tool: name, description (the docstring the "
                            "model reads as a prompt), inputSchema (JSON Schema the "
                            "model's arguments must satisfy), outputSchema, annotations "
                            "(readOnlyHint), and _meta. Two tools: get_ticket, "
                            "get_escalation_history.",
        },
        "http": "200, JSON-RPC result.",
    },
    "tools_call": {
        "request": {
            "jsonrpc": "\"2.0\".",
            "id": "3.",
            "method": "tools/call: execute one tool. The model chose it, in the host, "
                      "before this request was written.",
            "params": "name (the server's own tool name, without the host's "
                      "\"ticket-history__\" prefix) and arguments (the model's input).",
        },
        "response": {
            "jsonrpc": "\"2.0\".",
            "id": "3.",
            "result": "The tool's output (fields below). Plain data -- no model ran.",
            "result.content": "Content blocks for the model: one text block holding the "
                              "ticket as JSON. This is what goes into the tool_result.",
            "result.structuredContent": "The same record as a JSON object, typed by the "
                                        "tool's outputSchema, for code rather than the model.",
            "result.isError": "false: the call succeeded.",
        },
        "http": "200.",
    },
    "tools_call_error": {
        "request": {
            "jsonrpc": "\"2.0\".",
            "id": "4.",
            "method": "tools/call again.",
            "params": "A malformed id, TCK-44, as a model might copy it from a message.",
        },
        "response": {
            "jsonrpc": "\"2.0\".",
            "id": "4.",
            "result": "Still a RESULT, not a JSON-RPC error: the protocol worked, the "
                      "tool failed. That is what lets the model see and fix it.",
            "result.content": "The error text the model reads: it says the id is "
                              "malformed, what ids look like, and not to retry this value.",
            "result.isError": "true: tells the host this tool_result is an error "
                              "(sent to Claude as is_error).",
        },
        "http": "200 -- a tool error is not an HTTP or JSON-RPC error.",
    },
}

# ---------------------------------------------------------------- capture


def _body(resp: httpx.Response):
    if not resp.content:
        return None
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        data = [l[5:].strip() for l in resp.text.splitlines() if l.startswith("data:")]
        return json.loads(data[-1]) if data else None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _headers(h: dict, keep=("content-type", "mcp-session-id", "www-authenticate",
                            "mcp-protocol-version", "authorization", "accept")) -> dict:
    out = {k.lower(): v for k, v in h.items() if k.lower() in keep}
    if "authorization" in out:
        out["authorization"] = "Bearer <redacted>"
    return out


def capture() -> list[dict]:
    steps = []
    base = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": PROTOCOL, "capabilities": {},
        "clientInfo": {"name": "week9-wire-capture", "version": "1.0"}}}

    with httpx.Client(timeout=30) as http:
        def send(step, msg, headers):
            r = http.post(URL, json=msg, headers=headers)
            steps.append({"step": step, "http": {
                "request": f"POST {URL}", "status": r.status_code,
                "request_headers": _headers(headers),
                "response_headers": _headers(dict(r.headers))},
                "request": msg, "response": _body(r)})
            return r

        send("unauthenticated", init, base)
        auth = {**base, "Authorization": f"Bearer {TOKEN}"}
        r = send("initialize", init, auth)
        sess = {**auth, "mcp-session-id": r.headers["mcp-session-id"],
                "mcp-protocol-version": PROTOCOL}
        send("initialized", {"jsonrpc": "2.0", "method": "notifications/initialized"}, sess)
        send("tools_list", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, sess)
        send("tools_call", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "get_ticket", "arguments": {"ticket_id": "TCK-4403"}}}, sess)
        send("tools_call_error", {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "get_ticket", "arguments": {"ticket_id": "TCK-44"}}}, sess)
        http.delete(URL, headers=sess)      # end the session politely
    return steps


def annotate(steps: list[dict]) -> dict:
    out = []
    for s in steps:
        notes = ANNOTATIONS[s["step"]]
        out.append({"step": s["step"], "http": {**s["http"], "_note": notes["http"]},
                    "request": s["request"], "_request_notes": notes["request"],
                    "response": s["response"], "_response_notes": notes["response"]})
    return {"_how_to_read": ("Each step holds the exact JSON sent and received; the "
                             "_request_notes/_response_notes beside it annotate every "
                             "top-level field (and the top-level fields of result)."),
            "where_the_model_runs": MODEL_CALL,
            "server": URL, "exchange": out}


def main() -> None:
    os.makedirs(runtime.EVIDENCE, exist_ok=True)
    with runtime.ticket_server():
        steps = capture()
    with open(os.path.join(runtime.EVIDENCE, "wire.raw.json"), "w") as fh:
        json.dump(steps, fh, indent=1)
    with open(os.path.join(runtime.EVIDENCE, "wire.json"), "w") as fh:
        json.dump(annotate(steps), fh, indent=1)
    for s in steps:
        resp = s["response"]
        keys = list(resp) if isinstance(resp, dict) else resp
        print(f"{s['step']:18} HTTP {s['http']['status']}  response keys: {keys}")
    print(MODEL_CALL)


if __name__ == "__main__":
    main()
