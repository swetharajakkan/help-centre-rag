"""Week 10: the triage squad vs single-agent race.

Two halves. The artifact tests read week10/race.json and check that what was
reported is internally consistent (same cases, multiplier arithmetic,
hand-off totals, the verdict's required parts). The arm tests drive
run_single / run_squad with retrieval stubbed out, so the hand-off log and
the injected 500 are checked without loading the embedder.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from week10 import race  # noqa: E402

RACE = os.path.join(ROOT, "week10", "race.json")


@pytest.fixture(scope="module")
def out() -> dict:
    if not os.path.exists(RACE):
        pytest.skip("run week10/race.py first")
    return json.load(open(RACE))


@pytest.fixture
def stub(monkeypatch):
    res = {"answered": True, "claims": [{"claim": "ERR-4215 means X.", "chunk_id": "c1"}],
           "refusal": ""}
    monkeypatch.setattr(race, "_search",
                        lambda index, t: (res, [{"chunk_id": "c1", "text": "ERR-4215 means X."}]))
    monkeypatch.setattr(race, "LAT_BASE_S", 0)
    monkeypatch.setattr(race, "LAT_PER_IN_S", 0)
    monkeypatch.setattr(race, "LAT_PER_OUT_S", 0)
    return {"ticket_id": "TCK-4002", "case_id": "C-02", "tier": "Standard",
            "days_since_purchase": 9, "refund_requested": False, "refund_amount_usd": None,
            "question": "What does ERR-4215 mean and what should I do?",
            "product_area": "subscriptions"}


class TestWeek10Race:
    def test_same_ten_week6_cases(self, out):
        judged = [json.loads(l)["case_id"] for l in
                  open(os.path.join(ROOT, "week6", "eval_set.jsonl"))
                  if l.strip() and json.loads(l)["judged"]]
        assert out["cases"] == judged[:10]
        for arm in ("single", "squad"):
            assert [r["case_id"] for r in out["runs"][arm]] == out["cases"]

    def test_four_numbers_both_arms(self, out):
        for arm in ("single", "squad"):
            s = out["summary"][arm]
            for k in ("pass_rate", "p50_s", "p99_s", "total_tokens", "cost_per_ticket_usd"):
                assert s[k] is not None
            assert s["p99_s"] >= s["p50_s"]

    def test_multiplier_and_attribution(self, out):
        S, M = out["summary"]["single"], out["summary"]["squad"]
        assert out["multiplier"] == round(M["total_tokens"] / S["total_tokens"], 1)
        assert sum(h["tokens"] for h in out["handoff_shares"]) == M["total_tokens"]
        assert out["handoff_shares"][0]["handoff"] in out["multiplier_line"]

    def test_handoffs_sum_to_totals(self, out):
        for arm in ("single", "squad"):
            for r in out["runs"][arm]:
                assert sum(h["tokens"] for h in r["handoffs"]) == r["tokens"]

    def test_verdict_names_sunk_cost_and_numbers(self, out):
        text = " ".join(out["verdict"])
        assert "sunk-cost" in text.lower()
        assert "Pass rate" in text and "Tokens" in text
        assert out["verdict"][-1].startswith("VERDICT: ")


class TestWeek10Arms:
    def test_single_three_calls_one_history(self, stub):
        r = race.run_single(stub, index=None)
        assert len(r["handoffs"]) == 3
        # One growing history: each call sends more than the one before.
        ins = [h["tokens_in"] for h in r["handoffs"]]
        assert ins == sorted(ins)
        assert "TCK-4002" in r["reply"]

    def test_squad_hands_off_to_both_workers(self, stub):
        r = race.run_squad(stub, index=None)
        to = [h["to"] for h in r["handoffs"]]
        assert to == ["orchestrator", "triage worker", "policy worker",
                      "policy worker", "orchestrator"]
        assert r["worker_error"] is None

    def test_injected_500_is_recorded_not_retried(self, stub):
        r = race.run_squad(stub, index=None, inject_500=True)
        errs = [h for h in r["handoffs"] if h["error"]]
        assert len(errs) == 1 and "500" in errs[0]["error"]
        assert r["policy_attempts"] == 1
        assert r["final"]["answered"] is False
        healthy = race.run_squad(stub, index=None)
        healthy["grade"] = r["grade"] = {}
        assert race.classify_failure(r, healthy)["behaviour"] == "degraded"


class TestWeek10A2A:
    @pytest.fixture
    def pair(self, stub):
        from week10 import a2a
        worker = a2a.PolicyWorker(index=None)
        return a2a, worker, a2a.Orchestrator(worker.handle, index=None), stub

    def test_card_advertises_skills_modes_auth(self, pair):
        _, worker, _, _ = pair
        card = worker.card()
        assert card["skills"] and card["defaultInputModes"] and card["securitySchemes"]

    def test_healthy_ticket_completes(self, pair):
        a2a, _, orch, t = pair
        task = orch.start(t)
        assert [x["state"] for x in task["transitions"]] == ["submitted", "working", "completed"]
        assert "TCK-4002" in a2a.view(task)["reply"]

    def test_worker_500_pauses_ticket_for_owner(self, pair):
        a2a, worker, orch, t = pair
        task = orch.start(t, inject_500=True)
        assert task["status"]["state"] == "input-required"
        assert a2a.view(task)["reply"] is None
        wt = list(worker.store.tasks.values())[-1]
        assert wt["status"]["state"] == "failed"
        again = orch.resume(task["id"], "retry")
        assert [x["state"] for x in again["transitions"]][-2:] == ["working", "completed"]

    def test_jsonrpc_errors(self, pair):
        _, worker, _, _ = pair
        assert worker.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})["error"]["code"] == -32601
        assert worker.handle({"jsonrpc": "2.0", "id": 2, "method": "tasks/get",
                              "params": {"id": "missing"}})["error"]["code"] == -32001


class TestWeek10Fanout:
    """Race 2: the single agent as built runs out of Week 7's call budget on
    many-issue tickets; the squad's workers each stay at two calls."""

    @pytest.fixture
    def rows(self, monkeypatch):
        from week10 import fanout
        monkeypatch.setattr(race, "LAT_BASE_S", 0)
        monkeypatch.setattr(race, "LAT_PER_IN_S", 0)
        monkeypatch.setattr(race, "LAT_PER_OUT_S", 0)
        monkeypatch.setattr(fanout, "_lookup", lambda index, code: (
            [{"claim": f"| {code} | cause | fix |", "chunk_id": f"c-{code}"}],
            [{"chunk_id": f"c-{code}", "text": f"| {code} | cause | fix |"}]))
        return fanout

    def test_single_hits_call_budget_at_seven_issues(self, rows):
        ok = rows.run_single(rows.sweep_ticket(6)["ticket"], None)
        over = rows.run_single(rows.sweep_ticket(7)["ticket"], None)
        assert ok["terminated"] is None and ok["calls"] == 8
        assert over["terminated"] and "max_iterations" in over["terminated"]
        assert not over["answered"] and "[ESCALATED]" in over["reply"]

    def test_squad_agents_stay_small_and_answer(self, rows):
        r = rows.run_squad(rows.sweep_ticket(10)["ticket"], None)
        assert r["terminated"] is None and r["answered"]
        assert r["agents"] == 12                      # orchestrator + triage + 10 workers
        assert all(c in r["reply"] for c in rows.SWEEP_CODES)

    def test_parallel_single_needs_three_calls(self, rows):
        r = rows.run_single(rows.sweep_ticket(10)["ticket"], None, parallel=True)
        assert r["calls"] == 3 and r["terminated"] is None
