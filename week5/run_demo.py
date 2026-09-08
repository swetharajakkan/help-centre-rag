"""Bonus: the CURATED demo set, run exactly the way a demo runs it.

`/api/examples` serves golden_set.jsonl to the UI as one-click questions, so
these twelve ARE the tickets we show clients. They are run at the UI defaults
(mode=week4, k=3, no product-area filter) because that is what a demo does:
nobody touches the dropdowns while a client is watching.
"""
from __future__ import annotations

import json, os, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_traces import build_index, params_block, run_one  # noqa: E402

SEED = 20260907


def main() -> None:
    golden = [json.loads(l) for l in
              open(os.path.join(HERE, "..", "backend", "eval", "golden_set.jsonl"))
              if l.strip()]
    rows = [{"trace_id": f"D-{g['id']}", "question": g["question"],
             "template": "demo_golden", "k": 3, "mode": "week4",
             "product_area": None, "strategy": "structure_aware"}
            for g in golden]

    index = build_index("structure_aware")
    params = params_block()
    out = os.path.join(HERE, "demo_traces.jsonl")
    with open(out, "w") as fh:
        for r in rows:
            tr = run_one(index, r, params)
            tr["population"] = "curated_demo"
            fh.write(json.dumps(tr, ensure_ascii=False) + "\n")

    ids = sorted(r["trace_id"] for r in rows)
    sample = sorted(random.Random(SEED).sample(ids, 10))
    with open(os.path.join(HERE, "demo_sample.json"), "w") as fh:
        json.dump({"seed": SEED, "population_size": len(ids),
                   "sample": sample}, fh, indent=1)
    print(f"demo traces: {len(rows)} -> {out}")
    print(f"seed={SEED} sample of 10:", ", ".join(sample))


if __name__ == "__main__":
    main()
