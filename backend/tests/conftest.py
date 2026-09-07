"""Shared fixtures for the backend test suite.

Two things are stubbed so the suite runs offline, fast and deterministically:

* `embed` is replaced with a hashed bag-of-words vectoriser. The real scorer
  (bge-small-en-v1.5) would download ~130MB on first use and is frozen anyway,
  so it is not what these tests are checking. The stub is still lexically
  meaningful — vectors of texts that share tokens have a higher cosine — so
  ranking assertions stay honest. Set `HELP_CENTRE_TEST_REAL_EMBED=1` to run
  the same suite against the real model.
* `ANTHROPIC_API_KEY` is removed, which pins generation to the bundled
  deterministic extractive engine. No network call is made by any test.
* `HELP_CENTRE_RERANK` is forced to `0`. Week 4's cross-encoder ships enabled
  by default in the app, but it would download ~150MB and add ~0.8s per query,
  and every assertion here is about the first-stage retriever, `verify()` and
  the HTTP surface. Set `HELP_CENTRE_RERANK=1` to exercise the reranked path.
  The flag also turns off `generation.answerability()`, which is part of the
  same cross-encoder feature -- so with it at `0` the extractive engine answers
  from whatever was retrieved, and the week3/week4 answer split documented in
  frontend/UI.md needs `HELP_CENTRE_RERANK=1` to reproduce (TestArmSplit).

`store.DATA_DIR` is redirected at a tmp dir so `Index.save()` (called from the
app's lifespan) never writes into `backend/data/`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app import store, uploads  # noqa: E402
from backend.app.embeddings import tokenize  # noqa: E402
from backend.app.ingest import CORPUS_DIR, build_index, load_articles  # noqa: E402

EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "eval")
FAKE_DIM = 256
REAL_EMBED = os.environ.get("HELP_CENTRE_TEST_REAL_EMBED") == "1"

# Keep the suite offline and sub-second: opt into reranking explicitly.
os.environ.setdefault("HELP_CENTRE_RERANK", "0")


def fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic hashed bag-of-words, L2-normalised like the real one."""
    vecs = np.zeros((len(texts), FAKE_DIM), dtype=np.float32)
    for i, text in enumerate(texts):
        for tok in tokenize(text):
            bucket = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % FAKE_DIM
            vecs[i, bucket] += 1.0
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


@pytest.fixture(scope="session", autouse=True)
def _isolated_backend(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.delenv("ANTHROPIC_API_KEY", raising=False)
    mp.setattr(store, "DATA_DIR", str(tmp_path_factory.mktemp("data")))
    # Uploads go to a tmp dir so the suite never reads or writes the real
    # backend/uploads/, and one developer's dropped file cannot change what
    # another developer's test run indexes.
    mp.setattr(uploads, "UPLOAD_DIR", str(tmp_path_factory.mktemp("uploads")))
    if not REAL_EMBED:
        # store.py did `from .embeddings import embed`, so patch the name it
        # actually calls, not the one in embeddings.
        mp.setattr(store, "embed", fake_embed)
    yield
    mp.undo()


@pytest.fixture(scope="session")
def articles():
    """The 6 shipped articles as (source_file, frontmatter, body)."""
    return load_articles()


@pytest.fixture(scope="session")
def structure_index():
    return build_index("structure_aware")


@pytest.fixture(scope="session")
def fixed_index():
    return build_index("fixed_window")


@pytest.fixture(scope="session")
def questions():
    with open(os.path.join(EVAL_DIR, "questions.json")) as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.app.main import app

    # The context manager is required: it runs the lifespan that builds and
    # saves both indexes. Without it every endpoint 400s on an empty INDEXES.
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def corpus_dir():
    return CORPUS_DIR


# --------------------------------------------------------------------------
# Per-area pass/fail summary, printed after the usual pytest output.
# --------------------------------------------------------------------------

AREAS = {
    "TestChunkers": "Chunkers (fixed_window + structure_aware)",
    "TestIngest": "Ingest (chunk ids + required metadata)",
    "TestEmbeddings": "Embeddings (tokeniser, BM25, min-max)",
    "TestIndex": "Index (hybrid search, filtering, persistence)",
    "TestVerification": "Citation verification (verify())",
    "TestGeneration": "Generation (extractive engine + refusals)",
    "TestShippedCalibration": "Shipped calibration (results.md numbers)",
    "TestApi": "API endpoints (HTTP)",
    "TestChatStream": "Chat (SSE stream + week3/week4 modes)",
    "TestDocuments": "Document upload (any type -> indexed + durable)",
    "TestArmSplit": "Week3/Week4 answer split (needs the cross-encoder)",
    "TestImageUploads": "Image upload (OCR -> indexed + checkable)",
}


def pytest_terminal_summary(terminalreporter):
    tally: dict[str, dict[str, int]] = {
        cls: {"passed": 0, "failed": 0, "skipped": 0} for cls in AREAS
    }

    def area_of(report) -> str | None:
        parts = report.nodeid.split("::")
        return parts[1] if len(parts) > 2 and parts[1] in tally else None

    for outcome in ("passed", "failed", "error", "skipped"):
        for report in terminalreporter.stats.get(outcome, []):
            area = area_of(report)
            if area is None:
                continue
            if outcome == "passed" and getattr(report, "when", "call") != "call":
                continue  # setup/teardown pass is not a test result
            tally[area]["failed" if outcome == "error" else outcome] += 1

    if not any(sum(c.values()) for c in tally.values()):
        return

    width = max(len(label) for label in AREAS.values())
    terminalreporter.write_sep("=", "backend areas")
    for cls, label in AREAS.items():
        counts = tally[cls]
        total = sum(counts.values())
        if not total:
            continue
        if counts["failed"]:
            verdict, colour = f"FAILED  ({counts['failed']}/{total} failing)", {"red": True}
        elif counts["passed"]:
            verdict = f"passed  ({counts['passed']}/{total}"
            verdict += f", {counts['skipped']} skipped)" if counts["skipped"] else ")"
            colour = {"green": True}
        else:
            verdict, colour = f"skipped ({counts['skipped']})", {"yellow": True}
        terminalreporter.write(f"{label.ljust(width)}  ")
        terminalreporter.write_line(verdict, **colour)
