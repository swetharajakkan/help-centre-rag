"""Bonus: both servers behind one gateway, one audit line per call, and a
scoped token whose denial reaches the model as a recoverable message.

    .venv/bin/python week9/bonus_gateway.py

Same agent package, pointed at week9/mcp_config.gateway.json (one server).
Runs one question twice: with token agent-full, then agent-no-escalations.
Writes week9/evidence/bonus_gateway.md and appends to gateway_audit.log.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import runtime  # noqa: E402
from week9.agent import config, loop  # noqa: E402
from week9.agent.host import Host  # noqa: E402
from week9.agent.model import default_model  # noqa: E402

QUESTION = "Show me the escalation history for TCK-4403."
CONFIG = os.path.join(HERE, "mcp_config.gateway.json")
AUDIT = os.path.join(runtime.EVIDENCE, "gateway_audit.log")


async def ask(token: str) -> dict:
    os.environ["GATEWAY_TOKEN"] = token
    async with Host(config.load(CONFIG)) as host:
        disc = host.discovery()
        run = await loop.run_agent(host, default_model(), QUESTION)
    return {"token": token, "tools": disc["tool_names"], "run": run}


def section(r: dict) -> list[str]:
    run = r["run"]
    out = [f"## token `{r['token']}`", "",
           f"attached context: {[c['uri'] for c in run['context']] or 'none (denied or absent)'}", ""]
    for s in run["steps"]:
        if s["kind"] == "tool":
            tag = "**isError**" if s["is_error"] else "ok"
            out.append(f"- tools/call `{s['qualified']}({json.dumps(s['args'])})` → {tag}: "
                       f"`{s['text'][:300]}`")
    out += ["", f"**answer:** {run['final']['answer']}", ""]
    return out


def main() -> None:
    start = sum(1 for _ in open(AUDIT)) if os.path.exists(AUDIT) else 0
    with runtime.ticket_server(), runtime.serve([os.path.join(HERE, "gateway.py"), "--port",
                                                 "8766"], 8766):
        full = asyncio.run(ask("agent-full"))
        limited = asyncio.run(ask("agent-no-escalations"))
    audit = open(AUDIT).read().splitlines()[start:]
    lines = ["# Bonus: one gateway, audited, with a scoped token", "",
             "Agent config: `week9/mcp_config.gateway.json` — a single server. The gateway "
             "(`week9/gateway.py`) fans out to both upstreams listed in `week9/mcp_config.json`.",
             "", f"Tools the agent discovered through the gateway ({len(full['tools'])}): "
             + ", ".join(f"`{t}`" for t in full["tools"]), "", f"**User:** {QUESTION}", ""]
    lines += section(full) + section(limited)
    lines += ["## Audit lines written by this run (`week9/evidence/gateway_audit.log`)", "",
              "```jsonl", *audit, "```", ""]
    with open(os.path.join(runtime.EVIDENCE, "bonus_gateway.md"), "w") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
