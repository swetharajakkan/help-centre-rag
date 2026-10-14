"""Week 9: MCP host, discovery, recoverable errors, the crew, and the logins.

The MCP tests spawn the two real servers over stdio (the ticket-history
server needs no token on stdio) and drive the real agent package, so what is
tested is the protocol path the app uses. Reranking is off and the scenarios
run once per module, so the whole file costs one embedder load.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from week9.agent import crew, loop  # noqa: E402
from week9.agent.host import Host  # noqa: E402
from week9.agent.model import OfflineModel, identifiers, route_id  # noqa: E402

RAG = {"transport": "stdio", "command": sys.executable,
       "args": [os.path.join(ROOT, "week9", "servers", "rag_server.py")], "cwd": ROOT,
       "env": {"HELP_CENTRE_RERANK": "0"}}
TICKETS = {"transport": "stdio", "command": sys.executable,
           "args": [os.path.join(ROOT, "week9", "servers", "ticket_history", "server.py"),
                    "--transport", "stdio"],
           "env": {"TICKET_HISTORY_LOG": os.devnull},
           "attach": [{"uri": "tickets://{id}/escalations", "when": r"TCK-\d{4}"}]}


def cfg(**servers) -> dict:
    return {"path": "<test>", "servers": servers}


async def _scenarios() -> dict:
    out = {}
    model = OfflineModel()
    async with Host(cfg(**{"help-centre-rag": RAG})) as one:
        out["one"] = one.discovery()
    async with Host(cfg(**{"help-centre-rag": RAG, "ticket-history": TICKETS})) as both:
        out["both"] = both.discovery()
        out["ticket_run"] = await loop.run_agent(both, model, "Why was TCK-4403 escalated?")
        out["bm4"] = await loop.run_agent(both, model, "Open help article BM-4")
        out["crew"] = await crew.run_crew(both, model, "What is the status of TCK-4401?")
        v = crew.Verifier(both)
        good = {"text": "TCK-4403 is escalated with urgent priority.", "source_id": "TCK-4403",
                "quote": "Proration charged twice after mid-cycle upgrade",
                "facts": {"status": "escalated", "priority": "urgent"}}
        out["v_good"] = await v.verify({"kind": "answer", "claims": [good]})
        out["v_fact"] = await v.verify({"kind": "answer", "claims": [
            {**good, "facts": {"status": "resolved"}}]})
        out["v_quote"] = await v.verify({"kind": "answer", "claims": [
            {**good, "quote": "customer was refunded $41.50"}]})
        out["v_number"] = await v.verify({"kind": "answer", "claims": [
            {**good, "text": "TCK-4403 was escalated 7 times."}]})
        out["v_empty"] = await v.verify({"kind": "answer", "claims": []})
        out["bad_id"] = await both.call_tool("ticket-history__get_ticket", {"ticket_id": "TCK-44"})
        out["unknown_tool"] = await both.call_tool("ticket-history__drop_tables", {})
    legacy = {**RAG, "env": {**RAG["env"], "HELP_CENTRE_RAG_ERRORS": "legacy"}}
    async with Host(cfg(**{"help-centre-rag": legacy})) as old:
        out["bm4_legacy"] = await loop.run_agent(old, model, "Open help article BM-4")
    async with Host(cfg(dead={"transport": "http", "url": "http://127.0.0.1:9/mcp"},
                        **{"help-centre-rag": RAG})) as partial:
        out["partial"] = partial.discovery()
    return out


@pytest.fixture(scope="module")
def s():
    return asyncio.run(_scenarios())


def _names(d, server):
    return [t["name"] for t in d["servers"][server]["tools"]]


class TestWeek9Discovery:
    def test_server_one_alone(self, s):
        assert _names(s["one"], "help-centre-rag") == ["search_help_centre", "get_article"]
        assert s["one"]["tool_count"] == 2

    def test_server_two_by_config_only(self, s):
        assert s["both"]["tool_count"] == 4
        assert _names(s["both"], "ticket-history") == ["get_ticket", "get_escalation_history"]
        assert "ticket-history__get_ticket" in s["both"]["tool_names"]

    def test_primitives_beyond_tools(self, s):
        rag, tk = s["both"]["servers"]["help-centre-rag"], s["both"]["servers"]["ticket-history"]
        assert "kb://articles" in rag["resources"] and "grounded_answer" in rag["prompts"]
        assert tk["resource_templates"] == ["tickets://{ticket_id}/escalations"]
        assert tk["server_info"]["name"] == "ticket-history"

    def test_dead_server_does_not_sink_the_rest(self, s):
        assert not s["partial"]["servers"]["dead"]["connected"]
        assert s["partial"]["servers"]["dead"]["error"]
        assert s["partial"]["tool_count"] == 2


class TestWeek9Loop:
    def test_ticket_query_calls_server_two(self, s):
        r = s["ticket_run"]
        assert "ticket-history__get_ticket" in r["tool_calls"]
        # escalation history was attached by the host, so not fetched as a tool
        assert [c["uri"] for c in r["context"]] == ["tickets://TCK-4403/escalations"]
        assert "ticket-history__get_escalation_history" not in r["tool_calls"]
        assert "L3-ledger-eng" in r["final"]["answer"]

    def test_recoverable_error_recovers(self, s):
        r = s["bm4"]
        calls = [x["args"] for x in r["steps"] if x["kind"] == "tool"]
        assert calls == [{"article_id": "BM-4"}, {"article_id": "BM-004"}]
        assert r["final"]["kind"] == "answer" and "BM-004" in r["final"]["answer"]

    def test_opaque_error_is_retried_then_abandoned(self, s):
        r = s["bm4_legacy"]
        assert r["tool_calls"] == ["help-centre-rag__get_article"] * 3
        assert r["tool_errors"] == 3 and r["final"]["kind"] == "refusal"

    def test_tool_errors_come_back_as_data(self, s):
        assert s["bad_id"]["is_error"] and "TCK-nnnn" in s["bad_id"]["text"]
        assert s["unknown_tool"]["is_error"] and "no tool" in s["unknown_tool"]["text"]


class TestWeek9Crew:
    def test_crew_answer_is_verified(self, s):
        r = s["crew"]
        assert r["approved"] and r["verified_claims"] >= 3
        assert r["rounds"][0]["verdict"]["summary"].endswith("claims verified")

    def test_verifier_passes_a_true_claim(self, s):
        assert s["v_good"]["approved"]
        assert s["v_good"]["checks"][0]["refetched_via"] == "ticket-history__get_ticket"

    @pytest.mark.parametrize("case,why", [("v_fact", "status is"),
                                          ("v_quote", "not verbatim"),
                                          ("v_number", "figure 7")])
    def test_verifier_rejects_a_tampered_claim(self, s, case, why):
        assert not s[case]["approved"]
        assert any(why in r for r in s[case]["checks"][0]["reasons"])

    def test_uncited_answer_rejected(self, s):
        assert not s["v_empty"]["approved"]


class TestWeek9Routing:
    def test_identifiers(self):
        assert identifiers("see TCK-4403 and BM-4, Phase 2") == ["TCK-4403", "BM-4"]

    def test_route_prefers_plain_fetch(self):
        tools = [{"name": "t__get_ticket", "description": "ids look like TCK-nnnn",
                  "input_schema": {"type": "object", "required": ["ticket_id"],
                                   "properties": {"ticket_id": {"type": "string"}}}},
                 {"name": "t__get_escalation_history", "description": "TCK-nnnn",
                  "input_schema": {"type": "object", "required": ["ticket_id"],
                                   "properties": {"ticket_id": {"type": "string"}}}}]
        assert route_id("TCK-4403", tools)[0][1]["name"] == "t__get_ticket"
        assert route_id("TCK-4403", tools, "escalation history please")[0][1]["name"] \
            == "t__get_escalation_history"

    def test_gateway_scopes(self):
        from week9.gateway import required_scope
        assert required_scope("ticket-history_get_escalation_history") == "tickets:escalations"
        assert required_scope("ticket-history_get_ticket") == "tickets:read"
        assert required_scope("help-centre-rag_search_help_centre") == "kb:read"


class TestWeek9Auth:
    @pytest.fixture()
    def guarded(self, client, monkeypatch):
        monkeypatch.setenv("HELP_CENTRE_AUTH", "1")
        client.cookies.clear()
        yield client
        client.cookies.clear()

    def login(self, c, user, pw):
        return c.post("/api/auth/login", json={"username": user, "password": pw})

    def test_anonymous_is_locked_out(self, guarded):
        assert guarded.get("/api/documents").status_code == 401
        assert guarded.get("/api/health").status_code == 200

    def test_wrong_password(self, guarded):
        assert self.login(guarded, "admin", "nope").status_code == 401

    def test_user_can_only_ask(self, guarded):
        assert self.login(guarded, "user", "user123").json()["role"] == "user"
        assert guarded.get("/api/auth/me").json()["role"] == "user"
        for path in ("/api/documents", "/api/week9", "/api/week8"):
            assert guarded.get(path).status_code == 403, path
        assert guarded.post("/api/chat", json={"question": "x"}).status_code == 403

    def test_admin_gets_everything(self, guarded):
        assert self.login(guarded, "admin", "admin123").json()["role"] == "admin"
        assert guarded.get("/api/documents").status_code == 200

    def test_tampered_cookie_rejected(self, guarded):
        self.login(guarded, "user", "user123")
        tok = guarded.cookies.get("hc_session")
        body, sig = tok.rsplit(".", 1)
        import base64
        forged = base64.urlsafe_b64encode(json.dumps(
            {"u": "user", "r": "admin", "exp": 9999999999}).encode()).rstrip(b"=").decode()
        guarded.cookies.set("hc_session", f"{forged}.{sig}")
        assert guarded.get("/api/documents").status_code == 401

    def test_logout(self, guarded):
        self.login(guarded, "admin", "admin123")
        guarded.post("/api/auth/logout")
        guarded.cookies.clear()
        assert guarded.get("/api/auth/me").status_code == 401


class TestWeek9Track:
    @pytest.fixture()
    def log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HELP_CENTRE_TRACK_LOG", str(tmp_path / "track.jsonl"))
        return tmp_path / "track.jsonl"

    def test_record_from_a_real_crew_run(self, s, log):
        from backend.app import track
        rec = track.build({"username": "user", "role": "user"}, "What is the status of TCK-4401?",
                          s["crew"])
        track.append(rec)
        assert [a["name"] for a in rec["agents"]] == ["Responder", "Verifier"]
        assert "ticket-history__get_ticket" in rec["tools_called"]
        assert rec["agents"][1]["calls"], "verifier re-fetches are recorded"
        assert rec["rounds"][0]["checks"] and rec["context"] == ["tickets://TCK-4401/escalations"]
        listed = track.recent(role="user")
        assert listed["total"] == 1 and listed["items"][0]["n_agents"] == 2
        assert track.get(rec["id"])["question"] == rec["question"]
        assert track.recent(role="admin")["total"] == 0

    def test_failed_question_is_tracked(self, log):
        from backend.app import track
        track.append(track.build({"username": "user", "role": "user"}, "x", error="boom", ms=1.0))
        assert track.recent()["items"][0]["error"] == "boom"

    def test_only_admin_reads_the_track(self, client, monkeypatch, log):
        monkeypatch.setenv("HELP_CENTRE_AUTH", "1")
        client.cookies.clear()
        client.post("/api/auth/login", json={"username": "user", "password": "user123"})
        assert client.get("/api/track").status_code == 403
        assert client.get("/api/w9/questions").status_code == 200
        groups = client.get("/api/w9/questions").json()["groups"]
        assert groups["golden"] and set(groups["golden"][0]) == {"id", "question"}
        client.cookies.clear()
        client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert client.get("/api/track").status_code == 200
        assert client.get("/api/track/nope").status_code == 404
        client.cookies.clear()


class TestWeek9SmallTalk:
    @pytest.mark.parametrize("text,kind", [
        ("Hi", "greeting"), ("hello!!", "greeting"), ("Good morning", "greeting"),
        ("thanks", "thanks"), ("Thank you so much!", "thanks"), ("hi thanks", "thanks"),
        ("ok bye", "bye"), ("How are you?", "how_are_you"), ("who are you", "who"),
        ("what can you do?", "help"), ("cool", "ack")])
    def test_small_talk_recognised(self, text, kind):
        from week9.agent.smalltalk import classify
        r = classify(text)
        assert r and r["kind"] == kind and r["rest"] is None and r["reply"]

    @pytest.mark.parametrize("text", ["Why was TCK-4403 escalated?", "high priority tickets",
                                      "What happens to stored cards?", "Open help article BM-4"])
    def test_real_questions_are_not_small_talk(self, text):
        from week9.agent.smalltalk import classify
        assert classify(text) is None

    def test_greeting_then_question(self):
        from week9.agent.smalltalk import classify
        r = classify("hi, why was TCK-4403 escalated?")
        assert r["rest"] == "why was TCK-4403 escalated?"

    def test_crew_answers_small_talk_without_tools(self):
        class NoHost:          # any tool call or attach would raise
            pass
        r = asyncio.run(crew.run_crew(NoHost(), OfflineModel(), "Hello!"))
        assert r["kind"] == "smalltalk" and r["approved"] and "support agent" in r["answer"]
        from backend.app import track
        rec = track.build({"username": "user", "role": "user"}, "Hello!", r)
        assert [a["name"] for a in rec["agents"]] == ["Router"] and rec["tools_called"] == []
