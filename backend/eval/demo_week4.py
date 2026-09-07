"""Week 4 live demo: one question, both retrieval arms, side by side.

    .venv/bin/python backend/eval/demo_week4.py                # runs G07 (the fixed one)
    .venv/bin/python backend/eval/demo_week4.py G12            # a golden-set question by id
    .venv/bin/python backend/eval/demo_week4.py "any question" # anything you type

Only one variable differs between the two columns: whether the cross-encoder
in backend/app/rerank.py runs. Same index, same embeddings, same BM25, same k.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

HERE = os.path.dirname(os.path.abspath(__file__))
K = 3


def golden() -> dict:
    with open(os.path.join(HERE, "golden_set.jsonl")) as fh:
        return {json.loads(l)["id"]: json.loads(l) for l in fh if l.strip()}


def run(arm: str, question: str):
    os.environ["HELP_CENTRE_RERANK"] = "0" if arm == "before" else "1"
    for m in [m for m in list(sys.modules) if m.startswith("backend.app")]:
        del sys.modules[m]
    from backend.app.ingest import build_index

    index = build_index("structure_aware")
    index.search("warm up", k=K)                       # exclude model load time
    t0 = time.perf_counter()
    hits = index.search(question, k=K)
    return hits, (time.perf_counter() - t0) * 1000


def main() -> None:
    arg = " ".join(sys.argv[1:]).strip()
    g = golden()
    spec = g.get(arg.upper()) or (g["G07"] if not arg else None)
    question = spec["question"] if spec else arg
    gold = spec["expected_chunk_id"] if spec else None

    print(f"\nQ: {question}")
    if spec:
        print(f"gold chunk: {gold.split('::', 1)[1]}  ({spec['gold_article']} — "
              f"{spec['gold_section']})")

    for arm, label in (("before", "BEFORE — week 3, no reranking"),
                       ("after", "AFTER  — week 4, cross-encoder reranking")):
        hits, ms = run(arm, question)
        found = gold and gold in [h["chunk_id"] for h in hits]
        verdict = "" if not gold else ("  ->  HIT" if found else "  ->  MISS")
        print(f"\n{label}   [{ms:.0f} ms]{verdict}")
        for h in hits:
            mark = "  <<< GOLD" if gold and h["chunk_id"] == gold else ""
            extra = (f" rerank={h['rerank_score']}" if "rerank_score" in h
                     else "")
            print(f"  #{h['rank']}  {h['chunk_id'].split('::', 1)[1]:52} "
                  f"fused={h['score']:<7}{extra}{mark}")
            for line in h["text"].splitlines():
                print(f"      {line}")
    print()


if __name__ == "__main__":
    main()
