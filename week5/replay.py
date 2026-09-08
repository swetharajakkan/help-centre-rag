"""Replay one trace FROM THE TRACE ALONE and diff it against the original.

The rule this obeys: nothing is read from population.jsonl and nothing is
re-derived from the run that produced the trace. The only inputs are

    (a) the fields inside the trace record, and
    (b) the corpus + code the trace names by hash, which the replay verifies
        it is actually running against before it replays anything.

If the trace does not carry enough to reproduce the output, that shows up here
as a mismatch rather than being papered over.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("HELP_CENTRE_RERANK", "1")

from backend.app.generation import extractive_engine, grounding, verify
from backend.app.ingest import build_index


def corpus_sha() -> str:
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(ROOT, "corpus", "*.md"))):
        h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def code_version() -> str:
    return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "HEAD"],
                                   text=True).strip()[:12]


def replay(trace: dict) -> dict:
    """Reconstruct the answer using ONLY what the trace records."""
    q = trace["question"]
    req = trace["request"]
    where = ({"product_area": req["product_area"]}
             if req["product_area"] else None)

    index = build_index(req["strategy"])
    hits = index.search(q, k=req["k"], where=where,
                        use_rerank={"week3": False, "week4": True}.get(req["mode"]))
    score, uncovered, refusal = grounding(q, hits, index)
    raw = extractive_engine(q, hits, index,
                            use_cross_encoder=req["rerank_resolved"])
    return {"hits": hits, "grounding": (score, uncovered, refusal),
            "raw": raw, "result": verify(raw, hits)}


def claim_texts(result: dict) -> list[str]:
    return [c["claim"] for c in result.get("claims", [])]


def main(trace_id: str) -> None:
    rows = {json.loads(l)["trace_id"]: json.loads(l)
            for l in open(os.path.join(HERE, "traces.jsonl")) if l.strip()}
    tr = rows[trace_id]
    p = tr["params"]

    print("=" * 72)
    print(f"REPLAY OF {trace_id}")
    print("=" * 72)
    print("\nEnvironment check (the trace names what it ran against):")
    for label, recorded, live in [
        ("code_version", p["code_version"], code_version()),
        ("corpus_sha256", p["corpus_sha256"], corpus_sha()),
    ]:
        mark = "MATCH" if recorded == live else "DIFFERS"
        print(f"  {label:15s} trace={recorded}  live={live}  [{mark}]")
    print(f"  engine          {p['engine']}  prompt_version={p['prompt_version']}"
          f"  system_prompt_sha={p['system_prompt_sha256']}")

    print(f"\nQuestion: {tr['question']}")
    print(f"Request:  k={tr['request']['k']} mode={tr['request']['mode']} "
          f"product_area={tr['request']['product_area']} "
          f"rerank={tr['request']['rerank_resolved']}")

    rp = replay(tr)

    print("\n--- RETRIEVAL ---")
    print(f"{'rank':<5}{'original chunk_id':<58}{'replayed chunk_id':<58}")
    orig_hits = tr["retrieval"]["hits"]
    for i in range(max(len(orig_hits), len(rp["hits"]))):
        o = orig_hits[i]["chunk_id"] if i < len(orig_hits) else "-"
        r = rp["hits"][i]["chunk_id"] if i < len(rp["hits"]) else "-"
        print(f"{i+1:<5}{o:<58}{r:<58}{'ok' if o == r else 'DIFF'}")
    o_scores = [(h["score"], h.get("rerank_score")) for h in orig_hits]
    r_scores = [(h["score"], h.get("rerank_score")) for h in rp["hits"]]
    print(f"scores  original={o_scores}\n        replayed={r_scores}"
          f"  [{'MATCH' if o_scores == r_scores else 'DIFFERS'}]")

    print("\n--- GROUNDING GATE ---")
    og = tr["grounding"]
    rs, ru, rr = rp["grounding"]
    print(f"  coverage   original={og['in_corpus_coverage']}  replayed={round(rs,4)}"
          f"  [{'MATCH' if og['in_corpus_coverage'] == round(rs,4) else 'DIFFERS'}]")
    print(f"  refusal    original={og['gate_refusal']!r}")
    print(f"             replayed={rr!r}"
          f"  [{'MATCH' if og['gate_refusal'] == rr else 'DIFFERS'}]")

    print("\n--- RAW ENGINE OUTPUT (pre-verification) ---")
    same_raw = tr["raw_engine_output"] == rp["raw"]
    print(f"  identical: {same_raw}")

    print("\n--- FINAL OUTPUT ---")
    print("ORIGINAL (from traces.jsonl):")
    for c in tr["result"].get("claims", []):
        print(f"  [{c['chunk_id']}]\n    {c['claim']}")
    if not tr["result"]["answered"]:
        print(f"  REFUSAL: {tr['result']['refusal']}")
    print("REPLAYED (rebuilt from the trace):")
    for c in rp["result"].get("claims", []):
        print(f"  [{c['chunk_id']}]\n    {c['claim']}")
    if not rp["result"]["answered"]:
        print(f"  REFUSAL: {rp['result']['refusal']}")

    identical = (claim_texts(tr["result"]) == claim_texts(rp["result"])
                 and tr["result"]["answered"] == rp["result"]["answered"]
                 and tr["result"].get("refusal") == rp["result"].get("refusal"))
    print(f"\nVERDICT: outputs {'IDENTICAL' if identical else 'DIFFER'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "T-0015")
