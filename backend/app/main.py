"""FastAPI service for the help-centre RAG app."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .chat import MODES, chat_stream, resolve_mode
from .generation import answer_auto, api_key_present
from .ingest import build_index, load_articles, load_uploads, records_for
from .rerank import RERANK_CANDIDATES, RERANK_MODEL, rerank_enabled
from .ocr import available_engines as ocr_engines
from .uploads import Rejected, delete as delete_upload, store as store_upload

INDEXES: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Index the 6 new articles only. The historical corpus is NOT re-indexed."""
    for strategy in ("fixed_window", "structure_aware"):
        # The running app is the one caller that also indexes uploads.
        INDEXES[strategy] = build_index(strategy, include_uploads=True)
        INDEXES[strategy].save()
    yield


app = FastAPI(title="Help Centre RAG", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def _index(strategy: str):
    if strategy not in INDEXES:
        raise HTTPException(400, f"unknown strategy {strategy!r}")
    return INDEXES[strategy]


def _rerank_for(mode: str | None) -> bool | None:
    """`mode` picks the experiment arm per request, so one server can serve
    both. Omitting it keeps the process-wide HELP_CENTRE_RERANK default."""
    try:
        return resolve_mode(mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class SearchRequest(BaseModel):
    query: str
    strategy: str = "structure_aware"
    k: int = Field(default=5, ge=1, le=10)
    product_area: str | None = None
    mode: str | None = None


class AskRequest(BaseModel):
    question: str
    strategy: str = "structure_aware"
    k: int = Field(default=3, ge=1, le=10)
    product_area: str | None = None
    mode: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "generation_engine": "claude-opus-5" if api_key_present()
                             else "extractive-deterministic",
        # Which retrieval arm this process is serving. Week 4's before/after
        # demo is two servers that differ only in this block.
        "reranking": {
            "enabled": rerank_enabled(),
            "model": RERANK_MODEL if rerank_enabled() else None,
            "candidates": RERANK_CANDIDATES if rerank_enabled() else None,
            "arm": "after (week 4)" if rerank_enabled() else "before (week 3)",
        },
        # Per-request arms. `reranking.enabled` above is only the default
        # used when a request sends no `mode`.
        "modes": {m: v["label"] for m, v in MODES.items()},
        "strategies": {s: len(i.records) for s, i in INDEXES.items()},
        "articles_indexed": len(load_articles()),
        "uploaded_documents": len(load_uploads()),
        # Empty list means images will be refused: there is nothing that can
        # read text out of them on this server.
        "ocr_engines": ocr_engines(),
        "indexed_chunks": len(_index("structure_aware").records),
        "historical_corpus_reindexed": False,
    }


def _upload_article(stored_name: str):
    """Re-read one stored upload from disk as (source_file, front, body)."""
    return next((a for a in load_uploads() if a[0] == stored_name), None)


@app.get("/api/documents")
def documents() -> dict:
    """Everything currently indexed, shipped corpus and uploads alike."""
    counts: dict[str, int] = {}
    for rec in _index("structure_aware").records:
        counts[rec.source_file] = counts.get(rec.source_file, 0) + 1
    uploaded = {name for name, _, _ in load_uploads()}
    docs = []
    for source_file, front, _ in load_articles() + load_uploads():
        docs.append({
            "source_file": source_file,
            "article_id": front.get("article_id", ""),
            "title": front.get("title", ""),
            "product_area": front.get("product_area", ""),
            "last_updated": front.get("last_updated", ""),
            "chunks": counts.get(source_file, 0),
            "uploaded": source_file in uploaded,
            "extracted_by": front.get("extracted_by", ""),
            "original_file": front.get("original_file", ""),
        })
    return {"documents": docs, "total_chunks": len(_index("structure_aware").records)}


@app.post("/api/documents")
async def upload_documents(files: list[UploadFile]) -> dict:
    """Drag-and-drop ingest. Any file type may be sent.

    Each accepted file is normalised to markdown-with-frontmatter under
    `backend/uploads/`, chunked by BOTH strategies and added to both live
    indexes, then persisted. Because the normalised file is on disk, a restart
    re-ingests it through the ordinary startup path -- the upload is durable,
    not just resident in memory.
    """
    accepted, rejected = [], []
    for upload in files:
        name = upload.filename or "document"
        try:
            data = await upload.read()
            stored_name, article_id = store_upload(name, data)
        except Rejected as exc:
            rejected.append({"filename": name, "reason": str(exc)})
            continue
        except Exception as exc:  # unreadable stream, permissions, ...
            rejected.append({"filename": name,
                             "reason": f"{type(exc).__name__}: {exc}"})
            continue

        article = _upload_article(stored_name)
        if article is None:
            rejected.append({"filename": name,
                             "reason": "stored but could not be re-read"})
            continue

        added = 0
        for strategy, index in INDEXES.items():
            # Overwrite semantics: a re-upload of the same name replaces the
            # previous chunks instead of indexing the document twice.
            index.remove_source(stored_name)
            new = records_for(strategy, [article])
            index.add(new)
            index.save()
            if strategy == "structure_aware":
                added = len(new)
        accepted.append({"filename": name, "stored_as": stored_name,
                         "article_id": article_id, "chunks": added,
                         "extracted_by": _upload_article(stored_name)[1]
                                         .get("extracted_by", "")})

    if not accepted and rejected:
        # Nothing was indexed -- say why, with the status the UI can branch on.
        raise HTTPException(422, {"accepted": [], "rejected": rejected})
    return {"accepted": accepted, "rejected": rejected,
            "total_chunks": len(_index("structure_aware").records)}


@app.delete("/api/documents/{stored_name}")
def delete_document(stored_name: str) -> dict:
    """Remove an uploaded document and every chunk it produced."""
    if stored_name not in {name for name, _, _ in load_uploads()}:
        raise HTTPException(404, "no uploaded document by that name "
                                 "(shipped corpus articles cannot be deleted)")
    dropped = 0
    for index in INDEXES.values():
        dropped = max(dropped, index.remove_source(stored_name))
        index.save()
    delete_upload(stored_name)
    return {"deleted": stored_name, "chunks_removed": dropped,
            "total_chunks": len(_index("structure_aware").records)}


@app.get("/api/product_areas")
def product_areas() -> dict:
    areas = sorted({r.meta.get("product_area", "")
                    for r in _index("structure_aware").records if r.meta.get("product_area")})
    return {"product_areas": areas}


@app.get("/api/examples")
def examples() -> dict:
    """The Week 4 golden set, served to the UI as one-click questions.

    Read from golden_set.jsonl rather than duplicated in the frontend, so the
    questions the UI offers are exactly the ones the eval harness scores.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "eval",
                        "golden_set.jsonl")
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            g = json.loads(line)
            out.append({
                "id": g["id"],
                "question": g["question"],
                "gold_article": g.get("gold_article"),
                "gold_section": g.get("gold_section"),
                "expected_chunk_id": g.get("expected_chunk_id"),
            })
    return {"examples": out}


@app.post("/api/search")
def search(req: SearchRequest) -> dict:
    where = {"product_area": req.product_area} if req.product_area else None
    return {
        "query": req.query,
        "strategy": req.strategy,
        "filter": where,
        "mode": req.mode,
        "results": _index(req.strategy).search(
            req.query, k=req.k, where=where, use_rerank=_rerank_for(req.mode)),
    }


@app.post("/api/compare")
def compare(req: SearchRequest) -> dict:
    """Same query, both chunkers, everything else held constant."""
    where = {"product_area": req.product_area} if req.product_area else None
    use_rerank = _rerank_for(req.mode)
    return {
        "query": req.query,
        "filter": where,
        "mode": req.mode,
        "by_strategy": {
            s: _index(s).search(req.query, k=req.k, where=where,
                                use_rerank=use_rerank)
            for s in ("fixed_window", "structure_aware")
        },
    }


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    where = {"product_area": req.product_area} if req.product_area else None
    return answer_auto(_index(req.strategy), req.question, k=req.k, where=where,
                       use_rerank=_rerank_for(req.mode))


@app.post("/api/chat")
def chat(req: AskRequest) -> StreamingResponse:
    """Streamed grounded answer, as server-sent events.

    Event order: meta, status(retrieving), retrieval, status(generating),
    then either claim_start/delta/claim_end per verified claim or a streamed
    refusal, then done. See backend/app/chat.py for why only verified text is
    ever streamed.
    """
    _rerank_for(req.mode)  # reject a bad mode with 400 before the stream opens
    where = {"product_area": req.product_area} if req.product_area else None
    return StreamingResponse(
        chat_stream(_index(req.strategy), req.question, k=req.k, where=where,
                    mode=req.mode, strategy=req.strategy),
        media_type="text/event-stream",
        # Without this an intermediary can buffer the whole stream and defeat
        # the point of streaming it.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/chunk/{chunk_id:path}")
def chunk(chunk_id: str) -> dict:
    """Resolve a citation. Every chunk_id in an answer must resolve here."""
    strategy = chunk_id.split("::", 1)[0]
    rec = _index(strategy).get(chunk_id)
    if rec is None:
        raise HTTPException(404, "chunk_id does not resolve")
    return {"chunk_id": rec.chunk_id, "text": rec.text, "meta": rec.meta}
