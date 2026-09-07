"""Server-sent-events chat: one streamed, grounded answer per question.

Why the stream is ordered the way it is
---------------------------------------
The grounding contract in `generation.py` is that no claim reaches a user
before `verify()` has checked its `supporting_quote` byte-for-byte against the
chunk it cites. Streaming the model's raw token deltas would break that: the
JSON schema emits `claim` before `supporting_quote`, so the answer text would
be on screen a second before the evidence that justifies it -- and claims that
verification later drops would have to be retracted mid-answer.

So the stream is staged instead. Retrieval is emitted first (it is real,
finished work and it is what the Week 3 / Week 4 toggle changes), then a
progress stage while the engine composes, then the *verified* answer is typed
out claim by claim. Nothing that fails verification is ever streamed.

The typing cadence is a display effect, not model latency: both engines return
their answer in one shot. `CHAR_DELAY_S` controls it and 0 disables it.
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterator

from .generation import (answer_auto, api_key_present, call_model,
                         extractive_engine, verify)
from .rerank import rerank_enabled

# Typing cadence for the verified answer. Purely cosmetic -- see module docstring.
CHAR_DELAY_S = 0.012

MODES = {
    "week3": {"rerank": False, "label": "Week 3 - fused retrieval, no reranking"},
    "week4": {"rerank": True, "label": "Week 4 - cross-encoder reranking"},
}


def resolve_mode(mode: str | None) -> bool | None:
    """Map a UI mode onto a per-request rerank override.

    None means "whatever HELP_CENTRE_RERANK says", which is how the server
    behaves for clients that do not send a mode.
    """
    if mode is None:
        return None
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODES)}")
    return MODES[mode]["rerank"]


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _trace(hits: list[dict]) -> list[dict]:
    """The retrieval evidence the UI shows above the answer."""
    return [{
        "rank": h["rank"],
        "chunk_id": h["chunk_id"],
        "article_id": h["meta"].get("article_id"),
        "product_area": h["meta"].get("product_area"),
        "section": h["meta"].get("section", ""),
        "score": h["score"],
        "dense": h["dense"],
        "bm25": h["bm25"],
        # Present only on the Week 4 arm; the UI uses its absence to label
        # which arm produced the ordering.
        "rerank_score": h.get("rerank_score"),
        "text": h["text"],
    } for h in hits]


def _type_out(text: str) -> Iterator[str]:
    """Yield `delta` events word by word, keeping whitespace attached."""
    for piece in re.findall(r"\S+\s*", text):
        yield sse("delta", {"text": piece})
        if CHAR_DELAY_S:
            time.sleep(CHAR_DELAY_S * len(piece))


def chat_stream(index, question: str, k: int = 3,
                where: dict | None = None,
                mode: str | None = None,
                strategy: str = "structure_aware") -> Iterator[str]:
    use_rerank = resolve_mode(mode)
    # Resolved once here: it selects the retrieval arm AND tells the extractive
    # engine whether the cross-encoder is available to rank answer sentences.
    # Without this the streamed answer used the weaker term-overlap ranker
    # while /api/ask used the cross-encoder, so the same question gave a worse
    # answer in the chat than over the plain endpoint.
    on = rerank_enabled() if use_rerank is None else bool(use_rerank)
    engine = "claude-opus-5" if api_key_present() else "extractive-deterministic"

    yield sse("meta", {
        "question": question,
        "engine": engine,
        "strategy": strategy,
        "k": k,
        "mode": mode,
        "mode_label": MODES[mode]["label"] if mode in MODES else "server default",
        "reranking": use_rerank,
        "product_area": (where or {}).get("product_area"),
    })

    try:
        yield sse("status", {"stage": "retrieving"})
        t0 = time.perf_counter()
        hits = index.search(question, k=k, where=where, use_rerank=use_rerank)
        retrieval_ms = round((time.perf_counter() - t0) * 1000, 1)
        yield sse("retrieval", {"ms": retrieval_ms, "hits": _trace(hits)})

        if not hits:
            msg = "No chunks matched the filter."
            yield sse("status", {"stage": "refusing"})
            yield from _type_out(msg)
            yield sse("done", {"answered": False, "refusal": msg, "claims": [],
                               "rejected_claims": [], "retrieved": [],
                               "timings": {"retrieval_ms": retrieval_ms,
                                           "generation_ms": 0.0}})
            return

        yield sse("status", {"stage": "generating", "engine": engine})
        t1 = time.perf_counter()
        raw = (call_model(question, hits) if api_key_present()
               else extractive_engine(question, hits, index,
                                      use_cross_encoder=on))
        result = verify(raw, hits)
        generation_ms = round((time.perf_counter() - t1) * 1000, 1)

        if result["answered"]:
            yield sse("status", {"stage": "answering",
                                 "claims": len(result["claims"])})
            for i, c in enumerate(result["claims"]):
                yield sse("claim_start", {
                    "index": i, "chunk_id": c["chunk_id"],
                    "article_id": c["article_id"], "section": c["section"],
                })
                yield from _type_out(c["claim"])
                yield sse("claim_end", {"index": i,
                                        "supporting_quote": c["supporting_quote"]})
        else:
            yield sse("status", {"stage": "refusing"})
            yield from _type_out(result["refusal"])

        yield sse("done", {**result, "engine": engine,
                           "timings": {"retrieval_ms": retrieval_ms,
                                       "generation_ms": generation_ms}})
    except Exception as exc:  # surfaced in the transcript, not swallowed
        yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})


def chat_once(index, question: str, k: int = 3, where: dict | None = None,
              mode: str | None = None) -> dict:
    """Non-streaming equivalent, for curl and for the tests."""
    return answer_auto(index, question, k=k, where=where,
                       use_rerank=resolve_mode(mode))
