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
| `fixed_window` (current) | <<FW_CHUNKS>> |
| `structure_aware` (new) | <<SA_CHUNKS>> |

---

## 1. The 8 questions and their known-correct source

Written by reading the articles. Four of the eight (Q1–Q4) depend on a row
*inside* a troubleshooting table.

<<QUESTIONS>>

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
| `fixed_window` (current chunker) | **<<FW_HIT>>** | <<FW_HIT>> |
| `structure_aware` (new chunker) | **<<SA_HIT>>** | <<SA_HIT>> |

Per-question record:

<<HITTABLE>>

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

<<FILTER>>

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

<<GENERATION>>

Every `chunk_id` above resolves over HTTP at
`GET /api/chunk/{chunk_id}` — e.g.
`curl 'http://127.0.0.1:8000/api/chunk/structure_aware::BM-002-payment-method-migration-errors.md::004'`
returns the chunk whose text contains the quoted ERR-4032 row.

---

## 5. Bonus: structure-aware wins retrieval, loses the answer

<<BONUS>>

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

**`structure_aware` ships.** It scores <<SA_HIT>> against <<FW_HIT>> on the same 8
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
40% more chunks (<<SA_CHUNKS>> vs <<FW_CHUNKS>>) and therefore a larger index and more
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
