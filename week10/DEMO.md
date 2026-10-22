# Week 10 demo: triage squad vs single agent, Task Set A

About 8 minutes. The order follows the rubric, highest marks first. Run every command from `help-centre/`.

## Before you start

| Terminal | Command |
|---|---|
| T1 backend | `.venv/bin/uvicorn backend.app.main:app --port 8000` (restart it if it was already running) |
| T2 frontend | `cd frontend && npm run dev` |
| T3 commands | below |

1. Re-run the race so the numbers are fresh (about 1 minute): `.venv/bin/python week10/race.py`
2. Open http://localhost:5173 and log in as **admin / admin123**. Go to **Chat**, then the **Agent race** tab.

## 1. All four numbers, both arms, same 10 cases (30)
- UI: **Agent race → Race**. Show the metric table, then the per-ticket table, which lists C-01, C-02 and C-04 to C-11.
- Say: these are the first ten judged cases of the Week 6 eval set. C-03 is skipped because Week 6 left it unjudged. The judge is `judge_v2.txt` plus the four SP-001 checks, the same as Week 6. No new cases were written.
- File: `week10/race_table.md`.

## 2. Context re-send multiplier, attributed (25)
- UI: **Agent race → Hand-offs**. Read the top line: squad tokens / single tokens = **1.1x**, and orchestrator → policy worker carries **70%** of the squad's tokens.
- Say why: the orchestrator forwards the whole ticket, the triage output and the full SP-001 text, then sends it all again with the chunks on the worker's second turn. That is our context strategy, not the multi-agent pattern itself.

## 3. Injected worker failure (20)
- UI: **Agent race → Worker failure**. The policy worker returns HTTP 500 on C-01.
- One line: **it degraded**. There was no retry, the 500 was swallowed, and it shipped a no-answer reply tagged [ESCALATED] that never tells the customer a step failed.
- Point at the judge tile: the healthy run passes and the failed run fails (NOT_RESOLVED), so the eval does catch the bad reply, but nothing in the orchestrator raised the error: it only shows up after grading.
- Be honest about the refund sentence: it appears in both replies because the shared reply template writes it, not the worker.
- File: `week10/failure_case.md`.

## 4. Verdict (15)
- UI: **Agent race → Verdict**. Read the sunk-cost line out loud first, then: 10/10 vs 10/10 pass, 1.1x tokens, $0.0203 vs $0.0151 per ticket, and a slower p99 (3.81s vs 2.44s). **KILL.**
- If asked why both arms pass 10/10: the first run scored 0/10 on both, and the cause was the shared Week 6 pipeline, not the topology. We fixed it once, for both arms (see "What changed from 0/10" below). The cases and the judge did not change. Pass rate ties, so the bill and the failure behaviour decide the verdict.

## 5. Hand-off log (10)
- UI: **Agent race → Hand-offs**, then switch between Single agent and Triage squad to show every hand-off with tokens in and out.
- File: `week10/handoffs.log`.

## Race 2: when the squad IS the right call (if asked "so when would you use it?")
- UI: **Agent race → Race 2: many issues**. File: `week10/fanout.md` (`.venv/bin/python week10/fanout.py`, about 2 minutes).
- Say: race 1's tickets have one issue each, so the work does not split. Race 2 was declared separately (not added to race 1, which would be moving the goalposts): tickets with several independent error codes from different articles, every agent under Week 7's budget (8 calls, 20,000 tokens).
- The result: the single agent as built (one tool call per turn) **fails from 7 issues**: 7 searches + policy + reply = 9 calls against a budget of 8. The squad passes all sizes up to 10, and its largest agent stays around 3,000 tokens, while the single agent's one history grows by ~1,700 tokens per issue.
- Honest caveat, say it before they do: a single agent with **parallel tool calls** also passes every size and is cheaper. The squad didn't win on speed (output tokens and the shared CPU retriever dominate). Its real edge is **context isolation**: each worker holds one issue.
- Justification line: *use the triage squad when a ticket has several independent issues that each need their own context; use the single agent for everything else.*

## Live (optional)
- Chat, with **Triage squad** selected in the filter bar: type `What does ERR-4215 mean and what should I do?`. Both arms answer side by side with their token bills.

## Bonus
- UI: **Agent race → Agent card**. Files: `week10/agent_card.json` and `week10/a2a_lifecycle.md`. The failed case should end at `input-required` waiting for the ticket owner, with the worker task at `failed`.

## A2A live (bonus, strongest part)
- UI: **Agent race → A2A**. Pick C-01, choose **Worker 500**, click **Run**. The ticket task goes `submitted → working → input-required`, the worker task goes `submitted → working → failed`, and no reply ships.
- Click **Retry**: the ticket task goes `→ working → completed` and the reply appears.
- Say: in the race, the same 500 was swallowed by a plain function call. Over A2A the failure is a task state the orchestrator has to deal with.
- Raw protocol: `GET /api/a2a/policy-worker/.well-known/agent.json` (the card), and `POST /api/a2a/policy-worker` with `message/send` / `tasks/get`.

## What changed from 0/10 (if asked)
The first run failed every case on both arms, for reasons that sat in the shared pipeline:
- **Retrieval (6 cases declined):** the whole question was searched under the ticket's product-area filter, so codes documented in another article came back "not found". Now each reported `ERR-nnnn` is looked up on its own, unfiltered, and other questions use the Week 5 unfiltered retry (`race._search`).
- **Unrequested codes (3 cases):** replies listed fixes for codes the customer never reported. Now a code row is kept only if the customer named the code or described its condition (SP-001 "What resolution means"; judge_v2's symptom-match lesson), and SP-001 is never quoted to the customer (`race._reported`).
- **Reply envelope (all four SP-001 checks):** the Week 6 template dropped the ticket ID on refusals, offered refunds past day 30, wrote "the full amount" instead of a figure, and tagged Priority tickets only when unanswered. `race.render` follows SP-001; `week6/draft.render` is left as Week 6 measured it.

Same 10 cases, same judge_v2 and assertions, both arms changed identically.

## Concepts (if asked)
`week10/CONCEPTS.md` covers all 10 topics: orchestrator–worker, specialists, when multi-agent helps, re-send cost, the race, the 4 metrics, A2A, AgentCard and lifecycle, MCP vs A2A, and CrewAI/AutoGen (`week10/frameworks/`, not run).

## Proof it's tested
`.venv/bin/python -m pytest -q backend/tests/test_week10.py` (12 tests)
