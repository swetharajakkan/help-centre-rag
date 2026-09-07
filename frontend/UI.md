# Frontend — app shell, streaming chat, document ingest

A sidebar app with three views. `Chat` is the default and the one that streams.

- Shell and routing: [`src/App.jsx`](src/App.jsx)
- Chat transcript: [`src/Chat.jsx`](src/Chat.jsx) · SSE reader: [`src/sse.js`](src/sse.js)
- Sidebar, upload, document list: [`src/Sidebar.jsx`](src/Sidebar.jsx)
- Styles: [`src/styles.css`](src/styles.css)
- Server: [`../backend/app/chat.py`](../backend/app/chat.py),
  [`../backend/app/uploads.py`](../backend/app/uploads.py),
  [`../backend/app/main.py`](../backend/app/main.py)

```
┌───────────────────────────┬────────────────────────────────────────────────┐
│ ◈ Help Centre RAG         │ [ Chat ] Compare  Documents  ●35 chunks        │
│   BILLING MIGRATION KB    │                    retrieval▾ top k▾ area▾     │
├───────────────────────────┼────────────────────────────────────────────────┤
│ Upload & store documents  │   you ──────────────── "ERR-4033, which token?"│
│   ┌─────────────────────┐ │                                                │
│   │        ↥            │ │   ▸ retrieved 3 chunks in 512 ms · reranked    │
│   │  Drop documents     │ │   Delete the newer of the two tokens…          │
│   │  here               │ │   ↳ structure_aware::BM-002-…::004             │
│   └─────────────────────┘ │                                                │
│                           │   CITED KNOWLEDGE BASE SOURCES                 │
│ Your documents        2   │   [ BM-002 — Troubleshooting ]                 │
│   onboard.md          ✕   │                                                │
│                           │   extractive-deterministic · Week 4 · top 3 ·  │
│ Quick test questions      │   retrieval 512 ms · generation 41 ms          │
│  [ Choose a question… ▾ ] │                                                │
│                           ├────────────────────────────────────────────────┤
│ Clear chat session        │  [ Ask about the billing migration…  ] [ Send ]│
└───────────────────────────┴────────────────────────────────────────────────┘
```

The sidebar holds only what you act on — upload, your documents, the question
picker, clear session. Index and engine status moved to a compact strip in the
top bar (and the chat's empty state), because it is a readout, not a control.

---

## 1. Views

| View | What it does |
|---|---|
| **Chat** | Streamed, grounded answers. One question per turn; each turn is retrieved from scratch. |
| **Compare chunkers** | The Week 3 surface: one query through `fixed_window` and `structure_aware` side by side, everything else held constant. |
| **Documents** | Everything indexed — the 6 shipped articles and anything you have uploaded — with chunk counts and origin. |

Clicking **Chat** in the top nav switches to the chat view; choosing from the
**Quick test questions** dropdown switches to it *and* asks that question. The
dropdown resets after each pick, so the same question can be asked twice in a
row (useful for asking it once per arm). The transcript is client-side only, so
a reload clears it.

Each turn is independent and nothing from earlier turns enters the prompt. That
is deliberate: an answer drawn from conversation history rather than a
retrieved chunk could not satisfy `verify()`, so grounding would be quietly
weaker on turn 2 than on turn 1.

## 2. Controls

| Control | Values | Sends | Effect |
|---|---|---|---|
| **retrieval** | `Week 4 — reranked` (default), `Week 3 — baseline` | `mode` | Which retrieval arm serves this request. §4. |
| **top k** | 1–10 (default 3) | `k` | Chunks retrieved and handed to the answering engine. |
| **area** | `all` or any `product_area` | `product_area` | Exact-match filter applied **before** ranking, so scores are renormalised over the subset and the ordering can genuinely change. |

## 3. Uploading documents

Drop files on the sidebar dropzone, or click it to pick them. **Any file type is
accepted** — there is no `accept` filter on the picker; the server decides what
it can recover text from.

Each accepted file is normalised into the same markdown-with-frontmatter shape
the shipped corpus uses and written to `backend/uploads/`. That is the whole
mechanism: once a dropped file looks like a corpus article, the existing
chunkers, the `REQUIRED_META` validator, the citation contract and both
retrieval arms apply to it unchanged.

| Type | How text is recovered |
|---|---|
| `.md` `.markdown` | kept as-is, including frontmatter it already has |
| `.csv` `.tsv` | converted to a **markdown table**, so `structure_aware` keeps each row attached to its header row |
| `.json` | flattened to `path.to.leaf: value`, one leaf per line |
| `.html` `.htm` `.xml` | tags stripped |
| **images** — png, jpg, gif, webp, heic, tiff, bmp | **read with OCR**, see below |
| anything else | decoded as UTF-8, accepted if it is mostly printable text |

### Images

Drop a screenshot and its text is read out and indexed like any other
document. Images are detected by magic bytes as well as extension, so a
screenshot saved as `.dat` is still handled as one, and they get a 15 MB limit
rather than the 5 MB text limit.

Two OCR engines, tried best-first, mirroring how `generation.py` picks its
answerer — `GET /api/health` reports which exist as `ocr_engines`:

1. **`claude`** — used when `ANTHROPIC_API_KEY` is set. Works on any platform,
   and it reconstructs a screenshotted **table as a markdown table**, which
   matters here because `structure_aware` keeps a table row glued to its
   header row.
2. **`macos-vision`** — Apple's on-device Vision framework. Offline, no model
   download, no API key. It reads line by line and cannot recover table
   structure, so it emits one markdown list item per recognised line.

With neither available, images are refused with instructions rather than
stored — an un-searchable document that appears in the index as if it worked is
worse than a clear rejection. An image containing no readable text is refused
for the same reason.

**The original image is kept** next to its transcript, and the transcript's
frontmatter records `extracted_by` and `original_file`. OCR misreads characters
— in testing, `Fix:` came back as `Fix"` — so an answer quoting a transcript
has to stay checkable against the picture. The UI flags these documents `OCR`.
Deleting removes both files.

Rejected with a reason, rather than indexed as noise: non-image binaries (a
PDF, a .docx), empty files, oversized files, and anything yielding under 40
characters of text. Dropping a mix indexes
what it can and reports the rest — one bad file does not fail the batch.

**Durability.** The normalised markdown on disk is the record of truth, so an
upload survives a restart: the ordinary startup path re-ingests
`backend/uploads/` alongside the corpus. Re-uploading the same filename
*replaces* the document rather than double-indexing it. The ✕ button deletes an
uploaded document and every chunk it produced; shipped corpus articles cannot
be deleted (`404`).

Endpoints: `POST /api/documents` (multipart, repeated `files`),
`GET /api/documents`, `DELETE /api/documents/{stored_name}`.

## 4. The Week 3 / Week 4 switch

Week 4 shipped cross-encoder reranking behind the process-wide
`HELP_CENTRE_RERANK`, and demoed before/after with **two servers**. The UI needs
both arms in one window, so the arm is also a **per-request** argument:

```
mode: "week3"  ->  use_rerank=False   # Week 3 fused ordering
mode: "week4"  ->  use_rerank=True    # + jina-reranker-v1-turbo-en
mode omitted   ->  whatever HELP_CENTRE_RERANK says
```

Open the retrieval trace on any answer: week3 hits show `fused · dense · bm25`,
week4 hits also show `rerank` and are in the cross-encoder's order. The Week 3
fused score is still printed unchanged, so a result can be traced back to what
stage 1 thought of it.

**Retrieval.** The clearest case is **G07** (*"The status endpoint says
halted…"*):

| | rank 1 | rank 2 | rank 3 | gold in top 3? |
|---|---|---|---|---|
| week3 | `BM-001::003` | `BM-005::001` | `BM-001::006` | **no** |
| week4 | `BM-001::003` | **`BM-001::004`** | `BM-001::006` | **yes** |

`BM-001::004` is the status row containing `halted | Stopped by an automated
guardrail | Until support acts`. Over all 12 quick questions at k=3:
**week3 10/12 = 83.3%, week4 11/12 = 91.7%** — the same numbers as
`week4_report.json`. Week 4 costs roughly +0.5–1.0 s per question.

**Answers.** Ask the same question on each arm and one question changes verdict:

| | week 3 | week 4 |
|---|---|---|
| golden questions answered | **11/12** | **12/12** |
| **G11** trial in flight | declines | answers |

G11 is the payoff, and it needs no threshold to produce. On the baseline arm
the term-overlap ranker finds no sentence in the retrieved chunks containing
any of the question's terms, so there is nothing to quote and it declines;
reranking retrieves the trial chunk and the answer is a sentence inside it.

**G12 is the honest bad case.** Its gold chunk is outside the top 3 on *both*
arms — min-max fusion buries it at rank 9, and reranking cannot reach what
retrieval never hands it (`results_week4.md` §8) — so both arms quote a
related-but-wrong sentence and present it as an answer. Making it decline was
tried and reverted: every threshold that rejects G12's week-3 sentence also
rejects the correct answer to Q1. Fixing it needs the retrieval change in
`results_week4.md` §9 item 2 (RRF), not a generation threshold.

The rest of the difference is in answer *content*, not in the verdict: on the
baseline arm G05, G07 and G08 answer confidently while quoting the wrong
sentence. Open the retrieval trace to see it.

Pinned by `TestArmSplit`, which needs the real scorer and the cross-encoder:

```bash
HELP_CENTRE_TEST_REAL_EMBED=1 HELP_CENTRE_RERANK=1 \
  .venv-test/bin/python -m pytest -q -k ArmSplit
```

## 5. The stream

`POST /api/chat` returns `text/event-stream`. `EventSource` cannot send a
request body and this endpoint needs one, so frames are read off `fetch`'s
`ReadableStream` and parsed in [`src/sse.js`](src/sse.js).

| Event | Payload | When |
|---|---|---|
| `meta` | `question, engine, strategy, k, mode, mode_label, reranking, product_area` | once, first |
| `status` | `stage: retrieving \| generating \| answering \| refusing` | at each stage change |
| `retrieval` | `ms`, `hits[]` with `rank, chunk_id, article_id, product_area, section, score, dense, bm25, rerank_score, text` | after retrieval |
| `claim_start` | `index, chunk_id, article_id, section` | per verified claim |
| `delta` | `text` | many, word by word |
| `claim_end` | `index, supporting_quote` | per verified claim |
| `done` | `answered, claims, rejected_claims, retrieved, refusal?, engine, timings` | once, last |
| `error` | `message` | instead of `done`, on an exception |

`delta` events before the first `claim_start` belong to a refusal. An unknown
`mode` is a `400` *before* the stream opens.

### Why the answer is verified before it is streamed

`generation.py`'s contract is that no claim reaches a user until `verify()` has
matched its `supporting_quote` byte-for-byte against the chunk it cites.
Forwarding raw model deltas would break that twice over: the JSON schema emits
`claim` before `supporting_quote`, so the assertion would be on screen before
its evidence, and claims `verify()` later drops would have to be retracted
mid-answer.

So the stream is **staged**. Retrieval is emitted as soon as it finishes, then a
progress stage, then the verified answer typed out claim by claim. Nothing that
fails verification is ever streamed. The consequence, stated plainly: the typing
cadence is a **display effect**, not model latency — both engines return their
answer in one shot. `CHAR_DELAY_S` in `backend/app/chat.py` controls it; `done.timings`
reports the real numbers.

## 6. The grounding gate — what changed, and what it cost

**All 12 golden-set questions are answered offline on the reranked arm (11 on
the baseline), with 17 of 22 pre-registered answer spans recovered.**
Previously all 12 refused, including the 11 where retrieval put the correct
chunk at rank 1.

The old gate (`COVERAGE_FLOOR = 0.65`) weighted every question term by idf, so a
word the corpus has *never* used scored the maximum and always counted as
uncovered. Ticket prose is full of those — "furious", "orange", "callbacks",
"fourteen" — so a realistically phrased question scored low however good the
retrieval was.

`results_week4.md` §9 proposed recalibrating that floor. **Measured, that cannot
work**, and it was swept rather than assumed: golden-set coverage spans
0.12–0.48 while the three out-of-corpus control probes sit at 0.37, 0.47 and
0.59, so the ranges interleave. Five candidate signals were each swept over
every threshold from 0 to 1; none separated the two sets.

The gate now asks a different question — coverage over **only the terms the
corpus actually uses**, which is the sole part of a question the corpus can be
judged against — plus two structural escapes that carry the refusals a floor
cannot:

1. **Coined identifier.** An unknown token containing a digit (`ERR-4099`) means
   the corpus cannot define it. Restricted to digit-bearing tokens so ordinary
   hyphenated words (`re-ran`) do not trip it. → refuses U3.
2. **Perfect coverage with an unknown subject.** Every term the corpus knows is
   already covered, yet the question still turns on vocabulary the corpus has
   never used — so those unknown words *are* the subject, and retrieval matched
   only the generic framing. Generic support vocabulary ("problem", "take",
   "customer") is excluded from this test. → refuses U1.

### Why sentence scores are not used as a threshold

An earlier build refused whenever the sentence about to be quoted scored below
a fixed cross-encoder threshold. It was calibrated on 15 questions and **it was
wrong**. Measured across all 23 labelled questions, the *correct* answer to Q1
(*"What does ERR-4032 mean and what is the fix?"*) scores **-0.65** — below the
out-of-corpus probe U2 at **+0.85**. This cross-encoder scores a markdown table
row low against a terse question however well the row answers it, so its scores
are **not comparable across questions**, and any bar low enough to admit Q1
admits far worse.

Within a single question they are excellent: for Q1 the right row leads the
next candidate by 0.50, and the ordering is right every time. So the
cross-encoder ranks candidate sentences — what it is good at — and does not
gate them. Refusals are carried by the grounding gate, which is measured on
vocabulary rather than on an uncalibrated score.

### The cost, stated plainly

**Refusals went from 3/3 to 2/3.** U2 — *"how do I roll a workspace back from
Ledger v2 to v1"* — is now **answered**, and there is no rollback procedure in
the corpus. Its in-corpus coverage is 0.59, above 8 of the 12 questions that
must answer, so no floor rejects it while admitting them. This is pinned by
`TestGeneration.test_u2_is_the_known_gap_in_the_grounding_gate`, which fails
loudly if a future change fixes it, so the fix gets recorded.

Answer *sentences* are chosen by the Week 4 cross-encoder when the request is on
the reranking arm (the model is loaded either way), falling back to term
overlap otherwise: 18/22 answer spans versus 13/22 for overlap alone, and G07,
G08 and G09 go from quoting a topically adjacent lead-in to quoting the sentence
that answers.

**The LLM path remains the engine to run when correctness matters more than
running for free** — rules 1–5 plus `verify()` are a different kind of signal,
not a better threshold:

```bash
ANTHROPIC_API_KEY=… .venv/bin/uvicorn backend.app.main:app --port 8000
```

The sidebar and every turn's footer name the live engine, so it is never
ambiguous which one produced an answer.

## 7. Run it

```bash
.venv/bin/uvicorn backend.app.main:app --port 8000     # backend
cd frontend && npm install && npm run dev              # http://localhost:5173
```

The dev server proxies `/api` to `127.0.0.1:8000` and streams SSE through that
proxy without buffering. `X-Accel-Buffering: no` and `Cache-Control: no-cache`
are set for deployments behind nginx. An `ErrorBoundary` wraps the view area, so
a render exception shows a message and stack rather than blanking the page.
