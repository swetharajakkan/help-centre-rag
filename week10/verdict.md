# Verdict

- Sunk-cost check, said out loud: we spent a week building the squad, and that week is not evidence. It is the reason we would want it to win, so it gets no weight below.
- Pass rate: squad 10/10 vs single 10/10 on the same 10 Week-6 cases and the same judge.
- Tokens: squad 31,903 vs single 28,231 (1.1x); cost per ticket $0.0203 vs $0.0151.
- Latency: p50 2.19s vs 1.33s, p99 3.81s vs 2.44s.
- Single agent with parallel tool calls: 10/10, 28,291 tokens. These tickets need one search each, so there is nothing to run in parallel: it behaves like the single agent (race 2 is where it differs).
- Failure: with the policy worker returning 500 on C-01 the squad degraded silently (no retry, no error surfaced) — a failure mode the single agent does not have.
- VERDICT: KILL — no pass-rate gain to pay for 1.1x the tokens and a slower p99. Ship the single agent; we tried it and it lost.
