"""Admin documents: upload into MongoDB with categories, for the Week 9 agent.

Every route here is admin-only (the auth guard lets a `user` reach none of
them). An uploaded document is stored whole in the `documents` collection --
its original bytes, its extracted text and its categories -- and the Week 9
documents MCP server (week9/servers/documents_server.py) searches that
collection on every call, so a question asked right after the upload can be
answered from it with no restart and no re-index.

  POST   /api/docs                 multipart: file, title?, categories ("Refund,Billing")
  GET    /api/docs[?category=X]    list (no bytes, no text)
  GET    /api/docs/categories      the fixed categories plus any in use
  GET    /api/docs/{doc_id}        one document's text and metadata
  DELETE /api/docs/{doc_id}
"""
from __future__ import annotations

import io
import json
import os

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from . import db
from .uploads import MAX_BYTES, MIN_CHARS, Rejected, extract_text

router = APIRouter(prefix="/api/docs")


def _db():
    if not db.configured():
        raise HTTPException(503, "documents need the database: set MONGODB_URI in .env")
    try:
        return db.database()
    except Exception as exc:  # noqa: BLE001 -- unreachable cluster
        raise HTTPException(503, f"the database is not reachable: {type(exc).__name__}") from exc


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n\n".join((p.extract_text() or "").strip() for p in reader.pages)
    except Exception as exc:  # noqa: BLE001 -- corrupt or encrypted PDF
        raise Rejected(f"could not read this PDF ({type(exc).__name__})") from exc
    if len(text.strip()) < MIN_CHARS:
        raise Rejected("no text found in this PDF; if it is a scan, upload it as an image")
    return text.strip()


def _text_of(filename: str, data: bytes) -> str:
    if not data:
        raise Rejected("the file is empty")
    if len(data) > MAX_BYTES and not filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise Rejected(f"file is {len(data) // 1024} KB; the limit is {MAX_BYTES // 1024} KB")
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        return _pdf_text(data)
    return extract_text(filename, data)[0]


def _parse_categories(raw: str | None) -> list[str]:
    raw = (raw or "").strip()
    if raw.startswith("["):
        try:
            items = json.loads(raw)
        except ValueError:
            items = []
    else:
        items = raw.split(",")
    return db.clean_categories([str(x) for x in items])


@router.post("")
async def upload(request: Request, file: UploadFile, title: str = Form(""),
                 categories: str = Form("")) -> dict:
    _db()
    name = os.path.basename(file.filename or "document")
    cats = _parse_categories(categories)
    if not cats:
        raise HTTPException(422, "pick at least one category (e.g. Refund)")
    data = await file.read()
    try:
        text = _text_of(name, data)
    except Rejected as exc:
        raise HTTPException(422, str(exc)) from exc
    who = getattr(request.state, "user", None) or {}
    doc = db.insert_document(
        title=(title.strip() or os.path.splitext(name)[0])[:200], filename=name,
        content_type=file.content_type or "application/octet-stream", raw=data,
        text=text, categories=cats, uploaded_by=who.get("username", "?"))
    return {"document": doc}


@router.get("")
def listing(category: str | None = None) -> dict:
    _db()
    return {"documents": db.list_documents(category or None)}


@router.get("/categories")
def categories() -> dict:
    _db()
    return {"categories": db.categories_in_use(), "fixed": list(db.CATEGORIES)}


@router.get("/{doc_id}")
def one(doc_id: str) -> dict:
    _db()
    d = db.get_document(doc_id)
    if d is None:
        raise HTTPException(404, f"no document {doc_id}")
    return {**db.public(d), "text": d["text"]}


@router.delete("/{doc_id}")
def remove(doc_id: str) -> dict:
    _db()
    if not db.delete_document(doc_id):
        raise HTTPException(404, f"no document {doc_id}")
    return {"deleted": doc_id.upper()}
