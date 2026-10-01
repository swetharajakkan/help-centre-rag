# Week 7 demo script

One story, told in order: *a refund ticket → the loop that solves it → how it is kept safe → do we even need an agent → how it remembers → the same thing in a framework.* About 15–20 minutes. Every command runs offline from `help-centre/`.

Before you start: `source .venv/bin/activate`, open `week7/` in the editor, and run the two memory commands once (step 7) so the model files are cached and nothing downloads live.

| # | Topic | File | Command | Time |
|---|---|---|---|---|
| 1 | The agent loop | `agent.py` | `python week7/agent.py TCK-7001` | 2 min |
| 2 | ReAct | `react.py` | `python week7/react.py TCK-7009` | 2 min |
| 3 | Tool design | `tools.py` | (show code) | 2 min |
| 4 | Stop conditions & budgets | `agent.py`, `budget_demo.py` | `python week7/budget_demo.py` | 2 min |
| 5 | Workflows vs agents | `workflow.py` | `python week7/workflow.py` | 1 min |
| 6 | Agent vs workflow race | `race.py` | `python week7/race.py` | 3 min |
| 7 | Memory: short & long term, summarisation, vector | `bonus.py`, `memory.py` | `python week7/memory.py` | 3 min |
| 8 | mem0 | `mem0_demo.py` | `write`, then `recall` | 2 min |
| 9 | LangChain / LangGraph | `graph.py` | `python week7/graph.py` | 3 min |

---

## 1. The agent loop — `agent.py`

**Show** `run_agent()`, the `while True:` block: call the model → if `stop_reason != "tool_use"` stop → otherwise run every tool it asked for → append results → repeat.

**Run** `python week7/agent.py TCK-7001` and then `TCK-7009`. Point at the path column: 3 tool calls vs 4.

**Say:** "The model decides which tool runs next from what the last one returned. That choice is the only thing that makes it an agent."

## 2. ReAct — `react.py`

**Run** `python week7/react.py TCK-7009`.

**Point at** Thought 3: *"The ticket names 2 orders and I have only fetched ORD-5109. To find the duplicate I must compare charges…"* That's the step the workflow skips.

**Say:** "ReAct is the same loop with the reasoning written down: Thought → Action → Observation. The value is the audit trail." Be upfront that the offline engine picks the Action for real and the Thought text is generated from the observations; with a hosted model, the model writes the Thought itself.

## 3. Tool design — `tools.py`

**Show**, in this order:
1. `TOOLS_BEFORE` vs `TOOLS`: `get_order` used to say "check whether it can be refunded", which overlapped with the policy tool. Now it says "Does not decide refund eligibility."
2. `pattern: ^ORD-\d{4}$`: bad ids are rejected by the schema.
3. `lookup_refund_policy`: every input is an enum and the output `decision` is an enum.
4. `call()`: an unknown tool or bad arguments returns an error *result*. It never raises.

**Say:** "Give each tool one job, make its inputs typed, make its description say what it doesn't do, and have errors come back as data."

## 4. Stop conditions & budgets — `agent.py` + `budget_demo.py`

**Show** `Budgets` (iterations, tokens, cost, wall-clock) and `_breached()`, which is checked *before* every call and again *after* one, so an over-budget call can't trigger more tools.

**Run** `python week7/budget_demo.py`. The log ends in `budget_exceeded max_tokens … observed 2745` → `terminated_cleanly` → `[ESCALATED]`.

**Also show** the natural stop condition: the model returning text instead of `tool_use`. Two kinds of stop: *done* and *out of budget*.

## 5. Workflows vs agents — `workflow.py`

**Show** the file: four hard-coded steps, no `while`, and the model is never given a tool schema.

**Run** `python week7/workflow.py`. Every row has the same path.

## 6. Agent vs workflow race — `race.py`

**Run** `python week7/race.py` (about 30 s). The table at the end:

| | Agent | Workflow |
|---|---|---|
| Pass | 10/10 | 9/10 |
| p50 | 1.32 s | 0.59 s |
| Tokens | 28,233 | 3,432 (8.2× fewer) |
| $/ticket | $0.0183 | $0.0039 (4.7× cheaper) |

**Say the decision rule:** "Does the execution path vary with the input? Only on multi-order tickets (TCK-7009). The branch tickets didn't need an agent, because the enum policy tool absorbs the branching. So use the workflow and route multi-order tickets to the agent."

## 7. Agent memory — `bonus.py` → `memory.py`

**Run** `python week7/memory.py`. Walk the table:

- **Short-term** = what's in the prompt. *Full history* is 706 tokens; *window + summary* is about 214.
- **Summarisation** is lossy. TCK-LONG-03 with window + summary → **FAIL**, because the rolling summary dropped waiver code `MGR-AUTH-8821`.
- **Vector memory** is long-term. Every customer turn is embedded (bge-small) and stored per customer. Before deciding, the agent recalls "any authorisation for ORD-5108?" and gets the waiver back verbatim at score 0.83 → **PASS**.
- **Long-term fact**: tier in `tier_store.json`, one exact value per key.

**Run it again.** The first line now says *"44 items loaded from disk (written by an earlier process)"*, which shows it survives a restart.

**Say:** "Summaries keep the gist and lose the exact values. Vector memory brings back exact text on demand, so use both."

## 8. mem0 — `mem0_demo.py`

**Run** these as two separate commands, so the audience sees two processes:
```bash
python week7/mem0_demo.py reset
python week7/mem0_demo.py write
python week7/mem0_demo.py recall
```
**Point at:** the tier recalled for each customer; the waiver as the top hit (0.916); *"same query as CUST-901 returns the waiver? False"*, which shows memory is scoped per user.

**Say:** "`memory.py` is 40 lines of hand-built vector memory. mem0 is the packaged version: embedder, vector store, user scoping, history. With `infer=True` it also uses an LLM to extract and de-duplicate facts, which is exactly where an exact code can get paraphrased away."

## 9. LangChain / LangGraph — `graph.py`

**Run** `python week7/graph.py --mermaid` and paste the output into mermaid.live, or show it as text. The agent graph has a **cycle** (`model ⇄ tools`); the workflow graph is a **straight line**. That picture is the workflow-vs-agent difference.

**Run** `python week7/graph.py`: 10/10 and 9/10, the same as the hand-written race, because it uses the same model and tools.

**Run** `python week7/graph.py TCK-7009`: the checkpoint list, one snapshot per step. That's LangGraph's short-term memory per `thread_id`, and any step can be resumed or replayed.

**Map it for the audience:** `StructuredTool` (LangChain) = our tool specs · `ToolNode` = our tool-running `for` loop · conditional edge = our `if stop_reason` · `recursion_limit` = a framework budget on top of our four.

**Say:** "The framework doesn't make it smarter. It gives you the graph, checkpoints and replay for free. I built it by hand first so I know what it's doing."

---

## Likely questions

- **Is the model real?** No. It's an offline deterministic engine with the Messages API's shape. Its decisions are real: it only sees the conversation. Tokens are estimated at chars/4, cost uses claude-opus-5 pricing, and latency is simulated. The notes are in `model.py`.
- **Why does bonus.py special-case TCK-LONG-03?** It does (`if thread_id == "TCK-LONG-03"`). `memory.py` replaces that with a generic rule: a waiver-code regex over whatever is in the agent's context. Show `memory.py` if asked.
- **When would you choose the agent anyway?** When the number or order of tool calls can't be known until you've read the input.
