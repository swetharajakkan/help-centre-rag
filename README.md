# Help Centre RAG — billing-migration article drop

Measures two chunking strategies over 6 newly published help-centre articles
that are half prose and half troubleshooting tables, and makes the app refuse
what it cannot source.

**Read [results.md](results.md) first** — it is the deliverable. The code is
here to make those numbers reproducible.

**Week 4** extends this with a retrieval failure study:
[results_week4.md](results_week4.md) — a 12-question golden set, baseline
hit-rate@3, an R/G/Not-In-Corpus failure tally, and one retrieval change
(cross-encoder reranking) measured before and after. **hit-rate@3 83.3% →
91.7%, p50 latency 50 ms → 834 ms — shipped**, enabled by default. Roll back
with `HELP_CENTRE_RERANK=0`, which restores the Week 3 ordering exactly.

- `corpus/` — the 6 new articles (frontmatter carries `article_id`,
  `product_area`, `last_updated`)
- `backend/app/chunkers.py` — `fixed_window` (the pipeline's existing chunker)
  and `structure_aware` (never separates a table row from its header row)
- `backend/app/embeddings.py` — the **frozen** scorer: bge-small-en-v1.5 +
  BM25 + fixed fusion weight. Not modified when chunkers change, so the
  chunker is the only variable.
- `backend/app/generation.py` — grounded answering with a forced refusal:
  no best-judgement escape hatch in the prompt, plus `verify()`, which drops
  in code any claim whose `supporting_quote` is not verbatim in its cited
  chunk. Its offline gate was **reworked** after Week 4: it now answers 12/12
  of the golden set on the reranked arm (was 0/12) and refuses 2/3 of the
  out-of-corpus probes (was 3/3). Both numbers and why no threshold does better are in
  [frontend/UI.md](frontend/UI.md) §6 and `results_week4.md` §11.
- `backend/app/rerank.py` — Week 4's single retrieval change: cross-encoder
  reranking (`jina-reranker-v1-turbo-en`) over the top 12 Week 3 fused
  candidates. Gated by `HELP_CENTRE_RERANK`, default on.
- `backend/eval/` — the harness and its outputs (`search_dump.md`,
  `filter_demo.md`, `generation_transcripts.md`, `bonus.md`), plus Week 4's
  `golden_set.jsonl`, `run_week4.py` and `week4_report.json`
- `DIFF.md` — the second chunker + metadata-fields diff
- `backend/app/chat.py` — the streaming chat endpoint (`POST /api/chat`,
  server-sent events) and the per-request `week3`/`week4` arm switch
- `backend/app/ocr.py` — image ingest: text is read out of a screenshot with
  Claude vision when an API key is set, otherwise Apple's on-device Vision
  framework; the original image is kept beside the transcript
- `backend/app/uploads.py` — drag-and-drop ingest: any dropped file is
  normalised into the corpus's own markdown-with-frontmatter shape under
  `backend/uploads/`, so the existing chunkers, validator and citation
  contract apply to it unchanged and it survives a restart
- `frontend/` — React UI: sidebar app shell with a streaming **Chat** view, a
  Week 3/Week 4 retrieval toggle, a top-k selector, a drag-and-drop document
  dropzone, the side-by-side chunker comparison and a documents table. See
  [frontend/UI.md](frontend/UI.md)

Only the 6 new articles are indexed at startup. The historical corpus is not
re-indexed. Documents dropped through the UI are indexed alongside them and
listed separately in `/api/documents`.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python backend/eval/run_eval.py     # week 3: chunker comparison
.venv/bin/python backend/eval/run_week4.py    # week 4: before/after reranking
.venv/bin/uvicorn backend.app.main:app --port 8000
cd frontend && npm install && npm run dev
```

`run_week4.py` runs both arms in one process and downloads the cross-encoder on
first use for the "after" arm. Reranking costs ~0.78s per query, so a
latency-sensitive search surface should run with `HELP_CENTRE_RERANK=0`.

For a one-command before/after demo of a single question:

```bash
.venv/bin/python backend/eval/demo_week4.py        # G07: MISS -> HIT
```

`results_week4.md` §10 has the full demo runbook, including running the two
arms as two servers. `GET /api/health` reports which arm a server is serving.

Either arm can also be selected **per request** with `"mode": "week3"` or
`"week4"` on `/api/search`, `/api/compare`, `/api/ask` and `/api/chat`, which is
how the UI shows both from one server. Omitting `mode` keeps the
`HELP_CENTRE_RERANK` default, so nothing existing changes behaviour.

Set `ANTHROPIC_API_KEY` to run generation through `claude-opus-5` instead of
the bundled deterministic engine; `/api/health` reports which is live.

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                               # ~0.5s, offline
HELP_CENTRE_TEST_REAL_EMBED=1 .venv/bin/python -m pytest # + the frozen scorer
```

`backend/tests/test_backend.py` covers the chunkers, ingest, the scorer, the
index, `verify()`, the extractive engine and every HTTP endpoint. By default it
stubs `embed` with a hashed bag-of-words vectoriser so the suite runs offline in
half a second, unsets `ANTHROPIC_API_KEY` so no request is made, and pins
`HELP_CENTRE_RERANK=0` so no reranker is downloaded. The
`TestShippedCalibration` tests reproduce the numbers in `results.md` and run
only under `HELP_CENTRE_TEST_REAL_EMBED=1`, since those are a property of
bge-small-en-v1.5 rather than of the code.
