"""In-process vector + BM25 index, persisted to JSON."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

import numpy as np

from .embeddings import Bm25, DENSE_WEIGHT, embed, minmax, tokenize

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@dataclass
class Record:
    chunk_id: str
    text: str
    source_file: str
    meta: dict = field(default_factory=dict)


class Index:
    """One index per chunking strategy."""

    def __init__(self, name: str):
        self.name = name
        self.records: list[Record] = []
        self.vectors: np.ndarray | None = None
        self.bm25: Bm25 | None = None

    def build(self, records: list[Record]) -> None:
        self.records = records
        self.vectors = embed([r.text for r in records])
        self.bm25 = Bm25([tokenize(r.text) for r in records])

    def search(self, query: str, k: int = 5,
               where: dict | None = None) -> list[dict]:
        """`where` is an exact-match metadata filter, e.g.
        {"product_area": "payments"}. Filtering is applied to the candidate
        set BEFORE ranking, so scores are renormalised over the filtered
        subset and the ordering can genuinely change, not just get truncated.
        """
        if not self.records:
            return []
        keep = self._matching(where)
        if keep.size == 0:
            return []
        dense_all = (self.vectors @ embed([query])[0]).astype(np.float32)
        lex_all = self.bm25.scores(query)
        dense, lexical = dense_all[keep], lex_all[keep]
        fused = DENSE_WEIGHT * minmax(dense) + (1 - DENSE_WEIGHT) * minmax(lexical)
        order = np.argsort(-fused)[:k]
        return [self._hit(int(keep[i]), float(fused[i]), float(dense[i]),
                          float(lexical[i]), rank)
                for rank, i in enumerate(order, start=1)]

    def _matching(self, where: dict | None) -> np.ndarray:
        if not where:
            return np.arange(len(self.records))
        return np.array(
            [i for i, r in enumerate(self.records)
             if all(r.meta.get(k) == v for k, v in where.items())],
            dtype=int,
        )

    def get(self, chunk_id: str) -> Record | None:
        return next((r for r in self.records if r.chunk_id == chunk_id), None)

    def _hit(self, i, fused, dense, lexical, rank) -> dict:
        r = self.records[i]
        return {
            "rank": rank,
            "chunk_id": r.chunk_id,
            "score": round(fused, 4),
            "dense": round(dense, 4),
            "bm25": round(lexical, 4),
            "source_file": r.source_file,
            "text": r.text,
            "meta": r.meta,
        }

    def save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, f"{self.name}.json"), "w") as fh:
            json.dump([asdict(r) for r in self.records], fh, indent=1)
