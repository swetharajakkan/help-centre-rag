"""Assemble results.md from the generated artifacts (nothing hand-transcribed)."""
from __future__ import annotations
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
read = lambda n: open(os.path.join(HERE, n)).read()

spec = json.load(open(os.path.join(HERE, "questions.json")))
rep = json.load(open(os.path.join(HERE, "eval_report.json")))
fw, sa = rep["totals"]["fixed_window"], rep["totals"]["structure_aware"]

# ---- 8 questions table ---------------------------------------------------
qrows = ["| # | Type | Question | Known-correct article / section |",
         "|---|---|---|---|"]
for q in spec["questions"]:
    qrows.append(f"| {q['id']} | {q['type'].replace('_',' ')} | {q['question']} "
                 f"| **{q['gold_article']}** — {q['gold_section']} |")

# ---- per-question hit record --------------------------------------------
hrows = ["| # | Type | `fixed_window` (current) | `structure_aware` (new) |",
         "|---|---|---|---|"]
for q in spec["questions"]:
    r = rep["per_question"][q["id"]]
    def cell(s):
        d = r[s]
        return (f"HIT @ rank {d['first_hit_rank']}" if d["hit_at_5"]
                else "**MISS**")
    hrows.append(f"| {q['id']} | {q['type'].replace('_',' ')} "
                 f"| {cell('fixed_window')} | {cell('structure_aware')} |")
hrows.append(f"| **TOTAL** | | **{fw['hit_at_5']}** | **{sa['hit_at_5']}** |")

out = read("_results_body.md")
out = (out.replace("<<QUESTIONS>>", "\n".join(qrows))
          .replace("<<HITTABLE>>", "\n".join(hrows))
          .replace("<<FW_HIT>>", fw["hit_at_5"]).replace("<<SA_HIT>>", sa["hit_at_5"])
          .replace("<<FW_CHUNKS>>", str(fw["chunks_indexed"]))
          .replace("<<SA_CHUNKS>>", str(sa["chunks_indexed"]))
          .replace("<<FILTER>>", read("filter_demo.md"))
          .replace("<<GENERATION>>", read("generation_transcripts.md"))
          .replace("<<BONUS>>", read("bonus.md")))
open(os.path.join(ROOT, "results.md"), "w").write(out)
print("wrote results.md")
