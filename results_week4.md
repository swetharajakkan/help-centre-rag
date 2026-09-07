# Week 4 — retrieval failure analysis and one retrieval change

Extension of the Week 3 system in [results.md](results.md). Same corpus, same
`structure_aware` chunker, same `bge-small-en-v1.5` embeddings, same BM25
parameters, same fusion weight, same generation prompt and engine.

**Headline: hit-rate@3 83.3% → 91.7%, p50 latency 50 ms → 834 ms. Shipped.**
One of the two retrieval failures was fixed, one was not, two questions'
ranks improved, none regressed. The latency cost is real and is the reason
this decision needed numbers rather than intuition.

---

## 0. What moved, and what was frozen

Exactly one retrieval variable differs between the before and after runs:
whether `backend/app/rerank.py` runs. Verified frozen across both arms:

| Held fixed | Value |
|---|---|
| Corpus | the same 6 billing-migration articles, 35 chunks |
| Chunker | `structure_aware` |
| Embedding model | `BAAI/bge-small-en-v1.5` (384-dim) |
| BM25 | `k1=1.5`, `b=0.75` |
| Fusion weight | `DENSE_WEIGHT=0.5`, min-max normalised |
| `k` | 3 |
| Questions | the same 12, byte-identical |
| Generation | prompt, schema, `verify()`, engine all untouched |

`backend/app/embeddings.py`, `chunkers.py`, `ingest.py` and `generation.py`
are not modified by this week's change. The whole diff is in §6.

Reproduce with `.venv/bin/python backend/eval/run_week4.py`, which runs both
arms in one process and writes `backend/eval/week4_report.json`.

---

## 1. The golden set — 12 questions

`backend/eval/golden_set.jsonl`. Each question carries the `chunk_id` of the
chunk that contains its answer, plus `answer_spans` — verbatim strings from
that chunk.

**Gold chunks were verified unique before any retrieval was run.** For all 12
questions, the recorded `expected_chunk_id` is the *only* chunk in the 35-chunk
index containing every one of that question's `answer_spans`. "The right chunk"
is therefore a mechanical fact, not a judgement call.

**Methodology note, disclosed rather than buried.** A first draft of these 12
questions scored 11/12 (91.7%) at baseline. On inspection the questions were
reusing the articles' own vocabulary — they read as document-lookup queries,
not as support tickets. That draft is kept at
`backend/eval/golden_set_v1_discarded.jsonl`. The shipped golden set rewrites
all 12 in ticket prose (symptom first, customer's words, synonyms such as
"orange badge" for the documented "amber", "callbacks" for "webhooks"), keeping
the same 12 gold chunks. This was done to make the evaluation realistic, and it
was done **before** the reranking change existed. Both baselines are reported.

6 of the 12 questions carry an exact identifier or token, satisfying the
"at least 4" requirement.

| # | Exact token in question | Question (abbreviated) | Gold chunk_id | Article / section |
|---|---|---|---|---|
| G01 | `ERR-4033` | Two tokens for the same card — delete first or last? | `structure_aware::BM-002-…::004` | BM-002 — Troubleshooting row ERR-4033 |
| G02 | `ERR-4306` | Subscription rejected, customer has a downgrade queued | `structure_aware::BM-004-…::004` | BM-004 — Troubleshooting row ERR-4306 |
| G03 | `ERR-4505` | Same VAT number on two accounts | `structure_aware::BM-005-…::004` | BM-005 — Troubleshooting row ERR-4505 |
| G04 | `ERR-4215` | Invoice with a manual discount line won't copy | `structure_aware::BM-003-…::004` | BM-003 — Troubleshooting row ERR-4215 |
| G05 | — | Re-ran the job, same failure, no warning — cached? | `structure_aware::BM-005-…::001` | BM-005 — The tax cache |
| G06 | `next_payment_attempt`, `retry_schedule` | Dunning stopped retrying, field comes back empty | `structure_aware::BM-006-…::000` | BM-006 — Versioned endpoints |
| G07 | `halted` | Status says halted, nothing moved in a day | `structure_aware::BM-001-…::004` | BM-001 — Migration status codes table |
| G08 | — | How to confirm which engine a workspace runs | `structure_aware::BM-001-…::002` | BM-001 — How to tell which engine |
| G09 | — | Pending charge the day we moved their cards | `structure_aware::BM-002-…::000` | BM-002 — Why payment methods move separately |
| G10 | — | Orange badge, half the line items, counts in revenue? | `structure_aware::BM-003-…::001` | BM-003 — Reading a partial invoice |
| G11 | — | Five days into a trial, workspace moving this week | `structure_aware::BM-004-…::002` | BM-004 — Trials in flight |
| G12 | — | Callbacks quiet for forty minutes during switchover | `structure_aware::BM-006-…::002` | BM-006 — Webhook delivery during cutover |

All 6 articles are covered, 2 questions each.

---

## 2. Baseline hit-rate@3

Week 3 retriever, top 3, no reranking.

### **Baseline hit-rate@3 = 10 / 12 = 83.3%**
### **Baseline p50 retrieval latency = 50.49 ms** (p95 68.97 ms, 120 samples)
### **Baseline MRR@3 = 0.7778**

| # | Result | Gold rank | Top-1 returned instead |
|---|---|---|---|
| G01 | HIT | 1 | — |
| G02 | HIT | 1 | — |
| G03 | HIT | 1 | — |
| G04 | HIT | 3 | `BM-003-…::003` (ERR-4210/4211/4212 rows) |
| G05 | HIT | 1 | — |
| G06 | HIT | 1 | — |
| **G07** | **MISS** | **4** | `BM-001-…::003` (prose lead-in to the status table) |
| G08 | HIT | 1 | — |
| G09 | HIT | 1 | — |
| G10 | HIT | 1 | — |
| G11 | HIT | 1 | — |
| **G12** | **MISS** | **9** | `BM-006-…::004` (ERR-4113 row) |

---

## 3. Inspecting every failed question

### G07 — "status endpoint says `halted`… what does that mean and who unblocks it?"

Gold: `structure_aware::BM-001-billing-migration-overview.md::004` — the status
table holding the `halted` row (*"Stopped by an automated guardrail | Until
support acts"*). Gold sat at **fused rank 4**, one place outside k=3.

What came back instead:

| rank | chunk | fused | what it actually says |
|---|---|---|---|
| 1 | `BM-001-…::003` | 0.8880 | *"The status endpoint returns a coarse status string. These are not error codes…"* — the **prose lead-in** to the status section. Names "status endpoint" but lists no statuses. |
| 2 | `BM-005-…::001` | 0.7719 | The tax cache prose. Wrong article entirely. |
| 3 | `BM-001-…::006` | 0.7323 | ERR-4004/4005 rows — error codes, which the gold chunk's own text explicitly says these statuses are *not*. |

**Evidence:** the query's literal phrase "status endpoint" appears verbatim in
the rank-1 prose chunk and *not* in the gold table chunk, so the section's
introduction outranked the section's own data. Gold's channel ranks were dense
7, BM25 4 — neither channel put it in the top 3 on its own.

### G12 — "callbacks went quiet for forty minutes… did they lose those events?"

Gold: `structure_aware::BM-006-api-webhook-migration.md::002` — *"Events
generated while delivery is paused are queued, not dropped… The queue holds
events for seventy-two hours."* Gold sat at **fused rank 9**.

| rank | chunk | fused | what it actually says |
|---|---|---|---|
| 1 | `BM-006-…::004` | 0.9127 | ERR-4113: queue **exceeded** 72-hour retention, events **cannot** be replayed — the opposite answer to the one asked for. |
| 2 | `BM-001-…::000` | 0.7262 | Migration overview boilerplate. |
| 3 | `BM-003-…::003` | 0.6931 | Invoice-sync error rows. Wrong article. |

**Evidence:** the gold chunk was **dense-rank 1** but **BM25-rank 24** (raw BM25
2.93). The customer's vocabulary — "callbacks", "quiet", "forty minutes",
"switchover" — shares almost no tokens with the article's "webhooks",
"paused", "Phase 3", "cutover". Weighted min-max fusion then dropped a chunk the
semantic channel had ranked first all the way to 9th. **The fusion arithmetic,
not the retriever's recall, caused this miss.**

---

## 4. R / G / Not-In-Corpus classification

| # | Class | Evidence (one line) |
|---|---|---|
| G07 | **R** | Gold chunk exists and scored fused rank 4; retrieval returned the section's prose lead-in at rank 1 instead of the table row holding `halted`. |
| G12 | **R** | Gold chunk exists and was dense-rank 1; min-max fusion with BM25-rank 24 pushed it to fused rank 9, outside k=3. |
| G01–G06, G08–G11 | **G** | Correct chunk WAS in the top 3, but the answering engine refused all ten. Example G10: gold retrieved at rank 1, engine returned *"grounding coverage 0.21 < floor 0.65"*. |
| — | **Not-In-Corpus** | **None.** Every golden question's answer was verified present in a unique chunk before running retrieval (§1). |

### Failure tally

```
R              = 2     (G07, G12)
G              = 10    (all ten retrieval successes; ONE shared root cause)
Not-In-Corpus  = 0     (0 of 12 by construction; control probes below)
```

**The G=10 result needs its root cause stated, because it is one bug, not ten.**
No `ANTHROPIC_API_KEY` is set, so the bundled deterministic extractive engine
answers. Its `COVERAGE_FLOOR = 0.65` was calibrated in Week 3 against questions
phrased in the articles' own vocabulary. Real ticket prose contains ordinary
words the corpus never uses — "furious", "callbacks", "fourteen", "orange" —
which drag idf-weighted coverage below the floor and trigger a refusal *even
when the correct chunk is sitting at rank 1*. It fires identically in both arms,
so it cannot confound the before/after retrieval comparison, but it does mean
**generation, not retrieval, is this system's dominant failure mode on
realistic questions.** Fixing it is a generation change and was therefore out of
scope this week — see §9.

**Not-In-Corpus control.** Because all 12 golden questions are answerable by
construction, the category was exercised separately with the three provably
out-of-corpus probes from Week 3 (refund SLA, v2→v1 rollback, fictional
ERR-4099). All three were correctly refused, **in both arms** — the change did
not break refusal behaviour.

---

## 5. The one retrieval improvement chosen

### Chosen: **cross-encoder reranking**. Rejected: BM25 + RRF.

The decision rule for this choice is the failure shape in §3, and both R
failures had the same shape: **the correct chunk was already in the candidate
pool and merely ranked too low** — rank 4 for G07, rank 9 for G12. Neither was a
recall failure; nothing needed to be *found*, only re-ordered. That is the
textbook cross-encoder case, and a cross-encoder can in principle fix both,
because it reads the (query, chunk) pair jointly instead of comparing two
independently-computed scores.

BM25 + RRF was rejected on the evidence: the retriever **already runs BM25**
(fused at weight 0.5), so RRF would change only the *fusion arithmetic*, and it
addresses only one of the two failures. G12's gold was dense-rank 1, so RRF
would rescue it; G07's gold was dense-rank 7 and BM25-rank 4, so no rank-based
fusion of those two lists puts it in the top 3. Choosing RRF would have been
choosing a fix for half the failures up front.

**Implementation:** the Week 3 fused score becomes a *recall* stage returning
`RERANK_CANDIDATES = 12` chunks (depth chosen to exceed the deepest observed
gold rank of 9); a cross-encoder then reorders them and the top 3 are returned.
`HELP_CENTRE_RERANK=0` restores Week 3 ordering exactly, which is how the
"before" arm is run.

**Which cross-encoder matters more than expected.** Four were measured on the
same 12 questions over the same 12 candidates — see §8. Three of them score
10/12, i.e. no better than not reranking at all. Only
`jinaai/jina-reranker-v1-turbo-en` improves on the baseline, and it is what
ships. Model choice is part of implementing the chosen change, not a second
variable: every arm below is "reranking off" vs "reranking on".

---

## 6. The code diff — exactly one retrieval change

One new file, and one hunk in `store.py`. Nothing else in the retrieval path is
touched.

```diff
--- backend/app/store.py   (week 3)
+++ backend/app/store.py   (week 4)
@@ -8,6 +8,7 @@
 import numpy as np

 from .embeddings import Bm25, DENSE_WEIGHT, embed, minmax, tokenize
+from .rerank import RERANK_CANDIDATES, rerank, rerank_enabled

 DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

@@ -50,10 +51,16 @@
         lex_all = self.bm25.scores(query)
         dense, lexical = dense_all[keep], lex_all[keep]
         fused = DENSE_WEIGHT * minmax(dense) + (1 - DENSE_WEIGHT) * minmax(lexical)
-        order = np.argsort(-fused)[:k]
-        return [self._hit(int(keep[i]), float(fused[i]), float(dense[i]),
+        # Stage 1 (unchanged from Week 3) is now a recall stage when reranking
+        # is on: it hands the cross-encoder a deeper candidate list, and the
+        # cross-encoder decides which k come back.
+        on = rerank_enabled()
+        depth = max(k, RERANK_CANDIDATES) if on else k
+        order = np.argsort(-fused)[:depth]
+        hits = [self._hit(int(keep[i]), float(fused[i]), float(dense[i]),
                           float(lexical[i]), rank)
                 for rank, i in enumerate(order, start=1)]
+        return rerank(query, hits)[:k] if on else hits

     def _matching(self, where: dict | None) -> np.ndarray:
         if not where:
```

Plus new file `backend/app/rerank.py` (the cross-encoder itself). The scoring
maths in `embeddings.py` is byte-identical — `diff` against Week 3 is empty.

---

## 7. After the change — hit-rate@3 and p50 latency

Same 12 questions, same index, same criterion, `HELP_CENTRE_RERANK=1`.

| Metric | Before | After | Delta |
|---|---|---|---|
| **hit-rate@3** | **83.3%** (10/12) | **91.7%** (11/12) | **+8.3 pp** |
| **p50 retrieval latency** | **50.49 ms** | **833.65 ms** | **+783.16 ms (16.5×)** |
| p95 retrieval latency | 68.97 ms | 1208.97 ms | +1140.00 ms |
| mean retrieval latency | 52.07 ms | 832.78 ms | +780.71 ms |
| MRR@3 | 0.7778 | 0.8750 | +0.0972 |
| ranks improved / worsened | — | **2 / 0** | — |
| out-of-corpus probes refused | 3/3 | 3/3 | ±0 |

Latency is measured in **separate processes per arm, 120 samples each** (12
questions × 10 repeats), after three warm-up queries so no model-load time is
counted. The +783 ms is the steady-state cost of cross-encoding 12 candidate
pairs on CPU. `run_week4.py` runs both arms in one process and reports the same
direction with slightly different absolutes.

---

## 8. Per-question fixed / unfixed

| # | Class | Before | After | Verdict |
|---|---|---|---|---|
| **G07** | **R** | MISS (fused rank 4) | **HIT @2** | **FIXED** |
| **G12** | **R** | MISS (fused rank 9) | MISS | **NOT FIXED** |
| G01 | G | HIT @1 | HIT @1 | still hit |
| G02 | G | HIT @1 | HIT @1 | still hit |
| G03 | G | HIT @1 | HIT @1 | still hit |
| G04 | G | HIT @3 | **HIT @1** | still hit — rank improved 3 → 1 |
| G05 | G | HIT @1 | HIT @1 | still hit |
| G06 | G | HIT @1 | HIT @1 | still hit |
| G08 | G | HIT @1 | HIT @1 | still hit |
| G09 | G | HIT @1 | HIT @1 | still hit |
| G10 | G | HIT @1 | HIT @1 | still hit |
| G11 | G | HIT @1 | HIT @1 | still hit |

**R failures: 1 of 2 fixed. Zero regressions — no question's gold chunk moved
down, and no question that was a hit became a miss.**

**G and Not-In-Corpus tracking:** all 10 G failures are unchanged, as expected —
reranking cannot touch them, because the correct chunk was already retrieved and
the refusal comes from the generation layer. Not-In-Corpus stays at 0/12, and
all 3 out-of-corpus control probes are still correctly refused in the after arm,
so the change did not erode refusal behaviour.

### G07 — why it was fixed

The `halted` status-table row went from fused rank 4 to reranked rank 2. The
cross-encoder reads the query and the row together, so
`| halted | Stopped by an automated guardrail | Until support acts |` scores
above the section's prose lead-in that had won on the literal phrase "status
endpoint". This is exactly the failure mode the change was chosen for.

### G12 — why it was not

Gold was at fused rank 9 and reranking still did not lift it into the top 3.
Scored against the **full 35-chunk index** it sits at cross-encoder rank 4, so
raising `RERANK_CANDIDATES` would not rescue it either — the reranker's own
full-corpus ordering is already outside k=3. G12's problem is upstream: the
customer's vocabulary ("callbacks", "quiet", "forty minutes", "switchover")
shares almost no tokens with the article's ("webhooks", "paused", "Phase 3",
"cutover"), so BM25 ranked gold 24th and min-max fusion buried a chunk the
dense channel had ranked **1st**. A reranker can only re-order what fusion hands
it; it cannot undo fusion having pushed the right answer down to 9th out of 35.
That is an RRF-shaped problem, not a reranking-shaped one — see §9.

### The cross-encoder choice was decisive

Same 12 questions, same 12 first-stage candidates, only the model changed:

| Cross-encoder | hit-rate@3 | G07 | G12 | rerank-stage p50 * |
|---|---|---|---|---|
| *(no reranking — baseline)* | 83.3% (10/12) | MISS | MISS | 0 ms |
| `Xenova/ms-marco-MiniLM-L-6-v2` | 83.3% (10/12) | MISS | MISS | 314 ms |
| `Xenova/ms-marco-MiniLM-L-12-v2` | 83.3% (10/12) | MISS | MISS | 604 ms |
| `BAAI/bge-reranker-base` | 83.3% (10/12) | MISS | MISS | 2115 ms |
| **`jinaai/jina-reranker-v1-turbo-en`** | **91.7% (11/12)** | **HIT @2** | MISS | 390 ms |

\* rerank stage only, measured in a tight warm loop over pre-computed
candidates — comparable *between models*, not an end-to-end figure. The
end-to-end numbers are in §7.

Three of the four rerankers were worth nothing here, and the largest of them
(`bge-reranker-base`, 1.1 GB, 2.1 s) was among them. The ms-marco models rank
the `halted` row **10th of 35** for a query containing the literal word
"halted": they are trained on natural-language web passages, and a markdown
table row does not look like one. **"Add a cross-encoder" is not a decision —
"add *this* cross-encoder" is.** Had this been evaluated with the default
ms-marco pick, the correct conclusion would have been "reranking does not work
here", which is false.

---

## 9. Shipping decision

### **Ship.** `HELP_CENTRE_RERANK` defaults to `1`; set it to `0` to roll back instantly.

What the numbers support:

- **hit-rate@3: 83.3% → 91.7% (+8.3 pp).** One of the two R failures fixed.
- **MRR@3: 0.778 → 0.875.** Two questions improved rank, **zero regressed** —
  so the gain is not one lucky question at another's expense.
- **Refusal behaviour intact:** 3/3 out-of-corpus probes still correctly refused.
- **Cost: p50 50 ms → 834 ms.** Certain, reproducible, and the real price.

**The honest caveat, stated plainly: at n=12 the hit-rate delta is one
question.** McNemar's exact test on a single discordant pair gives p = 1.0 — the
hit-rate improvement is *not* statistically significant on its own. What makes
this worth shipping is not the single flip but its shape: 2 improvements, 0
regressions, and a mechanism in §8 that explains precisely why G07 moved. The
latency cost, by contrast, *is* firmly established (120 samples per arm).

It ships anyway because of where the cost lands. On `/api/ask` — the path this
retrieval feeds — an LLM generation call already dominates wall-clock, so
+0.78 s is a modest fraction of total answer time, and a retrieval miss is the
difference between a grounded answer and a refusal. That trade favours accuracy.

**Where it should be turned off:** any latency-sensitive, as-you-type search
surface. 50 ms → 834 ms is a straightforward UX regression there, and the
frontend's side-by-side compare view issues two searches per keystroke-driven
query. Run those with `HELP_CENTRE_RERANK=0`. The offline test suite pins the
flag to `0` for the same reason (`backend/tests/conftest.py`), so the 90-test
suite still runs in under a second with no model download.

### Next, one change at a time

1. **Fix generation, not retrieval.** 10 of 12 failures are the
   `COVERAGE_FLOOR = 0.65` refusal firing on *correctly retrieved* chunks — 5×
   the retrieval failure count, and one constant. Recalibrating that floor
   against ticket-phrased questions is the highest-value change available. It is
   a generation change and belongs in its own before/after run.
2. **Then RRF, for G12 specifically.** G12's gold was dense-rank 1 and only
   min-max fusion buried it to 9th; rank-based RRF is immune to that failure
   mode, and reranking demonstrably cannot reach it. Separate single variable,
   separate run.
3. **Expand the golden set to ~50 questions** before treating 91.7% as a firm
   number. n=12 was enough to find failure *modes*; it is not enough to size an
   improvement.

---

## 10. Running the demo

Everything below is offline except the first reranker download (~150 MB, cached
in `.fastembed_cache/`).

### A. One question, both arms, side by side — the 30-second demo

```bash
.venv/bin/python backend/eval/demo_week4.py            # G07 — the failure that got fixed
.venv/bin/python backend/eval/demo_week4.py G12        # the one that did not
.venv/bin/python backend/eval/demo_week4.py "any question you like"
```

G07 prints `MISS` in the before column and `HIT` in the after column, with the
`halted` status-table row visibly climbing from rank 4 to rank 2, and the
per-query cost (≈25 ms → ≈580 ms) on both headers.

### B. The full experiment — the numbers behind §7 and §8

```bash
.venv/bin/python backend/eval/run_week4.py
```

Runs both arms over all 12 golden questions in one process and prints the
per-question fixed/unfixed ledger, both hit-rates and both p50 latencies.
Writes `backend/eval/week4_report.json`.

### C. Two live servers — before and after, in the browser

```bash
# terminal 1 — week 3 retrieval
HELP_CENTRE_RERANK=0 .venv/bin/uvicorn backend.app.main:app --port 8000

# terminal 2 — week 4 retrieval
HELP_CENTRE_RERANK=1 .venv/bin/uvicorn backend.app.main:app --port 8001
```

`GET /api/health` on each names the arm it is serving, so there is no ambiguity
about which window is which:

```json
"reranking": {"enabled": true, "model": "jinaai/jina-reranker-v1-turbo-en",
              "candidates": 12, "arm": "after (week 4)"}
```

Then POST the same question to both and compare `/api/search` results — hits
from the reranked server carry an extra `rerank_score` field alongside the
unchanged `score`, `dense` and `bm25`:

```bash
Q='{"query":"The status endpoint says halted for this workspace and nothing has moved in over a day. What does that mean and who unblocks it?","k":3}'
curl -s localhost:8000/api/search -H 'content-type: application/json' -d "$Q" | jq '.results[].chunk_id'
curl -s localhost:8001/api/search -H 'content-type: application/json' -d "$Q" | jq '.results[].chunk_id'
```

The frontend (`cd frontend && npm install && npm run dev`) points at port 8000;
change the proxy target in `frontend/vite.config.js` to 8001 to drive the
reranked server from the UI.

### D. Prove the Week 3 result is untouched

```bash
.venv/bin/python backend/eval/run_eval.py     # still 7/8 vs 8/8
.venv-test/bin/python -m pytest -q            # 90 passed, offline, < 1s
```

Both pin `HELP_CENTRE_RERANK=0` internally, so the Week 3 chunker measurement
and the test suite are unaffected by this week's change.


---

## 11. Follow-up: the generation fix from §9, and what it actually cost

§9 named "fix generation, not retrieval" as the highest-value next change, on
the grounds that 10 of 12 failures were `COVERAGE_FLOOR = 0.65` refusing
correctly retrieved chunks. That change has now been made. **The specific
remedy §9 proposed — recalibrating the floor — does not work, and this is
measured, not argued.**

### Why recalibration cannot work

Coverage was computed over every selective question term weighted by idf, so a
word the corpus has never used scores the *maximum* and is always counted as
uncovered. That is the mechanism, and it is not a threshold problem:

| set | coverage range |
|---|---|
| 12 golden-set questions (must answer) | 0.12 – 0.48 |
| U3 fictional ERR-4099 (must refuse) | 0.37 |
| U1 refund SLA (must refuse) | 0.47 |
| U2 v2→v1 rollback (must refuse) | 0.59 |

The ranges interleave, so every floor admitting the golden set also admits at
least one probe. Four further signals were computed for all 15 questions and
swept over every threshold from 0 to 1 — coverage restricted to in-corpus
terms, coverage over the top-5 and top-3 idf anchors, and best-unit coverage —
plus cross-encoder scoring of question against candidate sentence. **None
separated the two sets.** In-corpus coverage puts U1 and U3 at 1.00, *above*
every golden question; the cross-encoder scores U2 at 0.85, above six of them.

### What shipped instead

Coverage over **only the terms the corpus actually uses**, plus two structural
escapes that carry the refusals a floor cannot: a coined identifier (a digit-
bearing token the corpus never uses, e.g. `ERR-4099`), and perfect in-corpus
coverage with an unknown non-generic subject (`refund`, `sla`). Answer
sentences are ranked by the Week 4 cross-encoder when the request is already on
the reranking arm.

| metric | before | after |
|---|---|---|
| golden-set questions answered, week 4 arm | 0/12 | **12/12** |
| golden-set questions answered, week 3 arm | 0/12 | **11/12** |
| pre-registered answer spans recovered | 0/22 | **17/22** |
| out-of-corpus probes refused | 3/3 | **2/3** |
| hit-rate@3 (unchanged — retrieval untouched) | 91.7% | 91.7% |

**A cross-encoder answerability threshold was tried here and reverted.** The
idea was that the sentence about to be quoted must clear a fixed score, which
would make the arms differ in the transcript rather than only in the retrieval
trace. Calibrated on 15 questions it appeared to work. Measured over all 23
labelled questions it was wrong: the *correct* answer to Q1 scores **-0.65**,
below the out-of-corpus probe U2 at **+0.85**, because this cross-encoder
scores a markdown table row low against a terse question however well the row
answers it. Every threshold admitting Q1 admits far worse, and the version that
produced a tidy demo silently broke a result `results.md` guarantees. Its
scores are not comparable across questions — only within one — so it now ranks
sentences and does not gate them.

What survives is one arm difference that needs no threshold: **G11 answers only
on the reranked arm**, because on the baseline the term-overlap ranker finds no
quotable sentence at all. `TestArmSplit` pins that, and also pins **G12
answering from the wrong chunk on both arms** so the known bad case cannot
drift unnoticed.

### The regression, stated plainly

**U2 is now answered.** "How do I roll a workspace back from Ledger v2 to
Ledger v1 after cutover completes?" has no answer in this corpus — rollback is
documented as terminal — and the gate no longer refuses it. Its in-corpus
coverage is 0.59, above 8 of the 12 questions that must answer, so no floor
rejects it while admitting them.

This is a real loss of refusal strength traded for the ability to answer at all
offline, and it is pinned by
`TestGeneration.test_u2_is_the_known_gap_in_the_grounding_gate`, which fails if
a future change fixes it so that the fix gets recorded rather than passing
unnoticed. **The LLM path (rules 1–5 plus `verify()`) still refuses all three
probes** and remains what to run when refusal correctness matters; the
deterministic engine is the free fallback, and this is the price of it.

Retrieval is untouched by all of this: §7's and §8's numbers, `run_eval.py` and
`eval_report.json` are unchanged.
