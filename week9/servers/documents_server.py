"""Server three: admin-uploaded documents, from MongoDB, as an MCP server.

Admins upload documents with categories (Refund, Billing, ...) through the
app (backend/app/documents.py); they land in the `documents` collection. This
server reads that collection on every call, so a document is answerable the
moment it is uploaded -- no restart, no re-index. It was added to the agent
the Week 9 way: one block in week9/mcp_config.json, nothing in week9/agent.

    .venv/bin/python week9/servers/documents_server.py          # stdio

Primitives:

  tool      search_documents(query, k, category)   model-invoked search
  tool      get_document(document_id)              model-invoked fetch (DOC-nnn)
  resource  docs://catalog                         every document: id, title, categories
  resource  docs://categories                      the categories in use

Ranking uses the same cross-encoder as the help-centre server (when
HELP_CENTRE_RERANK=1), so a document hit and a help-centre hit carry scores
on the same scale and the same "weak" cut-off. The document's title and
categories are scored with each passage, so a refund question finds a
document filed under Refund. No model runs in here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)          # the reranker's model cache is relative to the repo root

from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ResourceError, ToolError  # noqa: E402

from backend.app import db  # noqa: E402  (loads .env -> MONGODB_URI)

ID_SHAPE = re.compile(r"^DOC-\d{3,}$")
WORD = re.compile(r"[a-z0-9]+")
STOP = set("a an and are as at be by can do does for from how i if in is it my of on "
           "or our the this to was what when where which who why will with you your".split())
WEAK_BELOW = -1.5           # same cut-off as week9/servers/rag_server.py
CANDIDATES = 12
CHUNK_CHARS = 700
DOWN_FOR_S = 60             # after a failed connection, don't wait on Atlas every call

_down_until = 0.0


def _docs(category: str | None = None) -> tuple[list[dict], str | None]:
    """(documents, note). An unconfigured or unreachable database is an empty
    result with a note, not an error: every plain question searches here, and
    a missing database must not turn each of them into a failed tool call."""
    global _down_until
    if not db.configured():
        return [], "the documents database is not configured (MONGODB_URI is unset)"
    if time.time() < _down_until:
        return [], "the documents database is unreachable right now"
    try:
        return db.all_documents_text(category), None
    except Exception as exc:  # noqa: BLE001
        _down_until = time.time() + DOWN_FOR_S
        return [], f"the documents database is unreachable ({type(exc).__name__})"


def _is_heading(p: str) -> bool:
    """A title line ("# Refund Policy", an HTML <h1>): short, one line, no
    sentence end. Scored via the document title instead of quoted."""
    return "\n" not in p and len(p) < 80 and not p.rstrip().endswith((".", "!", "?", ":"))


def chunks(doc: dict) -> list[dict]:
    """One paragraph per chunk, headings dropped, long paragraphs cut at line
    breaks near CHUNK_CHARS. A chunk is quoted from its first sentence, so two
    topics must never share one; and each chunk is a verbatim slice of the
    document text, so anything quoted from it can be re-found there."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", doc.get("text") or "") if p.strip()]
    out = []
    for p in paras:
        if _is_heading(p):
            continue
        cur = ""
        for line in p.splitlines():
            if cur and len(cur) + len(line) > CHUNK_CHARS:
                out.append(cur)
                cur = ""
            cur = f"{cur}\n{line}" if cur else line
        if cur:
            out.append(cur)
    return [{"chunk_id": f"{doc['doc_id']}#{i}", "document_id": doc["doc_id"],
             "title": doc.get("title", ""), "categories": doc.get("categories", []), "text": t}
            for i, t in enumerate(out, start=1)]


def _terms(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


def _header(c: dict) -> str:
    return f"{c['title']} ({', '.join(c['categories'])})"


def _rerank_on() -> bool:
    return os.environ.get("HELP_CENTRE_RERANK", "1") not in ("0", "false", "")


def rank(query: str, cands: list[dict], k: int) -> list[dict]:
    q = _terms(query)
    for c in cands:
        overlap = q & (_terms(c["text"]) | _terms(_header(c)))
        c["_kw"] = len(overlap) / max(1, len(q))
    cands = sorted(cands, key=lambda c: -c["_kw"])[:CANDIDATES]
    if _rerank_on() and cands:
        from backend.app.rerank import _encoder

        scores = list(_encoder().rerank(query, [f"{_header(c)}\n{c['text']}" for c in cands]))
        for c, s in zip(cands, scores):
            c["score"] = round(float(s), 4)
            c["relevance"] = "weak" if s < WEAK_BELOW else "strong"
    else:
        for c in cands:
            c["score"] = round(c["_kw"], 4)
            c["relevance"] = "strong" if c["_kw"] >= 0.34 else "weak"
    cands.sort(key=lambda c: -c["score"])
    return [{"rank": i, **{k2: v for k2, v in c.items() if not k2.startswith("_")}}
            for i, c in enumerate(cands[:k], start=1)]


mcp = FastMCP(
    name="admin-documents",
    version="1.0.0",
    instructions=("Documents uploaded by Help Centre admins (refund policies, "
                  "billing notes, ...), each filed under categories. Search with "
                  "search_documents; fetch a whole one (DOC-nnn) with get_document."),
)


@mcp.tool(annotations={"readOnlyHint": True})
def search_documents(query: str, k: int = 3, category: str | None = None) -> dict:
    """Search the documents Help Centre admins uploaded (policies, procedures,
    notes) and return the k best passages.

    Use this for any customer question -- especially refunds, billing,
    payments, account or policy questions -- alongside the help centre: an
    uploaded document is often the newest word on a topic. Pass the user's
    question as `query` in plain words.

    k: 1-10, default 3. category: optional exact filter, e.g. "Refund",
    "Billing", "Payments" (resource docs://categories lists them).

    Each hit has chunk_id, document_id (DOC-nnn), title, categories, score,
    relevance and text. Cite document_id and quote text verbatim. Treat
    "weak" hits, or no hits, as "the uploaded documents do not cover this".
    """
    k = max(1, min(int(k), 10))
    docs, note = _docs(category or None)
    cands = [c for d in docs for c in chunks(d)]
    out = {"query": query, "category": category, "hits": rank(query, cands, k) if cands else []}
    if note:
        out["note"] = note
    return out


@mcp.tool(annotations={"readOnlyHint": True})
def get_document(document_id: str) -> dict:
    """Fetch the full text of ONE uploaded document by its id.

    Use it when you already hold a document id (ids look like DOC-nnn, e.g.
    DOC-001) from the user or from a search_documents hit. With only a topic,
    call search_documents instead; never guess an id.

    Returns document_id, title, categories, filename, uploaded_at and text.
    Errors say which case they are: a malformed id (reformat it and call once
    more) or an id that does not exist (call search_documents instead).
    """
    did = (document_id or "").strip().upper()
    if not ID_SHAPE.match(did):
        raise ToolError(f"document {document_id!r} not found: ids look like DOC-nnn (DOC- "
                        "then three digits, e.g. DOC-001). Reformat the id and call again.")
    if not db.configured():
        raise ToolError("the documents database is not configured; retrying will not help.")
    try:
        d = db.get_document(did)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"the documents database is unreachable ({type(exc).__name__}); "
                        "retrying will not help right now.") from exc
    if d is None:
        raise ToolError(f"no document {did}: the id is well-formed but does not exist. "
                        "Call search_documents with the topic instead of retrying this id.")
    return {"document_id": d["doc_id"], "title": d.get("title", ""),
            "categories": d.get("categories", []), "filename": d.get("filename", ""),
            "uploaded_at": str(d.get("created_at", "")), "text": d.get("text", "")}


@mcp.resource("docs://catalog", mime_type="application/json",
              description="Every uploaded document: id, title, categories. For the host.")
def catalog() -> str:
    docs, note = _docs()
    if note:
        raise ResourceError(note)
    return json.dumps([{"document_id": d["doc_id"], "title": d.get("title", ""),
                        "categories": d.get("categories", [])} for d in docs], indent=1)


@mcp.resource("docs://categories", mime_type="application/json",
              description="The document categories in use (for the category filter).")
def categories() -> str:
    docs, note = _docs()
    if note:
        raise ResourceError(note)
    return json.dumps(sorted({c for d in docs for c in d.get("categories", [])}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=None, metavar="PORT")
    a = ap.parse_args()
    if a.http:
        mcp.run(transport="http", host="127.0.0.1", port=a.http, path="/mcp", show_banner=False)
    else:
        mcp.run(transport="stdio", show_banner=False)
