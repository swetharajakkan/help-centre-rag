# Bonus: the failed case on the A2A task lifecycle

This is now implemented, not only described: `week10/a2a.py` (run `.venv/bin/python -m week10.a2a`)
writes `a2a_trace.json` with healthy `submitted → working → completed`, failed
`submitted → working → input-required`, and, after the owner answers "retry", `→ working → completed`.

AgentCard: [agent_card.json](agent_card.json). It advertises two skills (draft-ticket-reply,
triage-ticket), JSON/text in and out, and admin session-cookie auth.

**C-01 with the policy worker returning 500.** What happened: the task ended `completed`,
with a no-answer reply and no sign of the error. What should have happened: the
policy-lookup subtask goes to `failed` (a 500 is not something the ticket owner can fix by
answering a question). The parent ticket task then goes to **`input-required`**, waiting
for the agent's ticket owner to decide whether to retry, send it to Billing Review or reply
by hand. It should not report `completed`. `input-required` is right for the parent because
there is a human owner who can unblock it. `failed` is right for the worker because it
cannot recover on its own.

**What A2A gives you over a plain REST call to the worker:**
1. A task has a state a caller can read (`working` / `input-required` / `failed` /
   `completed`), so a dead worker shows up as a state instead of an exception the
   orchestrator can quietly swallow, which is exactly what happened here.
2. The worker publishes its skills and auth on a card, so the orchestrator can find workers
   and know what they accept without hard-coded URLs and payload shapes.
