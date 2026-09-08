"""The falsification metric for the Week 5 prediction.

M1 = of all traces whose question names an ERR-code that IS written in the
     corpus, the fraction the assistant refused.

Fully mechanical: the code is either in a corpus file or it is not, and the
trace either refused or it did not. No judgement, no labelling, so a re-run
after a change can confirm or kill the prediction without me in the loop.
"""
from __future__ import annotations

import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "..", "corpus")

corpus_text = "".join(open(p).read() for p in sorted(glob.glob(os.path.join(CORPUS, "*.md"))))
KNOWN = set(re.findall(r"ERR-\d+", corpus_text))


def measure(path: str) -> dict:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    denom, refused, examples = 0, 0, []
    for t in rows:
        codes = {c for c in re.findall(r"ERR-\d+", t["question"]) if c in KNOWN}
        if not codes:
            continue
        denom += 1
        if not t["result"]["answered"]:
            refused += 1
            examples.append((t["trace_id"], sorted(codes),
                             t["request"]["product_area"]))
    return {"traces": len(rows), "denominator": denom, "refused": refused,
            "M1": round(refused / denom, 4) if denom else None,
            "examples": examples}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "traces.jsonl")
    m = measure(path)
    print(f"corpus knows {len(KNOWN)} ERR-codes")
    print(f"traces={m['traces']}  questions naming a known code={m['denominator']}")
    print(f"refused anyway={m['refused']}   M1={m['M1']:.3f}")
    withf = sum(1 for _, _, a in m["examples"] if a)
    print(f"of those refusals, {withf}/{m['refused']} had a product_area filter set")
