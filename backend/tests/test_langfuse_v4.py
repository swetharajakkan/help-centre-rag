"""Langfuse v4 instrumentation contract, checked on the spans actually emitted.

The real SDK client is constructed through backend/app/tracing.py and routed
to an in-memory OpenTelemetry exporter, so these tests read the exact span
attributes that would be shipped -- no network, no credentials. Its own
exporter points at a closed local port and never delivers anything.

What v4 requires of this codebase, and what each test pins:

  * no trace-level input/output (deprecated) -- the root observation carries
    the readable input and output instead
  * session id, tags and release reach every observation in the trace,
    including the cost-bearing generation, because propagate_attributes wraps
    the root span
  * `base_url`, not the deprecated `host`, and an environment taken from
    LANGFUSE_TRACING_ENVIRONMENT
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

import pytest

pytest.importorskip("langfuse")

from opentelemetry import trace as otel_trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter)

from backend.app import tracing  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
TRACE_INPUT = "langfuse.trace.input"
TRACE_OUTPUT = "langfuse.trace.output"
OBS_INPUT = "langfuse.observation.input"
OBS_OUTPUT = "langfuse.observation.output"
OBS_TYPE = "langfuse.observation.type"

EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(EXPORTER))


@pytest.fixture(scope="module")
def langfuse_on():
    """Tracing ON for this module only, then back to the suite's OFF state."""
    mp = pytest.MonkeyPatch()
    mp.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-00000000-0000-0000-0000-000000000000")
    mp.setenv("LANGFUSE_SECRET_KEY", "sk-lf-00000000-0000-0000-0000-000000000000")
    mp.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:9")
    mp.setenv("LANGFUSE_TRACING_ENVIRONMENT", "verification")
    # Langfuse attaches to a globally registered provider when there is one.
    otel_trace.set_tracer_provider(_PROVIDER)
    tracing._client.cache_clear()
    client = tracing._client()
    assert client is not None, "tracing._client() failed to construct"
    yield client
    tracing._client.cache_clear()
    mp.undo()


@pytest.fixture
def spans(langfuse_on):
    EXPORTER.clear()

    def collect():
        langfuse_on.flush()
        return list(EXPORTER.get_finished_spans())
    return collect


def _one_trace(spans):
    ids = {s.context.trace_id for s in spans}
    assert len(ids) == 1, f"expected one trace, got {len(ids)}"
    return spans


def _root(spans, name):
    root = [s for s in spans if s.name == name]
    assert len(root) == 1, [s.name for s in spans]
    assert root[0].parent is None, f"{name} is not the root observation"
    return root[0]


def _assert_no_trace_io(spans):
    for s in spans:
        assert TRACE_INPUT not in s.attributes, f"{s.name} sets deprecated trace input"
        assert TRACE_OUTPUT not in s.attributes, f"{s.name} sets deprecated trace output"


# ------------------------------------------------------------ the answer path

def test_answer_root_carries_io_and_session_reaches_every_child(
        structure_index, spans):
    from backend.app.generation import answer_extractive

    q = "What does ERR-4036 mean?"
    answer_extractive(structure_index, q, k=3, session_id="sess-v4",
                      user_id="user-v4")
    out = _one_trace(spans())
    root = _root(out, "answer-question")

    assert q in root.attributes[OBS_INPUT]
    assert root.attributes.get(OBS_OUTPUT), "root observation has no output"
    _assert_no_trace_io(out)

    # Every observation, the generation included, carries the session and
    # user, so session cost and user filters see the whole trace.
    names = {s.name for s in out}
    assert {"retrieve-chunks", "check-grounding", "compose-answer"} <= names
    for s in out:
        assert s.attributes.get("session.id") == "sess-v4", s.name
        assert s.attributes.get("user.id") == "user-v4", s.name
    gen = next(s for s in out if s.name == "compose-answer")
    assert gen.attributes[OBS_TYPE] == "generation"


def test_release_and_environment_are_set(structure_index, spans):
    from backend.app.generation import answer_extractive

    answer_extractive(structure_index, "What does ERR-4036 mean?", k=3)
    for s in spans():
        assert s.attributes.get("langfuse.release") == tracing._code_version()
        assert s.attributes.get("langfuse.environment") == "verification"


# ---------------------------------------------------------- week 7 systems

def _week7():
    for p in (ROOT / "week7", ROOT / "week6"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import agent
    import workflow
    return agent, workflow


@pytest.mark.parametrize("system", ["agent", "workflow"])
def test_week7_root_has_contract_and_generations_are_costed(system, spans):
    agent, workflow = _week7()
    fn = agent.run_agent if system == "agent" else workflow.run_workflow
    result = fn("TCK-7004")
    out = _one_trace(spans())
    root = _root(out, f"resolve-ticket-{system}")

    assert "TCK-7004" in root.attributes[OBS_INPUT]
    contract = json.loads(root.attributes[OBS_OUTPUT])
    assert contract["decision"] == result["output"]["decision"]
    assert "reply" in contract
    _assert_no_trace_io(out)

    gens = [s for s in out if s.attributes.get(OBS_TYPE) == "generation"]
    assert len(gens) == result["llm_calls"]
    for g in gens:
        usage = json.loads(g.attributes["langfuse.observation.usage_details"])
        cost = json.loads(g.attributes["langfuse.observation.cost_details"])
        assert usage["input"] > 0
        assert usage["output"] > 0
        assert cost["total"] > 0
    tools = [s.name for s in out if s.attributes.get(OBS_TYPE) == "tool"]
    assert tools == result["path"]
    for s in out:
        tags = s.attributes.get("langfuse.trace.tags")
        assert tags, s.name
        assert f"system:{system}" in tags, s.name


def test_week6_grading_trace(spans):
    from backend.app.main import eval_week6

    body = eval_week6(grader="human")
    out = _one_trace(spans())
    root = _root(out, "grade-week6-eval")
    assert "Human labels" in root.attributes[OBS_INPUT]
    assert f"{body['summary']['pass_total']}/" in root.attributes[OBS_OUTPUT]
    _assert_no_trace_io(out)
    evaluators = [s for s in out if s.attributes.get(OBS_TYPE) == "evaluator"]
    assert len(evaluators) == body["summary"]["n_cases"]


# ------------------------------------------------------------ static checks

DEPRECATED = re.compile(r"\bset_(?:current_)?trace_io\b|Langfuse\([^)]*\bhost\s*=", re.S)


def test_no_deprecated_langfuse_calls_in_source():
    hits = []
    for base in ("backend/app", "week5", "week6", "week7"):
        for path in (ROOT / base).rglob("*.py"):
            text = path.read_text()
            for m in DEPRECATED.finditer(text):
                hits.append(f"{path.relative_to(ROOT)}: {m.group(0)[:40]}")
    assert not hits, hits


def test_sdk_is_v4_and_pinned():
    import importlib.metadata as md
    pinned = re.search(r"^langfuse==(\S+)", (ROOT / "requirements.txt").read_text(), re.M)
    assert pinned, "langfuse is not pinned in requirements.txt"
    assert pinned.group(1).split(".")[0] == "4"
    assert md.version("langfuse") == pinned.group(1)
