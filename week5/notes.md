# Week 5 notes — open coding, replay evidence, prediction

## 0. Where the traces came from

This deployment had **no persistent trace log**. `backend/app/chat.py` streams
a retrieval trace to the browser over SSE and nothing writes it to disk, so
there was no week of traffic to sample. Rather than invent traces, I generated
a question population mechanically from the corpus under a fixed seed and put
it through the **real, unmodified assistant**. Every trace is a genuine system
output. The population is synthetic and that is the main limitation on these
frequencies.

The population was committed to git (`0496465`) **before** the runner existed,
so it provably was not curated against observed failures. 182 traces,
22,083 lines pretty-printed.

| Fact | Value |
| --- | --- |
| Engine | `extractive-deterministic` (`ANTHROPIC_API_KEY` unset) |
| Corpus | 6 articles, 35 chunks, `corpus_sha256=62b822165c07ccc4` |
| Traces | 182 (`week5/traces.jsonl`), 115 answered / 67 refused |

---

## 1. The seeded random sample

**Seed: `20260907`.** Procedure, reproducible by running `week5/sample.py`:

```python
ids    = sorted(trace_id for every trace in traces.jsonl)   # 182 ids
rng    = random.Random(20260907)
SAMPLE = sorted(rng.sample(ids, 20))     # draw 1
REPLAY = rng.choice(ids)                 # draw 2
```

**The 20 selected trace_ids:**

```
T-0004  T-0032  T-0043  T-0049  T-0054  T-0057  T-0060  T-0062  T-0064  T-0066
T-0074  T-0090  T-0096  T-0106  T-0113  T-0130  T-0134  T-0146  T-0157  T-0182
```

**Replay target (draw 2): `T-0015`** — not one of the 20, drawn independently.

The sample and the full trace log were committed (`b1c2703`) before a single
trace was read, so the sample provably precedes the coding.

---

## 2. Open coding — 20 traces, one observation sentence each

Written while reading the traces, before any clustering. These describe what I
saw. **Zero code changes were made during this step**; `git diff` over
`backend/` and `corpus/` between the pre-week-5 baseline and the prediction
commit is empty.

1. **T-0004** — Asked which FX rate applies when a customer pays in a non-plan currency, it answered with two invoice error-code rows and a sentence about hourly usage windows, never said no exchange rate is documented, and I do not know why this cleared the grounding gate at 0.80 when other unanswerable questions did not.
2. **T-0032** — Asked what changes about trials in flight, the first claim correctly said trials are not extended or restarted, and the two claims printed after it were about proration mode and a trial-timestamp error code that the question did not ask about.
3. **T-0043** — Asked whether ERR-4502 and ERR-4301 share a root cause with the filter set to invoicing, every retrieved chunk came from the invoicing article and the reply stated the indexed articles do not cover this, though both codes are written in BM-005 and BM-004.
4. **T-0049** — Asked what ERR-4003 means, it quoted the correct ERR-4003 row and then printed the ERR-4001 and ERR-4002 rows underneath it with no indication they were different errors.
5. **T-0054** — Asked how migration status codes work with the filter set to developer-api, it answered confidently about invoice response fields and a /v2 path error, and the migration status table named in the question was not among the retrieved chunks.
6. **T-0057** — Asked what ERR-4215 means with the filter set to subscriptions, it replied that the indexed articles do not cover ERR-4215, which is written in the BM-003 troubleshooting table.
7. **T-0060** — Asked what ERR-4301 means, it quoted the correct row and then added the ERR-4505 tax row and the ERR-4303 row, so three different error codes with three different fixes appeared in one answer.
8. **T-0062** — A ticket reading "Escalated from tier 1. What does ERR-4038 mean? Please advise." retrieved the chunk containing ERR-4038 at rank 1 and then withheld the answer, saying the question turns on "advis" and "tier", which the articles never mention.
9. **T-0064** — Asked how versioned URLs work, it refused because the articles never mention "url", while the Versioned endpoints section sat at rank 2 behind a BM-001 chunk with a lower fused score, and I do not know why the reranker ordered it that way.
10. **T-0066** — Asked how an expired exemption certificate is handled, the first two claims gave the enforcement rule and the ERR-4503 fix, and a third claim about clearing a reverse-charge flag followed them.
11. **T-0074** — Asked about restoring an original billing anchor with the filter set to billing, it said the indexed articles do not cover this; BM-004 has a Billing anchors section stating a support action is required, and no BM-004 chunk was retrieved.
12. **T-0090** — Asked how to resolve ERR-4213 with the filter set to tax-compliance, it said the indexed articles do not cover ERR-4213, which is written in the BM-003 troubleshooting table.
13. **T-0096** — Asked what ERR-4115 means with the filter set to invoicing, it said the indexed articles do not cover ERR-4115, which is written in the BM-006 troubleshooting table.
14. **T-0106** — Asked whether ERR-4005 and ERR-4112 share a root cause, it refused at a grounding score of 0.38 against a floor of 0.40 and listed "thes", "account" and "hav" among the terms no chunk contained, while the ERR-4112 row was in the retrieved set.
15. **T-0113** — Asked the fix for a line item referencing a retired SKU, it returned exactly one claim, the ERR-4211 row, and nothing else.
16. **T-0130** — Asked what ERR-4504 means, the first claim was the correct row and it was followed by a sentence about the tax cache reading a stale failure and by the ERR-4502 row.
17. **T-0134** — Asked what to tell a customer whose migration halted on a usage guardrail, it returned the ERR-4005 row and the "halted" status-table row and stopped there.
18. **T-0146** — Asked "Can you explain versioned endpoints?" with that exact section retrieved at rank 1 and grounding coverage at 1.0, it refused because the articles never use the word "explain".
19. **T-0157** — A ticket reading "Escalated from tier 1. How do I fix ERR-4036? Please advise." with the filter set to billing scored 0.00 grounding and was refused as not covered, with "escalat" and "err-4036" listed as the missing terms.
20. **T-0182** — Asked how to tell which engine a workspace is on, the first two claims gave the Settings path and the Engine field, and the third claim, taken from the API article, told the reader to read the retry_schedule array instead.

---

## 3. Replay evidence — T-0015

Replayed by `week5/replay.py` using **only** the fields inside the trace
record. `population.jsonl` is not read and nothing is re-derived from the
original run.

**Question:** *"A client is asking about Cards that expire within thirty days
of. What is the detail here?"* — k=5, mode=week4, no filter, rerank=True.

| Stage | Original | Replayed | |
| --- | --- | --- | --- |
| Retrieved chunk_ids, ranks 1–5 | BM-002::002, BM-002::003, BM-005::002, BM-002::005, BM-004::000 | identical | MATCH |
| Fused + rerank scores | `(1.0, 0.179) (0.2746, -1.2709) (0.3647, -1.5337) (0.2868, -2.0988) (0.2918, -2.5061)` | identical | MATCH |
| Grounding coverage | 0.8508 | 0.8508 | MATCH |
| Raw engine output (pre-verification) | — | — | IDENTICAL |
| Final claims | 3 | 3 | IDENTICAL |

**Original output** (from `traces.jsonl`) and **replayed output** are the same
three claims, byte for byte:

```
[BM-002::002] Cards that expire within thirty days of the migration date are deliberately
              skipped rather than re-tokenised, because the provider would reject the token
              at first use.
[BM-002::003] | ERR-4030 | Card network declined the tokenisation request | Ask the customer
              to re-enter the card in Billing then Payment methods; the old vault entry
              cannot be recovered |
[BM-005::002] The exemption certificate expiry date is now enforced: an expired certificate
              makes the customer taxable at the next invoice, where v1 would have kept
              applying the exemption indefinitely.
```

**VERDICT: outputs IDENTICAL.** Full transcript: `week5/replay_T-0015.txt`.

The one field that did not match is `code_version` (trace `0496465`, live
`b1c2703`). `git diff --name-only 0496465 b1c2703 -- backend corpus` returns
nothing, so no assistant code and no article changed between them; the commit
only added week-5 files.

### Fields that did not exist, and were added to make replay possible

The shipped SSE trace carried only rank, chunk_id, article_id, product_area,
section, score, dense, bm25, rerank_score and text. All of the following were
absent and are added by `week5/run_traces.py`:

- `prompt_version` and `system_prompt_sha256` — **no prompt version existed at
  all**; `extractive-v1` is assigned here for the first time.
- `engine`, `model`, and the decoding parameters.
- `raw_engine_output` — the pre-verification output. Only the verified survivor
  was ever visible, so a claim dropped by `verify()` left no evidence behind.
- `rejected_claims` with the reason each was dropped.
- The grounding gate's score, uncovered anchors and refusal text.
- `code_version` and `corpus_sha256`, so a replay can prove what it ran against.
- The request parameters as resolved: k, mode, rerank on/off, product-area filter.

### What could not be reconstructed

- **The user.** These questions are generated, not observed, so there is no
  session id, no ticket id, no follow-up turn and no user reaction. Whether an
  agent accepted or discarded an answer is unrecoverable.
- **Production latency.** Timings are from this machine, not under load.
- **The LLM path.** `ANTHROPIC_API_KEY` is unset, so all 182 traces ran the
  deterministic extractive engine. No trace of the `claude-opus-5` path exists
  and none was invented. Modes 2, 4 and 5 are properties of the extractive
  claim-selection code and may not transfer to the model path.

---

## 4. The dated prediction

Full text: `week5/PREDICTION.md`.
**Commit: `b59531ea493ba01ad8a22e533a3267f300e4f348`** (2026-09-07).

`git diff --name-only 008ad14 b59531e -- backend corpus` returns **0 files** —
the prediction was committed with the assistant untouched.

> **Mode attacked:** "Says the answer isn't documented when the product-area
> filter hid it" (35%, 7/20).
> **Change:** when a filtered search yields a refusal, re-run it once
> unfiltered; and stop the refusal text claiming the corpus is empty while a
> filter was active.

| Measurement | Baseline 2026-09-07 | Predicted by 2026-09-14 |
| --- | --- | --- |
| Refusal rate, filtered questions naming a documented code | 88.5% (23/26) | under 35% (≤9/26) |
| `M1` overall, all 182 traces | 47.4% (37/78) | under 32% (≤25/78) |
| Mode 1 share of a fresh seeded sample of 20 | 35% (7/20) | under 15% (≤3/20) |

Point estimate for `M1` is 26.9%, the rate unfiltered questions already
achieve. **Guards:** out-of-scope refusals stay ≥8/13; total refusals stay ≥40
of 182; the padding mode stays ≤30% of 20. Without these, "refuse less" would
satisfy the prediction.

---

## 5. Why a public benchmark would have missed the top three modes

A public benchmark scores answers against questions someone else wrote, and
those questions never arrive carrying our product-area dropdown, so mode 1 —
where a filter the agent set hides the article and the assistant then blames
the corpus — cannot occur during a benchmark run at all. Mode 2 is invisible
for the opposite reason: a benchmark marks an answer correct when the expected
fix is present, and our answer does contain the correct ERR-4003 row, so
printing the ERR-4001 and ERR-4002 fixes underneath it scores as a clean hit
while a support agent pastes the wrong remediation to a customer. Mode 3 is a
property of how our users type rather than of what they ask — benchmark items
are edited prose, ours arrive with "Escalated from tier 1" and "Please advise"
attached, and it is exactly those words, absent from our six articles, that
trigger the refusal.

---

## 6. Bonus — the curated demo set

`/api/examples` serves `golden_set.jsonl` to the UI as one-click questions, so
those twelve **are** the tickets we show clients. Run at the UI defaults
(`mode=week4`, `k=3`, no filter — nobody touches a dropdown while a client is
watching). Seeded sample of 10, seed `20260907`: `D-G01, D-G03, D-G04, D-G05,
D-G07, D-G08, D-G09, D-G10, D-G11, D-G12`.

### Open coding, 10 demo traces

1. **D-G01** — Returned exactly the ERR-4033 row and nothing else, answering which of the two tokens to delete.
2. **D-G03** — Quoted the correct ERR-4505 row and then printed the ERR-4502 and ERR-4501 rows, neither of which the ticket mentioned.
3. **D-G04** — Quoted the correct ERR-4215 row and then printed the ERR-4212 and ERR-4216 rows, both saying "No action needed", directly under a fix that does require action.
4. **D-G05** — All three claims were the tax-cache passage, in order, and together they answered the question about the silent no-op re-run.
5. **D-G07** — Opened with two scaffolding sentences about status strings not being error codes before reaching the "halted" row that actually answers who unblocks it.
6. **D-G08** — Gave the API field for reading the engine version, and did not quote the Settings then Billing then Advanced path from the chunk it retrieved at rank 1.
7. **D-G09** — Three claims, all from the re-tokenisation passage, stating no money moves and that a pending charge is ordinary usage.
8. **D-G10** — Three claims about the amber badge, the partial-invoice definition and what sync copies, all from the invoicing article.
9. **D-G11** — Answered that the trial keeps its end timestamp, then added a claim about re-tokenising cards and one about the seven-day Phase 2 floor, neither about trials.
10. **D-G12** — Asked about a forty-minute webhook gap, it quoted the ERR-4113 row saying dropped events cannot be replayed, then a tax-ID revalidation row, while the "Webhook delivery during cutover" section that says events are queued and redelivered was not retrieved.

### The two numbers

| | Random sample | Curated demo set |
| --- | ---: | ---: |
| **Mode 1** — "says it isn't documented when the filter hid it" | **35%** (7/20) | **0%** (0/10) |
| Mode 2 — "prints fixes for codes nobody reported" | 25% (5/20) | 30% (3/10) |
| Mode 3 — "refuses over 'please advise' / 'explain'" | 15% (3/20) | 0% (0/10) |
| Mode 4 — "confident answer that doesn't address the question" | 10% (2/20) | 10% (1/10) |
| Refused anything at all | 67/182 | 0/12 |

Structural measurements over both populations:

| | Random (182) | Demo (12) |
| --- | ---: | ---: |
| Requests with a product-area filter | 52 | **0** |
| Traces at in-corpus coverage ≥ 0.999 | 66 | **0** |
| Mean question length, words | 12.7 | **28.4** |

### What the team has been telling itself

For a month we have been saying the assistant is solid and what is left is
edge cases, and the demo set agrees: all twelve golden questions answer, none
refuse, and nothing visibly goes wrong. But the two modes that account for
half of the random sample cannot occur in a demo, and they cannot occur for
reasons that have nothing to do with the assistant being right. Nobody touches
the product-area dropdown while a client is watching, so mode 1 — our largest
at 35% — has never once fired in front of anyone. And our demo questions run
28.4 words against 12.7 in the random sample; that length holds in-corpus
coverage between 0.42 and 0.79 for all twelve, always under the 0.999 that
arms the "question turns on words the corpus never mentions" refusal, so mode
3 has never fired either. Mode 2 is the one that does show up in demos, at 30%
versus 25% — we have been looking straight at it and reading it as
thoroughness, because when the client does not know which error code they
reported, three fixes look more helpful than one. What we have actually been
demonstrating for a month is that the assistant works on long, carefully
written, unfiltered questions. We then told ourselves that was the assistant
working.
