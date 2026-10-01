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


def unset(key: str, value: str | None) -> bool:
    """True when `value` is not a usable setting for `key`.

    Empty is unset, and so is a placeholder copied out of .env.example: the
    documented stand-in is a prefix followed by an ellipsis. A placeholder is
    worse than nothing, because it is a non-empty string, so `enabled()` goes
    true, the client constructs, /api/health reports tracing live, and every
    batch is then rejected 401 on a background thread nobody reads.

    A real Langfuse key is a prefix plus a UUID, so anything short is a
    stand-in too. Only the keys get the length rule; a self-hosted host URL is
    legitimately short.
    """
    if not value:
        return True
    if value.endswith("..."):
        return True
    return key.endswith("_KEY") and len(value) < 20


def load_dotenv(path: str | None = None) -> None:
    """Read a .env file into os.environ, without adding a dependency.

    uvicorn does not load .env on its own, so without this the keys pasted
    into .env would be ignored and tracing would silently stay off -- the
    worst failure mode for telemetry, because it looks like it is working.

    A real value already in the environment still wins, so an explicit
    `export` overrides the file. A placeholder in the environment does not:
    `export LANGFUSE_PUBLIC_KEY=pk-lf-...` used to beat the real key in this
    file and turn tracing off for the whole process while health still
    reported it on. Tracing has to come up whenever .env holds real keys, and
    a leftover export in someone's shell is not a decision to disable it.
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
        if not key or unset(key, value):
            continue
        if unset(key, os.environ.get(key)):
            os.environ[key] = value


def enabled() -> bool:
    """True only when both keys are present.

    Deliberately not a "is langfuse importable" check: having the package
    installed as a transitive dependency must not silently start shipping
    customer questions to a third party.
    """
    return not (unset("LANGFUSE_PUBLIC_KEY",
                      os.environ.get("LANGFUSE_PUBLIC_KEY"))
                or unset("LANGFUSE_SECRET_KEY",
                         os.environ.get("LANGFUSE_SECRET_KEY")))


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

        # `base_url`, not `host`: `host` is deprecated in SDK v4. The release
        # is the git commit, so Langfuse can group and compare traces by the
        # code that produced them. Environment is left to the SDK's own
        # LANGFUSE_TRACING_ENVIRONMENT, so a test run can be kept apart from
        # production traffic without a code change.
        return Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            base_url=os.environ.get("LANGFUSE_BASE_URL",
                                    "https://cloud.langfuse.com"),
            release=_code_version(),
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


# Ordered least to most damaging, so index() is the numeric rank.
SEVERITY_LEVELS = ("low", "medium", "high")


def severity(result: dict, area: str | None = None) -> tuple[str, str]:
    """Rank one answer by how much damage it can do, as (level, why).

    The levels are the two-way split from week5/taxonomy.md turned into three,
    because "embarrasses the client" and "annoys the user" are what the
    account manager actually escalates on and a clean answer needs a name too:

        high    something wrong went OUT. The answer shipped and its claims
                are not confined to one article, or one cites outside the
                product area the caller asked for. That is taxonomy modes 2
                and 5 -- the right fix followed by rows for error codes the
                customer never reported -- which is the family the client
                sees, and the reason mode 2 survived a month of review.
        medium  nothing wrong left the room, but the agent is blocked or was
                only rescued. A refusal while a product-area filter was set is
                the unrescued mode 1; the filter fallback firing is the same
                failure caught in flight, and is still worth counting because
                without Week 5 it would have been a refusal.
        low     a single-article answer, or a refusal on a question the corpus
                genuinely does not cover. Correct behaviour, named so that
                "everything is fine" is a filter and not the absence of one.

    Only what a live trace can actually observe is used. Hallucination
    (mode 4) is deliberately absent: an answer of real sentences about the
    wrong subject is invisible from inside the pipeline and needs a judge, so
    claiming to detect it here would make `low` mean less than it does.

    Rules are ordered, first match wins, and the reason is returned so the
    score carries its own justification into the Langfuse UI.
    """
    try:
        if not result.get("answered"):
            if area:
                return "medium", f"refused with the {area} filter set"
            return "low", "refused, no product-area filter was set"

        claims = result.get("claims") or []
        fired = bool((result.get("filter_fallback") or {}).get("fired"))
        articles = {c.get("article_id") for c in claims if c.get("article_id")}

        if len(articles) > 1:
            return "high", ("answer mixes " + str(len(articles)) + " articles: "
                            + ", ".join(sorted(a for a in articles if a)))
        # When the fallback fired the filter was dropped on purpose, so
        # answering from outside the area is the fix working, not a leak.
        if area and not fired:
            outside = sorted({c.get("product_area") for c in claims
                              if c.get("product_area")
                              and c.get("product_area") != area})
            if outside:
                return "high", (f"asked for {area}, cited "
                                + ", ".join(outside))
        if fired:
            return "medium", ("answered only after dropping the "
                              + str((result.get("filter_fallback") or {})
                                    .get("dropped_filter")) + " filter")
        return "low", "single-article answer, no filter retry"
    except Exception:
        # A severity that throws must not take the trace, or the request,
        # with it. An unknown level is better than a lost answer.
        return "low", "severity could not be determined"


def score(name: str, value: float | str, comment: str | None = None) -> None:
    """Attach a score to the current trace.

    Outcomes belong here rather than in tags: Langfuse tags are set at
    creation and describe what was known upfront, while whether the answer
    was refused is only known at the end. Scores are also what the eval and
    dashboard views filter on.

    A string value is sent as a CATEGORICAL score. Langfuse infers NUMERIC
    otherwise and would reject "high", so severity has to declare its type.
    """
    client = _client()
    if client is None:
        return
    try:
        client.score_current_trace(
            name=name, value=value, comment=comment,
            data_type="CATEGORICAL" if isinstance(value, str) else "NUMERIC")
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


def trace_url() -> str | None:
    """Link to the trace the current observation belongs to, for the UI.

    None when tracing is off, so the UI can show "not traced" instead of a
    dead link.
    """
    client = _client()
    if client is None:
        return None
    try:
        return client.get_trace_url(trace_id=client.get_current_trace_id())
    except Exception:
        return None


def flush() -> None:
    """Force pending events out. Called on app shutdown."""
    client = _client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        pass


@functools.lru_cache(maxsize=1)
def authenticated() -> bool | None:
    """Whether the keys are actually accepted by the host.

    True accepted, False rejected, None the check could not be made.

    One call per process, cached, because constructing a client proves
    nothing: it does not touch the network, so wrong keys look identical to
    right ones until the first batch is dropped in a background thread. That
    is how a day of traffic went untraced while /api/health said tracing was
    live. Reporting "on" now requires the host to agree.
    """
    client = _client()
    if client is None:
        return False
    try:
        return bool(client.auth_check())
    except Exception as exc:
        # A rejection is an answer worth reporting. No network, DNS, a proxy
        # in the way -- those are not evidence the keys are wrong, so they
        # stay unknown rather than being blamed on the credentials.
        if "401" in str(exc) or "Unauthorized" in type(exc).__name__:
            return False
        return None


def status() -> dict:
    """What /api/health reports, so the UI can show whether tracing is live."""
    host = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    if not enabled():
        return {"enabled": False,
                "reason": "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are "
                          "missing or still placeholders"}
    if _client() is None:
        return {"enabled": False, "reason": "langfuse package not importable"}
    if authenticated() is False:
        return {"enabled": False, "host": host,
                "reason": f"{host} rejected the LANGFUSE_* keys (401)"}
    return {
        "enabled": True,
        "host": host,
        "prompt_version": PROMPT_VERSION,
        # False means the host could not be reached to confirm the keys, so
        # spans are being buffered on trust rather than on an answer.
        "verified": authenticated() is True,
    }
