"""The MCP host: one MCP client per configured server, and tool discovery.

Host, client, server -- the three roles, as this file plays them:

  host    this process. It owns the conversation, the model call, the user's
          trust boundary and the decision of what to attach as context.
  client  one fastmcp.Client per server (self.conns[name].client). Each holds
          exactly one session with exactly one server; clients never talk to
          each other, and the host is the only thing that sees all of them.
  server  a separate process (stdio child, or a remote HTTP endpoint) that
          exposes tools/resources/prompts and runs no model.

Discovery is real: every tool the model can call comes from a tools/list
response received at connect time. Nothing in this package names a server or
a tool. A server that fails to connect is reported and skipped; the others
still work.

Tool names are qualified as "<server>__<tool>" before the model sees them, so
two servers can both ship a tool called `search` without colliding, and the
trace shows which server answered.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from . import config as config_mod

SEP = "__"


@dataclass
class Conn:
    name: str
    spec: dict
    client: Client | None = None
    server_info: dict | None = None
    protocol: str | None = None
    tools: list = field(default_factory=list)          # mcp.types.Tool
    resources: list = field(default_factory=list)
    templates: list = field(default_factory=list)
    prompts: list = field(default_factory=list)
    error: str | None = None
    connect_ms: float = 0.0


def _transport(spec: dict):
    kind = spec.get("transport") or ("http" if "url" in spec else "stdio")
    if kind == "stdio":
        return StdioTransport(spec["command"], list(spec.get("args", [])),
                              env=spec.get("env") or None,
                              cwd=spec.get("cwd") or None)
    if kind == "http":
        headers = {k: v for k, v in (spec.get("headers") or {}).items() if v}
        return StreamableHttpTransport(spec["url"], headers=headers or None)
    raise ValueError(f"unknown transport {kind!r}")


def _dump(obj) -> dict:
    return obj.model_dump(mode="json", exclude_none=True) if obj is not None else {}


def _text_of(result) -> str:
    parts = [getattr(c, "text", None) for c in (result.content or [])]
    return "\n".join(p for p in parts if p) or json.dumps(result.structured_content or {})


class Host:
    def __init__(self, cfg: dict | None = None, config_path: str | None = None):
        self.cfg = cfg or config_mod.load(config_path)
        self.conns: dict[str, Conn] = {n: Conn(n, s) for n, s in self.cfg["servers"].items()}
        self._stack: AsyncExitStack | None = None

    # ------------------------------------------------------------ lifecycle

    async def __aenter__(self) -> "Host":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        await asyncio.gather(*(self._connect(c) for c in self.conns.values()))

    async def _connect(self, c: Conn) -> None:
        t0 = time.perf_counter()
        try:
            client = Client(_transport(c.spec), timeout=c.spec.get("timeout_s", 60),
                            init_timeout=c.spec.get("init_timeout_s", 60))
            await self._stack.enter_async_context(client)
            init = client.initialize_result
            c.client = client
            c.server_info = _dump(init.serverInfo)
            c.protocol = init.protocolVersion
            caps = init.capabilities
            # tools/list is the source of truth for what the model may call.
            c.tools = await client.list_tools() if caps.tools else []
            if caps.resources:
                c.resources = await client.list_resources()
                c.templates = await client.list_resource_templates()
            c.prompts = await client.list_prompts() if caps.prompts else []
        except BaseException as exc:  # noqa: BLE001 -- one bad server must not sink the rest
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            c.client, c.error = None, f"{type(exc).__name__}: {exc}"[:400]
        c.connect_ms = round((time.perf_counter() - t0) * 1000, 1)

    async def close(self) -> None:
        if self._stack:
            try:
                await self._stack.aclose()
            except BaseException:  # noqa: BLE001 -- shutting down anyway
                pass
            self._stack = None

    # ------------------------------------------------------------ discovery

    def tool_specs(self) -> list[dict]:
        """Every discovered tool, in the shape the Messages API takes."""
        out = []
        for c in self.conns.values():
            for t in c.tools:
                out.append({"name": f"{c.name}{SEP}{t.name}",
                            "description": t.description or "",
                            "input_schema": t.inputSchema or {"type": "object"}})
        return out

    def discovery(self) -> dict:
        """What tools/list (and resources/prompts list) returned, per server."""
        servers = {}
        for c in self.conns.values():
            servers[c.name] = {
                "transport": c.spec.get("transport") or ("http" if "url" in c.spec else "stdio"),
                "endpoint": c.spec.get("url") or " ".join([c.spec.get("command", "")]
                                                           + list(c.spec.get("args", []))),
                "connected": c.client is not None, "error": c.error,
                "connect_ms": c.connect_ms, "protocol": c.protocol,
                "server_info": c.server_info,
                "tools": [{"name": t.name, "qualified": f"{c.name}{SEP}{t.name}",
                           "description": t.description or "",
                           "input_schema": t.inputSchema} for t in c.tools],
                "resources": [str(r.uri) for r in c.resources],
                "resource_templates": [r.uriTemplate for r in c.templates],
                "prompts": [p.name for p in c.prompts],
                "attach": c.spec.get("attach", []),
            }
        names = [t["name"] for t in self.tool_specs()]
        return {"config": self.cfg["path"], "servers": servers,
                "tool_count": len(names), "tool_names": names}

    # ------------------------------------------------------------ calls

    async def call_tool(self, qualified: str, args: dict) -> dict:
        """Run one tools/call. Errors come back as data (is_error=True) with
        the server's own message, so the model can read and act on it."""
        server, _, tool = qualified.partition(SEP)
        c = self.conns.get(server)
        t0 = time.perf_counter()
        out = {"server": server, "tool": tool, "qualified": qualified, "args": args}
        if c is None or c.client is None or not any(t.name == tool for t in c.tools):
            why = (f"server {server!r} is not connected ({c.error})" if c and c.error
                   else f"no tool {qualified!r} was discovered")
            return out | {"is_error": True, "text": f"host: {why}", "structured": None,
                          "ms": 0.0}
        try:
            r = await c.client.call_tool(tool, args, raise_on_error=False)
            out |= {"is_error": bool(r.is_error), "text": _text_of(r),
                    "structured": r.structured_content}
        except Exception as exc:  # noqa: BLE001 -- transport failure, not a tool error
            # Recorded on the connection so a long-lived owner knows to
            # reconnect; the model still gets a readable result.
            c.error = f"transport: {type(exc).__name__}: {exc}"[:400]
            out |= {"is_error": True, "structured": None,
                    "text": f"host: transport error talking to {server} (server unreachable, "
                            f"not a bad argument): {type(exc).__name__}: {exc}"[:400]}
        out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out

    async def read_resource(self, server: str, uri: str) -> dict:
        c = self.conns.get(server)
        if c is None or c.client is None:
            return {"server": server, "uri": uri, "ok": False, "text": "not connected"}
        try:
            parts = await c.client.read_resource(uri)
            text = "\n".join(getattr(p, "text", "") or "" for p in parts)
            return {"server": server, "uri": uri, "ok": True, "text": text}
        except Exception as exc:  # noqa: BLE001
            return {"server": server, "uri": uri, "ok": False, "text": str(exc)[:300]}

    async def attach(self, user_text: str) -> list[dict]:
        """Read the resources the config says to attach for this message.
        This is the app deciding what context the model starts with."""
        jobs = []
        for c in self.conns.values():
            for rule in c.spec.get("attach", []):
                for m in dict.fromkeys(re.findall(rule["when"], user_text, re.I)):
                    jobs.append(self.read_resource(c.name, rule["uri"].replace("{id}", m.upper())))
        return list(await asyncio.gather(*jobs)) if jobs else []
