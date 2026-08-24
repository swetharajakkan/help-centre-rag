"""Bonus: a question where structure-aware WINS retrieval but LOSES the answer."""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.app.ingest import build_index          # noqa: E402
from backend.app.generation import answer_auto      # noqa: E402

HERE = os.path.dirname(__file__)
K = 3
CAVEAT_MARKERS = ("twenty-four hour", "cache_written_at", "reads the cached failure")

def main():
    spec = json.load(open(os.path.join(HERE, "questions.json")))
    q = next(x for x in spec["questions"] if x["id"] == "Q4")
    parts = [f"**Question (Q4):** {q['question']}",
             f"**Known-correct source:** {q['gold_article']} / {q['gold_section']}",
             f"**The complete answer also requires** the prose caveat in "
             f"BM-005 “The tax cache and why re-running the backfill too early "
             f"does nothing”.", ""]
    for strategy in ("fixed_window", "structure_aware"):
        index = build_index(strategy)
        hits = index.search(q["question"], k=K)
        r = answer_auto(index, q["question"], k=K)
        ctx = " ".join(h["text"] for h in hits).lower()
        has_caveat = any(m in ctx for m in CAVEAT_MARKERS)
        deep = index.search(q["question"], k=10)
        caveat_rank = next((h["rank"] for h in deep
                            if any(m in h["text"].lower() for m in CAVEAT_MARKERS)), None)
        answer_has = any(m in " ".join(c["claim"] for c in r["claims"]).lower()
                         for m in CAVEAT_MARKERS)
        parts += [f"#### {strategy}", "",
                  f"- top-1: `{hits[0]['chunk_id']}` (score {hits[0]['score']}, "
                  f"{len(hits[0]['text'])} chars)",
                  f"- gold row ERR-4501 in top-1: "
                  f"**{'YES' if 'ERR-4501' in hits[0]['text'] else 'NO'}**",
                  f"- 24-hour-cache caveat anywhere in the k={K} context: "
                  f"**{'YES' if has_caveat else 'NO'}**",
                  f"- rank at which the caveat first appears: "
                  f"**{caveat_rank if caveat_rank else 'not in top 10'}**",
                  f"- caveat present in the generated answer: "
                  f"**{'YES' if answer_has else 'NO'}**", "",
                  "Answer produced:", ""]
        for i, c in enumerate(r["claims"], 1):
            parts.append(f"{i}. {c['claim']}  \n   `{c['chunk_id']}`")
        parts.append("")
    open(os.path.join(HERE, "bonus.md"), "w").write("\n".join(parts))
    print("\n".join(parts))

if __name__ == "__main__":
    main()
