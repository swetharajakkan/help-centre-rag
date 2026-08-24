"""Ingest the new article drop into an index.

NOTE: this ingests ONLY the files handed to it. The historical corpus is not
re-indexed and is not touched.
"""
from __future__ import annotations

import glob
import os

from .chunkers import fixed_window, split_frontmatter, structure_aware
from .store import Index, Record

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")

CHUNKERS = {"fixed_window": fixed_window, "structure_aware": structure_aware}

# Every chunk MUST carry these. A chunk missing source_file is a failed ingest.
REQUIRED_META = ("source_file", "article_id", "product_area", "last_updated")


def load_articles(corpus_dir: str = CORPUS_DIR) -> list[tuple[str, dict, str]]:
    out = []
    for path in sorted(glob.glob(os.path.join(corpus_dir, "*.md"))):
        raw = open(path).read()
        front, body = split_frontmatter(raw)
        out.append((os.path.basename(path), front, body))
    return out


def build_index(strategy: str, corpus_dir: str = CORPUS_DIR) -> Index:
    chunker = CHUNKERS[strategy]
    records: list[Record] = []
    for source_file, front, body in load_articles(corpus_dir):
        for chunk in chunker(body, source_file):
            chunk_id = f"{strategy}::{source_file}::{chunk.ordinal:03d}"
            records.append(Record(
                chunk_id=chunk_id,
                text=chunk.text,
                source_file=source_file,
                meta={
                    "source_file": source_file,
                    "article_id": front.get("article_id", ""),
                    "product_area": front.get("product_area", ""),
                    "last_updated": front.get("last_updated", ""),
                    "title": front.get("title", ""),
                    **chunk.meta,
                },
            ))
    validate(records)
    index = Index(strategy)
    index.build(records)
    return index


def validate(records: list[Record]) -> None:
    """Fail the ingest loudly rather than shipping unattributable chunks."""
    for r in records:
        missing = [f for f in REQUIRED_META if not r.meta.get(f)]
        if missing:
            raise ValueError(f"failed ingest: {r.chunk_id} missing {missing}")
