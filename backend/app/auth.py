"""Two logins: `user` may only ask the agent; `admin` gets the whole app.

Sessions are an HMAC-signed cookie (HttpOnly, SameSite=Lax), so every
existing fetch() in the UI carries it without being touched. The guard below
runs on every /api/ request:

  public       /api/auth/login, /api/auth/me, /api/auth/logout, /api/health
  role user    the above + /api/w9/ask (ask a question, get the agent's reply)
               + /api/w9/questions (the quick questions, text only)
  role admin   everything

Accounts live in two places:
  MongoDB     people who signed up (backend/app/db.py, `users`), logging in
              by email. Anyone may sign up as `user`. Signing up as `admin`
              needs BOTH an email listed in the `admin_emails` collection and
              the admin code (HELP_CENTRE_ADMIN_CODE).
  env         HELP_CENTRE_USERS ("name:password:role,..."); the default is two
              local demo accounts, user/user123 and admin/admin123 -- change
              them before this leaves a laptop. They work without a database.
HELP_CENTRE_AUTH=0 turns the guard off (the test suite does, so the
pre-existing endpoint tests are unchanged).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

COOKIE = "hc_session"
TTL_S = 12 * 3600
# A per-process secret unless one is configured: a restart logs everyone out,
# which is the safe failure.
SECRET = (os.environ.get("HELP_CENTRE_AUTH_SECRET") or secrets.token_hex(32)).encode()

PUBLIC = ("/api/auth/login", "/api/auth/signup", "/api/auth/me", "/api/auth/logout",
          "/api/health")
USER_ALLOWED = PUBLIC + ("/api/w9/ask", "/api/w9/questions", "/api/w10/auto")


def enabled() -> bool:
    return os.environ.get("HELP_CENTRE_AUTH", "1") != "0"


def users() -> dict[str, tuple[str, str]]:
    raw = os.environ.get("HELP_CENTRE_USERS", "user:user123:user,admin:admin123:admin")
    out = {}
    for item in raw.split(","):
        name, pw, role = (item.strip().split(":") + ["", ""])[:3]
        if name and pw and role in ("user", "admin"):
            out[name] = (pw, role)
    return out


def admin_code() -> str:
    return os.environ.get("HELP_CENTRE_ADMIN_CODE", "HC-ADMIN-2026")


def _db_user(email: str) -> dict | None:
    """A signed-up account, or None (also when the database is unreachable,
    which then fails closed: the session is treated as logged out)."""
    from . import db

    if "@" not in email or not db.configured():
        return None
    try:
        return db.find_user(email)
    except Exception:  # noqa: BLE001 -- unreachable cluster
        return None


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign(username: str, role: str) -> str:
    body = _b64(json.dumps({"u": username, "r": role, "exp": int(time.time()) + TTL_S}).encode())
    sig = _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    good = _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    if data.get("exp", 0) < time.time():
        return None
    if data.get("u") in users():
        return {"username": data["u"], "role": users()[data["u"]][1]}
    acct = _db_user(data.get("u", ""))
    if acct is None:
        return None
    # The role is re-read from the database, not trusted from the cookie.
    return {"username": acct["email"], "name": acct.get("name"), "role": acct["role"]}


def current(request: Request) -> dict | None:
    if not enabled():
        return {"username": "admin", "role": "admin", "auth": "disabled"}
    return verify(request.cookies.get(COOKIE))


async def guard(request: Request, call_next):
    """HTTP middleware: who may call what."""
    path = request.url.path
    if not enabled() or not path.startswith("/api/") or request.method == "OPTIONS":
        request.state.user = current(request)
        return await call_next(request)
    who = verify(request.cookies.get(COOKIE))
    request.state.user = who
    if path in PUBLIC:
        return await call_next(request)
    if who is None:
        return JSONResponse({"detail": "login required"}, status_code=401)
    if who["role"] != "admin" and path not in USER_ALLOWED:
        return JSONResponse({"detail": "admin only"}, status_code=403)
    return await call_next(request)


router = APIRouter(prefix="/api/auth")


class Login(BaseModel):
    username: str           # an email, or a demo account name
    password: str


class Signup(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["user", "admin"] = "user"
    admin_code: str | None = None


def _set_session(response: Response, username: str, role: str) -> None:
    response.set_cookie(COOKIE, sign(username, role), max_age=TTL_S,
                        httponly=True, samesite="lax",
                        secure=os.environ.get("HELP_CENTRE_COOKIE_SECURE") == "1")


def _need_db():
    from . import db

    if not db.configured():
        raise HTTPException(503, "sign-up needs the database: set MONGODB_URI in .env")
    return db


@router.post("/login")
def login(req: Login, response: Response) -> dict:
    name = req.username.strip()
    acct = users().get(name)
    if acct is not None:
        if not hmac.compare_digest(acct[0].encode(), req.password.encode()):
            raise HTTPException(401, "wrong username or password")
        _set_session(response, name, acct[1])
        return {"username": name, "role": acct[1]}
    if "@" not in name:
        raise HTTPException(401, "wrong username or password")
    db = _need_db()
    try:
        user = db.find_user(name)
    except db.NotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 -- unreachable cluster
        raise HTTPException(503, "the database is not reachable; try again shortly") from exc
    if user is None or not db.check_password(req.password, user["password"]):
        raise HTTPException(401, "wrong email or password")
    _set_session(response, user["email"], user["role"])
    return {"username": user["email"], "name": user.get("name"), "role": user["role"]}


@router.post("/signup")
def signup(req: Signup, response: Response) -> dict:
    """Anyone may become a `user`. An `admin` needs an email in admin_emails
    AND the admin code; the two failures get the same message, so the form
    does not reveal which admin emails exist."""
    db = _need_db()
    email = db.norm_email(req.email)
    if not db.EMAIL.match(email):
        raise HTTPException(422, "enter a valid email address")
    try:
        if req.role == "admin":
            code_ok = hmac.compare_digest((req.admin_code or "").strip().encode(),
                                          admin_code().encode())
            if not (code_ok and db.is_admin_email(email)):
                raise HTTPException(403, "admin sign-up refused: this email is not on the "
                                         "admin list, or the admin code is wrong")
        user = db.create_user(email, req.name, req.password, req.role)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 -- unreachable cluster
        raise HTTPException(503, "the database is not reachable; try again shortly") from exc
    _set_session(response, user["email"], user["role"])
    return {"username": user["email"], "name": user["name"], "role": user["role"]}


@router.get("/me")
def me(request: Request) -> dict:
    who = current(request)
    if who is None:
        raise HTTPException(401, "not logged in")
    return who


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}
