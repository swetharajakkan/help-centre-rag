"""Drag-and-drop document ingest.

Every accepted upload is normalised into the same markdown-with-frontmatter
shape the shipped corpus uses, and written into `backend/uploads/`. That is the
whole trick: once a dropped file looks like a corpus article, the existing
chunkers, the `REQUIRED_META` validator, the citation contract and both
retrieval arms apply to it unchanged, and it survives a restart because the
normalised file on disk is the record of truth.

Anything may be dropped. What differs by type is only how text is recovered:

* `.md`/`.markdown`  kept as-is, including any frontmatter it already carries
* `.csv`/`.tsv`      converted to a markdown table, so `structure_aware` keeps
                     each row attached to its header row -- the property this
                     repo exists to measure
* `.json`            flattened to `path: value` lines, one leaf per line
* `.html`/`.htm`/`.xml`  tags stripped
* images             read with OCR (see `ocr.py`); the original file is kept
                     next to the transcript so a quote can be checked against
                     the picture it came from
* everything else    decoded as UTF-8 with replacement, then accepted only if
                     it is mostly printable text

A file that yields no usable text is rejected with a reason rather than being
indexed as binary noise, which would poison BM25 and produce uncitable chunks.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re

from . import ocr

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")

# A dropped file bigger than this is refused before it is read into memory.
MAX_BYTES = 5 * 1024 * 1024
# Images get more room: a phone photo or a retina screenshot routinely exceeds
# the text limit, and the indexed artefact is the transcript, not the pixels.
MAX_IMAGE_BYTES = 15 * 1024 * 1024
# Below this share of printable characters the decode is treated as binary.
MIN_PRINTABLE_RATIO = 0.85
# Too little text to chunk usefully.
MIN_CHARS = 40


class Rejected(Exception):
    """Raised with a message meant to be shown to the person who dropped it."""


def slugify(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug or "document"


def _printable_ratio(text: str) -> float:
    """Share of characters that survived decoding as real text.

    U+FFFD counts as BAD, not good: `errors="replace"` turns undecodable bytes
    into it and it reports as printable, so counting printability alone lets a
    PNG through as 100% text.
    """
    if not text:
        return 0.0
    good = sum(1 for c in text
               if c != "\ufffd" and (c.isprintable() or c in "\n\r\t"))
    return good / len(text)


def _from_csv(text: str) -> str:
    """CSV/TSV -> a markdown table, header row first."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        raise Rejected("the file has no rows")
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    def line(cells):
        return "| " + " | ".join(c.replace("|", "\\|").strip() for c in cells) + " |"

    out = [line(rows[0]), "| " + " | ".join(["---"] * width) + " |"]
    out += [line(r) for r in rows[1:]]
    return "\n".join(out)


def _from_json(text: str) -> str:
    """JSON -> one `a.b.c: value` line per leaf, which chunks and quotes well."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Rejected(f"not valid JSON ({exc.msg} at line {exc.lineno})") from exc

    lines: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        else:
            lines.append(f"{path}: {node}")

    walk(data, "")
    return "\n".join(lines)


def _from_markup(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"[ \t]*\n\s*\n\s*", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """Recover indexable text from any dropped file.

    Returns (text, engine) where engine is "" for text formats and the OCR
    engine's name for images. Raises Rejected with a message meant to be read
    by the person who dropped the file.
    """
    if not data:
        raise Rejected("the file is empty")

    ext = os.path.splitext(filename)[1].lower()

    # Images are routed BEFORE the binary guard below -- they are binary by
    # definition, and OCR is what makes them indexable.
    if ocr.is_image(filename, data):
        if len(data) > MAX_IMAGE_BYTES:
            raise Rejected(f"image is {len(data) // 1024 // 1024} MB; the limit "
                           f"is {MAX_IMAGE_BYTES // 1024 // 1024} MB")
        try:
            text, engine = ocr.transcribe(filename, data)
        except RuntimeError as exc:
            raise Rejected(f"could not read text from this image — {exc}") from exc
        if len(text.strip()) < MIN_CHARS:
            raise Rejected(
                f"only {len(text.strip())} characters of text were found in "
                f"this image; at least {MIN_CHARS} are needed to index it"
            )
        return text.strip(), engine

    if len(data) > MAX_BYTES:
        raise Rejected(f"file is {len(data) // 1024} KB; the limit is "
                       f"{MAX_BYTES // 1024} KB")

    # A NUL byte never appears in text and is the cheapest binary tell.
    if b"\x00" in data[:8192]:
        raise Rejected(
            f"{ext or 'this file'} is binary and is not an image. Convert it "
            "to .md, .txt, .csv or .json first, or screenshot it and drop the "
            "image instead."
        )
    text = data.decode("utf-8", errors="replace")

    if _printable_ratio(text) < MIN_PRINTABLE_RATIO:
        raise Rejected(
            f"{ext or 'this file type'} looks like binary, not text. "
            "Convert it to .md, .txt, .csv or .json first — indexing "
            "undecodable bytes would produce chunks nothing can cite."
        )

    if ext in (".csv", ".tsv"):
        text = _from_csv(text)
    elif ext == ".json":
        text = _from_json(text)
    elif ext in (".html", ".htm", ".xml"):
        text = _from_markup(text)

    text = text.strip()
    if len(text) < MIN_CHARS:
        raise Rejected(f"only {len(text)} characters of text were recovered; "
                       f"at least {MIN_CHARS} are needed to chunk it")
    return text, ""


def _existing_frontmatter(text: str) -> bool:
    return text.lstrip().startswith("---")


def store(filename: str, data: bytes, product_area: str = "uploaded",
          upload_dir: str | None = None) -> tuple[str, str]:
    """Normalise, write to `upload_dir`, and return (stored_name, article_id).

    A re-upload of the same filename overwrites, so dropping a corrected
    version of a document replaces it instead of double-indexing it.
    """
    # Resolved at call time, not bound as a default, so tests (and anything
    # else) can redirect UPLOAD_DIR without every caller passing it through.
    upload_dir = upload_dir or UPLOAD_DIR
    text, engine = extract_text(filename, data)
    slug = slugify(filename)
    os.makedirs(upload_dir, exist_ok=True)

    # Keep the original image beside its transcript. OCR misreads characters,
    # and an answer quoting a transcript must stay checkable against the
    # picture it came from. Only the .md is indexed -- load_articles globs
    # *.md -- so the image is inert as far as retrieval is concerned.
    original = ""
    if engine:
        ext = os.path.splitext(filename)[1].lower() or ".png"
        original = f"{slug}{ext}"
        with open(os.path.join(upload_dir, original), "wb") as fh:
            fh.write(data)

    if _existing_frontmatter(text):
        # It already looks like a corpus article; trust its own frontmatter.
        body = text
        article_id = ""
        for line in text.splitlines()[1:]:
            if line.strip() == "---":
                break
            if line.startswith("article_id:"):
                article_id = line.split(":", 1)[1].strip().strip("\"'")
        article_id = article_id or f"UP-{slug[:24].upper()}"
    else:
        article_id = f"UP-{slug[:24].upper()}"
        title = os.path.splitext(os.path.basename(filename))[0]
        provenance = ""
        if engine:
            # Recorded in the frontmatter and shown in the UI: a reader should
            # know a quote was machine-read from a picture, not typed.
            provenance = (f"extracted_by: {engine}\n"
                          f"original_file: {original}\n")
        body = (
            "---\n"
            f"article_id: {article_id}\n"
            f"title: {title}\n"
            f"product_area: {product_area}\n"
            f"last_updated: {dt.date.today().isoformat()}\n"
            f"source_filename: {os.path.basename(filename)}\n"
            f"{provenance}"
            "---\n\n"
            f"# {title}\n\n{text}\n"
        )

    stored_name = f"{slug}.md"
    with open(os.path.join(upload_dir, stored_name), "w") as fh:
        fh.write(body)
    return stored_name, article_id


def stored_files(upload_dir: str | None = None) -> list[str]:
    upload_dir = upload_dir or UPLOAD_DIR
    if not os.path.isdir(upload_dir):
        return []
    return sorted(f for f in os.listdir(upload_dir) if f.endswith(".md"))


def delete(stored_name: str, upload_dir: str | None = None) -> bool:
    """Remove the transcript and, for an image upload, its kept original."""
    upload_dir = upload_dir or UPLOAD_DIR
    path = os.path.join(upload_dir, os.path.basename(stored_name))
    if not os.path.isfile(path):
        return False

    # The frontmatter names the original, so no guessing at extensions.
    original = ""
    with open(path) as fh:
        for line in fh.read().splitlines()[1:]:
            if line.strip() == "---":
                break
            if line.startswith("original_file:"):
                original = line.split(":", 1)[1].strip()
    os.remove(path)
    if original:
        sibling = os.path.join(upload_dir, os.path.basename(original))
        if os.path.isfile(sibling):
            os.remove(sibling)
    return True
