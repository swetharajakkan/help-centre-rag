"""FastAPI service for the help-centre RAG app."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .generation import answer_auto, api_key_present
from .ingest import build_index, load_articles

INDEXES: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Index the 6 new articles only. The historical corpus is NOT re-indexed."""
    for strategy in ("fixed_window", "structure_aware"):
        INDEXES[strategy] = build_index(strategy)
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


class SearchRequest(BaseModel):
    query: str
    strategy: str = "structure_aware"
    k: int = 5
    product_area: str | None = None


class AskRequest(BaseModel):
    question: str
    strategy: str = "structure_aware"
    k: int = Field(default=3, ge=1, le=10)
    product_area: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "generation_engine": "claude-opus-5" if api_key_present()
                             else "extractive-deterministic",
        "strategies": {s: len(i.records) for s, i in INDEXES.items()},
        "articles_indexed": len(load_articles()),
        "historical_corpus_reindexed": False,
    }


@app.get("/api/product_areas")
def product_areas() -> dict:
    areas = sorted({r.meta.get("product_area", "")
                    for r in _index("structure_aware").records if r.meta.get("product_area")})
    return {"product_areas": areas}


@app.post("/api/search")
def search(req: SearchRequest) -> dict:
    where = {"product_area": req.product_area} if req.product_area else None
    return {
        "query": req.query,
        "strategy": req.strategy,
        "filter": where,
        "results": _index(req.strategy).search(req.query, k=req.k, where=where),
    }


@app.post("/api/compare")
def compare(req: SearchRequest) -> dict:
    """Same query, both chunkers, everything else held constant."""
    where = {"product_area": req.product_area} if req.product_area else None
    return {
        "query": req.query,
        "filter": where,
        "by_strategy": {
            s: _index(s).search(req.query, k=req.k, where=where)
            for s in ("fixed_window", "structure_aware")
        },
    }


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    where = {"product_area": req.product_area} if req.product_area else None
    return answer_auto(_index(req.strategy), req.question, k=req.k, where=where)


@app.get("/api/chunk/{chunk_id:path}")
def chunk(chunk_id: str) -> dict:
    """Resolve a citation. Every chunk_id in an answer must resolve here."""
    strategy = chunk_id.split("::", 1)[0]
    rec = _index(strategy).get(chunk_id)
    if rec is None:
        raise HTTPException(404, "chunk_id does not resolve")
    return {"chunk_id": rec.chunk_id, "text": rec.text, "meta": rec.meta}
