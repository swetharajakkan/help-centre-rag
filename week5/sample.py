"""Draw the sample. Seeded, documented, reproducible, drawn before reading.

Procedure, in this exact order, from one seed:

    ids  = sorted(every trace_id in traces.jsonl)      # 182 ids, sorted
    rng  = random.Random(20260907)
    SAMPLE   = sorted(rng.sample(ids, 20))             # draw 1: the 20
    REPLAY   = rng.choice(ids)                         # draw 2: replay target

Anyone can re-run this file and get the same 20 ids and the same replay id.
The seed is 20260907 -- today's date -- so it is checkable rather than a
number chosen after seeing which draw looked convenient.
"""
from __future__ import annotations

import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20260907


def main() -> None:
    rows = [json.loads(l) for l in open(os.path.join(HERE, "traces.jsonl"))
            if l.strip()]
    ids = sorted(r["trace_id"] for r in rows)
    rng = random.Random(SEED)
    sample = sorted(rng.sample(ids, 20))
    replay = rng.choice(ids)

    out = {"seed": SEED, "population_size": len(ids),
           "sample_size": 20, "sample": sample, "replay_trace_id": replay,
           "procedure": "ids=sorted(trace_ids); rng=random.Random(20260907); "
                        "sample=sorted(rng.sample(ids,20)); replay=rng.choice(ids)"}
    with open(os.path.join(HERE, "sample.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"seed={SEED}  population={len(ids)}")
    print("sample of 20:", ", ".join(sample))
    print("replay target:", replay)


if __name__ == "__main__":
    main()
