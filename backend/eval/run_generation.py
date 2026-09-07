"""Produce the generation transcripts and independently verify every citation."""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Week 3 measured the CHUNKER. Pin Week 4's reranker off so this harness
# keeps reproducing the numbers published in results.md.
os.environ.setdefault("HELP_CENTRE_RERANK", "0")

from backend.app.ingest import build_index          # noqa: E402
from backend.app.generation import answer_auto      # noqa: E402

HERE = os.path.dirname(__file__)
K = 3


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def render(qid, question, result, index) -> str:
    out = [f"### {qid} — {question}", "",
           f"`engine: {result['engine']}`  ·  "
           f"`retrieved (k={K}): {', '.join(result['retrieved'])}`", ""]
    if not result["answered"]:
        out += ["**REFUSED.**", "", "```", result["refusal"], "```", ""]
        return "\n".join(out)
    out += ["**Answer (one citation per claim):**", ""]
    for i, c in enumerate(result["claims"], 1):
        rec = index.get(c["chunk_id"])
        ok = norm(c["supporting_quote"]) in norm(rec.text) if rec else False
        out += [f"{i}. {c['claim']}",
                f"   - **cite:** `{c['chunk_id']}` "
                f"→ {c['article_id']} ({c['source_file']}), section “{c['section']}”",
                f"   - **chunk_id resolves:** {'YES' if rec else 'NO'} · "
                f"**quote verbatim in that chunk:** {'YES' if ok else 'NO'}", ""]
    return "\n".join(out)


def main():
    spec = json.load(open(os.path.join(HERE, "questions.json")))
    index = build_index("structure_aware")
    byid = {q["id"]: q for q in spec["questions"]}
    parts, verified, total = [], 0, 0

    parts.append("## Cited answers (3 answerable)\n")
    for qid in spec["generation_answerable"]:
        r = answer_auto(index, byid[qid]["question"], k=K)
        parts.append(render(qid, byid[qid]["question"], r, index))
        for c in r["claims"]:
            total += 1
            rec = index.get(c["chunk_id"])
            verified += bool(rec and norm(c["supporting_quote"]) in norm(rec.text))

    parts.append("## Refusal transcripts (3 out-of-corpus)\n")
    refused = 0
    for u in spec["generation_unanswerable"]:
        r = answer_auto(index, u["question"], k=K)
        refused += not r["answered"]
        parts.append(render(u["id"], u["question"], r, index))

    parts.append(f"**Citation audit: {verified}/{total} claims have a chunk_id "
                 f"that resolves AND a quote verbatim in that chunk.**\n")
    parts.append(f"**Refusal audit: {refused}/3 out-of-corpus questions refused.**\n")

    open(os.path.join(HERE, "generation_transcripts.md"), "w").write(
        "\n".join(parts))
    print(f"citations verified {verified}/{total}; refused {refused}/3")
    print("wrote", os.path.join(HERE, "generation_transcripts.md"))


if __name__ == "__main__":
    main()
