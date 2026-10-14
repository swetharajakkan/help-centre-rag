"""Command line for the Week 9 agent.

    .venv/bin/python -m week9.agent.cli --list-tools
    .venv/bin/python -m week9.agent.cli "What is the status of TCK-4403?"
    .venv/bin/python -m week9.agent.cli --crew "Why was TCK-4403 escalated?"
    .venv/bin/python -m week9.agent.cli --config week9/mcp_config.gateway.json ...

--json PATH writes the full result (discovery + trace) for evidence files.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from . import crew, loop
from .host import Host
from .model import default_model


async def main_async(a) -> dict:
    async with Host(config_path=a.config) as host:
        disc = host.discovery()
        out = {"discovery": disc}
        for name, s in disc["servers"].items():
            state = "ok" if s["connected"] else f"FAILED {s['error']}"
            print(f"[{name}] {s['transport']} {state} -> {len(s['tools'])} tools: "
                  + ", ".join(t["name"] for t in s["tools"]))
        print(f"tools discovered: {disc['tool_count']}")
        if a.question:
            model = default_model()
            if a.crew:
                r = await crew.run_crew(host, model, a.question)
                trace = r["responder"]["steps"]
            else:
                r = await loop.run_agent(host, model, a.question)
                trace = r["steps"]
            for s in trace:
                if s["kind"] == "tool":
                    flag = "ERROR " if s["is_error"] else ""
                    print(f"  tools/call {s['qualified']}({json.dumps(s['args'])}) -> {flag}{s['text'][:90]}")
            ans = r["answer"] if a.crew else r["final"]["answer"]
            print(("\nverified: " + str(r["approved"]) + "\n") if a.crew else "", end="")
            print(f"\n{ans}")
            out["run"] = r
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--config")
    ap.add_argument("--list-tools", action="store_true")
    ap.add_argument("--crew", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    out = asyncio.run(main_async(a))
    if a.json:
        out.get("run", {}).pop("messages", None)
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1, default=str)


if __name__ == "__main__":
    main()
