"""Sign-up (user / admin), MongoDB-backed login, and admin documents.

MongoDB is mongomock (in memory), and the documents MCP server runs
in-process over fastmcp's memory transport so it shares that database; the
help-centre server is the real one over stdio. Reranking is off.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

DOC = b"""# Refund policy after the billing migration

Customers who were double charged during the migration receive a full refund
within 10 business days. Refunds go back to the original payment method.
"""


@pytest.fixture()
def mongo(monkeypatch):
    pytest.importorskip("mongomock")
    from backend.app import db

    monkeypatch.setenv("MONGODB_URI", "mongomock://")
    monkeypatch.setenv("MONGODB_DB", "test_help_centre")
    db.database.cache_clear()
    yield db
    db.database.cache_clear()


@pytest.fixture()
def client(mongo, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import app

    monkeypatch.setenv("HELP_CENTRE_AUTH", "1")
    monkeypatch.setenv("HELP_CENTRE_ADMIN_CODE", "letmein")
    return TestClient(app)


def signup(c, email, role="user", code=None):
    return c.post("/api/auth/signup", json={"name": "N", "email": email, "password": "password1",
                                            "role": role, "admin_code": code})


class TestSignup:
    def test_seeded_admin_list(self, mongo):
        assert mongo.is_admin_email("SwethaRajakkan@yopmail.com")
        assert mongo.database().admin_emails.count_documents({}) >= 3

    def test_user_signs_up_and_is_a_user(self, client):
        assert signup(client, "ann@example.com").json()["role"] == "user"
        assert client.get("/api/auth/me").json()["role"] == "user"
        assert client.get("/api/docs").status_code == 403

    @pytest.mark.parametrize("email,code", [("eve@example.com", "letmein"),       # not listed
                                            ("swetharajakkan@yopmail.com", "no"),  # wrong code
                                            ("swetharajakkan@yopmail.com", None)])
    def test_admin_needs_list_and_code(self, client, email, code):
        assert signup(client, email, "admin", code).status_code == 403

    def test_listed_admin_with_code(self, client):
        assert signup(client, "swetharajakkan@yopmail.com", "admin", "letmein").json()["role"] == "admin"
        assert client.get("/api/docs").status_code == 200

    def test_duplicate_and_login(self, client):
        signup(client, "ann@example.com")
        assert signup(client, "ANN@example.com").status_code == 409
        client.post("/api/auth/logout")
        bad = client.post("/api/auth/login", json={"username": "ann@example.com", "password": "x"})
        assert bad.status_code == 401
        ok = client.post("/api/auth/login", json={"username": "ann@example.com", "password": "password1"})
        assert ok.json()["role"] == "user"

    def test_password_is_hashed(self, client, mongo):
        signup(client, "ann@example.com")
        assert mongo.find_user("ann@example.com")["password"].startswith("pbkdf2_sha256$")

    def test_demo_accounts_still_work(self, client):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert r.json()["role"] == "admin"


class TestDocuments:
    @pytest.fixture()
    def admin(self, client):
        signup(client, "swetharajakkan@yopmail.com", "admin", "letmein")
        return client

    def up(self, c, cats="Refund, billing"):
        return c.post("/api/docs", files={"file": ("refund.md", DOC, "text/markdown")},
                      data={"title": "Refund policy", "categories": cats})

    def test_upload_stores_document_and_categories(self, admin, mongo):
        d = self.up(admin).json()["document"]
        assert d["doc_id"] == "DOC-001" and d["categories"] == ["Refund", "Billing"]
        stored = mongo.get_document("DOC-001", with_raw=True)
        assert stored["raw"] == DOC and "double charged" in stored["text"]
        assert [x["doc_id"] for x in admin.get("/api/docs?category=Refund").json()["documents"]] == ["DOC-001"]
        assert admin.get("/api/docs?category=Tax").json()["documents"] == []

    def test_category_required(self, admin):
        assert self.up(admin, cats="").status_code == 422

    def test_delete(self, admin):
        self.up(admin)
        assert admin.delete("/api/docs/DOC-001").status_code == 200
        assert admin.get("/api/docs/DOC-001").status_code == 404


class TestWeek9AnswersFromDocuments:
    def test_refund_question_answered_from_upload(self, mongo, monkeypatch):
        monkeypatch.setenv("HELP_CENTRE_RERANK", "0")
        mongo.insert_document(title="Refund policy", filename="refund.md", content_type="text/markdown",
                              raw=DOC, text=DOC.decode(), categories=["Refund"], uploaded_by="t")
        import week9.agent.host as host_mod
        import week9.servers.documents_server as ds
        from week9.agent import crew
        from week9.agent.model import OfflineModel

        real = host_mod._transport
        monkeypatch.setattr(host_mod, "_transport",
                            lambda spec: ds.mcp if spec.get("inproc") else real(spec))
        rag = {"transport": "stdio", "command": sys.executable,
               "args": [os.path.join(ROOT, "week9", "servers", "rag_server.py")], "cwd": ROOT,
               "env": {"HELP_CENTRE_RERANK": "0"}}

        async def run():
            cfg = {"path": "<test>", "servers": {"help-centre-rag": rag,
                                                 "admin-documents": {"inproc": True}}}
            async with host_mod.Host(cfg) as h:
                assert "admin-documents__search_documents" in h.discovery()["tool_names"]
                r = await crew.run_crew(h, OfflineModel(), "Do double charged customers get a refund?")
                fixed = await crew.run_crew(h, OfflineModel(), "Open DOC-1")
                return r, fixed

        r, fixed = asyncio.run(run())
        assert "admin-documents__search_documents" in r["responder"]["tool_calls"]
        assert r["approved"] and "DOC-001" in r["answer"]
        # the malformed id is reshaped from the error text, then verified
        assert fixed["responder"]["tool_calls"][-1] == "admin-documents__get_document"
        assert fixed["approved"] and "DOC-001" in fixed["answer"]
