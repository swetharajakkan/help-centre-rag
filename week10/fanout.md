# Race 2: when the triage squad is the right call

Race 1 (the 10 Week-6 cases, one issue each) said **kill**: the work is sequential and does not split. This is a separate experiment, declared before it ran, on the one workload the multi-agent pattern is built for: **a ticket with several independent issues, each documented in a different article.**

Same retrieval, same reply renderer, same judge as race 1. Every agent run gets Week 7's budget: 8 model calls, 20,000 tokens.

## Four multi-issue tickets (3-6 codes)

| Arm | Pass | Tokens | Cost/ticket | Mean latency | Biggest single context |
|---|---|---|---|---|---|
| Single agent (one tool call per turn, as built) | 4/4 | 31,792 | $0.0422 | 4.23s | 10,951 |
| Single agent + parallel tool calls | 4/4 | 17,795 | $0.0282 | 3.62s | 5,329 |
| Triage squad (one worker per code, concurrent) | 4/4 | 18,740 | $0.0399 | 4.06s | 1,994 |

## Size sweep: one ticket naming K codes, K = 2..10

| K | Single | Single + parallel | Squad | Single context | Parallel context | Largest squad agent |
|---|---|---|---|---|---|---|
| 2 | PASS 2.2s | PASS 1.9s | PASS 2.5s | 3,661 | 2,978 | 797 |
| 3 | PASS 3.0s | PASS 2.6s | PASS 3.2s | 5,153 | 3,597 | 1,117 |
| 4 | PASS 3.9s | PASS 3.3s | PASS 3.8s | 6,838 | 4,162 | 1,397 |
| 5 | PASS 4.8s | PASS 4.0s | PASS 4.6s | 8,797 | 4,773 | 1,724 |
| 6 | PASS 5.7s | PASS 4.8s | PASS 5.1s | 10,932 | 5,321 | 1,992 |
| 7 | **FAIL** (budget) 3.7s | PASS 5.5s | PASS 5.7s | 9,779 | 5,865 | 2,262 |
| 8 | **FAIL** (budget) 4.0s | PASS 6.3s | PASS 6.4s | 9,810 | 6,470 | 2,594 |
| 9 | **FAIL** (budget) 4.0s | PASS 7.1s | PASS 7.1s | 9,770 | 6,902 | 2,807 |
| 10 | **FAIL** (budget) 4.1s | PASS 7.4s | PASS 7.5s | 9,790 | 7,462 | 3,031 |

## What it shows

- **The single agent as built fails from K = 7.** One tool call per code + policy + reply = K + 2 calls, so 7 codes needs 9 calls against a budget of 8. It is escalated with no answer. The squad passes every size: no agent in it makes more than 2 calls.
- **Context per agent.** The single agent carries every issue in one history (10,932 tokens at K = 6). The squad's largest agent is 3,031 tokens at K = 10 (+279 per code, the orchestrator's synthesis), vs 7,462 for the parallel single agent (+560 per code).
- **Speed: no win.** Workers run concurrently, but the reply's output tokens and the shared CPU retriever dominate, so the squad is about as fast as the parallel single agent, not faster.
- **The honest caveat.** A single agent with parallel tool calls also passes every size here and is cheaper ($0.0282 vs $0.0399 per ticket). On pure lookups, that is the better fix.

## So: when to use the triage squad

Use it when a ticket has **several independent issues and each one needs its own context** (its own article, history, multi-step lookup). The single agent then has to hold all of them in one history: it runs out of calls (measured: from 7 issues) or, with bigger per-issue context, out of tokens. Each squad worker holds one issue and stays small however big the ticket gets.

Do **not** use it for single-issue tickets (race 1: same quality, 1.1x tokens, slower, fails silently), or when the issues are plain lookups a single agent can fetch with parallel tool calls.

Routing rule: single agent by default; triage squad when triage counts more independent issues than the single agent's budget allows (K + 2 > 8), or when each issue's context is large.

Model calls are simulated as in race 1; concurrency, retrieval and grading are real.
