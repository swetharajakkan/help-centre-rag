"""Chunking strategies for the help-centre RAG index.

`fixed_window` is the pipeline's original chunker: a character window with
overlap, cut at the nearest whitespace. It has no idea what a markdown table
is, which is exactly the property this repo is measuring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

FIXED_WINDOW_CHARS = 900
FIXED_WINDOW_OVERLAP = 120


@dataclass
class Chunk:
    text: str
    source_file: str
    ordinal: int
    strategy: str
    meta: dict = field(default_factory=dict)


def _cut_at_whitespace(body: str, start: int, end: int) -> int:
    """Pull `end` back to the last whitespace so words are not sliced."""
    if end >= len(body):
        return len(body)
    window = body[start:end]
    idx = window.rfind(" ")
    nl = window.rfind("\n")
    boundary = max(idx, nl)
    if boundary <= 0:
        return end
    return start + boundary


def fixed_window(body: str, source_file: str) -> Iterator[Chunk]:
    """The chunker this app already shipped with."""
    body = body.strip()
    pos = 0
    ordinal = 0
    while pos < len(body):
        end = _cut_at_whitespace(body, pos, pos + FIXED_WINDOW_CHARS)
        text = body[pos:end].strip()
        if text:
            yield Chunk(
                text=text,
                source_file=source_file,
                ordinal=ordinal,
                strategy="fixed_window",
            )
            ordinal += 1
        if end >= len(body):
            break
        pos = max(end - FIXED_WINDOW_OVERLAP, pos + 1)


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def split_frontmatter(raw: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, raw[m.end():]


# --------------------------------------------------------------------------
# Structure-aware chunker
#
# Hard invariant: a markdown table row is NEVER emitted without the header row
# and separator that give its cells meaning. Every table chunk is a valid,
# self-contained markdown table. Prose is packed at paragraph boundaries and
# a paragraph is never split.
# --------------------------------------------------------------------------

STRUCTURE_PROSE_BUDGET = 900
STRUCTURE_TABLE_BUDGET = 700

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def _is_separator(line: str) -> bool:
    return _is_table_row(line) and set(line.strip("| \n")) <= set("-: |")


def _blocks(section_lines: list[str]):
    """Split a section body into ('prose', text) and ('table', rows) blocks."""
    i, out = 0, []
    while i < len(section_lines):
        if (
            _is_table_row(section_lines[i])
            and i + 1 < len(section_lines)
            and _is_separator(section_lines[i + 1])
        ):
            j = i + 2
            while j < len(section_lines) and _is_table_row(section_lines[j]):
                j += 1
            out.append(("table", section_lines[i:j]))
            i = j
        else:
            j = i
            while j < len(section_lines) and not (
                _is_table_row(section_lines[j])
                and j + 1 < len(section_lines)
                and _is_separator(section_lines[j + 1])
            ):
                j += 1
            text = "\n".join(section_lines[i:j]).strip()
            if text:
                out.append(("prose", text))
            i = j
    return out


def _sections(body: str):
    """Yield (breadcrumb, heading, lines) for each markdown section."""
    doc_title, current, buf = "", "", []
    for line in body.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if buf or current:
                yield (doc_title, current, buf)
            level, title = len(m.group(1)), m.group(2).strip()
            if level == 1:
                doc_title, current = title, ""
            else:
                current = title
            buf = []
        else:
            buf.append(line)
    if buf or current:
        yield (doc_title, current, buf)


def structure_aware(body: str, source_file: str) -> Iterator[Chunk]:
    ordinal = 0
    for doc_title, heading, lines in _sections(body):
        crumb = " > ".join(p for p in (doc_title, heading) if p)
        for kind, payload in _blocks(lines):
            if kind == "prose":
                para_buf: list[str] = []
                size = 0
                paras = [p.strip() for p in re.split(r"\n\s*\n", payload) if p.strip()]
                for para in paras:
                    if para_buf and size + len(para) > STRUCTURE_PROSE_BUDGET:
                        yield Chunk(
                            text=f"{crumb}\n\n" + "\n\n".join(para_buf),
                            source_file=source_file, ordinal=ordinal,
                            strategy="structure_aware",
                            meta={"section": heading or doc_title,
                                  "block_type": "prose"},
                        )
                        ordinal += 1
                        para_buf, size = [], 0
                    para_buf.append(para)
                    size += len(para)
                if para_buf:
                    yield Chunk(
                        text=f"{crumb}\n\n" + "\n\n".join(para_buf),
                        source_file=source_file, ordinal=ordinal,
                        strategy="structure_aware",
                        meta={"section": heading or doc_title, "block_type": "prose"},
                    )
                    ordinal += 1
            else:
                header, sep, rows = payload[0], payload[1], payload[2:]
                head_txt = f"{crumb}\n\n{header}\n{sep}"
                group: list[str] = []
                size = len(head_txt)
                for row in rows:
                    # A row is never split, and never leaves its header behind.
                    if group and size + len(row) > STRUCTURE_TABLE_BUDGET:
                        yield Chunk(
                            text=head_txt + "\n" + "\n".join(group),
                            source_file=source_file, ordinal=ordinal,
                            strategy="structure_aware",
                            meta={"section": heading or doc_title,
                                  "block_type": "table"},
                        )
                        ordinal += 1
                        group, size = [], len(head_txt)
                    group.append(row)
                    size += len(row)
                if group:
                    yield Chunk(
                        text=head_txt + "\n" + "\n".join(group),
                        source_file=source_file, ordinal=ordinal,
                        strategy="structure_aware",
                        meta={"section": heading or doc_title, "block_type": "table"},
                    )
                    ordinal += 1
