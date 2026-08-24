# Billing-migration article drop — chunking measurement

## 0. Scope, and what was deliberately not done

**Only the 6 new articles were indexed.** The historical corpus was not
re-indexed, not touched, and not loaded. `GET /api/health` reports
`"historical_corpus_reindexed": false` and `"articles_indexed": 6`. Re-indexing
history would have burned the whole session on plumbing and produced no
measurement, and the measurement is the deliverable.

**Exactly one variable moved between the two runs.** The embedding model
(`BAAI/bge-small-en-v1.5`, 384-dim), the BM25 parameters (`k1=1.5`, `b=0.75`),
the dense/lexical fusion weight (`0.5`), `k=5`, and the 8 questions are byte
identical across both runs. `backend/app/embeddings.py` is untouched by the
commit that adds the second chunker — verifiable with
`git diff 1a12fbc 90b6ebb -- backend/app/embeddings.py`, which is empty.

**The questions were written before retrieval existed.** Commit `bcc0234`
contains the corpus and all 8 questions with their gold spans. `chunkers.py`,
`store.py` and every line of retrieval code first appear in commit `1a12fbc`.
The hit criterion was pre-registered in `questions.json` at that first commit,
not chosen after seeing results.

### Ingest metadata

Every chunk carries `source_file`, `article_id`, `product_area` and
`last_updated`. `ingest.validate()` raises on any chunk missing one, so a
chunk with no `source_file` fails the ingest rather than shipping silently.

| Strategy | Chunks from the 6 articles |
|---|---|
| `fixed_window` (current) | 25 |
| `structure_aware` (new) | 35 |

---

## 1. The 8 questions and their known-correct source

Written by reading the articles. Four of the eight (Q1–Q4) depend on a row
*inside* a troubleshooting table.

| # | Type | Question | Known-correct article / section |
|---|---|---|---|
| Q1 | table row | What does ERR-4032 mean and what is the fix? | **BM-002** — Troubleshooting (table row ERR-4032) |
| Q2 | table row | Reconciliation found a rounding difference above one cent on an invoice. What should I do? | **BM-003** — Troubleshooting (table row ERR-4217) |
| Q3 | table row | Our client gets a 409 idempotency_reuse error on the billing API after migrating. What is the documented fix? | **BM-006** — Troubleshooting (table row ERR-4111) |
| Q4 | table row | A customer's tax ID failed revalidation. What is the fix? | **BM-005** — Troubleshooting (table row ERR-4501) |
| Q5 | prose | How long does a workspace have to stay in the dual-write phase, and can support waive it? | **BM-001** — Cutover phases |
| Q6 | prose | What happens to a subscription whose billing anchor is the 31st after it migrates during a short month? | **BM-004** — Billing anchors |
| Q7 | prose | A customer's card expires next month. Does that block their billing migration? | **BM-002** — Expired and soon-to-expire cards |
| Q8 | prose | A customer got a credit note during dual-write and their v2 totals now look too high. Should we issue another credit note? | **BM-003** — Credit notes are the common surprise |

**Hit criterion, pre-registered in `backend/eval/questions.json`:** a question
counts as a hit only if **at least one single chunk in the top 5 contains every
one of its `must_contain` spans** (whitespace-normalised, case-insensitive).
For the table questions those spans are the error code *and* its fix text, so a
chunk that carries the code but loses the fix across a boundary is scored a
miss — which is exactly the failure being hunted.

---

## 2. Hit-in-top-5: two numbers over the same 8 questions

| Strategy | hit-in-top-5 | union@5 |
|---|---|---|
| `fixed_window` (current chunker) | **7/8** | 7/8 |
| `structure_aware` (new chunker) | **8/8** | 8/8 |

Per-question record:

| # | Type | `fixed_window` (current) | `structure_aware` (new) |
|---|---|---|---|
| Q1 | table row | **MISS** | HIT @ rank 1 |
| Q2 | table row | HIT @ rank 1 | HIT @ rank 1 |
| Q3 | table row | HIT @ rank 3 | HIT @ rank 2 |
| Q4 | table row | HIT @ rank 1 | HIT @ rank 1 |
| Q5 | prose | HIT @ rank 1 | HIT @ rank 1 |
| Q6 | prose | HIT @ rank 2 | HIT @ rank 1 |
| Q7 | prose | HIT @ rank 1 | HIT @ rank 1 |
| Q8 | prose | HIT @ rank 1 | HIT @ rank 1 |
| **TOTAL** | | **7/8** | **8/8** |

`union@5` allows the evidence to be assembled across all five retrieved chunks
rather than found in one. It does not rescue Q1: the missing half of the
ERR-4032 fix is not in the top 5 at all, it is in a chunk ranked outside it.

Full search-only dump for all 8 questions under both strategies, with scores
and the raw chunk text: **`backend/eval/search_dump.md`** (1,200+ lines,
regenerate with `python backend/eval/make_dumps.py`).

### The retrieval that embarrassed me

**Q1, `fixed_window`, rank 1, score 0.8412 — it looks like a clean win and it
is not.** The chunk contains the string `ERR-4032`. If I had eyeballed the
retrieved text and called it "looks right", I would have shipped this. Here is
where the chunk ends:

```
| ERR-4032 | The stored payment token was issued by the legacy vault and has
no provider-side equivalent | Ask the customer to re-add the payment
```

The 900-character window closed mid-sentence, four words into the fix. The rest
of the instruction — *"...method, then re-run the migration for that workspace
only from the Migration panel using **Retry failed instruments**. Do not re-run
the full workspace migration"* — landed in
`fixed_window::BM-002-...::003`, which does **not** appear in the top 5.

**Diagnosis.** The window boundary fell inside a table row. Retrieval was not
wrong about the article, the section, or even the row — the ranking was
excellent. The chunker destroyed the evidence before retrieval ever ran. A
generator handed this chunk sees a fix that terminates at "re-add the payment"
and has to either refuse or invent the remainder. This is precisely the
mechanism by which ERR-4032 gets an invented fix, and the ranking score gives
no warning at all: **0.8412 and rank 1 on a chunk that cannot answer the
question.** The number that catches it is the pre-registered span check; no
amount of looking at the text would have.

### A second thing I got wrong

I wrote a prediction into `questions.json` before running the filter demo:
that the unfiltered top-1 for the idempotency query would come from BM-006
(`developer-api`), because its idempotency prose is denser and names the 409.
It did not — BM-002 (`payments`) won unfiltered at 1.0000 vs 0.9055. The
filter demo below therefore runs in the opposite direction to the one I
planned. The prediction is left in the file rather than quietly edited.

### A third: the refusal gate I tried first does not work

The obvious refusal gate is a retrieval-score floor. Measured on this corpus it
is unusable. Raw top-1 cosine:

| Question | cosine | in corpus? |
|---|---|---|
| U2 "roll back to Ledger v1" | 0.798 | **no** |
| Q5 "dual-write minimum" | 0.743 | yes |
| Q1 "ERR-4032" | 0.703 | yes |

An out-of-corpus question outranks two real ones. **Any floor that rejects U2
also rejects Q1 and Q5.** The refusal had to move to claim level instead —
see §4.

---

## 3. Metadata filter changing retrieval

`product_area` is an exact-match filter applied to the candidate set **before**
ranking, so scores are renormalised over the filtered subset and the ordering
genuinely changes rather than being truncated.

**Query:** `idempotency key reuse during migration retries`  ·  strategy `structure_aware`, k=5

### UNFILTERED (all product areas)
```
#1  score=1.0     dense=0.8094  bm25=11.2142  [payments      ] structure_aware::BM-002-payment-method-migration-errors.md::001
      Payment Method Migration Errors > Idempotency during retries
#2  score=0.9055  dense=0.7783  bm25=10.2661  [developer-api ] structure_aware::BM-006-api-webhook-migration.md::001
      API and Webhook Changes for the Billing Migration > Idempotency keys on the billing API
#3  score=0.6693  dense=0.6883  bm25=8.3644   [developer-api ] structure_aware::BM-006-api-webhook-migration.md::003
      API and Webhook Changes for the Billing Migration > Troubleshooting
#4  score=0.4084  dense=0.6858  bm25=2.6057   [payments      ] structure_aware::BM-002-payment-method-migration-errors.md::006
      Payment Method Migration Errors > Troubleshooting
#5  score=0.3414  dense=0.6748  bm25=1.5219   [developer-api ] structure_aware::BM-006-api-webhook-migration.md::004
      API and Webhook Changes for the Billing Migration > Troubleshooting
```

### FILTERED product_area = developer-api
```
#1  score=1.0     dense=0.7783  bm25=10.2661  [developer-api ] structure_aware::BM-006-api-webhook-migration.md::001
      API and Webhook Changes for the Billing Migration > Idempotency keys on the billing API
#2  score=0.694   dense=0.6883  bm25=8.3644   [developer-api ] structure_aware::BM-006-api-webhook-migration.md::003
      API and Webhook Changes for the Billing Migration > Troubleshooting
#3  score=0.3173  dense=0.6748  bm25=1.5219   [developer-api ] structure_aware::BM-006-api-webhook-migration.md::004
      API and Webhook Changes for the Billing Migration > Troubleshooting
#4  score=0.1964  dense=0.6483  bm25=0.3504   [developer-api ] structure_aware::BM-006-api-webhook-migration.md::000
      API and Webhook Changes for the Billing Migration > Versioned endpoints
#5  score=0.0688  dense=0.5642  bm25=1.7143   [developer-api ] structure_aware::BM-006-api-webhook-migration.md::002
      API and Webhook Changes for the Billing Migration > Webhook delivery during cutover
```


**Top-1 changes:** `BM-002-...::001` (`payments`, dense 0.8094) → `BM-006-...::001`
(`developer-api`, dense 0.7783). Both are legitimate answers to a
deliberately ambiguous query — BM-002 is about idempotency in the
re-tokenisation *worker*, BM-006 is about idempotency on the *public billing
API*. Without the filter a developer asking about their 409 gets the internal
worker doc first. Note the raw `dense` and `bm25` columns are unchanged by
filtering, as they must be; only the fused, renormalised `score` and the
ordering move.

---

## 4. Grounded generation: 3 cited answers, 3 forced refusals

**Engine.** No `ANTHROPIC_API_KEY` and no `ant` profile were available on this
machine, so the recorded transcripts were produced by the **deterministic
extractive engine**, labelled `engine: extractive-deterministic` in every
transcript below. The real model path (`claude-opus-5`, adaptive thinking,
`output_config.format` JSON schema) is implemented in
`backend/app/generation.py::call_model` and activates automatically when a key
is present — `/api/health` reports which engine is live. **The refusals below
are rule-based, not model judgement.** That is a real limitation and it is the
weakest part of this submission.

**The refusal is forced, in two layers, neither of which is advice to a model:**

1. The system prompt (`generation.py::SYSTEM`) contains no "use your best
   judgement" escape hatch. Rule 3 reads: *"You have no other knowledge... Do
   not infer, extrapolate, generalise, or fill gaps. There is no
   best-judgement fallback."* Rule 5: *"A chunk that is merely on the same
   topic is not an answer."*
2. **`verify()` drops claims in code, after the fact.** Every claim must cite a
   `chunk_id` present in the retrieved set *and* carry a `supporting_quote`
   that appears **verbatim** in that chunk. Anything failing either check is
   deleted by Python, not by the model. If nothing survives, the answer is
   replaced with a refusal. A hallucinated fix cannot survive this even if the
   model emits it, because the quote will not be in the chunk.

**Grounding-coverage floor (the extractive engine's refusal trigger).** Because
a score floor does not work (§2), the gate is the idf-weighted fraction of the
question's selective terms that the retrieved chunks actually contain. Rare
terms dominate, so a question hinging on a word the corpus never uses scores
near zero however topically close the retrieved text looks.

**Honest disclosure: this floor is calibrated on these 11 questions, and the
margin is thin.** Answerable questions score 0.70–1.00; out-of-corpus questions
score 0.15–0.59. The floor sits at 0.65, i.e. **0.06 above the worst false
negative (U2 at 0.59) and 0.05 below the worst true positive (Q6 at 0.70).**
That is a narrow gap on a sample of 11 and I would not claim it generalises. It
is a stand-in for model judgement, not a substitute for it.

## Cited answers (3 answerable)

### Q1 — What does ERR-4032 mean and what is the fix?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-002-payment-method-migration-errors.md::004, structure_aware::BM-002-payment-method-migration-errors.md::006, structure_aware::BM-002-payment-method-migration-errors.md::005`

**Answer (one citation per claim):**

1. | ERR-4032 | The stored payment token was issued by the legacy vault and has no provider-side equivalent | Ask the customer to re-add the payment method, then re-run the migration for that workspace only from the Migration panel using Retry failed instruments. Do not re-run the full workspace migration |
   - **cite:** `structure_aware::BM-002-payment-method-migration-errors.md::004` → BM-002 (BM-002-payment-method-migration-errors.md), section “Troubleshooting”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

### Q3 — Our client gets a 409 idempotency_reuse error on the billing API after migrating. What is the documented fix?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-006-api-webhook-migration.md::001, structure_aware::BM-006-api-webhook-migration.md::003, structure_aware::BM-001-billing-migration-overview.md::006`

**Answer (one citation per claim):**

1. Reusing a key that was already used anywhere in the workspace within the last twenty-four hours returns 409 with an idempotency_reuse error body, even if the original request targeted a different endpoint.
   - **cite:** `structure_aware::BM-006-api-webhook-migration.md::001` → BM-006 (BM-006-api-webhook-migration.md), section “Idempotency keys on the billing API”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

2. In v1 an idempotency key was scoped to the endpoint, so the same key could be reused against POST /v1/invoices and POST /v1/charges without conflict.
   - **cite:** `structure_aware::BM-006-api-webhook-migration.md::001` → BM-006 (BM-006-api-webhook-migration.md), section “Idempotency keys on the billing API”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

3. Ledger v2 enforces idempotency keys far more strictly than v1 did.
   - **cite:** `structure_aware::BM-006-api-webhook-migration.md::001` → BM-006 (BM-006-api-webhook-migration.md), section “Idempotency keys on the billing API”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

### Q5 — How long does a workspace have to stay in the dual-write phase, and can support waive it?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-001-billing-migration-overview.md::001, structure_aware::BM-002-payment-method-migration-errors.md::000, structure_aware::BM-004-subscription-proration-migration.md::002`

**Answer (one citation per claim):**

1. A workspace stays in Phase 2 for a minimum of seven days.
   - **cite:** `structure_aware::BM-001-billing-migration-overview.md::001` → BM-001 (BM-001-billing-migration-overview.md), section “Cutover phases”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

2. The seven-day floor is not configurable by support and cannot be waived by an account manager; it exists so the shadow comparison has at least one full weekly billing boundary to check against.
   - **cite:** `structure_aware::BM-001-billing-migration-overview.md::001` → BM-001 (BM-001-billing-migration-overview.md), section “Cutover phases”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

3. Phase 2 (dual-write) makes Ledger v2 authoritative for new usage while Ledger v1 continues to own historical invoices.
   - **cite:** `structure_aware::BM-001-billing-migration-overview.md::001` → BM-001 (BM-001-billing-migration-overview.md), section “Cutover phases”
   - **chunk_id resolves:** YES · **quote verbatim in that chunk:** YES

## Refusal transcripts (3 out-of-corpus)

### U1 — What is the refund SLA for a disputed invoice during the billing migration?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-001-billing-migration-overview.md::000, structure_aware::BM-001-billing-migration-overview.md::005, structure_aware::BM-003-invoice-sync-troubleshooting.md::000`

**REFUSED.**

```
The indexed articles do not cover this (grounding coverage 0.47 < floor 0.65). No retrieved chunk contains: sla, refund. The retrieved chunks are on the same topic but do not state the thing asked for.
```

### U2 — How do I roll a workspace back from Ledger v2 to Ledger v1 after cutover completes?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-001-billing-migration-overview.md::000, structure_aware::BM-001-billing-migration-overview.md::002, structure_aware::BM-001-billing-migration-overview.md::001`

**REFUSED.**

```
The indexed articles do not cover this (grounding coverage 0.59 < floor 0.65). No retrieved chunk contains: back, complet. The retrieved chunks are on the same topic but do not state the thing asked for.
```

### U3 — What does error ERR-4099 mean and how do I fix it?

`engine: extractive-deterministic`  ·  `retrieved (k=3): structure_aware::BM-003-invoice-sync-troubleshooting.md::005, structure_aware::BM-001-billing-migration-overview.md::005, structure_aware::BM-002-payment-method-migration-errors.md::004`

**REFUSED.**

```
The indexed articles do not cover this (grounding coverage 0.15 < floor 0.65). No retrieved chunk contains: err-4099, doe. The retrieved chunks are on the same topic but do not state the thing asked for.
```

**Citation audit: 7/7 claims have a chunk_id that resolves AND a quote verbatim in that chunk.**

**Refusal audit: 3/3 out-of-corpus questions refused.**


Every `chunk_id` above resolves over HTTP at
`GET /api/chunk/{chunk_id}` — e.g.
`curl 'http://127.0.0.1:8000/api/chunk/structure_aware::BM-002-payment-method-migration-errors.md::004'`
returns the chunk whose text contains the quoted ERR-4032 row.

---

## 5. Bonus: structure-aware wins retrieval, loses the answer

**Question (Q4):** A customer's tax ID failed revalidation. What is the fix?
**Known-correct source:** BM-005 / Troubleshooting (table row ERR-4501)
**The complete answer also requires** the prose caveat in BM-005 “The tax cache and why re-running the backfill too early does nothing”.

#### fixed_window

- top-1: `fixed_window::BM-005-tax-id-validation-migration.md::002` (score 0.9925, 897 chars)
- gold row ERR-4501 in top-1: **YES**
- 24-hour-cache caveat anywhere in the k=3 context: **YES**
- rank at which the caveat first appears: **2**
- caveat present in the generated answer: **NO**

Answer produced:

1. | ERR-4501 | Tax ID failed revalidation against the authority | Ask the customer to confirm the ID, correct it if wrong, then re-run the backfill with --force-tax-refresh |  
   `fixed_window::BM-005-tax-id-validation-migration.md::002`
2. | ERR-4503 | Exemption certificate has expired | Collect a new certificate and upload it in Billing then Tax then Certificates. The customer is taxable until it is uploaded |  
   `fixed_window::BM-005-tax-id-validation-migration.md::002`
3. | ERR-4502 | Tax authority endpoint was unreachable during the sweep | No action needed. The sweep retries the unreachable authority on the next daily run |  
   `fixed_window::BM-005-tax-id-validation-migration.md::002`

#### structure_aware

- top-1: `structure_aware::BM-005-tax-id-validation-migration.md::003` (score 1.0, 611 chars)
- gold row ERR-4501 in top-1: **YES**
- 24-hour-cache caveat anywhere in the k=3 context: **NO**
- rank at which the caveat first appears: **4**
- caveat present in the generated answer: **NO**

Answer produced:

1. | ERR-4501 | Tax ID failed revalidation against the authority | Ask the customer to confirm the ID, correct it if wrong, then re-run the backfill with --force-tax-refresh |  
   `structure_aware::BM-005-tax-id-validation-migration.md::003`
2. | ERR-4503 | Exemption certificate has expired | Collect a new certificate and upload it in Billing then Tax then Certificates. The customer is taxable until it is uploaded |  
   `structure_aware::BM-005-tax-id-validation-migration.md::003`
3. | ERR-4502 | Tax authority endpoint was unreachable during the sweep | No action needed. The sweep retries the unreachable authority on the next daily run |  
   `structure_aware::BM-005-tax-id-validation-migration.md::003`


**Two sentences on the tension.** The structure-aware chunker retrieves Q4 more
precisely — a 611-character chunk that is exactly the ERR-4501 row plus its
header, top-1 at a perfect fused score of 1.000, against the fixed window's
sprawling 897-character chunk that happens to straddle the section boundary —
but that precision is achieved by cutting the row away from the prose section
"The tax cache and why re-running the backfill too early does nothing", which
pushes the caveat from **rank 2 down to rank 4** and therefore out of a `k=3`
context entirely. The result is an answer that is correct and useless: it tells
the support engineer to re-run the backfill with `--force-tax-refresh`, and
omits that doing so within 24 hours of the cached failure silently no-ops and
is indistinguishable in the UI from a second genuine failure — so tight chunks
buy you retrieval precision and pay for it in the surrounding context the model
needs to answer *completely*, which is a `k` problem created by a chunking
decision.

---

## 6. Which chunker ships, and why

**`structure_aware` ships.** It scores 8/8 against 7/8 on the same 8
pre-registered questions with every other variable frozen, but the raw score
gap is not the reason — one question is one question, and on a sample of 8 that
delta is not statistically meaningful on its own. The reason is *which*
question moved and *how* it failed. The fixed window's Q1 miss is not a ranking
error that a better embedding or a larger `k` would fix; it is the chunker
handing the generator a truncated remedy (`"Ask the customer to re-add the
payment"`) that reads as complete and terminates four words into the
instruction. That failure is silent, it is invisible to score inspection, and
it is concentrated precisely on the troubleshooting tables that make up half of
this article drop — so its frequency scales with exactly the content we are
ingesting. `structure_aware` makes that class of failure structurally
impossible rather than unlikely: a table row is never emitted without its
header row, and a paragraph is never split. The costs are real and accepted:
40% more chunks (35 vs 25) and therefore a larger index and more
embedding calls, and the precision/completeness regression demonstrated in §5.
**Ship it with `k` raised from 3 to 5 for generation** to buy back the
surrounding prose that tight table chunks drop, and re-measure Q4's caveat rank
after that change.

---

## 7. Reproducing

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python backend/eval/run_eval.py         # the two hit@5 numbers
.venv/bin/python backend/eval/make_dumps.py       # search_dump.md, filter_demo.md
.venv/bin/python backend/eval/run_generation.py   # cited answers + refusals
.venv/bin/python backend/eval/run_bonus.py        # §5
.venv/bin/uvicorn backend.app.main:app --port 8000
cd frontend && npm install && npm run dev         # UI on :5173
```

Set `ANTHROPIC_API_KEY` before `run_generation.py` to produce the transcripts
with `claude-opus-5` instead of the deterministic engine.

## 8. Code diff

| Commit | Contents |
|---|---|
| `bcc0234` | 6 articles + 8 questions with gold spans — **before any retrieval code** |
| `1a12fbc` | The existing pipeline: `fixed_window` chunker, frozen hybrid scorer |
| `90b6ebb` | **The diff asked for:** `structure_aware` chunker, the four required metadata fields with ingest-time validation, and the `product_area` filter |
| `e03b64e` | Eval harness, forced-refusal generation, FastAPI + React |

`git show 90b6ebb` is the second-chunker-and-metadata diff; it is reproduced in
**`DIFF.md`**.
