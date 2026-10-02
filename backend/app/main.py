"""FastAPI service for the help-centre RAG app."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import tracing

# Before anything reads the environment, so keys pasted into .env take effect.
tracing.load_dotenv()
from .chat import MODES, chat_stream, resolve_mode, resolve_fallback
from .generation import answer_auto, api_key_present
from .ingest import build_index, load_articles, load_uploads, records_for
from .rerank import RERANK_CANDIDATES, RERANK_MODEL, rerank_enabled
from .ocr import available_engines as ocr_engines
from .uploads import Rejected, delete as delete_upload, store as store_upload

INDEXES: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Index the 6 new articles only. The historical corpus is NOT re-indexed."""
    for strategy in ("fixed_window", "structure_aware"):
        # The running app is the one caller that also indexes uploads.
        INDEXES[strategy] = build_index(strategy, include_uploads=True)
        INDEXES[strategy].save()
    st = tracing.status()
    if st["enabled"]:
        print(f"[tracing] langfuse ON -> {st['host']}"
              + ("" if st["verified"] else "  (keys unverified: host unreachable)"))
    else:
        # Loud on purpose. Tracing off is not a normal operating state here --
        # every answer the app produces is meant to be recorded, and a silent
        # one-line OFF is exactly what let a day of traffic go untraced.
        print("\n".join(("!" * 72,
                         "[tracing] langfuse OFF -- answers are NOT being recorded",
                         f"[tracing] {st['reason']}",
                         "[tracing] put real keys in .env; a leftover shell",
                         "[tracing] export no longer overrides them",
                         "!" * 72)))
    yield
    # Short-lived events would otherwise die with the process.
    tracing.flush()


app = FastAPI(title="Help Centre RAG", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def _index(strategy: str):
    if strategy not in INDEXES:
        raise HTTPException(400, f"unknown strategy {strategy!r}")
    return INDEXES[strategy]


def _rerank_for(mode: str | None) -> bool | None:
    """`mode` picks the experiment arm per request, so one server can serve
    both. Omitting it keeps the process-wide HELP_CENTRE_RERANK default."""
    try:
        return resolve_mode(mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _fallback_for(mode: str | None) -> bool:
    """Week 5 only: retry without the product-area filter before refusing."""
    try:
        return resolve_fallback(mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class SearchRequest(BaseModel):
    query: str
    strategy: str = "structure_aware"
    k: int = Field(default=5, ge=1, le=10)
    product_area: str | None = None
    mode: str | None = None


class AskRequest(BaseModel):
    question: str
    strategy: str = "structure_aware"
    k: int = Field(default=3, ge=1, le=10)
    product_area: str | None = None
    mode: str | None = None
    # Groups every turn of one chat into a Langfuse session, so a conversation
    # can be replayed as a whole rather than as loose, unrelated traces.
    session_id: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "generation_engine": "claude-opus-5" if api_key_present()
                             else "extractive-deterministic",
        # Which retrieval arm this process is serving. Week 4's before/after
        # demo is two servers that differ only in this block.
        "reranking": {
            "enabled": rerank_enabled(),
            "model": RERANK_MODEL if rerank_enabled() else None,
            "candidates": RERANK_CANDIDATES if rerank_enabled() else None,
            "arm": "after (week 4)" if rerank_enabled() else "before (week 3)",
        },
        # Per-request arms. `reranking.enabled` above is only the default
        # used when a request sends no `mode`.
        "modes": {m: v["label"] for m, v in MODES.items()},
        "tracing": tracing.status(),
        "strategies": {s: len(i.records) for s, i in INDEXES.items()},
        "articles_indexed": len(load_articles()),
        "uploaded_documents": len(load_uploads()),
        # Empty list means images will be refused: there is nothing that can
        # read text out of them on this server.
        "ocr_engines": ocr_engines(),
        "indexed_chunks": len(_index("structure_aware").records),
        "historical_corpus_reindexed": False,
    }


def _upload_article(stored_name: str):
    """Re-read one stored upload from disk as (source_file, front, body)."""
    return next((a for a in load_uploads() if a[0] == stored_name), None)


@app.get("/api/documents")
def documents() -> dict:
    """Everything currently indexed, shipped corpus and uploads alike."""
    counts: dict[str, int] = {}
    for rec in _index("structure_aware").records:
        counts[rec.source_file] = counts.get(rec.source_file, 0) + 1
    uploaded = {name for name, _, _ in load_uploads()}
    docs = []
    for source_file, front, _ in load_articles() + load_uploads():
        docs.append({
            "source_file": source_file,
            "article_id": front.get("article_id", ""),
            "title": front.get("title", ""),
            "product_area": front.get("product_area", ""),
            "last_updated": front.get("last_updated", ""),
            "chunks": counts.get(source_file, 0),
            "uploaded": source_file in uploaded,
            "extracted_by": front.get("extracted_by", ""),
            "original_file": front.get("original_file", ""),
        })
    return {"documents": docs, "total_chunks": len(_index("structure_aware").records)}


@app.post("/api/documents")
async def upload_documents(files: list[UploadFile]) -> dict:
    """Drag-and-drop ingest. Any file type may be sent.

    Each accepted file is normalised to markdown-with-frontmatter under
    `backend/uploads/`, chunked by BOTH strategies and added to both live
    indexes, then persisted. Because the normalised file is on disk, a restart
    re-ingests it through the ordinary startup path -- the upload is durable,
    not just resident in memory.
    """
    accepted, rejected = [], []
    for upload in files:
        name = upload.filename or "document"
        try:
            data = await upload.read()
            stored_name, article_id = store_upload(name, data)
        except Rejected as exc:
            rejected.append({"filename": name, "reason": str(exc)})
            continue
        except Exception as exc:  # unreadable stream, permissions, ...
            rejected.append({"filename": name,
                             "reason": f"{type(exc).__name__}: {exc}"})
            continue

        article = _upload_article(stored_name)
        if article is None:
            rejected.append({"filename": name,
                             "reason": "stored but could not be re-read"})
            continue

        added = 0
        for strategy, index in INDEXES.items():
            # Overwrite semantics: a re-upload of the same name replaces the
            # previous chunks instead of indexing the document twice.
            index.remove_source(stored_name)
            new = records_for(strategy, [article])
            index.add(new)
            index.save()
            if strategy == "structure_aware":
                added = len(new)
        accepted.append({"filename": name, "stored_as": stored_name,
                         "article_id": article_id, "chunks": added,
                         "extracted_by": _upload_article(stored_name)[1]
                                         .get("extracted_by", "")})

    if not accepted and rejected:
        # Nothing was indexed -- say why, with the status the UI can branch on.
        raise HTTPException(422, {"accepted": [], "rejected": rejected})
    return {"accepted": accepted, "rejected": rejected,
            "total_chunks": len(_index("structure_aware").records)}


@app.delete("/api/documents/{stored_name}")
def delete_document(stored_name: str) -> dict:
    """Remove an uploaded document and every chunk it produced."""
    if stored_name not in {name for name, _, _ in load_uploads()}:
        raise HTTPException(404, "no uploaded document by that name "
                                 "(shipped corpus articles cannot be deleted)")
    dropped = 0
    for index in INDEXES.values():
        dropped = max(dropped, index.remove_source(stored_name))
        index.save()
    delete_upload(stored_name)
    return {"deleted": stored_name, "chunks_removed": dropped,
            "total_chunks": len(_index("structure_aware").records)}


@app.get("/api/product_areas")
def product_areas() -> dict:
    areas = sorted({r.meta.get("product_area", "")
                    for r in _index("structure_aware").records if r.meta.get("product_area")})
    return {"product_areas": areas}


@app.get("/api/examples")
def examples() -> dict:
    """The Week 4 golden set, served to the UI as one-click questions.

    Read from golden_set.jsonl rather than duplicated in the frontend, so the
    questions the UI offers are exactly the ones the eval harness scores.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "eval",
                        "golden_set.jsonl")
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            g = json.loads(line)
            out.append({
                "id": g["id"],
                "question": g["question"],
                "gold_article": g.get("gold_article"),
                "gold_section": g.get("gold_section"),
                "expected_chunk_id": g.get("expected_chunk_id"),
            })
    return {"examples": out, "sampled": _sampled_examples(),
            "replay": _replay_example(), "week6": _week6_examples(),
            "week7": _week7_examples(), "week8": _week8_examples()}


def _week6_examples() -> list[dict]:
    """The 27 Week 6 eval cases, as askable questions. [] if not run."""
    try:
        labels = _week6_json("labels_25.json")["labels"]
        return [{"id": c["case_id"], "question": c["ticket"]["question"],
                 "product_area": c["ticket"]["product_area"] or "",
                 "mode": c["mode"], "replay_verbatim": c["replay_verbatim"],
                 "human": labels.get(c["case_id"], {}).get("label")}
                for c in _week6_lines("eval_set.jsonl")]
    except (OSError, ValueError, KeyError):
        return []


def _week7_examples() -> list[dict]:
    """The 10 Week 7 race tickets, as askable customer messages."""
    try:
        _week7()
        from store import EXPECTED, TICKET_IDS, TICKETS
        return [{"id": t, "question": TICKETS[t]["message"],
                 "cls": EXPECTED[t]["cls"]} for t in TICKET_IDS]
    except Exception:
        return []


def _replay_example() -> dict | None:
    """The trace drawn for the replay proof.

    It is deliberately NOT one of the 20 -- it was a second, independent draw
    from the same seed -- so it does not appear in the sampled list and had no
    way to be reached from the UI. Served separately so the replay evidence
    can be demonstrated live rather than only read in notes.md.
    """
    week5 = os.path.join(os.path.dirname(__file__), "..", "..", "week5")
    try:
        want = json.load(open(os.path.join(week5, "sample.json")))["replay_trace_id"]
        with open(os.path.join(week5, "traces.jsonl")) as fh:
            for line in fh:
                if not line.strip():
                    continue
                t = json.loads(line)
                if t["trace_id"] != want:
                    continue
                return {
                    "id": t["trace_id"],
                    "question": t["question"],
                    "product_area": t["request"]["product_area"],
                    "k": t["request"]["k"],
                    "mode": t["request"]["mode"],
                    "answered": t["result"]["answered"],
                    "claims": [c["claim"] for c in t["result"].get("claims", [])],
                }
    except (OSError, KeyError, ValueError):
        return None
    return None


def _sampled_examples() -> list[dict]:
    """The 20 traces drawn at random in Week 5, offered beside the golden set.

    These are the opposite of the golden set and that is the point: the golden
    questions were written to be answerable and are what gets demoed, while
    these were drawn with a seed from 182 logged traces and never curated.
    Showing both in one menu is what makes the demo-vs-random gap visible.

    Returns [] if the Week 5 files are absent, so the endpoint keeps working
    for anyone who has not run the analysis.
    """
    week5 = os.path.join(os.path.dirname(__file__), "..", "..", "week5")
    try:
        sample = set(json.load(open(os.path.join(week5, "sample.json")))["sample"])
        out = []
        with open(os.path.join(week5, "traces.jsonl")) as fh:
            for line in fh:
                if not line.strip():
                    continue
                t = json.loads(line)
                if t["trace_id"] not in sample:
                    continue
                out.append({
                    "id": t["trace_id"],
                    "question": t["question"],
                    "product_area": t["request"]["product_area"],
                    "k": t["request"]["k"],
                    "answered": t["result"]["answered"],
                })
        return sorted(out, key=lambda r: r["id"])
    except (OSError, KeyError, ValueError):
        return []


@app.get("/api/error_analysis")
def error_analysis() -> dict:
    """Week 5's open coding, served to the UI.

    Read from week5/coding.json rather than duplicated in the frontend, so the
    categories the app displays are the same ones taxonomy.md reports. Returns
    an empty payload if the analysis has not been run, so the endpoint is safe
    on a checkout without it.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "..", "week5",
                        "coding.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"modes": [], "traces": [], "seed": None,
                "population": 0, "sample_size": 0}


WEEK6 = os.path.join(os.path.dirname(__file__), "..", "..", "week6")


def _week6_json(name: str):
    with open(os.path.join(WEEK6, name)) as fh:
        return json.load(fh)


def _week6_lines(name: str) -> list[dict]:
    with open(os.path.join(WEEK6, name)) as fh:
        return [json.loads(l) for l in fh if l.strip()]


GRADERS = {"judge_v1": "Judge v1", "judge_v2": "Judge v2", "human": "Human labels"}


@app.get("/api/eval_week6")
def eval_week6(grader: str = "judge_v2") -> dict:
    """Week 6's judge validation, served to the UI.

    Everything here is read from the files week6/run_week6.py writes -- the
    eval set, the drafted replies, the hand labels, both judge runs and both
    agreement reports. Nothing is recomputed except the assertions, which are
    run through week6/assertions.py itself rather than reimplemented, so the
    table in the browser and the table in the terminal cannot disagree.

    Returns an empty payload if Week 6 has not been run, so the endpoint is
    safe on a checkout without it.

    `grader` picks whose verdict decides pass/fail: judge v1, judge v2 or the
    human labels. Every number on the page is recomputed against it, and the
    grading is written to Langfuse as one trace -- an evaluator observation
    per case, plus pass rate and agreement-with-human as trace scores -- so
    switching graders in the UI leaves a record of what each one said.
    """
    import sys
    if grader not in GRADERS:
        raise HTTPException(400, f"grader must be one of {sorted(GRADERS)}")
    try:
        if WEEK6 not in sys.path:
            sys.path.insert(0, WEEK6)
        import assertions as A

        cases = {c["case_id"]: c for c in _week6_lines("eval_set.jsonl")}
        replies = _week6_lines("replies.jsonl")
        labels = _week6_json("labels_25.json")
        v1 = _week6_json("judge_run_judge_v1.json")
        v2 = _week6_json("judge_run_judge_v2.json")
        before = _week6_json("agreement_before.json")
        after = _week6_json("agreement_after.json")
        try:
            ragas = {r["case_id"]: r for r in _week6_json("ragas_report.json")}
        except (OSError, ValueError):
            ragas = {}
    except (OSError, ValueError, KeyError, ImportError):
        return {"ok": False, "cases": [], "modes": [], "summary": {},
                "assertions": [], "ragas": []}

    out, per_mode = [], {}
    astats = {name: {"PASS": 0, "FAIL": 0, "n/a": 0} for name, _ in A.ASSERTIONS}
    for r in replies:
        case = cases[r["case_id"]]
        checks = A.run(r["reply"], r["ticket"])
        for name, c in checks["checks"].items():
            astats[name][c["status"]] += 1
        hv1 = v1["verdicts"].get(r["case_id"], {})
        hv2 = v2["verdicts"].get(r["case_id"], {})
        human = labels["labels"].get(r["case_id"], {})
        chosen = {"judge_v1": hv1.get("verdict"), "judge_v2": hv2.get("verdict"),
                  "human": human.get("label")}[grader]
        # An unjudged case has no verdict from anyone and passes on the
        # assertions alone, whichever grader is selected.
        passed = checks["passed"] and (chosen or "RESOLVED") == "RESOLVED"
        slot = per_mode.setdefault(r["mode"], {"mode": r["mode"], "pass": 0, "n": 0})
        slot["n"] += 1
        slot["pass"] += passed
        out.append({
            "case_id": r["case_id"], "mode": r["mode"],
            "question": r["ticket"]["question"],
            "ticket_id": r["ticket"]["ticket_id"],
            "tier": r["ticket"]["tier"],
            "product_area": r["ticket"]["product_area"],
            "days_since_purchase": r["ticket"]["days_since_purchase"],
            "refund_requested": r["ticket"]["refund_requested"],
            "refund_amount_usd": r["ticket"]["refund_amount_usd"],
            "source_trace": case["source_trace"],
            "replay_verbatim": case["replay_verbatim"],
            "judged": case["judged"],
            "not_judged_because": case.get("not_judged_because", ""),
            "answered": r["answered"],
            "reply": r["reply"],
            "checks": checks["checks"], "failed": checks["failed"],
            "judge_v1": hv1.get("verdict"), "judge_v1_why": hv1.get("reasoning"),
            "judge_v2": hv2.get("verdict"), "judge_v2_why": hv2.get("reasoning"),
            "human": human.get("label"), "human_why": human.get("reason"),
            "agree_v1": bool(human) and human.get("label") == hv1.get("verdict"),
            "agree_v2": bool(human) and human.get("label") == hv2.get("verdict"),
            "ragas": ragas.get(r["case_id"]),
            "grader_verdict": chosen,
            "passed": passed,
        })

    order = ["mode_1", "mode_2", "mode_3", "mode_4", "mode_5", "no_failure"]
    modes = sorted(per_mode.values(), key=lambda m: order.index(m["mode"]))
    labelled = [c for c in out if c["human"]]
    agree = (sum(c["grader_verdict"] == c["human"] for c in labelled)
             / len(labelled) * 100) if labelled else None
    trace_url = _trace_week6_grading(grader, out, agree)
    return {
        "ok": True,
        "grader": grader,
        "graders": GRADERS,
        "grader_agreement": round(agree, 1) if agree is not None else None,
        "grader_resolved": sum(c["grader_verdict"] == "RESOLVED" for c in out),
        "trace_url": trace_url,
        "cases": out,
        "modes": modes,
        "assertions": [{"name": n, **astats[n]} for n, _ in A.ASSERTIONS],
        "summary": {
            "n_cases": len(out),
            "n_judged": sum(c["judged"] for c in out),
            "n_verbatim": sum(c["replay_verbatim"] for c in out),
            "pass_total": sum(c["passed"] for c in out),
            "agreement_before": before["agreement_pct"],
            "agreement_after": after["agreement_pct"],
            "kappa_before": before["cohens_kappa"],
            "kappa_after": after["cohens_kappa"],
            "engine": v2["engine"],
            "judge_model": v2["model"],
            "n_assertions": len(A.ASSERTIONS),
            "n_judged_criteria": 1,
            "labelled_at": labels["labelled_at"],
            "disagreements_before": before["disagreements"],
            "disagreements_after": after["disagreements"],
            "human_resolved_rate": before["human_resolved_rate"],
            "judge_resolved_rate_before": before["judge_resolved_rate"],
            "judge_resolved_rate_after": after["judge_resolved_rate"],
        },
    }


def _trace_week6_grading(grader: str, cases: list[dict],
                         agreement: float | None) -> str | None:
    """One Langfuse trace per grader switch: what that grader decided.

    Each case is an `evaluator` observation carrying the grader's verdict and
    the human label beside it; the trace carries pass rate and agreement as
    scores, so the three graders can be compared side by side in Langfuse.
    """
    passed = sum(c["passed"] for c in cases)
    with tracing.observe("grade-week6-eval", as_type="chain",
                         input={"grader": grader, "n_cases": len(cases)}) as root, \
            tracing.trace_attributes(tags=["week6", f"grader:{grader}"]):
        for c in cases:
            with tracing.observe(f"grade-{c['case_id']}", as_type="evaluator",
                                 input={"question": c["question"],
                                        "reply": c["reply"]}) as ev:
                ev.update(output={"verdict": c["grader_verdict"],
                                  "passed": c["passed"],
                                  "assertions_failed": c["failed"]},
                          metadata={"grader": grader, "mode": c["mode"],
                                    "human": c["human"],
                                    "judge_v1": c["judge_v1"],
                                    "judge_v2": c["judge_v2"]})
        # Readable IO on the root observation: it is what the trace table
        # shows. The numbers stay structured in metadata.
        root.update(input=f"Grade Week 6 eval with {GRADERS[grader]}",
                    output=f"{passed}/{len(cases)} passing",
                    metadata={"grader": grader, "passed": passed,
                              "n": len(cases),
                              "agreement_with_human_pct": agreement})
        tracing.score("pass_rate", passed / len(cases), GRADERS[grader])
        if agreement is not None:
            tracing.score("agreement_with_human", agreement / 100, GRADERS[grader])
        url = tracing.trace_url()
    tracing.flush()
    return url


# ------------------------------------------------------------------ week 7

WEEK7 = os.path.join(os.path.dirname(__file__), "..", "..", "week7")


def _week7():
    """Import the week7 modules. They use flat imports (store, tools, model),
    so their directory goes on sys.path, as when run from the command line."""
    import sys
    for p in (os.path.abspath(WEEK7), os.path.abspath(WEEK6)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import agent, budget_demo, race, tools, workflow  # noqa: E401
    try:
        import bonus
    except ImportError:
        bonus = None
    return agent, workflow, race, budget_demo, tools, bonus


def _tool_diff(tools) -> list[dict]:
    """Before/after of every tool definition, as unified diff lines."""
    import difflib
    before = {t["name"]: t for t in tools.TOOLS_BEFORE}
    out = []
    for t in tools.TOOLS:
        old = before.get(t["name"])
        a = json.dumps(old, indent=2).splitlines() if old else []
        b = json.dumps(t, indent=2).splitlines()
        diff = list(difflib.unified_diff(a, b, lineterm="", n=50))[2:]
        out.append({"name": t["name"], "status": "changed" if old else "added",
                    "before": old, "after": t,
                    "diff": diff or ["  " + l for l in b]})
    return out


class Week7Run(BaseModel):
    ticket_id: str
    system: str = "agent"


class Week7Budget(BaseModel):
    ticket_id: str = "TCK-7009"
    budget: str = "max_tokens"
    limit: float = 2500
    save: bool = False


@app.get("/api/week7")
def week7() -> dict:
    """Everything the Week 7 page shows, read from the files the CLI writes."""
    agent, _, _, budget_demo, tools, bonus = _week7()
    try:
        results = json.load(open(os.path.join(WEEK7, "race.json")))
    except (OSError, ValueError):
        results = None
    try:
        log = open(budget_demo.LOG).read()
    except OSError:
        log = ""
    bonus_data = None
    try:
        bonus_data = json.load(open(os.path.join(WEEK7, "bonus_results.json")))
    except (OSError, ValueError):
        pass
    src = {}
    for name in ("agent.py", "react.py", "workflow.py", "tools.py", "model.py", "store.py", "bonus.py", "memory.py", "mem0_demo.py", "graph.py"):
        p = os.path.join(WEEK7, name)
        if os.path.exists(p):
            with open(p) as fh:
                src[name] = fh.read()
    return {"ok": results is not None, "race": results, "budget_log": log,
            "tool_diff": _tool_diff(tools),
            "enums": {"order_status": tools.ORDER_STATUS,
                      "customer_tier": tools.CUSTOMER_TIER,
                      "request_type": tools.REQUEST_TYPE,
                      "decision": tools.DECISION},
            "default_budgets": vars(agent.Budgets()),
            "bonus": bonus_data,
            "source": src}


@app.post("/api/week7/race")
def week7_race() -> dict:
    """Re-run the whole race (both systems, 10 tickets, ~25s) and return it."""
    _, _, race, _, _, _ = _week7()
    race.main()
    return week7()


@app.post("/api/week7/run")
def week7_run(req: Week7Run) -> dict:
    """One ticket through one system, graded, with its step trace."""
    agent, workflow, race, _, _, _ = _week7()
    from store import TICKETS
    if req.ticket_id not in TICKETS:
        raise HTTPException(404, f"unknown ticket {req.ticket_id!r}")
    if req.system not in ("agent", "workflow"):
        raise HTTPException(400, "system must be 'agent' or 'workflow'")
    fn = agent.run_agent if req.system == "agent" else workflow.run_workflow
    r = fn(req.ticket_id)
    r["grade"] = race.grade(req.ticket_id, r["output"])
    tracing.flush()
    return r


@app.post("/api/week7/budget")
def week7_budget(req: Week7Budget) -> dict:
    """Run one ticket under a chosen budget. `save` overwrites the log file."""
    _, _, _, budget_demo, _, _ = _week7()
    if req.budget not in budget_demo.KINDS:
        raise HTTPException(400, f"budget must be one of {list(budget_demo.KINDS)}")
    r = budget_demo.run_demo(req.ticket_id, req.budget, req.limit,
                             write=req.save)
    tracing.flush()
    return r


@app.post("/api/week7/bonus")
def week7_bonus() -> dict:
    """Re-run the bonus challenge across 3 long threads with sliding window and persistent tier memory."""
    _, _, _, _, _, bonus = _week7()
    if bonus is None:
        raise HTTPException(500, "bonus module not found")
    return bonus.run_bonus_race()


class Week7ReactRequest(BaseModel):
    ticket_id: str = "TCK-7009"


@app.api_route("/api/week7/react", methods=["GET", "POST"])
def week7_react(req: Week7ReactRequest = Week7ReactRequest()) -> dict:
    """Run ReAct loop showing Thought -> Action -> Observation step by step."""
    import sys
    if os.path.abspath(WEEK7) not in sys.path:
        sys.path.insert(0, os.path.abspath(WEEK7))
    import react
    return react.run_react(req.ticket_id, verbose=False)


@app.api_route("/api/week7/memory", methods=["GET", "POST"])
def week7_memory() -> dict:
    """Run short vs vector memory comparison across the 3 long threads."""
    import sys
    if os.path.abspath(WEEK7) not in sys.path:
        sys.path.insert(0, os.path.abspath(WEEK7))
    import memory
    from bonus import LONG_THREADS
    mem = memory.VectorMemory()
    results = {}
    for tid, thread in LONG_THREADS.items():
        results[tid] = {
            "title": thread.get("title", tid),
            "customer_id": thread["customer_id"],
            "modes": {}
        }
        for mode in memory.MODES:
            r = memory.resolve(thread, mode, mem)
            results[tid]["modes"][mode] = {
                "decision": r.get("decision"),
                "passed": r.get("passed", False),
                "tokens": r.get("context_tokens", 0),
                "waiver_recalled": bool(r.get("recalled")),
                "recalled_items": r.get("recalled", [])
            }
    return {
        "ok": True,
        "loaded_from_disk": mem.loaded_from_disk,
        "results": results
    }


class Mem0RecallReq(BaseModel):
    user_id: str = "CUST-903"
    query: str = "manager authorization or waiver code approving the refund"


@app.api_route("/api/week7/mem0", methods=["GET", "POST"])
def week7_mem0(req: Mem0RecallReq = Mem0RecallReq()) -> dict:
    """Query mem0 for user-scoped memories."""
    import sys
    if os.path.abspath(WEEK7) not in sys.path:
        sys.path.insert(0, os.path.abspath(WEEK7))
    import mem0_demo
    if not os.path.exists(mem0_demo.DATA):
        mem0_demo.write()
    m = mem0_demo.memory()
    res = m.search(req.query, filters={"user_id": req.user_id}, top_k=3)
    return {"ok": True, "query": req.query, "user_id": req.user_id, "results": res.get("results", [])}


class Week7GraphReq(BaseModel):
    ticket_id: str = "TCK-7009"


@app.api_route("/api/week7/graph", methods=["GET", "POST"])
def week7_graph(req: Week7GraphReq = Week7GraphReq()) -> dict:
    """Run LangGraph agent & workflow and return checkpoints & mermaid diagrams."""
    import sys
    if os.path.abspath(WEEK7) not in sys.path:
        sys.path.insert(0, os.path.abspath(WEEK7))
    import graph
    from langgraph.checkpoint.memory import InMemorySaver
    r_agent = graph.run_graph_agent(req.ticket_id, checkpointer=InMemorySaver())
    r_workflow = graph.run_graph_workflow(req.ticket_id)
    m_agent = graph.build_agent_graph(graph.Meter("m", "-"), graph.Budgets()).get_graph().draw_mermaid()
    m_workflow = graph.build_workflow_graph(graph.Meter("m", "-")).get_graph().draw_mermaid()
    
    history = []
    if "app" in r_agent and "config" in r_agent:
        for snap in r_agent["app"].get_state_history(r_agent["config"]):
            last = snap.values["messages"][-1] if snap.values.get("messages") else None
            what = (type(last).__name__ + (f" tool_calls={[c['name'] for c in last.tool_calls]}"
                    if hasattr(last, 'tool_calls') and last.tool_calls else "")) if last else "-"
            history.append({
                "step": snap.metadata.get("step"),
                "next": list(snap.next) or ["END"],
                "last_message": what
            })
    return {
        "ticket_id": req.ticket_id,
        "agent": {"output": r_agent["output"], "path": r_agent["path"], "llm_calls": r_agent["llm_calls"]},
        "workflow": {"output": r_workflow["output"], "path": r_workflow["path"], "llm_calls": r_workflow["llm_calls"]},
        "checkpoints": history,
        "mermaid": {"agent": m_agent, "workflow": m_workflow}
    }


# ------------------------------------------------ chat: week 6 and week 7

JUDGES = {"judge_v1": "judge_v1.txt", "judge_v2": "judge_v2.txt"}
_W6: dict = {}


def _week6_live():
    """draft, judge and assertions modules plus the corpus+policy index the
    Week 6 drafter answers from. Built once, on first use: indexing the policy
    article next to the corpus takes a few seconds."""
    import sys
    if not _W6:
        if os.path.abspath(WEEK6) not in sys.path:
            sys.path.insert(0, os.path.abspath(WEEK6))
        import assertions
        import draft
        import judge
        _W6.update(draft=draft, judge=judge, assertions=assertions,
                   index=draft.build_index_with_policy(),
                   cases={c["case_id"]: c
                          for c in _week6_lines("eval_set.jsonl")},
                   labels=_week6_json("labels_25.json")["labels"])
    return _W6


class Week6Ask(BaseModel):
    question: str
    judge: str = "judge_v2"
    product_area: str | None = None
    session_id: str | None = None
    # Sent by the question picker. Two eval cases can share a question, so
    # the id, not the text, is what reproduces a specific case.
    case_id: str | None = None


class Week7Ask(BaseModel):
    question: str
    system: str = "agent"
    session_id: str | None = None


@app.post("/api/ask_week6")
def ask_week6(req: Week6Ask) -> dict:
    """Week 6 in the chat: draft a ticket reply, then grade it.

    A question from the Week 6 eval set is drafted exactly as week6/draft.py
    drafts it -- with that case's ticket, area filter and, for the three
    regression cases, the frozen verbatim reply -- so the chat reproduces the
    eval. Any other question gets a plain Standard-tier ticket with no refund.
    The reply then goes through the four SP-001 assertions and the chosen
    judge prompt, and the human label is shown when the case has one.
    """
    if req.judge not in JUDGES:
        raise HTTPException(400, f"judge must be one of {sorted(JUDGES)}")
    w = _week6_live()
    q = req.question.strip()
    case = w["cases"].get(req.case_id or "")
    if case is None or case["ticket"]["question"].strip() != q:
        case = next((c for c in w["cases"].values()
                     if c["ticket"]["question"].strip() == q), None)
    if case is None:
        case = {"case_id": "live", "mode": None, "replay_verbatim": False,
                "ticket": {"ticket_id": "TCK-LIVE", "tier": "Standard",
                           "days_since_purchase": 0, "refund_requested": False,
                           "refund_amount_usd": None, "question": q,
                           "product_area": req.product_area}}
    ticket = case["ticket"]

    with tracing.observe("answer-week6", as_type="chain") as root, \
            tracing.trace_attributes(session_id=req.session_id,
                                     tags=["week6", f"judge:{req.judge}"]):
        drafted = w["draft"].draft_one(case, w["index"])
        checks = w["assertions"].run(drafted["reply"], ticket)
        prompt = open(os.path.join(WEEK6, JUDGES[req.judge])).read()
        with tracing.observe(f"judge-{req.judge}", as_type="evaluator",
                             input={"question": q,
                                    "reply": drafted["reply"]}) as ev:
            if os.environ.get("ANTHROPIC_API_KEY"):
                engine = "anthropic"
                verdict, why = w["judge"].anthropic_verdict(prompt, ticket,
                                                            drafted["reply"])
            else:
                engine = "offline"
                verdict, why = w["judge"].offline_verdict(
                    drafted["reply"], ticket["ticket_id"],
                    w["judge"].parse_prompt(prompt), q)
            ev.update(output={"verdict": verdict, "reasoning": why},
                      metadata={"engine": engine, "prompt": JUDGES[req.judge]})
        human = w["labels"].get(case["case_id"], {})
        passed = checks["passed"] and verdict == "RESOLVED"
        root.update(input=q, output=drafted["reply"], metadata={
            "case_id": case["case_id"], "judge": req.judge,
            "verdict": verdict, "assertions_failed": checks["failed"],
            "human": human.get("label")})
        tracing.score("judge_verdict", verdict, why)
        tracing.score("passed", 1.0 if passed else 0.0)
        url = tracing.trace_url()
    tracing.flush()
    return {
        "question": q, "judge": req.judge, "judge_engine": engine,
        "case_id": case["case_id"], "case_mode": case.get("mode"),
        "replay_verbatim": case["replay_verbatim"], "ticket": ticket,
        "reply": drafted["reply"], "answered": drafted["answered"],
        "claims": drafted["claims"], "refusal": drafted["refusal"],
        "verdict": verdict, "reasoning": why,
        "checks": checks["checks"], "assertions_failed": checks["failed"],
        "human": human.get("label"), "human_why": human.get("reason"),
        "passed": passed, "trace_url": url,
    }


@app.post("/api/ask_week7")
def ask_week7(req: Week7Ask) -> dict:
    """Week 7 in the chat: one message through the agent or the workflow.

    A ticket id or one of the 10 race tickets is run as that ticket and graded
    against its answer key. Any other message is filed as a new ticket (see
    week7/store.resolve_ticket) and run ungraded.
    """
    if req.system not in ("agent", "workflow"):
        raise HTTPException(400, "system must be 'agent' or 'workflow'")
    agent, workflow, race, *_ = _week7()
    from store import TICKETS, resolve_ticket
    tid, known = resolve_ticket(req.question)
    fn = agent.run_agent if req.system == "agent" else workflow.run_workflow
    r = fn(tid, session_id=req.session_id)
    r["grade"] = race.grade(tid, r["output"]) if known else None
    tracing.flush()
    return {**r, "known": known, "ticket": {"ticket_id": tid, **TICKETS[tid]}}


# ------------------------------------------------------------------ week 8

WEEK8 = os.path.join(os.path.dirname(__file__), "..", "..", "week8")


def _week8():
    """Import the week8 modules (flat imports, like week7). Week 7 and Week 6
    go on the path too: week8 reuses Week 7's tools, model and grader."""
    import sys
    for p in (os.path.abspath(WEEK6), os.path.abspath(WEEK7),
              os.path.abspath(WEEK8)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import agent8, injection, store8, tools8, trajectory_eval  # noqa: E401
    return agent8, trajectory_eval, injection, store8, tools8


def _week8_examples() -> list[dict]:
    """The 10 Week 8 tickets (customer-quoted figures), as askable messages."""
    try:
        _, te, _, store8, _ = _week8()
        out = [{"id": t, "question": store8.TICKETS[t]["message"],
                "alternate": t in te.ALTERNATE_PATH_CASES, "wording": "week8"}
               for t in store8.TICKET_IDS]
        # The Week 7 questions too, as Week 7 wrote them. Where the text is
        # the same in both weeks it is already listed above.
        out += [{"id": f"{t} (W7)", "question": store8.S7.TICKETS[t]["message"],
                 "alternate": t in te.ALTERNATE_PATH_CASES, "wording": "week7"}
                for t in store8.TICKET_IDS
                if store8.S7.TICKETS[t]["message"] != store8.TICKETS[t]["message"]]
        return out
    except Exception:
        return []


def _w8_compact(r: dict) -> dict:
    s = r["score"]
    return {"ticket_id": r["ticket_id"], "seed": r["seed"], "path": r["path"],
            "keys": [list(k) for k in s["keys"]],
            "outcome_pass": s["outcome_pass"],
            "trajectory_pass": s["trajectory_pass"],
            "naive_trajectory_pass": s["naive_trajectory_pass"],
            "modes": s["modes"], "tool_errors": s["tool_errors"],
            "steps_taken": s["steps_taken"], "steps_needed": s["steps_needed"],
            "valid_args": s["valid_args"], "n_calls": s["n_calls"],
            "cost_usd": r["cost_usd"], "total_tokens": r["total_tokens"],
            "latency_s": r["latency_s"], "llm_calls": r["llm_calls"],
            "decision": r["output"].get("decision"),
            "refund_order_id": r["output"].get("refund_order_id"),
            "terminated": (r["terminated"] or {}).get("budget")}


def _w8_full(r: dict, te) -> dict:
    """One run with everything the trace view needs."""
    r = dict(r)
    r["score"] = {**r["score"], "keys": [list(k) for k in r["score"]["keys"]]}
    calls = te.keyed_calls(r) if r["ticket_id"] in te.EXPECTED_PATHS else []
    for c, k in zip(r["tool_calls"], calls):
        c["key"], c["valid"], c["error"] = list(k["key"]), k["valid"], k["error"]
    return r


@app.get("/api/week8")
def week8() -> dict:
    """Everything the Week 8 page shows, read from the files the CLI writes."""
    import inspect
    agent8, te, inj, store8, tools8 = _week8()
    if not os.path.exists(te.RESULTS):
        te.run_and_write()
    if not os.path.exists(inj.RESULTS):
        inj.run_and_write()
    res = json.load(open(te.RESULTS))
    injection = json.load(open(inj.RESULTS))
    report = open(os.path.join(WEEK8, "results_week8.md")).read() \
        if os.path.exists(os.path.join(WEEK8, "results_week8.md")) else ""
    src = {}
    for name in ("trajectory_eval.py", "tools8.py", "sim_model.py", "agent8.py",
                 "store8.py", "injection.py"):
        with open(os.path.join(WEEK8, name)) as fh:
            src[name] = fh.read()
    cond = {}
    for c in ("before", "after"):
        runs = res[c]["runs"]
        cond[c] = {"summary": res[c]["summary"],
                   "runs": [_w8_compact(r) for r in runs]}
    return {
        "seeds": res["seeds"], "rates": res["rates"],
        "top_mode": res.get("top_mode") or te.top_mode(res["before"]["summary"]),
        "severity": {k: list(v) for k, v in te.SEVERITY.items()},
        "modes": te.MODES,
        "expected_paths": res["expected_paths"],
        "alternate_path_cases": res["alternate_path_cases"],
        "tickets": {t: store8.TICKETS[t] for t in store8.TICKET_IDS},
        "expected": {t: store8.EXPECTED[t] for t in store8.TICKET_IDS},
        "ticket_ids": store8.TICKET_IDS,
        "before": cond["before"], "after": cond["after"],
        "mitigation_source": inspect.getsource(tools8.validate_policy_args),
        "mitigation_switch": inspect.getsource(tools8.call),
        "injection": injection, "attacks": inj.ATTACKS,
        "sanitize_source": inspect.getsource(inj.sanitize),
        "guardrail_source": inspect.getsource(inj.guardrail),
        "readonly_source": inspect.getsource(inj.refund_read_only),
        "results_md": report, "source": src,
    }


class Week8Run(BaseModel):
    ticket_id: str = "TCK-7001"
    seed: int = 2
    mitigate: bool = False


@app.post("/api/week8/run")
def week8_run(req: Week8Run) -> dict:
    """One ticket, one seed, mitigation on or off: the run, its trajectory
    score and outcome grade. Deterministic: the same inputs give the run the
    eval recorded."""
    agent8, te, _, store8, _ = _week8()
    if req.ticket_id not in te.EXPECTED_PATHS:
        raise HTTPException(404, f"unknown ticket {req.ticket_id!r}")
    r = agent8.run(req.ticket_id, req.seed,
                   agent8.Config(validate_policy_args=req.mitigate))
    r["score"] = te.score(r)
    out = _w8_full(r, te)
    out["accepted"] = te.EXPECTED_PATHS[req.ticket_id]
    out["ticket"] = {"ticket_id": req.ticket_id, **store8.TICKETS[req.ticket_id]}
    return out


class Week8Eval(BaseModel):
    seeds: int = Field(10, ge=1, le=50)


@app.post("/api/week8/eval")
def week8_eval(req: Week8Eval) -> dict:
    """Re-run the trajectory eval (before + after) and rewrite its files."""
    _, te, _, _, _ = _week8()
    te.run_and_write(req.seeds)
    return week8()


@app.post("/api/week8/injection")
def week8_injection() -> dict:
    """Re-run the bonus: three attacks, undefended vs defended, + eval cost."""
    _, _, inj, _, _ = _week8()
    inj.run_and_write()
    return week8()


class Week8Attack(BaseModel):
    attack_id: str = "A1-literal"
    defended: bool = False
    seed: int = 0


@app.post("/api/week8/attack")
def week8_attack(req: Week8Attack) -> dict:
    """One injection attack, one seed, with or without the three defences."""
    agent8, te, inj, store8, _ = _week8()
    if req.attack_id not in inj.ATTACKS:
        raise HTTPException(400, f"attack must be one of {list(inj.ATTACKS)}")
    tid = inj.plant(req.attack_id, inj.ATTACKS[req.attack_id])
    cfg = inj.DEFENDED if req.defended else inj.UNDEFENDED
    r = agent8.run(tid, req.seed,
                   agent8.Config(validate_policy_args=True, **cfg))
    return {**r, "verdict": inj.attack_outcome(r, req.attack_id),
            "ticket": {"ticket_id": tid, **store8.TICKETS[tid]}}


class Week8Ask(BaseModel):
    question: str
    mitigate: bool = False
    seed: int = 0
    session_id: str | None = None


@app.post("/api/ask_week8")
def ask_week8(req: Week8Ask) -> dict:
    """Week 8 in the chat: one message through the sampled agent, with its
    trajectory scored when the ticket is one of the 10 with expected paths."""
    agent8, te, _, store8, _ = _week8()
    w7 = store8.week7_wording(req.question)
    if w7:
        tid, known, message = w7, True, req.question.strip()
    else:
        tid, known = store8.resolve_ticket(req.question)
        message = None
    r = agent8.run(tid, req.seed,
                   agent8.Config(validate_policy_args=req.mitigate,
                                 ticket_message=message))
    if known:
        r["score"] = te.score(r)
        r = _w8_full(r, te)
        r["accepted"] = te.EXPECTED_PATHS[tid]
    else:
        r["score"] = None
    ticket = {"ticket_id": tid, **store8.TICKETS[tid]}
    if message:
        ticket["message"] = message
    return {**r, "known": known, "mitigate": req.mitigate,
            "wording": "week7" if message else "week8", "ticket": ticket}


@app.post("/api/search")
def search(req: SearchRequest) -> dict:
    where = {"product_area": req.product_area} if req.product_area else None
    return {
        "query": req.query,
        "strategy": req.strategy,
        "filter": where,
        "mode": req.mode,
        "results": _index(req.strategy).search(
            req.query, k=req.k, where=where, use_rerank=_rerank_for(req.mode)),
    }


@app.post("/api/compare")
def compare(req: SearchRequest) -> dict:
    """Same query, both chunkers, everything else held constant."""
    where = {"product_area": req.product_area} if req.product_area else None
    use_rerank = _rerank_for(req.mode)
    return {
        "query": req.query,
        "filter": where,
        "mode": req.mode,
        "by_strategy": {
            s: _index(s).search(req.query, k=req.k, where=where,
                                use_rerank=use_rerank)
            for s in ("fixed_window", "structure_aware")
        },
    }


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    where = {"product_area": req.product_area} if req.product_area else None
    return answer_auto(_index(req.strategy), req.question, k=req.k, where=where,
                       use_rerank=_rerank_for(req.mode),
                       fallback=_fallback_for(req.mode),
                       session_id=req.session_id)


@app.post("/api/chat")
def chat(req: AskRequest) -> StreamingResponse:
    """Streamed grounded answer, as server-sent events.

    Event order: meta, status(retrieving), retrieval, status(generating),
    then either claim_start/delta/claim_end per verified claim or a streamed
    refusal, then done. See backend/app/chat.py for why only verified text is
    ever streamed.
    """
    _rerank_for(req.mode)  # reject a bad mode with 400 before the stream opens
    where = {"product_area": req.product_area} if req.product_area else None
    return StreamingResponse(
        chat_stream(_index(req.strategy), req.question, k=req.k, where=where,
                    mode=req.mode, strategy=req.strategy,
                    session_id=req.session_id),
        media_type="text/event-stream",
        # Without this an intermediary can buffer the whole stream and defeat
        # the point of streaming it.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/chunk/{chunk_id:path}")
def chunk(chunk_id: str) -> dict:
    """Resolve a citation. Every chunk_id in an answer must resolve here."""
    strategy = chunk_id.split("::", 1)[0]
    rec = _index(strategy).get(chunk_id)
    if rec is None:
        raise HTTPException(404, "chunk_id does not resolve")
    return {"chunk_id": rec.chunk_id, "text": rec.text, "meta": rec.meta}
