"""MongoDB: accounts, the admin email allowlist, and admin-uploaded documents.

One database (MONGODB_DB, default "help_centre") on the cluster named by
MONGODB_URI. Collections:

  users         {email, name, role: "user"|"admin", password: pbkdf2 hash,
                 created_at}                         unique on email
  admin_emails  {email, added_at, note}              who MAY sign up as admin
  documents     {doc_id: "DOC-001", title, filename, content_type, size,
                 categories: [...], text, raw (the original bytes),
                 uploaded_by, created_at}            unique on doc_id
  counters      {_id: "documents", seq}              DOC-nnn numbering

Read by two processes: the FastAPI backend (sign-up, login, upload) and the
Week 9 documents MCP server (search_documents / get_document), which is why
the connection lives here and loads .env itself.

MONGODB_URI="mongomock://" gives an in-memory database (tests only: it is
per-process, so the MCP server would not see what the backend wrote).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
from functools import lru_cache

from .tracing import load_dotenv

load_dotenv()

# Who may sign up as admin. Seeded into admin_emails on first connect; more can
# be added in Atlas (or HELP_CENTRE_ADMIN_EMAILS) without touching code.
DEFAULT_ADMIN_EMAILS = (
    "swetharajakkan@yopmail.com",
    "helpcentre.admin@yopmail.com",
    "supportops.lead@yopmail.com",
    "billing.admin@yopmail.com",
)

# The fixed categories offered when uploading. Admins may add their own too.
CATEGORIES = ("Refund", "Billing", "Payments", "Invoicing", "Subscriptions",
              "Tax", "Account", "Technical", "Policy", "Other")

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2_ROUNDS = 200_000


class NotConfigured(RuntimeError):
    """MONGODB_URI is not set: sign-up and documents are unavailable."""


def configured() -> bool:
    return bool(os.environ.get("MONGODB_URI"))


@lru_cache(maxsize=1)
def database():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise NotConfigured("MONGODB_URI is not set; put the Atlas connection string in .env")
    if uri.startswith("mongomock://"):
        import mongomock

        client = mongomock.MongoClient()
    else:
        from pymongo import MongoClient

        client = MongoClient(uri, serverSelectionTimeoutMS=8000, appname="help-centre")
    db = client[os.environ.get("MONGODB_DB", "help_centre")]
    _init(db)
    return db


def _init(db) -> None:
    db.users.create_index("email", unique=True)
    db.admin_emails.create_index("email", unique=True)
    db.documents.create_index("doc_id", unique=True)
    db.documents.create_index("categories")
    seed = os.environ.get("HELP_CENTRE_ADMIN_EMAILS")
    emails = [e for e in (seed.split(",") if seed else DEFAULT_ADMIN_EMAILS) if e.strip()]
    for e in emails:
        db.admin_emails.update_one({"email": norm_email(e)},
                                   {"$setOnInsert": {"email": norm_email(e), "added_at": now(),
                                                     "note": "seeded"}}, upsert=True)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, want = stored.split("$")
    except (ValueError, AttributeError):
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
    return hmac.compare_digest(got.hex(), want)


# ------------------------------------------------------------------ users

def is_admin_email(email: str) -> bool:
    return database().admin_emails.find_one({"email": norm_email(email)}) is not None


def find_user(email: str) -> dict | None:
    return database().users.find_one({"email": norm_email(email)}, {"_id": 0})


def create_user(email: str, name: str, password: str, role: str) -> dict:
    """Insert one account. Raises ValueError if the email is taken."""
    from pymongo.errors import DuplicateKeyError

    doc = {"email": norm_email(email), "name": name.strip(), "role": role,
           "password": hash_password(password), "created_at": now()}
    try:
        database().users.insert_one(doc)
    except DuplicateKeyError as exc:
        raise ValueError("an account with this email already exists") from exc
    return {k: doc[k] for k in ("email", "name", "role")}


# ------------------------------------------------------------------ documents

def next_doc_id() -> str:
    from pymongo import ReturnDocument

    c = database().counters.find_one_and_update(
        {"_id": "documents"}, {"$inc": {"seq": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER)
    return f"DOC-{c['seq']:03d}"


def clean_categories(raw: list[str]) -> list[str]:
    """Title-cased, de-duplicated, the fixed ones spelt as offered."""
    fixed = {c.lower(): c for c in CATEGORIES}
    out = []
    for c in raw:
        c = re.sub(r"\s+", " ", (c or "").strip())[:40]
        if c:
            c = fixed.get(c.lower(), c.title())
            if c not in out:
                out.append(c)
    return out


def insert_document(*, title: str, filename: str, content_type: str, raw: bytes,
                    text: str, categories: list[str], uploaded_by: str) -> dict:
    doc = {"doc_id": next_doc_id(), "title": title, "filename": filename,
           "content_type": content_type, "size": len(raw), "categories": categories,
           "text": text, "raw": raw, "uploaded_by": uploaded_by, "created_at": now()}
    database().documents.insert_one(doc)
    return public(doc)


def public(doc: dict) -> dict:
    """A document without its bytes and Mongo id, for listings."""
    out = {k: v for k, v in doc.items() if k not in ("_id", "raw", "text")}
    if isinstance(out.get("created_at"), dt.datetime):
        out["created_at"] = out["created_at"].isoformat(timespec="seconds")
    out["chars"] = len(doc.get("text") or "")
    return out


def list_documents(category: str | None = None) -> list[dict]:
    q = {"categories": category} if category else {}
    return [public(d) for d in database().documents.find(q, {"raw": 0}).sort("doc_id", 1)]


def get_document(doc_id: str, with_raw: bool = False) -> dict | None:
    proj = {"_id": 0} if with_raw else {"_id": 0, "raw": 0}
    return database().documents.find_one({"doc_id": doc_id.strip().upper()}, proj)


def all_documents_text(category: str | None = None) -> list[dict]:
    q = {"categories": category} if category else {}
    return list(database().documents.find(q, {"_id": 0, "raw": 0}))


def delete_document(doc_id: str) -> bool:
    return database().documents.delete_one({"doc_id": doc_id.strip().upper()}).deleted_count == 1


def categories_in_use() -> list[str]:
    used = database().documents.distinct("categories")
    return sorted(set(used) | set(CATEGORIES), key=lambda c: (c not in CATEGORIES, c))
