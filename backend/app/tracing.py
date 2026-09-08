"""Optional Langfuse tracing for the answering pipeline.

Why this module exists
----------------------
Week 5's failure analysis could not start until a trace log existed, and this
deployment had none: `chat.py` streamed a retrieval trace to the browser and
nothing wrote it down. The 182 traces that week's taxonomy rests on were
produced by a one-off script replaying a generated question population, which
is why the write-up has to caveat every frequency as synthetic.

This is the permanent fix for that gap. Every answer the running app produces
is recorded, so the next taxonomy samples real traffic instead of replayed
traffic, and the caveat goes away.

The fields recorded here are exactly the ones `week5/run_traces.py` had to add
by hand, because those are the ones that turned out to be missing when someone
finally tried to replay an answer:

    prompt version and system-prompt hash, model and decoding parameters,
    every retrieved chunk_id with its fused / dense / bm25 / rerank scores,
    the grounding gate's score and refusal reason, the raw pre-verification
    output, the claims that were dropped and why, and the code and corpus
    hashes the answer was produced against.

Contract: OFF unless configured, and never fatal
------------------------------------------------
`enabled()` is False unless both Langfuse keys are in the environment, so the
offline test suite, the eval harness and a laptop with no network behave
exactly as they did before this file existed. Every call into the SDK is
wrapped: a tracing backend that is down, slow to import, or misconfigured must
never turn a working answer into a 500. Telemetry is not worth an outage.
"""
from __future__ import annotations

import contextlib
import functools
import re
import hashlib
import os
import subprocess
from typing import Any, Iterator

# Assigned in Week 5. There was no prompt version before that; see the module
# docstring in week5/run_traces.py.
PROMPT_VERSION = "extractive-v1"


def load_dotenv(path: str | None = None) -> None:
    """Read a .env file into os.environ, without adding a dependency.

    uvicorn does not load .env on its own, so without this the keys pasted
    into .env would be ignored and tracing would silently stay off -- the
    worst failure mode for telemetry, because it looks like it is working.

    Existing environment variables always win, so an explicit `export` still
    overrides the file.
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        # A placeholder left in from .env.example is not a credential.
        if key and key not in os.environ and value and not value.endswith("..."):
            os.environ[key] = value


def enabled() -> bool:
    """True only when both keys are present.

    Deliberately not a "is langfuse importable" check: having the package
    installed as a transitive dependency must not silently start shipping
    customer questions to a third party.
    """
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY")
                and os.environ.get("LANGFUSE_SECRET_KEY"))


# Support tickets carry customer data. These land in trace input, so they are
# redacted before anything leaves the process -- the alternative is shipping a
# customer's card number to a third party because someone pasted it into chat.
_REDACTIONS = (
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[card]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    (re.compile(r"\b(?:\+\d{1,3}[ -]?)?(?:\(?\d{3}\)?[ -]?){2}\d{4}\b"), "[phone]"),
    (re.compile(r"\b[A-Z]{2}[0-9A-Z]{8,30}\b"), "[iban-or-vat]"),
)


def mask(data: Any) -> Any:
    """Redact obvious customer identifiers anywhere in a traced payload.

    Passed to the SDK as its `mask` hook, so it applies to every field of
    every observation rather than only the ones a call site remembered.
    """
    try:
        if isinstance(data, str):
            for pattern, replacement in _REDACTIONS:
                data = pattern.sub(replacement, data)
            return data
        if isinstance(data, dict):
            return {k: mask(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [mask(v) for v in data]
        return data
    except Exception:
        # A mask that throws must not take the trace, or the request, with it.
        return "[mask-error]"


@functools.lru_cache(maxsize=1)
def _client():
    """The SDK client, or None if it cannot be constructed.

    Cached because constructing it opens a background exporter thread, and
    lru_cache means a failed import is not retried on every request.

    Imported here rather than at module scope on purpose: the SDK reads its
    credentials at construction, so it must not be imported before
    `load_dotenv()` has run.
    """
    if not enabled():
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=os.environ.get("LANGFUSE_BASE_URL",
                                "https://cloud.langfuse.com"),
            mask=mask,
        )
    except Exception:
        return None


@functools.lru_cache(maxsize=1)
def _code_version() -> str:
    try:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        return subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip()[:12]
    except Exception:
        return "unknown"


@functools.lru_cache(maxsize=1)
def _corpus_sha() -> str:
    import glob

    try:
        h = hashlib.sha256()
        pattern = os.path.join(os.path.dirname(__file__), "..", "..",
                               "corpus", "*.md")
        for path in sorted(glob.glob(pattern)):
            with open(path, "rb") as fh:
                h.update(fh.read())
        return h.hexdigest()[:16]
    except Exception:
        return "unknown"


def hit_summary(hits: list[dict]) -> list[dict]:
    """One row per retrieved chunk: the id and every score behind its rank.

    Rank alone is not replayable. The scores are what let someone later ask
    why a chunk placed where it did, which is the question Week 5 kept hitting.
    """
    return [{
        "rank": h.get("rank"),
        "chunk_id": h.get("chunk_id"),
        "article_id": (h.get("meta") or {}).get("article_id"),
        "product_area": (h.get("meta") or {}).get("product_area"),
        "fused": h.get("score"),
        "dense": h.get("dense"),
        "bm25": h.get("bm25"),
        "rerank": h.get("rerank_score"),
    } for h in hits]


def model_params(engine: str) -> dict:
    """The parameters that decide an answer, other than the question itself."""
    from . import generation

    llm = engine == "claude-opus-5"
    return {
        "engine": engine,
        "model": generation.MODEL if llm else "extractive-deterministic (no LLM)",
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": hashlib.sha256(
            generation.SYSTEM.encode()).hexdigest()[:16],
        "decoding": ({"max_tokens": 16000, "thinking": "adaptive",
                      "output_format": "json_schema"} if llm
                     else {"deterministic": True, "temperature": None}),
        "grounding_floor": generation.GROUNDING_FLOOR,
        "max_claims": generation.MAX_CLAIMS,
        "code_version": _code_version(),
        "corpus_sha256": _corpus_sha(),
    }


class _NullSpan:
    """Stands in for a Langfuse span when tracing is off.

    Every method is a no-op that accepts anything, so call sites never branch
    on whether tracing is enabled.
    """

    def update(self, **_: Any) -> None:
        pass

    def score(self, **_: Any) -> None:
        pass


@contextlib.contextmanager
def observe(name: str, as_type: str = "span", **attrs: Any) -> Iterator[Any]:
    """Open an observation, or yield a null one when tracing is off or broken.

    `as_type` is not decoration. Langfuse drives model analytics off
    `generation`, the agent graph off `agent`, and retrieval analytics off
    `retriever`; typing everything `span` throws all of that away. Names are
    verb-first per the Langfuse naming guidance so they read as operations.

    Any SDK failure degrades to the null observation rather than propagating:
    an answer must not fail because telemetry did.
    """
    client = _client()
    if client is None:
        yield _NullSpan()
        return
    try:
        with client.start_as_current_observation(as_type=as_type,
                                                 name=name) as span:
            if attrs:
                try:
                    span.update(**attrs)
                except Exception:
                    pass
            yield span
    except Exception:
        yield _NullSpan()


def score(name: str, value: float, comment: str | None = None) -> None:
    """Attach a score to the current trace.

    Outcomes belong here rather than in tags: Langfuse tags are set at
    creation and describe what was known upfront, while whether the answer
    was refused is only known at the end. Scores are also what the eval and
    dashboard views filter on.
    """
    client = _client()
    if client is None:
        return
    try:
        client.score_current_trace(name=name, value=value, comment=comment)
    except Exception:
        pass


@contextlib.contextmanager
def trace_attributes(**attrs: Any) -> Iterator[None]:
    """Propagate trace-level attributes to this span and every child.

    v4 has no `update_current_trace`. Trace-level dimensions -- session_id,
    user_id, tags -- come from the module-level `propagate_attributes` context
    manager, and the SDK is explicit that it must wrap the root span rather
    than be called at the end: only the active span and spans opened inside
    the context get the attributes, so aggregation by session or user silently
    misses anything created before it.

    None values are dropped, since passing session_id=None would blank a
    session the caller never meant to clear.
    """
    attrs = {k: v for k, v in attrs.items() if v is not None}
    if _client() is None or not attrs:
        yield
        return
    try:
        from langfuse import propagate_attributes

        with propagate_attributes(**attrs):
            yield
    except Exception:
        yield


def set_trace_io(span: Any, input: Any = None, output: Any = None) -> None:
    """Set what the trace table shows, which is not the same as the span's IO."""
    try:
        span.set_trace_io(input=input, output=output)
    except Exception:
        pass


def flush() -> None:
    """Force pending events out. Called on app shutdown."""
    client = _client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        pass


def status() -> dict:
    """What /api/health reports, so the UI can show whether tracing is live."""
    if not enabled():
        return {"enabled": False, "reason": "LANGFUSE_* keys not set"}
    if _client() is None:
        return {"enabled": False, "reason": "langfuse package not importable"}
    return {
        "enabled": True,
        "host": os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        "prompt_version": PROMPT_VERSION,
    }
