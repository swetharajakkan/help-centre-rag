"""Week 4: does cross-encoder reranking actually improve retrieval?

Runs the SAME 12 golden questions twice over the SAME index. Exactly one
variable differs between the arms: whether backend/app/rerank.py runs.
Everything else -- corpus, chunker, embedding model, BM25 parameters, fusion
weight, k, questions, generation prompt and engine -- is held fixed.

  before : HELP_CENTRE_RERANK=0  -> Week 3 fused top-3
  after  : HELP_CENTRE_RERANK=1  -> fused top-12, cross-encoder picks top-3

Hit criterion, pre-registered in golden_set.jsonl: a question is a HIT if the
expected_chunk_id appears anywhere in the top 3. Each expected_chunk_id was
verified to be the ONLY chunk in the corpus containing that question's
answer_spans, so "the right chunk" is not a judgement call.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

HERE = os.path.dirname(os.path.abspath(__file__))
K = 3
REPEATS = 5          # latency samples per question; median over all samples


def load_golden() -> list[dict]:
    with open(os.path.join(HERE, "golden_set.jsonl")) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def run_arm(arm: str, golden: list[dict]) -> dict:
    """One retrieval arm. `arm` is 'before' or 'after'."""
    os.environ["HELP_CENTRE_RERANK"] = "0" if arm == "before" else "1"

    # Reload the app so rerank_enabled() is re-read and no state leaks between
    # arms. The index is rebuilt identically in both arms (same chunker, same
    # embedding model), so the only difference is the reranking pass.
    for mod in [m for m in list(sys.modules) if m.startswith("backend.app")]:
        del sys.modules[mod]
    from backend.app.ingest import build_index
    from backend.app.generation import answer_auto, api_key_present

    index = build_index("structure_aware")
    index.search("warm up every lazily loaded model", k=K)   # exclude load time

    per_q, latencies, hits = {}, [], 0
    for q in golden:
        samples = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            res = index.search(q["question"], k=K)
            samples.append((time.perf_counter() - t0) * 1000.0)
        latencies.extend(samples)
        ids = [h["chunk_id"] for h in res]
        hit = q["expected_chunk_id"] in ids
        hits += hit
        gen = answer_auto(index, q["question"], k=K)
        blob = norm(" ".join(c["supporting_quote"] for c in gen["claims"]))
        spans_found = [s for s in q["answer_spans"] if norm(s) in blob]
        per_q[q["id"]] = {
            "question": q["question"],
            "expected_chunk_id": q["expected_chunk_id"],
            "hit_at_3": hit,
            "gold_rank": ids.index(q["expected_chunk_id"]) + 1 if hit else None,
            "top3": [{"rank": h["rank"], "chunk_id": h["chunk_id"],
                      "fused_score": h["score"],
                      "rerank_score": h.get("rerank_score")} for h in res],
            "median_latency_ms": round(statistics.median(samples), 2),
            "answered": gen["answered"],
            "refusal": gen.get("refusal", ""),
            "answer_spans_recovered": f"{len(spans_found)}/{len(q['answer_spans'])}",
            "answer_correct": len(spans_found) == len(q["answer_spans"]),
        }

    return {
        "arm": arm,
        "engine": "claude-opus-5" if api_key_present() else "extractive-deterministic",
        "chunks_indexed": len(index.records),
        "hits": hits,
        "n": len(golden),
        "hit_rate_at_3": round(hits / len(golden) * 100, 1),
        "p50_latency_ms": round(statistics.median(latencies), 2),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * len(latencies)) - 1], 2),
        "mean_latency_ms": round(statistics.mean(latencies), 2),
        "per_question": per_q,
    }


def out_of_corpus_probe(arm: str) -> dict:
    """Control for the Not-In-Corpus category: three questions whose answers
    are provably absent. The correct behaviour is a refusal, in BOTH arms."""
    os.environ["HELP_CENTRE_RERANK"] = "0" if arm == "before" else "1"
    for mod in [m for m in list(sys.modules) if m.startswith("backend.app")]:
        del sys.modules[mod]
    from backend.app.ingest import build_index
    from backend.app.generation import answer_auto

    index = build_index("structure_aware")
    spec = json.load(open(os.path.join(HERE, "questions.json")))
    out = {}
    for u in spec["generation_unanswerable"]:
        r = answer_auto(index, u["question"], k=K)
        out[u["id"]] = {"question": u["question"], "why_absent": u["why_absent"],
                        "refused": not r["answered"]}
    return out


def main() -> None:
    golden = load_golden()
    report = {"k": K, "n_questions": len(golden), "latency_repeats": REPEATS}

    for arm in ("before", "after"):
        report[arm] = run_arm(arm, golden)
        report[arm]["out_of_corpus_control"] = out_of_corpus_probe(arm)

    b, a = report["before"], report["after"]

    # Per-question fixed / unfixed ledger.
    ledger = {}
    for q in golden:
        was, now = b["per_question"][q["id"]], a["per_question"][q["id"]]
        if not was["hit_at_3"] and now["hit_at_3"]:
            verdict = "FIXED"
        elif not was["hit_at_3"]:
            verdict = "NOT FIXED"
        elif not now["hit_at_3"]:
            verdict = "REGRESSED"
        else:
            verdict = "still hit"
        ledger[q["id"]] = {"verdict": verdict,
                           "rank_before": was["gold_rank"],
                           "rank_after": now["gold_rank"]}
    report["ledger"] = ledger
    report["delta"] = {
        "hit_rate_at_3": f"{b['hit_rate_at_3']}% -> {a['hit_rate_at_3']}%",
        "p50_latency_ms": f"{b['p50_latency_ms']} -> {a['p50_latency_ms']}",
        "p50_overhead_ms": round(a["p50_latency_ms"] - b["p50_latency_ms"], 2),
        "fixed": [q for q, v in ledger.items() if v["verdict"] == "FIXED"],
        "not_fixed": [q for q, v in ledger.items() if v["verdict"] == "NOT FIXED"],
        "regressed": [q for q, v in ledger.items() if v["verdict"] == "REGRESSED"],
    }

    path = os.path.join(HERE, "week4_report.json")
    json.dump(report, open(path, "w"), indent=1)

    print(f"golden set: {len(golden)} questions, k={K}, "
          f"{b['chunks_indexed']} chunks, engine={b['engine']}\n")
    print(f"{'Q':5}{'before':>12}{'after':>12}   verdict")
    for q in golden:
        v = ledger[q["id"]]
        cell = lambda r: f"HIT@{r}" if r else "MISS"
        print(f"{q['id']:5}{cell(v['rank_before']):>12}{cell(v['rank_after']):>12}"
              f"   {v['verdict']}")
    print(f"\nhit-rate@3   {b['hit_rate_at_3']}%  ->  {a['hit_rate_at_3']}%")
    print(f"p50 latency  {b['p50_latency_ms']} ms  ->  {a['p50_latency_ms']} ms "
          f"({report['delta']['p50_overhead_ms']:+} ms)")
    print(f"p95 latency  {b['p95_latency_ms']} ms  ->  {a['p95_latency_ms']} ms")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
