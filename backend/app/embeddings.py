"""Frozen retrieval scorer.

This module is deliberately boring and is NOT touched when chunkers change.
Both chunking strategies are measured with the exact same embedding model,
the same BM25 parameters and the same fusion weight, so any movement in the
hit rate is attributable to chunking alone.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

import numpy as np

EMBED_MODEL = "BAAI/bge-small-en-v1.5"   # frozen for the whole experiment
CACHE_DIR = ".fastembed_cache"
DENSE_WEIGHT = 0.5                        # frozen
BM25_K1, BM25_B = 1.5, 0.75               # frozen

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBED_MODEL, cache_dir=CACHE_DIR)


def embed(texts: list[str]) -> np.ndarray:
    vecs = np.asarray(list(_model().embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


class Bm25:
    def __init__(self, docs: list[list[str]]):
        self.docs = docs
        self.n = len(docs)
        self.lens = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.lens.mean()) if self.n else 0.0
        self.tf = [Counter(d) for d in docs]
        df = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {
            t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()
        }

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(self.n, dtype=np.float32)
        for term in tokenize(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + BM25_K1 * (1 - BM25_B + BM25_B * self.lens[i] / self.avg)
                out[i] += idf * f * (BM25_K1 + 1) / denom
        return out


def minmax(a: np.ndarray) -> np.ndarray:
    if a.size == 0:
        return a
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-9:
        return np.zeros_like(a)
    return (a - lo) / (hi - lo)
