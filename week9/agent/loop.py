"""The agent loop: model -> tools/call -> model, over whatever was discovered.

The model call happens HERE (model.complete, in the host process), between
tools/list and tools/call. It never happens inside an MCP server and never
crosses the MCP wire -- the wire only ever carries a tool name, arguments and
a result.

    1. host.attach(user_text)      app-attached resources (resources/read)
    2. model.complete(tools=...)   the model picks a tool from tools/list
    3. host.call_tool(...)         tools/call, errors returned as data
    4. repeat until the model answers or the turn budget runs out
"""
from __future__ import annotations

import asyncio
import json
import time

from .model import cost_usd

SYSTEM = """\
You are the Responder for a billing-migration support desk. Answer the user's
question using ONLY the tools you have been given and any <context> blocks in
the user's message (the host attached those; do not re-fetch what is already
there). Tool errors are written for you: read them and act on them -- reformat
an id, call the tool they name, or stop -- never resend an identical call that
failed with a reason.

When you are done, reply with ONLY a JSON object:
  {"kind": "answer" | "refusal",
   "answer": "<the reply to the user, citing [source_id] after each claim>",
   "claims": [{"text": "<one factual claim>",
               "source_id": "<ticket id (TCK-nnnn) or article id (BM-nnn)>",
               "quote": "<words copied verbatim from that source>",
               "facts": {"<record field>": "<value>"}}]}
Every factual statement in "answer" must be one of the claims. Use
"kind": "refusal" with no claims when the sources do not cover the question.
"""


def context_block(ctx: dict) -> dict:
    return {"type": "text",
            "text": f'<context uri="{ctx["uri"]}" server="{ctx["server"]}">\n{ctx["text"]}\n</context>'}


def parse_final(text: str) -> dict:
    """The responder's JSON, tolerating prose or a code fence around it."""
    start, end = text.find("{"), text.rfind("}")
    try:
        d = json.loads(text[start:end + 1])
        if isinstance(d, dict) and "answer" in d:
            d.setdefault("claims", [])
            d.setdefault("kind", "answer")
            return d
    except ValueError:
        pass
    return {"kind": "answer", "answer": text.strip(), "claims": [], "unparsed": True}


async def run_agent(host, model, user_text: str, system: str = SYSTEM,
                    max_turns: int = 8, messages: list | None = None) -> dict:
    t0 = time.perf_counter()
    context = []
    if messages is None:
        context = [c for c in await host.attach(user_text) if c["ok"]]
        messages = [{"role": "user",
                     "content": [context_block(c) for c in context]
                     + [{"type": "text", "text": user_text}]}]
    tools = host.tool_specs()
    steps, final, tok_in, tok_out = [], None, 0, 0

    for turn in range(1, max_turns + 1):
        resp = await asyncio.to_thread(model.complete, system, messages, tools)
        u = resp["usage"]
        tok_in += u["input_tokens"]
        tok_out += u["output_tokens"]
        uses = [b for b in resp["content"] if b.get("type") == "tool_use"]
        steps.append({"kind": "model", "turn": turn, "model": resp.get("model"),
                      "stop_reason": resp["stop_reason"],
                      "tool_uses": [{"name": b["name"], "input": b["input"]} for b in uses],
                      "text": "".join(b.get("text", "") for b in resp["content"]
                                      if b.get("type") == "text")[:4000],
                      **u})
        messages.append({"role": "assistant", "content": resp["content"]})
        if resp["stop_reason"] != "tool_use":
            final = parse_final(steps[-1]["text"])
            break
        outs = await asyncio.gather(*(host.call_tool(b["name"], b["input"]) for b in uses))
        results = []
        for b, out in zip(uses, outs):
            steps.append({"kind": "tool", "turn": turn, **{k: out[k] for k in
                          ("qualified", "server", "tool", "args", "is_error", "text", "ms")}})
            results.append({"type": "tool_result", "tool_use_id": b["id"],
                            "content": out["text"], "is_error": out["is_error"]})
        # All results of one turn go back in ONE user message.
        messages.append({"role": "user", "content": results})

    if final is None:
        final = {"kind": "refusal", "claims": [], "budget_exhausted": True,
                 "answer": f"I stopped after {max_turns} model turns without an answer."}
    tool_steps = [s for s in steps if s["kind"] == "tool"]
    return {"question": user_text, "final": final, "steps": steps, "messages": messages,
            "context": context, "model_turns": sum(s["kind"] == "model" for s in steps),
            "tool_calls": [s["qualified"] for s in tool_steps],
            "tool_errors": sum(s["is_error"] for s in tool_steps),
            "tokens_in": tok_in, "tokens_out": tok_out,
            "cost_usd": round(cost_usd(tok_in, tok_out), 6),
            "ms": round((time.perf_counter() - t0) * 1000, 1)}
