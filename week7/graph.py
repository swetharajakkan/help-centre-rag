r"""The agent and the workflow again, this time as LangGraph graphs.

    .venv/bin/python week7/graph.py                 # both graphs on all 10, graded
    .venv/bin/python week7/graph.py TCK-7009        # one ticket + its checkpoints
    .venv/bin/python week7/graph.py --mermaid       # print both graphs as Mermaid

agent.py writes the loop by hand: `while True`, call the model, run the tools,
append, repeat. LangGraph makes that loop a graph you can draw:

    START -> model --(tool_calls?)--> tools --(budget ok?)--> model ...
                   \--(final text)--> END       \--(budget hit)--> handoff -> END

and the workflow is a straight line with no conditional edge at all:

    START -> get_ticket -> get_order -> policy -> draft -> END

That picture IS the workflow-vs-agent difference: an agent has a cycle whose
exit is decided by the model; a workflow has none.

LangChain pieces used: StructuredTool wraps each function in tools.py with its
JSON schema; AIMessage.tool_calls / ToolMessage are the message types;
ToolNode (langgraph.prebuilt) executes whatever tool_calls the model emitted.
LangGraph pieces: StateGraph, conditional edges, a checkpointer (short-term
memory per thread_id, one snapshot per step) and recursion_limit (the
framework's own stop condition, on top of our four budgets).

The model is the same offline model.complete() the hand-written agent calls,
so the graded results must match agent.py / workflow.py exactly.
"""
from __future__ import annotations

import json
import operator
import os
import sys
from typing import Annotated, TypedDict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from langchain_core.messages import (AIMessage, AnyMessage, HumanMessage,  # noqa: E402
                                     ToolMessage)
from langchain_core.tools import StructuredTool  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402

from agent import Budgets, Meter, _breached, _handoff, call_model, run_tool  # noqa: E402
import model  # noqa: E402
import tools as T  # noqa: E402
from store import TICKET_IDS  # noqa: E402


# ------------------------------------------------ LangChain <-> Messages API

def to_messages_api(msgs: list[AnyMessage]) -> list[dict]:
    """LangChain message objects -> the Anthropic-format list model.complete
    expects. Consecutive ToolMessages become one user turn of tool_results."""
    out: list[dict] = []
    for m in msgs:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            blocks = [{"type": "text", "text": m.content}] if m.content else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"],
                        "input": c["args"]} for c in m.tool_calls]
            out.append({"role": "assistant", "content": blocks})
        elif isinstance(m, ToolMessage):
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id,
                     "content": m.content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def to_ai_message(resp: dict) -> AIMessage:
    text = "".join(b["text"] for b in resp["content"] if b["type"] == "text")
    calls = [{"id": b["id"], "name": b["name"], "args": b["input"]}
             for b in resp["content"] if b["type"] == "tool_use"]
    return AIMessage(content=text, tool_calls=calls)


def langchain_tools(meter: Meter) -> list[StructuredTool]:
    """tools.TOOLS as LangChain tools. Same name, description and JSON schema;
    execution goes through agent.run_tool so it is metered and traced."""
    def make(spec: dict) -> StructuredTool:
        def fn(**kwargs) -> str:
            return json.dumps(run_tool(meter, spec["name"], kwargs))
        return StructuredTool.from_function(
            func=fn, name=spec["name"], description=spec["description"],
            args_schema=spec["input_schema"])
    return [make(s) for s in T.TOOLS]


# ------------------------------------------------------------ the agent graph

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    terminated: dict | None


def build_agent_graph(meter: Meter, b: Budgets, checkpointer=None):
    def model_node(state: AgentState) -> dict:
        resp = call_model(meter, model.SYSTEM_AGENT,
                          to_messages_api(state["messages"]), T.TOOLS)
        return {"messages": [to_ai_message(resp)]}

    def after_model(state: AgentState) -> str:
        if not state["messages"][-1].tool_calls:
            return END
        return "handoff" if _breached(meter, b, before_call=False) else "tools"

    def after_tools(state: AgentState) -> str:
        return "handoff" if _breached(meter, b, before_call=True) else "model"

    def handoff_node(state: AgentState) -> dict:
        return {"terminated": _breached(meter, b, before_call=True)
                or _breached(meter, b, before_call=False)}

    g = StateGraph(AgentState)
    g.add_node("model", model_node)
    g.add_node("tools", ToolNode(langchain_tools(meter)))
    g.add_node("handoff", handoff_node)
    g.add_edge(START, "model")
    g.add_conditional_edges("model", after_model, ["tools", "handoff", END])
    g.add_conditional_edges("tools", after_tools, ["model", "handoff"])
    g.add_edge("handoff", END)
    return g.compile(checkpointer=checkpointer)


def run_graph_agent(ticket_id: str, budgets: Budgets | None = None,
                    checkpointer=None) -> dict:
    b = budgets or Budgets()
    meter = Meter("graph-agent", ticket_id)
    app = build_agent_graph(meter, b, checkpointer)
    config = {"configurable": {"thread_id": ticket_id},
              "recursion_limit": 2 * b.max_iterations + 2}
    final = app.invoke({"messages": [HumanMessage(
        f"Resolve support ticket {ticket_id}.")], "terminated": None}, config)
    if final.get("terminated"):
        output = _handoff(ticket_id)
    else:
        output = json.loads(final["messages"][-1].content)
    return {"system": "graph-agent", "ticket_id": ticket_id, "output": output,
            "terminated": final.get("terminated"), "app": app,
            "config": config, **meter.summary()}


# --------------------------------------------------------- the workflow graph

class FlowState(TypedDict, total=False):
    ticket_id: str
    ticket: dict
    order: dict
    policy: dict
    output: dict
    trail: Annotated[list[str], operator.add]


def build_workflow_graph(meter: Meter):
    def get_ticket(s: FlowState) -> dict:
        return {"ticket": run_tool(meter, "get_ticket",
                                   {"ticket_id": s["ticket_id"]}),
                "trail": ["get_ticket"]}

    def get_order(s: FlowState) -> dict:
        oid = (s["ticket"].get("order_ids") or [None])[0]
        return {"order": run_tool(meter, "get_order", {"order_id": oid}),
                "trail": ["get_order"]}

    def policy(s: FlowState) -> dict:
        return {"policy": run_tool(meter, "lookup_refund_policy",
                                   model.policy_args(s["ticket"], s["order"])),
                "trail": ["policy"]}

    def draft(s: FlowState) -> dict:
        facts = {"ticket": s["ticket"], "order": s["order"],
                 "policy": s["policy"]}
        resp = call_model(meter, model.SYSTEM_DRAFT,
                          [{"role": "user", "content": json.dumps(facts)}],
                          tools=None)
        return {"output": json.loads(resp["content"][0]["text"]),
                "trail": ["draft"]}

    g = StateGraph(FlowState)
    for name, fn in (("get_ticket", get_ticket), ("get_order", get_order),
                     ("policy", policy), ("draft", draft)):
        g.add_node(name, fn)
    g.add_edge(START, "get_ticket")
    g.add_edge("get_ticket", "get_order")
    g.add_edge("get_order", "policy")
    g.add_edge("policy", "draft")
    g.add_edge("draft", END)
    return g.compile()


def run_graph_workflow(ticket_id: str) -> dict:
    meter = Meter("graph-workflow", ticket_id)
    final = build_workflow_graph(meter).invoke(
        {"ticket_id": ticket_id, "trail": []})
    return {"system": "graph-workflow", "ticket_id": ticket_id,
            "output": final["output"], "terminated": None, **meter.summary()}


# ----------------------------------------------------------------------- CLI

def main() -> None:
    args = sys.argv[1:]
    if args == ["--mermaid"]:
        m = Meter("graph", "-")
        print("%% agent\n" + build_agent_graph(m, Budgets()).get_graph().draw_mermaid())
        print("%% workflow\n" + build_workflow_graph(m).get_graph().draw_mermaid())
        return

    if args:
        tid = args[0]
        r = run_graph_agent(tid, checkpointer=InMemorySaver())
        print(f"{tid}  path: {' -> '.join(r['path'])}")
        print(f"decision: {r['output']['decision']}  "
              f"refund: {r['output']['refund_order_id']}  "
              f"escalate: {r['output']['escalate']}")
        history = list(r["app"].get_state_history(r["config"]))
        print(f"\ncheckpoints saved for thread_id={tid}: {len(history)} "
              "(newest first; any one can be resumed or replayed)")
        for snap in history:
            last = snap.values["messages"][-1] if snap.values.get("messages") else None
            what = (type(last).__name__ + (f" tool_calls={[c['name'] for c in last.tool_calls]}"
                    if isinstance(last, AIMessage) and last.tool_calls else "")) if last else "-"
            print(f"  step {snap.metadata.get('step'):>2}  next={list(snap.next) or ['END']!s:12} last={what}")
        return

    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "week6"))
    from race import grade

    print(f"{'ticket':9} {'graph agent':34} {'graph workflow':34}")
    passed = {"agent": 0, "workflow": 0}
    for tid in TICKET_IDS:
        a, w = run_graph_agent(tid), run_graph_workflow(tid)
        ga, gw = grade(tid, a["output"]), grade(tid, w["output"])
        passed["agent"] += ga["passed"]
        passed["workflow"] += gw["passed"]
        print(f"{tid:9} {'PASS' if ga['passed'] else 'FAIL'} {a['output']['decision']:24}"
              f"{a['llm_calls']}c  {'PASS' if gw['passed'] else 'FAIL'} "
              f"{w['output']['decision']:24}{w['llm_calls']}c")
    print(f"\ngraph agent {passed['agent']}/10, graph workflow "
          f"{passed['workflow']}/10  (hand-written race: 10/10 and 9/10)")


if __name__ == "__main__":
    main()
