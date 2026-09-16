"""Build week6/eval_set.jsonl: 27 support tickets, each tagged with one
Week-5 taxonomy mode.

Every case is anchored to a real trace in week5/traces.jsonl. The 20 coded
traces from the Week-5 sample keep the mode the coding sheet gave them
(week5/coding.json); the 7 additions were coded here by the same taxonomy and
are marked coded_in: "week6".

Ticket metadata -- id, tier, purchase date, refund request -- is NOT in the
traces; support tickets carry it and the replayed questions do not. It is
assigned from the fixed table below, written once, before any assertion or
judge was run, so nothing about the refund/escalation spread can be tuned
after seeing a result.

Three cases are replayed VERBATIM: the reply text is the model output recorded
in the trace, copied out of the trace file, not regenerated. Those are the
regression cases -- the Week-5 failures, frozen, so they cannot come back
unnoticed.
"""
from __future__ import annotations

import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TRACES = os.path.join(ROOT, "week5", "traces.jsonl")
CODING = os.path.join(ROOT, "week5", "coding.json")

# case_id, source trace, mode, tier, days_since_purchase, refund_requested,
# refund_amount_usd, replay_verbatim
#
# Modes are the Week-5 taxonomy:
#   mode_1 retrieval  - product-area filter hid a documented answer
#   mode_2 generation - prints fixes for codes the customer never reported
#   mode_3 guardrail  - refuses over ordinary support wording
#   mode_4 halluc.    - confident quotes that do not address the question
#   mode_5 generation - closes on an instruction from an unrelated article
#   no_failure        - no failure observed
CASES = [
    # id       trace     mode        tier        days  refund  amount  verbatim
    ("C-01", "T-0043", "mode_1", "Priority", 12, True,  41.50, False),
    ("C-02", "T-0057", "mode_1", "Standard", 44, True,  18.00, False),
    ("C-03", "T-0074", "mode_1", "Standard",  9, False, None,  False),
    ("C-04", "T-0096", "mode_1", "Priority", 31, True,  96.25, False),
    ("C-05", "T-0106", "mode_1", "Standard",  5, False, None,  False),
    ("C-06", "T-0157", "mode_1", "Priority",  3, False, None,  False),
    ("C-07", "T-0012", "mode_1", "Standard", 27, True,  12.00, False),
    ("C-08", "T-0032", "mode_2", "Standard", 61, True,  75.00, False),
    ("C-09", "T-0060", "mode_2", "Priority", 14, False, None,  False),
    ("C-10", "T-0066", "mode_2", "Standard", 22, True, 250.00, False),
    ("C-11", "T-0130", "mode_2", "Priority", 38, True,  33.40, False),
    ("C-12", "T-0006", "mode_2", "Standard",  8, False, None,  False),
    ("C-13", "T-0016", "mode_2", "Standard", 30, True,   9.99, False),
    ("C-14", "T-0062", "mode_3", "Priority", 19, False, None,  False),
    ("C-15", "T-0064", "mode_3", "Standard",  6, False, None,  False),
    ("C-16", "T-0025", "mode_3", "Standard", 52, True,  60.00, False),
    ("C-17", "T-0004", "mode_4", "Standard", 11, False, None,  False),
    ("C-18", "T-0054", "mode_4", "Priority", 25, True, 120.00, False),
    ("C-19", "T-0182", "mode_5", "Standard", 17, False, None,  False),
    ("C-20", "T-0113", "no_failure", "Standard", 4,  False, None, False),
    ("C-21", "T-0134", "no_failure", "Priority", 29, True, 47.75, False),
    ("C-22", "T-0040", "no_failure", "Standard", 33, True, 15.00, False),
    ("C-23", "T-0048", "no_failure", "Priority",  7, False, None, False),
    ("C-24", "T-0022", "no_failure", "Standard", 13, False, None, False),
    # Regression cases: replayed verbatim from real failed ticket traces.
    ("R-01", "T-0090", "mode_1", "Priority", 21, True,  88.00, True),
    ("R-02", "T-0049", "mode_2", "Standard", 35, True,  24.00, True),
    ("R-03", "T-0146", "mode_3", "Priority", 10, False, None,  True),
]

# Pre-registered exclusions from the judged subset. Both are excluded for a
# reason about the QUESTION, decided before any reply was drafted, not for
# anything about the reply.
NOT_JUDGED = {
    "C-03": "malformed question - the population template produced a sentence "
            "fragment ('Restoring the original anchor requires a support'), so "
            "'does the reply resolve it' has no determinate answer. Kept in "
            "the eval set because the assertions are still well defined.",
    "C-24": "out-of-corpus control - the corpus provably contains no GDPR "
            "export procedure, so non-resolution is correct by construction "
            "and the binary criterion cannot separate a good reply from a bad "
            "one here.",
}


def main() -> None:
    traces = {json.loads(l)["trace_id"]: json.loads(l)
              for l in open(TRACES) if l.strip()}
    coded = {}
    for m in json.load(open(CODING))["modes"]:
        for tid in m["trace_ids"]:
            coded[tid] = m["id"]

    rows = []
    for i, (cid, tid, mode, tier, days, refund_req, amount, verbatim) in \
            enumerate(CASES, start=1):
        t = traces[tid]
        row = {
            "case_id": cid,
            "mode": mode,
            "source_trace": tid,
            "source_file": "week5/traces.jsonl",
            "coded_in": "week5" if tid in coded else "week6",
            "replay_verbatim": verbatim,
            "ticket": {
                "ticket_id": f"TCK-{4000 + i}",
                "tier": tier,
                "days_since_purchase": days,
                "refund_requested": refund_req,
                "refund_amount_usd": amount,
                "question": t["question"],
                "product_area": t["request"]["product_area"],
            },
            "judged": cid not in NOT_JUDGED,
        }
        if cid in NOT_JUDGED:
            row["not_judged_because"] = NOT_JUDGED[cid]
        if verbatim:
            # Freeze the recorded output. Nothing is regenerated for these.
            row["frozen_result"] = t["result"]
            row["frozen_sha256"] = hashlib.sha256(
                json.dumps(t["result"], sort_keys=True).encode()).hexdigest()[:16]
        rows.append(row)

    out = os.path.join(HERE, "eval_set.jsonl")
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    from collections import Counter
    counts = Counter(r["mode"] for r in rows)
    print(f"wrote {out}: {len(rows)} cases")
    for mode, n in sorted(counts.items()):
        print(f"  {mode:12} {n}")
    print(f"  replayed verbatim: {sum(r['replay_verbatim'] for r in rows)}")
    print(f"  judged subset:     {sum(r['judged'] for r in rows)}")


if __name__ == "__main__":
    main()
