"""The one command. Drafts every reply, runs the assertions and the judge over
all 27 cases, and prints pass rate by Week-5 failure mode.

    .venv-test/bin/python week6/run_week6.py

A case PASSES when every applicable assertion passes AND, for the 25 judged
cases, the judge returns RESOLVED. The two unjudged cases (pre-registered in
eval_set.jsonl) pass on assertions alone.

Nothing here decides anything a human has to weigh in on. The judge's own
agreement with a human is measured separately, by week6/agreement.py, against
labels that were committed before any judge was ever run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import assertions as A  # noqa: E402

MODE_ORDER = ["mode_1", "mode_2", "mode_3", "mode_4", "mode_5", "no_failure"]
MODE_LABEL = {
    "mode_1": "filter hid the answer",
    "mode_2": "fixes nobody asked for",
    "mode_3": "refused on wording",
    "mode_4": "confident, off-topic",
    "mode_5": "instruction, wrong article",
    "no_failure": "no failure observed",
}


def sh(*cmd: str) -> None:
    # PYTHONHASHSEED pinned: see the note at the top of week6/draft.py.
    subprocess.run([sys.executable, *cmd], check=True, cwd=ROOT,
                   env={**os.environ, "PYTHONHASHSEED": "0"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", default="judge_v2.txt",
                    help="judge prompt to score with (default judge_v2.txt)")
    ap.add_argument("--skip-draft", action="store_true",
                    help="reuse week6/replies.jsonl instead of redrafting")
    args = ap.parse_args()

    if not args.skip_draft:
        sh(os.path.join("week6", "make_eval_set.py"))
        sh(os.path.join("week6", "draft.py"))

    judge_out = os.path.join(HERE, f"judge_run_{args.judge.split('.')[0]}.json")
    sh(os.path.join("week6", "judge.py"),
       "--prompt", os.path.join("week6", args.judge), "--out", judge_out)

    cases = {json.loads(l)["case_id"]: json.loads(l)
             for l in open(os.path.join(HERE, "eval_set.jsonl")) if l.strip()}
    replies = [json.loads(l) for l in
               open(os.path.join(HERE, "replies.jsonl")) if l.strip()]
    judged = json.load(open(judge_out))

    rows, per_mode = [], OrderedDict((m, [0, 0]) for m in MODE_ORDER)
    fail_counts, assertion_stats = Counter(), Counter()
    for r in replies:
        case = cases[r["case_id"]]
        res = A.run(r["reply"], r["ticket"])
        for name, c in res["checks"].items():
            assertion_stats[(name, c["status"])] += 1
        verdict = judged["verdicts"].get(r["case_id"], {}).get("verdict", "—")
        ok = res["passed"] and (verdict in ("RESOLVED", "—"))
        per_mode[r["mode"]][1] += 1
        per_mode[r["mode"]][0] += ok
        for f in res["failed"]:
            fail_counts[f] += 1
        rows.append((r["case_id"], r["mode"], case["replay_verbatim"],
                     "ok" if res["passed"] else ",".join(res["failed"]),
                     verdict, ok))

    print("\n" + "=" * 78)
    print(f"WEEK 6 EVAL — {len(replies)} cases, judge={judged['prompt_file']} "
          f"(engine={judged['engine']})")
    print("=" * 78)
    print(f"\n{'case':6}{'mode':12}{'rep':5}{'assertions':34}"
          f"{'judge':14}{'pass'}")
    print("-" * 78)
    for cid, mode, verbatim, adetail, verdict, ok in rows:
        print(f"{cid:6}{mode:12}{'yes' if verbatim else '':5}"
              f"{adetail[:33]:34}{verdict:14}{'PASS' if ok else 'FAIL'}")

    print("\nPASS RATE BY MODE")
    print("-" * 78)
    for mode, (ok, n) in per_mode.items():
        if not n:
            continue
        bar = "#" * round(ok / n * 20)
        print(f"  {mode:12} {MODE_LABEL[mode]:28} {ok:2}/{n:<3} "
              f"{ok / n * 100:5.1f}%  {bar}")
    tot_ok = sum(v[0] for v in per_mode.values())
    print(f"  {'OVERALL':12} {'':28} {tot_ok:2}/{len(rows):<3} "
          f"{tot_ok / len(rows) * 100:5.1f}%")

    print("\nDETERMINISTIC ASSERTIONS vs JUDGED CRITERIA")
    print("-" * 78)
    for name, _ in A.ASSERTIONS:
        p = assertion_stats[(name, "PASS")]
        f = assertion_stats[(name, "FAIL")]
        na = assertion_stats[(name, "n/a")]
        print(f"  {name:32} PASS {p:2}  FAIL {f:2}  n/a {na:2}")
    print(f"\n  assertions:      {len(A.ASSERTIONS)} "
          f"(were judge criteria 2-5 in judge_v0.txt)")
    print(f"  judged criteria: 1 (binary RESOLVED / NOT_RESOLVED)")
    print(f"  judge v0 scored 6 criteria on 1-10; "
          f"{len(A.ASSERTIONS)} moved out, 1 deleted, 1 kept and made binary.")

    regressions = [r for r in rows if r[2]]
    print(f"\n  regression cases replayed verbatim: {len(regressions)} "
          f"({', '.join(r[0] for r in regressions)}) — "
          f"{sum(r[5] for r in regressions)}/{len(regressions)} passing")

    labels = os.path.join(HERE, "labels_25.json")
    if os.path.exists(labels):
        from agreement import agreement
        a = agreement(json.load(open(labels)), judged)
        print(f"\n  judge-vs-human agreement on this run: {a['agreement_pct']}% "
              f"({a['agree']}/{a['n']})")
    print()


if __name__ == "__main__":
    main()
