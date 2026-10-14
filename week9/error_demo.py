"""Requirement 5: the same failing call, old docstring/error vs new.

    .venv/bin/python week9/error_demo.py

Runs the unchanged agent loop against OUR server (help-centre-rag) twice with
the same user message, which leads the model to call get_article("BM-4"):

  before  HELP_CENTRE_RAG_ERRORS=legacy: docstring "Get article.", error "Error 3"
  after   the rewritten docstring and the recoverable error

The only switch is an env value in the server's config entry, so the agent,
the model and the question are identical across the two runs. Writes
week9/evidence/error_before_after.md.
"""
from __future__ import annotations

import asyncio
import difflib
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

QUESTION = "Open help article BM-4 and tell me what it says about proration."
SERVER_ONE = os.path.join(HERE, "config", "mcp_config.server_one.json")


async def one(mode: str) -> dict:
    os.environ["HELP_CENTRE_RAG_ERRORS"] = mode
    async with Host(config.load(SERVER_ONE)) as host:
        tool = next(t for t in host.discovery()["servers"]["help-centre-rag"]["tools"]
                    if t["name"] == "get_article")
        run = await loop.run_agent(host, default_model(), QUESTION)
    return {"description": tool["description"], "run": run}


def transcript(label: str, r: dict) -> list[str]:
    run = r["run"]
    out = [f"## {label}", "", "Docstring the model saw (from tools/list):", "", "```text",
           r["description"].rstrip(), "```", "", f"**User:** {QUESTION}", ""]
    for s in run["steps"]:
        if s["kind"] == "model":
            if s["tool_uses"]:
                calls = ", ".join(f"`{u['name']}({json.dumps(u['input'])})`" for u in s["tool_uses"])
                out.append(f"{s['turn']}. **model** → tools/call {calls}")
            else:
                ans = json.loads(s["text"]) if s["text"].startswith("{") else {"answer": s["text"]}
                out.append(f"{s['turn']}. **model** → final answer: {ans['answer']}")
        else:
            tag = "**isError: true**" if s["is_error"] else "ok"
            text = s["text"] if s["is_error"] else s["text"][:160] + "…"
            out.append(f"   - tool_result ({tag}): `{text}`")
    errs = run["tool_errors"]
    out += ["", f"Model turns **{run['model_turns']}** · tool calls **{len(run['tool_calls'])}** "
                f"({errs} failed) · tokens {run['tokens_in'] + run['tokens_out']:,} · "
                f"answered: **{run['final']['kind'] == 'answer'}**", ""]
    return out


def main() -> None:
    before = asyncio.run(one("legacy"))
    after = asyncio.run(one(""))
    diff = difflib.unified_diff(before["description"].splitlines(), after["description"].splitlines(),
                                "get_article docstring (before)", "get_article docstring (after)",
                                lineterm="")
    b, a = before["run"], after["run"]
    model = b["steps"][0]["model"]
    lines = [
        "# Same failing call, before and after the rewrite",
        "",
        f"Server: `help-centre-rag` (ours) · tool: `get_article` · model: `{model}` · "
        "agent module unchanged between runs; the only switch is "
        "`HELP_CENTRE_RAG_ERRORS` in the server's config entry.",
        "",
        "| | before | after |", "|---|---|---|",
        f"| error text | `Error 3` | ids look like BM-nnn, known ids, what to call |",
        f"| model turns | {b['model_turns']} | {a['model_turns']} |",
        f"| tool calls (failed) | {len(b['tool_calls'])} ({b['tool_errors']}) | "
        f"{len(a['tool_calls'])} ({a['tool_errors']}) |",
        f"| tokens | {b['tokens_in'] + b['tokens_out']:,} | {a['tokens_in'] + a['tokens_out']:,} |",
        f"| answered the user | {b['final']['kind'] == 'answer'} | {a['final']['kind'] == 'answer'} |",
        "",
    ]
    if model == "offline-mcp-planner":
        lines += ["> Engine note: no ANTHROPIC_API_KEY on this checkout, so the model is the "
                  "offline planner in `week9/agent/model.py`. It re-plans only from the error "
                  "text it is handed (an id shape, a named tool, a do-not-retry phrase) and "
                  "resends an opaque error up to 3 times. Set a key and rerun this script to "
                  "get the same transcript from claude-opus-5-5.", ""]
    lines += ["## The docstring rewrite", "", "```diff", *diff, "```", ""]
    lines += transcript("Before — `Error 3`", before)
    lines += transcript("After — recoverable error", after)
    path = os.path.join(runtime.EVIDENCE, "error_before_after.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines[6:12]))


if __name__ == "__main__":
    main()
