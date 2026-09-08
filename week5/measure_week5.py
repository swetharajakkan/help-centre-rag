"""Re-run the frozen population on the Week 5 arm and score the prediction.

Writes to traces_week5.jsonl. The original traces.jsonl is the Week 4 baseline
and is not touched, so the before/after comparison stays honest.
"""
from __future__ import annotations
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("HELP_CENTRE_RERANK", "1")
from run_traces import build_index, params_block, run_one  # noqa: E402
import run_traces  # noqa: E402
from backend.app.generation import answer_extractive  # noqa: E402


def main() -> None:
    rows = [json.loads(l) for l in open(os.path.join(HERE, "population.jsonl")) if l.strip()]
    index, params = build_index("structure_aware"), params_block()
    out = os.path.join(HERE, "traces_week5.jsonl")
    with open(out, "w") as fh:
        for i, row in enumerate(rows, start=1):
            # Every request now goes through the Week 5 arm.
            tr = run_one(index, row, params)
            where = {"product_area": row["product_area"]} if row["product_area"] else None
            res = answer_extractive(index, row["question"], k=row["k"], where=where,
                                    use_rerank={"week3": False, "week4": True}.get(row["mode"]),
                                    fallback=True)
            tr["result"] = res
            tr["request"]["mode"] = "week5"
            fh.write(json.dumps(tr, ensure_ascii=False) + "\n")
            if i % 50 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
