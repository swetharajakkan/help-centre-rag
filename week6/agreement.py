"""Agreement between the hand labels and a judge run.

Raw agreement is the headline because it is the number leadership would read.
Cohen's kappa is printed next to it because raw agreement flatters a judge on
a skewed set: if 80% of replies are NOT_RESOLVED, a judge that says
NOT_RESOLVED every time scores 80% and has learned nothing.
"""
from __future__ import annotations

import json
import os
import sys


def agreement(labels: dict, judge_run: dict) -> dict:
    human = labels["labels"]
    machine = judge_run["verdicts"]
    ids = sorted(set(human) & set(machine))

    cells = {("RESOLVED", "RESOLVED"): 0, ("RESOLVED", "NOT_RESOLVED"): 0,
             ("NOT_RESOLVED", "RESOLVED"): 0,
             ("NOT_RESOLVED", "NOT_RESOLVED"): 0}
    disagreements = []
    for cid in ids:
        h, m = human[cid]["label"], machine[cid]["verdict"]
        cells[(h, m)] += 1
        if h != m:
            disagreements.append({
                "case_id": cid, "mode": machine[cid]["mode"],
                "human": h, "judge": m,
                "human_reason": human[cid]["reason"],
                "judge_reason": machine[cid]["reasoning"],
            })

    n = len(ids)
    agree = cells[("RESOLVED", "RESOLVED")] + cells[("NOT_RESOLVED", "NOT_RESOLVED")]
    po = agree / n if n else 0.0
    ph = sum(1 for c in ids if human[c]["label"] == "RESOLVED") / n
    pm = sum(1 for c in ids if machine[c]["verdict"] == "RESOLVED") / n
    pe = ph * pm + (1 - ph) * (1 - pm)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0

    return {"n": n, "agree": agree, "agreement_pct": round(po * 100, 1),
            "cohens_kappa": round(kappa, 3),
            "confusion": {f"human={h},judge={m}": v for (h, m), v in cells.items()},
            "human_resolved_rate": round(ph * 100, 1),
            "judge_resolved_rate": round(pm * 100, 1),
            "disagreements": disagreements,
            "judge_prompt": judge_run["prompt_file"],
            "judge_engine": judge_run["engine"]}


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    labels = json.load(open(os.path.join(here, "labels_25.json")))
    run = json.load(open(sys.argv[1]))
    a = agreement(labels, run)

    print(f"labels : {labels['file']} ({a['n']} cases, "
          f"labelled {labels['labelled_at']})")
    print(f"judge  : {a['judge_prompt']} (engine {a['judge_engine']})\n")
    print(f"  AGREEMENT      {a['agreement_pct']}%  ({a['agree']}/{a['n']})")
    print(f"  Cohen's kappa  {a['cohens_kappa']}")
    print(f"  RESOLVED rate  human {a['human_resolved_rate']}%  "
          f"judge {a['judge_resolved_rate']}%\n")
    for k, v in a["confusion"].items():
        print(f"  {k:38} {v}")
    print(f"\n  {len(a['disagreements'])} disagreement(s):")
    for d in a["disagreements"]:
        print(f"   - {d['case_id']} [{d['mode']}] human={d['human']} "
              f"judge={d['judge']}")
        print(f"       human: {d['human_reason']}")
        print(f"       judge: {d['judge_reason']}")

    out = sys.argv[2] if len(sys.argv) > 2 else None
    if out:
        json.dump(a, open(out, "w"), indent=1)
        print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
