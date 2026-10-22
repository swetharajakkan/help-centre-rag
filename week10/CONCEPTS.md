# Week 10 concepts and where each one lives in this repo

## 1. Orchestrator–worker
One agent (the orchestrator) owns the task. It breaks the task into pieces, hands each piece to a worker, and writes the final answer from what the workers return. The workers never talk to each other or to the customer.
**Here:** `race.run_squad`. The orchestrator plans, the triage worker classifies the ticket, the policy-lookup worker searches and applies SP-001, and the orchestrator synthesises the reply.

## 2. Specialist agents
A worker is useful because it is *narrow*: a short prompt, only the tools its job needs, and only the context its job needs. Narrow prompts are easier to get right and cheaper to run. If you give every worker every tool, you have built N copies of the single agent.
**Here:** the triage worker has no tools and sees only six ticket fields. The policy worker has one tool. The single agent has all four.

## 3. When multi-agent helps
It is worth the overhead only when at least one of these is true:
- **The work splits cleanly:** each piece needs a *different* slice of context, so no worker needs the whole thread.
- **The work runs in parallel:** independent sub-tasks cut wall-clock time.
- **The specialisation is real:** a narrow worker beats a generalist on its piece, which you have to measure.
- **There is a boundary between agents:** different owners, permissions or deployments, e.g. another team's agent.

It hurts when the steps are sequential (triage, then lookup, then reply), when every worker needs the full ticket anyway, or when the single agent already passes.
**Here:** the steps were sequential, the policy worker needed the whole ticket, and pass rate tied at 10/10, so none of the conditions held. Verdict: **kill**.
**Race 2 (`fanout.md`)** tests the condition that should hold: tickets with several independent issues. The single agent as built fails from 7 issues (Week 7's 8-call budget), the squad passes up to 10 with every agent under ~3,000 tokens. A single agent with parallel tool calls also passes, so the squad's real edge is context isolation per issue, not speed. Rule: single agent by default, squad for many-issue tickets.

## 4. Context re-send cost
Every hand-off re-sends context the receiving agent needs (or that you lazily forward), and every model turn re-sends that agent's history. Multi-agent systems pay this once per hand-off. **Multiplier = multi-agent tokens / single-agent tokens.**
**Here:** 1.1x. The orchestrator → policy worker hand-off is 70% of the squad's tokens, because it forwards the ticket, the triage output and all of SP-001, then sends them again on the worker's second turn. That is our context strategy, not something inherent to the pattern. Sending only the triage output would cut it.

## 5. Single vs multi race
The only fair comparison holds everything fixed except the topology: the **same eval cases**, the **same judge**, the **same retrieval**, the **same reply renderer**. Changing the eval set halfway through ("these cases don't suit the orchestrator") voids the result. Re-running the multi-agent arm until it wins is sunk-cost bias.
**Here:** `race.py`, with the first ten judged Week 6 cases fixed before either arm ran.

## 6. Quality, latency, tokens and cost
Report all four together, because each one alone misleads. Quality is the pass rate. Latency is p50 **and p99**: the p99 is the ticket that gets escalated. Tokens show the re-send cost. Cost per ticket is what finance sees.
**Here:** `race_table.md`. Pass 10/10 vs 10/10; p99 2.44s vs 3.81s; 28,231 vs 31,903 tokens; $0.0151 vs $0.0203.

## 7. A2A protocol
Agent2Agent is an open protocol for one agent to call another agent: one that may be built by another team, in another framework, on another server. It runs over HTTP with **JSON-RPC 2.0**:
- `message/send`: send a Message, made of Parts (`text`, `data` or `file`), and get back a **Task**.
- `tasks/get` and `tasks/cancel`: check on a task, or stop it.
- Results come back as **Artifacts** on the task.

**Here:** `a2a.py` is the policy worker as an A2A server. The routes are `POST /api/a2a/policy-worker` (JSON-RPC) and `GET /api/a2a/policy-worker/.well-known/agent.json` (the card). `a2a.Orchestrator` is the client.

## 8. AgentCard and task lifecycle
An **AgentCard** is the JSON an agent publishes so callers can discover it. It lists its name, URL, skills, input/output modes, capabilities (streaming, push notifications) and auth scheme. Callers read the card instead of hard-coding the payload.

The **task lifecycle** is the set of states a task can be in: `submitted → working → completed | failed | canceled | rejected`, or `input-required` / `auth-required` when it needs a human or a credential before it can continue. A caller always knows where a task stands.
**Here:**
- A healthy ticket goes `submitted → working → completed`.
- With the worker forced to return a 500, the **worker task** ends `failed` and the **ticket task** goes to `input-required` ("retry, billing_review or manual?") instead of shipping a reply.
- Answering "retry" moves it `input-required → working → completed`.
- In the plain-function race, the same 500 was silently swallowed. The task state is what makes the failure visible. (`a2a_trace.json`, and the A2A tab in the UI.)

## 9. MCP vs A2A

| | MCP (Week 9) | A2A (Week 10) |
|---|---|---|
| Connects | an agent to **tools and data** | an agent to **another agent** |
| The other side is | a deterministic server (the ticket-history DB, RAG search) | something that reasons, takes time, and can fail or ask back |
| Discovery | `tools/list`, `resources/list` | the AgentCard at `/.well-known/agent.json` |
| Unit of work | one tool call → one result | a **Task** with a lifecycle, history and artifacts |
| Long-running / needs a human | not modelled | `working`, `input-required`, push notifications |
| Wire format | JSON-RPC over stdio or HTTP | JSON-RPC over HTTP |

They work together. Our policy worker *uses* MCP-style tools internally (search_help_centre) and is *reached by* the orchestrator over A2A. Rule of thumb: if the other side just executes, use MCP; if it decides, use A2A.

## 10. CrewAI and AutoGen
Two frameworks that give you orchestrator–worker without writing the loop yourself.
- **CrewAI:** you declare `Agent`s (role, goal, backstory, tools), `Task`s and a `Crew`. `Process.hierarchical` adds a manager agent that delegates to workers, i.e. orchestrator–worker with the routing done by an LLM. It is good for role-based pipelines.
- **AutoGen** (`autogen-agentchat`): agents talk in a shared conversation, a "team". `SelectorGroupChat` lets a model pick who speaks next; `RoundRobinGroupChat` takes turns. Every agent sees the whole thread, so re-send cost is built into the structure. It is good for open-ended collaboration.

What you trade compared with our hand-built orchestrator: less code, but routing and context are decided by the framework or an LLM, so per-hand-off token counts and failure behaviour are harder to see and control. That is exactly what the race had to measure.
**Here:** `frameworks/crewai_squad.py` and `frameworks/autogen_squad.py` build the same squad with the same prompts and the same search tool. They are **not run** (no API key, and the packages aren't installed), so they are not in the race numbers.
