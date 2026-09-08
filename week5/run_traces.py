"""Run the frozen population through the real assistant and write a trace log.

This does not modify the assistant. It calls the same functions, in the same
order, that `generation.answer_extractive` calls, and records what passes
between them:

    index.search(...)  ->  extractive_engine(...)  ->  verify(...)

FIELDS THAT DID NOT EXIST BEFORE THIS FILE, and are added here
--------------------------------------------------------------
The shipped SSE trace (`chat._trace`) carries rank, chunk_id, article_id,
product_area, section, score, dense, bm25, rerank_score and text. Everything
below was absent and is added so a trace can be replayed from itself:

  * prompt_version / system_prompt_sha256 -- no prompt version existed at all
  * engine, model, and the decoding parameters
  * raw engine output, pre-verification (only the verified survivor was ever
    visible, so a claim dropped by verify() left no evidence behind)
  * rejected_claims with the reason each was dropped
  * the grounding gate's score, uncovered anchors and refusal text
  * code_version (git commit) and corpus_sha256, so a replay can prove it ran
    against the same code and the same articles
  * request params as resolved (k, mode, rerank on/off, product_area filter)

WHAT STILL CANNOT BE RECONSTRUCTED, and is recorded as unknown
--------------------------------------------------------------
  * The real user. These questions are generated, not observed, so no session
    id, no ticket id, no follow-up turn and no user reaction exists.
  * Wall-clock latency under production load; timings here are from this box.
  * The LLM path. ANTHROPIC_API_KEY is unset, so every trace runs the
    deterministic extractive engine. Traces of the claude-opus-5 path do not
    exist and none are invented.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

os.environ.setdefault("HELP_CENTRE_RERANK", "1")

from backend.app import generation
from backend.app.generation import (api_key_present, extractive_engine,
                                    grounding, verify)
from backend.app.ingest import build_index
from backend.app.rerank import RERANK_CANDIDATES, RERANK_MODEL, rerank_enabled

PROMPT_VERSION = "extractive-v1"      # assigned here; none existed before


def corpus_sha() -> str:
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(ROOT, "corpus", "*.md"))):
        h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def code_version() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", ROOT, "rev-parse", "HEAD"], text=True).strip()[:12]
    except Exception:
        return "unknown"


def params_block() -> dict:
    """Everything that decides the output, other than the question itself."""
    return {
        "engine": "claude-opus-5" if api_key_present() else "extractive-deterministic",
        "model": (generation.MODEL if api_key_present()
                  else "extractive-deterministic (no LLM)"),
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": hashlib.sha256(
            generation.SYSTEM.encode()).hexdigest()[:16],
        "decoding": ({"max_tokens": 16000, "thinking": "adaptive",
                      "output_format": "json_schema"} if api_key_present()
                     else {"deterministic": True, "temperature": None}),
        "embedding_dense_weight": generation and __import__(
            "backend.app.embeddings", fromlist=["DENSE_WEIGHT"]).DENSE_WEIGHT,
        "rerank_model": RERANK_MODEL,
        "rerank_candidates": RERANK_CANDIDATES,
        "grounding_floor": generation.GROUNDING_FLOOR,
        "coverage_floor_week3_metric": generation.COVERAGE_FLOOR,
        "max_claims": generation.MAX_CLAIMS,
        "min_claim_chars": generation.MIN_CLAIM_CHARS,
        "min_claim_words": generation.MIN_CLAIM_WORDS,
        "code_version": code_version(),
        "corpus_sha256": corpus_sha(),
    }


def hit_trace(h: dict) -> dict:
    return {"rank": h["rank"], "chunk_id": h["chunk_id"],
            "article_id": h["meta"].get("article_id"),
            "section": h["meta"].get("section", ""),
            "last_updated": h["meta"].get("last_updated"),
            "score": h["score"], "dense": h["dense"], "bm25": h["bm25"],
            "rerank_score": h.get("rerank_score")}


def run_one(index, row: dict, params: dict) -> dict:
    q = row["question"]
    k = row["k"]
    where = {"product_area": row["product_area"]} if row["product_area"] else None
    mode = row["mode"]
    use_rerank = {"week3": False, "week4": True}.get(mode) if mode else None
    on = rerank_enabled() if use_rerank is None else bool(use_rerank)

    t0 = time.perf_counter()
    hits = index.search(q, k=k, where=where, use_rerank=use_rerank)
    retrieval_ms = round((time.perf_counter() - t0) * 1000, 1)

    trace = {
        "trace_id": row["trace_id"],
        "population": "random",
        "template": row["template"],
        "question": q,
        "request": {"strategy": row["strategy"], "k": k, "mode": mode,
                    "product_area": row["product_area"],
                    "rerank_resolved": on},
        "params": params,
        "retrieval": {"ms": retrieval_ms, "n_hits": len(hits),
                      "hits": [hit_trace(h) for h in hits]},
    }

    if not hits:
        trace["grounding"] = None
        trace["raw_engine_output"] = None
        trace["result"] = {"answered": False,
                           "refusal": "No chunks matched the filter.",
                           "claims": [], "rejected_claims": [], "retrieved": []}
        trace["generation_ms"] = 0.0
        return trace

    score, uncovered, refusal = grounding(q, hits, index)
    trace["grounding"] = {"in_corpus_coverage": round(score, 4),
                          "uncovered_anchors": uncovered,
                          "gate_refusal": refusal}

    t1 = time.perf_counter()
    raw = extractive_engine(q, hits, index, use_cross_encoder=on)
    result = verify(raw, hits)
    trace["generation_ms"] = round((time.perf_counter() - t1) * 1000, 1)
    trace["raw_engine_output"] = raw
    trace["result"] = result
    return trace


def main() -> None:
    rows = [json.loads(l) for l in open(os.path.join(HERE, "population.jsonl"))
            if l.strip()]
    index = build_index("structure_aware")
    params = params_block()
    out = os.path.join(HERE, "traces.jsonl")
    with open(out, "w") as fh:
        for i, row in enumerate(rows, start=1):
            tr = run_one(index, row, params)
            fh.write(json.dumps(tr, ensure_ascii=False) + "\n")
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
    print(f"wrote {len(rows)} traces -> {out}")
    print(f"engine={params['engine']} code={params['code_version']} "
          f"corpus={params['corpus_sha256']}")


if __name__ == "__main__":
    main()
