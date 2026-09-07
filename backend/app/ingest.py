"""Ingest the new article drop into an index.

NOTE: this ingests ONLY the files handed to it. The historical corpus is not
re-indexed and is not touched.
"""
from __future__ import annotations

import glob
import os

from .chunkers import fixed_window, split_frontmatter, structure_aware
from .store import Index, Record
from . import uploads

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


def load_uploads(upload_dir: str | None = None) -> list[tuple[str, dict, str]]:
    """Documents dropped through the UI. Empty until someone uploads one, so
    the shipped measurement over the 6 articles is unchanged by this.

    `uploads.UPLOAD_DIR` is read at call time so it stays redirectable."""
    upload_dir = upload_dir or uploads.UPLOAD_DIR
    return load_articles(upload_dir) if os.path.isdir(upload_dir) else []


def records_for(strategy: str, articles: list[tuple[str, dict, str]]
                ) -> list[Record]:
    """Chunk already-loaded articles into records. Shared by the initial build
    and by incremental upload ingest, so a dropped file goes through exactly
    the same chunker, id scheme and metadata contract as a shipped article."""
    chunker = CHUNKERS[strategy]
    records: list[Record] = []
    for source_file, front, body in articles:
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
                    # Empty for typed documents; the OCR engine's name for a
                    # transcript, so the UI can flag machine-read text.
                    "extracted_by": front.get("extracted_by", ""),
                    **chunk.meta,
                },
            ))
    validate(records)
    return records


def build_index(strategy: str, corpus_dir: str = CORPUS_DIR,
                include_uploads: bool = False) -> Index:
    """Ingest ONLY the directory it is given. `include_uploads` is opt-in and
    is set by the running app, so a caller that passes a corpus dir -- an eval
    script, a test -- never silently picks up whatever a user has dropped
    through the UI."""
    articles = load_articles(corpus_dir)
    if include_uploads:
        articles += load_uploads()
    index = Index(strategy)
    index.build(records_for(strategy, articles))
    return index


def validate(records: list[Record]) -> None:
    """Fail the ingest loudly rather than shipping unattributable chunks."""
    for r in records:
        missing = [f for f in REQUIRED_META if not r.meta.get(f)]
        if missing:
            raise ValueError(f"failed ingest: {r.chunk_id} missing {missing}")
