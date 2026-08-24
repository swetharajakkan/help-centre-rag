"""Render the search-only dump (8 questions x 2 strategies) and the filter demo."""
from __future__ import annotations
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.app.ingest import build_index  # noqa: E402

HERE = os.path.dirname(__file__)
FILTER_STRATEGY = "structure_aware"


def contains_all(text: str, spans: list[str]) -> bool:
    t = re.sub(r"\s+", " ", text).lower()
    return all(re.sub(r"\s+", " ", m).lower() in t for m in spans)


def fmt(h, gold=None):
    mark = ""
    if gold is not None:
        mark = "  ✅ CONTAINS ALL GOLD SPANS" if gold else ""
    head = (f"#{h['rank']}  score={h['score']:<7} dense={h['dense']:<7} "
            f"bm25={h['bm25']:<8} [{h['meta']['product_area']}]{mark}")
    body = "\n".join("      " + l for l in h["text"].splitlines())
    return f"{head}\n  chunk_id: {h['chunk_id']}\n{body}\n"


def main():
    spec = json.load(open(os.path.join(HERE, "questions.json")))
    report = json.load(open(os.path.join(HERE, "eval_report.json")))
    out = ["# Search-only dump — all 8 questions, both chunking strategies",
           "",
           "Identical questions, identical embedding model "
           "(BAAI/bge-small-en-v1.5), identical BM25 params, identical fusion "
           "weight, k=5. The chunker is the only thing that differs.", ""]
    for q in spec["questions"]:
        out += [f"## {q['id']} — {q['question']}",
                f"*Known-correct source:* **{q['gold_article']} / "
                f"{q['gold_section']}*",
                f"*Hit criterion (pre-registered):* one chunk must contain "
                f"all of `{q['must_contain']}`", ""]
        for s in ("fixed_window", "structure_aware"):
            d = report["per_question"][q["id"]][s]
            verdict = (f"HIT at rank {d['first_hit_rank']}" if d["hit_at_5"]
                       else "**MISS**")
            out += [f"### {s} — {verdict}", "```"]
            for h in INDEX[s].search(q["question"], k=5):
                out.append(fmt(h, contains_all(h["text"], q["must_contain"])))
            out += ["```", ""]

    open(os.path.join(HERE, "search_dump.md"), "w").write("\n".join(out))

    # ---- filter demo -----------------------------------------------------
    fd = spec["filter_demo"]
    index = INDEX[FILTER_STRATEGY]
    lines = [f"**Query:** `{fd['query']}`  ·  strategy `{FILTER_STRATEGY}`, k=5",
             ""]
    for label, where in (("UNFILTERED (all product areas)", None),
                         ("FILTERED product_area = developer-api",
                          {"product_area": "developer-api"})):
        lines += [f"### {label}", "```"]
        for h in index.search(fd["query"], k=5, where=where):
            lines.append(f"#{h['rank']}  score={h['score']:<7} "
                         f"dense={h['dense']:<7} bm25={h['bm25']:<8} "
                         f"[{h['meta']['product_area']:<14}] {h['chunk_id']}")
            lines.append(f"      {h['text'].splitlines()[0][:96]}")
        lines += ["```", ""]
    open(os.path.join(HERE, "filter_demo.md"), "w").write("\n".join(lines))
    print("wrote search_dump.md and filter_demo.md")


INDEX = {s: build_index(s) for s in ("fixed_window", "structure_aware")}

if __name__ == "__main__":
    main()
