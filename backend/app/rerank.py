"""Cross-encoder reranking — the ONE retrieval change made in Week 4.

Week 3's retriever scored every chunk once, with a bi-encoder (bge-small) and
BM25 fused by weighted min-max, and returned the top k. Nothing ever looked at
a (query, chunk) pair together.

Failure analysis over the 12-question golden set found both baseline misses
were the same shape: the gold chunk WAS in the corpus and WAS scoring near the
top, just outside k=3 (fused rank 4 for G07, fused rank 9 for G12). That is the
textbook case for a cross-encoder — the candidate is already in hand and only
needs to be ranked correctly.

So: keep the Week 3 fused score exactly as it is, use it as a *recall* stage to
pull RERANK_CANDIDATES chunks, and let a cross-encoder decide the final order.
The bi-encoder, BM25 parameters, fusion weight, chunker, prompt and LLM are all
untouched. The only variable that differs between the before and after runs is
whether this reranking pass runs.
"""
from __future__ import annotations

import os
from functools import lru_cache

# Four cross-encoders were measured on the golden set before this one was
# picked (results_week4.md section 8). The three ms-marco/bge models all scored
# 10/12 -- no better than no reranking at all -- because a markdown table row
# does not look like the web passages they were trained on. jina-reranker-v1
# -turbo-en is the only one that reads a table row correctly, and it is what
# moves the hit rate.
RERANK_MODEL = "jinaai/jina-reranker-v1-turbo-en"
CACHE_DIR = ".fastembed_cache"

# Candidate depth handed to the cross-encoder. Must exceed the deepest rank at
# which a gold chunk was observed in the baseline run (9, for G12); 12 is the
# round number above that, and is ~1/3 of this 35-chunk index.
RERANK_CANDIDATES = 12


def rerank_enabled() -> bool:
    """On by default. `HELP_CENTRE_RERANK=0` restores the Week 3 ordering,
    which is how the 'before' arm of the experiment is run."""
    return os.environ.get("HELP_CENTRE_RERANK", "1") not in ("0", "false", "")


@lru_cache(maxsize=1)
def _encoder():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=RERANK_MODEL, cache_dir=CACHE_DIR)


def rerank(query: str, hits: list[dict]) -> list[dict]:
    """Re-order candidate hits by cross-encoder relevance, renumbering `rank`.

    The Week 3 fused score is preserved on each hit as `score`; the new
    ordering key is exposed separately as `rerank_score`, so a result can
    always be traced back to what the first stage thought of it.
    """
    if len(hits) < 2:
        return hits
    scores = list(_encoder().rerank(query, [h["text"] for h in hits]))
    ranked = sorted(zip(scores, hits), key=lambda p: -p[0])
    return [{**h, "rank": i, "rerank_score": round(float(s), 4)}
            for i, (s, h) in enumerate(ranked, start=1)]
