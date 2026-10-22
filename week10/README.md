# Week 10: triage squad vs single agent

    .venv/bin/python week10/race.py      # ~1 min, rewrites every file below

| File | What |
|---|---|
| [race_table.md](race_table.md) | 4 metrics x 2 arms on the same 10 Week-6 cases, plus the multiplier line |
| [handoffs.log](handoffs.log) | every hand-off with tokens in/out, plus the per-hand-off share |
| [failure_case.md](failure_case.md) | policy worker forced to return 500 on C-01, and what the orchestrator did |
| [verdict.md](verdict.md) | keep/kill, with the sunk-cost bias named first |
| [agent_card.json](agent_card.json), [a2a_lifecycle.md](a2a_lifecycle.md) | bonus |
| [a2a.py](a2a.py), a2a_trace.json | policy worker as a real A2A server (JSON-RPC, AgentCard, task lifecycle); `python -m week10.a2a` |
| [frameworks/](frameworks/) | the same squad in CrewAI and AutoGen (not run: no API key) |
| [fanout.py](fanout.py), [fanout.md](fanout.md) | Race 2: multi-issue tickets, where the squad is justified (`python week10/fanout.py`) |
| [CONCEPTS.md](CONCEPTS.md) | the 10 Week 10 topics and where each one is in the code |

Cases: C-01, C-02, C-04…C-11, the first ten judged cases in week6/eval_set.jsonl
(C-03 is skipped because Week 6 left it unjudged). The judge is week6/judge_v2.txt plus the four SP-001
assertions, the same pass rule as Week 6. Both arms share the same retrieval (`race._search`) and the same SP-001 reply
renderer (`race.render`), so the agent topology is the only thing that changes. Tokens are ceil(chars/4) of the exact
payloads. Cost is at claude-opus-5-5 list price. Latency is measured wall clock, with model time
simulated.

The UI's **Agent race** tab reads race.json. Picking **Triage squad** in the chat runs a typed
question through both arms live.
