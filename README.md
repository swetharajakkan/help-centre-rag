# Help Centre RAG — billing-migration article drop

Measures two chunking strategies over 6 newly published help-centre articles
that are half prose and half troubleshooting tables, and makes the app refuse
what it cannot source.

**Read [results.md](results.md) first** — it is the deliverable. The code is
here to make those numbers reproducible.

- `corpus/` — the 6 new articles (frontmatter carries `article_id`,
  `product_area`, `last_updated`)
- `backend/app/chunkers.py` — `fixed_window` (the pipeline's existing chunker)
  and `structure_aware` (never separates a table row from its header row)
- `backend/app/embeddings.py` — the **frozen** scorer: bge-small-en-v1.5 +
  BM25 + fixed fusion weight. Not modified when chunkers change, so the
  chunker is the only variable.
- `backend/app/generation.py` — grounded answering with a forced refusal:
  no best-judgement escape hatch in the prompt, plus `verify()`, which drops
  in code any claim whose `supporting_quote` is not verbatim in its cited chunk
- `backend/eval/` — the harness and its outputs (`search_dump.md`,
  `filter_demo.md`, `generation_transcripts.md`, `bonus.md`)
- `DIFF.md` — the second chunker + metadata-fields diff
- `frontend/` — React UI: side-by-side chunker comparison and a grounded ask box

Only the 6 new articles are indexed. The historical corpus is not re-indexed.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python backend/eval/run_eval.py
.venv/bin/uvicorn backend.app.main:app --port 8000
cd frontend && npm install && npm run dev
```

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
half a second, and unsets `ANTHROPIC_API_KEY` so no request is made. The
`TestShippedCalibration` tests reproduce the numbers in `results.md` and run
only under `HELP_CENTRE_TEST_REAL_EMBED=1`, since those are a property of
bge-small-en-v1.5 rather than of the code.
