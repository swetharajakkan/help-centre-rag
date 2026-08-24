"""Search-only evaluation: same 8 questions, both chunking strategies.

Only one variable changes between the two runs: the chunker. The embedding
model, BM25 parameters, fusion weight, k and the questions are identical.

Hit criterion is pre-registered in questions.json: a question counts as a hit
if at least ONE of the top-5 chunks contains every string in must_contain
(whitespace-normalised, case-insensitive). We also record a weaker
"union@5" number, where the evidence may be assembled across all five
retrieved chunks, because the gap between the two is the whole story.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.ingest import build_index  # noqa: E402

K = 5
STRATEGIES = ["fixed_window", "structure_aware"]
HERE = os.path.dirname(__file__)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).lower()


def chunk_is_hit(text: str, must_contain: list[str]) -> bool:
    t = norm(text)
    return all(norm(m) in t for m in must_contain)


def union_is_hit(hits: list[dict], must_contain: list[str]) -> bool:
    blob = norm(" ".join(h["text"] for h in hits))
    return all(norm(m) in blob for m in must_contain)


def main() -> None:
    spec = json.load(open(os.path.join(HERE, "questions.json")))
    questions = spec["questions"]
    report: dict = {"k": K, "per_question": {}, "totals": {}, "dump": {}}

    for strategy in STRATEGIES:
        index = build_index(strategy)
        report["dump"][strategy] = {}
        strict = union = 0
        for q in questions:
            hits = index.search(q["question"], k=K)
            hit_ranks = [h["rank"] for h in hits
                         if chunk_is_hit(h["text"], q["must_contain"])]
            is_hit = bool(hit_ranks)
            is_union = union_is_hit(hits, q["must_contain"])
            strict += is_hit
            union += is_union
            report["per_question"].setdefault(q["id"], {})[strategy] = {
                "hit_at_5": is_hit,
                "first_hit_rank": hit_ranks[0] if hit_ranks else None,
                "union_at_5": is_union,
                "top1_chunk_id": hits[0]["chunk_id"] if hits else None,
            }
            report["dump"][strategy][q["id"]] = {
                "question": q["question"],
                "gold": f"{q['gold_article']} / {q['gold_section']}",
                "must_contain": q["must_contain"],
                "results": [
                    {k: h[k] for k in
                     ("rank", "chunk_id", "score", "dense", "bm25", "text")}
                    | {"contains_all_gold_spans":
                       chunk_is_hit(h["text"], q["must_contain"])}
                    for h in hits
                ],
            }
        report["totals"][strategy] = {
            "hit_at_5": f"{strict}/{len(questions)}",
            "union_at_5": f"{union}/{len(questions)}",
            "chunks_indexed": len(index.records),
        }

    out = os.path.join(HERE, "eval_report.json")
    json.dump(report, open(out, "w"), indent=1)

    print(f"corpus: 6 new articles only (no historical re-index), k={K}\n")
    print(f"{'Q':4} {'type':11} {'fixed_window':>14} {'structure_aware':>17}")
    for q in questions:
        r = report["per_question"][q["id"]]
        def cell(s):
            d = r[s]
            return ("HIT @%d" % d["first_hit_rank"]) if d["hit_at_5"] else "MISS"
        print(f"{q['id']:4} {q['type']:11} {cell('fixed_window'):>14} "
              f"{cell('structure_aware'):>17}")
    print()
    for s in STRATEGIES:
        t = report["totals"][s]
        print(f"{s:16} hit@5={t['hit_at_5']}  union@5={t['union_at_5']}  "
              f"chunks={t['chunks_indexed']}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
