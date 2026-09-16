"""RAGAS faithfulness, answer relevancy and context precision — deterministic.

This is NOT the `ragas` package. RAGAS normally uses an LLM to decompose an
answer into statements and to judge each one against the retrieved context;
there is no ANTHROPIC_API_KEY in this environment, so the metric DEFINITIONS
are implemented directly against the pipeline's own structure. That is honest
here and nowhere else: this generator already emits claims as discrete units,
each carrying the verbatim `supporting_quote` it was extracted from, so the
decomposition step RAGAS pays a model for is already done and exact.

  faithfulness       supported claims / total claims. A claim is supported
                     when its supporting_quote appears verbatim in one of the
                     chunks that were actually retrieved for this question.

  answer_relevancy   mean over claims of the overlap between the claim's
                     content words and the question's content words.

  context_precision  the RAGAS formulation:
                       sum_k (precision@k * rel_k) / (number of relevant
                       chunks in the top K)
                     A retrieved chunk is relevant when it carries the
                     documented answer to the question -- mechanically: it
                     contains an ERR-code the question names, or, when the
                     question names no code, it restates at least 60% of the
                     question's content words.

The point of running this is the last block: a reply can score 1.00
faithfulness and still be quoting the wrong article, because faithfulness asks
"did you make this up?" and never asks "is this the customer's question?".
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CODE = re.compile(r"ERR-\d{4}")

# SP-001's subject matter. A claim quoted out of the support policy is on
# topic only if the ticket is about one of these.
POLICY_TERMS = {"refund", "refunded", "escalate", "escalated", "escalation",
                "priority", "tier", "ticket", "window", "reply", "queue"}
STOP = {"the", "a", "an", "is", "are", "was", "were", "and", "or", "to", "of",
        "in", "on", "for", "that", "this", "what", "how", "do", "does", "i",
        "we", "it", "has", "have", "with", "not", "no", "but", "be", "been",
        "correct", "fix", "client", "customer", "case", "hit", "should",
        "mean", "means", "work", "works", "seeing", "asking", "please",
        "tell", "them", "one", "another", "same", "root", "cause"}


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in STOP}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def is_relevant(chunk_text: str, question: str) -> bool:
    asked = set(CODE.findall(question))
    if asked:
        return bool(asked & set(CODE.findall(chunk_text)))
    q = words(question)
    return bool(q) and len(q & words(chunk_text)) / len(q) >= 0.6


def faithfulness(claims: list[dict], contexts: list[dict]) -> float | None:
    if not claims:
        return None
    blob = norm(" ".join(c["text"] for c in contexts))
    ok = sum(1 for c in claims if norm(c["supporting_quote"]) in blob)
    return round(ok / len(claims), 3)


def answer_relevancy(claims: list[dict], question: str) -> float | None:
    if not claims:
        return None
    q = words(question)
    if not q:
        return None
    scores = [len(q & words(c["claim"])) / len(q) for c in claims]
    return round(sum(scores) / len(scores), 3)


def context_precision(contexts: list[dict], question: str) -> float | None:
    if not contexts:
        return None
    rel = [is_relevant(c["text"], question) for c in contexts]
    total = sum(rel)
    if not total:
        return 0.0
    run = 0.0
    for k, r in enumerate(rel, start=1):
        if r:
            run += sum(rel[:k]) / k
    return round(run / total, 3)


def wrong_section_quotes(claims: list[dict], contexts: list[dict],
                         question: str) -> list[dict]:
    """Claims quoted verbatim out of SP-001 on a ticket that is not about
    SP-001's subject. Faithful to the retrieved text, wrong policy section."""
    by_id = {c["chunk_id"]: c for c in contexts}
    on_topic = bool(words(question) & POLICY_TERMS)
    out = []
    for c in claims:
        ctx = by_id.get(c["chunk_id"])
        if ctx and ctx["article_id"] == "SP-001" and not on_topic:
            out.append({"claim": c["claim"], "quoted_from": ctx["chunk_id"],
                        "policy_section": ctx.get("section", ""),
                        "verbatim_in_context":
                            norm(c["supporting_quote"]) in norm(ctx["text"])})
    return out


def main() -> None:
    replies = [json.loads(l) for l in
               open(os.path.join(HERE, "replies.jsonl")) if l.strip()]

    rows = []
    for r in replies:
        if not r["contexts"]:            # verbatim replays carry no contexts
            continue
        policy_backed = any(c["article_id"] == "SP-001" for c in r["contexts"])
        if not policy_backed:
            continue
        q = r["ticket"]["question"]
        rows.append({
            "case_id": r["case_id"], "mode": r["mode"], "question": q,
            "faithfulness": faithfulness(r["claims"], r["contexts"]),
            "answer_relevancy": answer_relevancy(r["claims"], q),
            "context_precision": context_precision(r["contexts"], q),
            "wrong_section": wrong_section_quotes(r["claims"], r["contexts"], q),
        })

    print(f"POLICY-BACKED CASES — {len(rows)} of {len(replies)} cases "
          f"retrieved at least one SP-001 chunk\n")
    print(f"{'case':6}{'mode':12}{'faith':>8}{'ans_rel':>9}{'ctx_prec':>10}"
          f"  wrong-section quotes")
    print("-" * 78)
    for r in rows:
        f = "—" if r["faithfulness"] is None else f"{r['faithfulness']:.2f}"
        a = "—" if r["answer_relevancy"] is None else f"{r['answer_relevancy']:.2f}"
        p = "—" if r["context_precision"] is None else f"{r['context_precision']:.2f}"
        print(f"{r['case_id']:6}{r['mode']:12}{f:>8}{a:>9}{p:>10}  "
              f"{len(r['wrong_section'])}")

    scored = [r for r in rows if r["faithfulness"] is not None]
    if scored:
        mf = sum(r["faithfulness"] for r in scored) / len(scored)
        mp = sum(r["context_precision"] for r in scored) / len(scored)
        print(f"\n  mean faithfulness      {mf:.3f}")
        print(f"  mean context precision {mp:.3f}")

    flagged = [r for r in rows
               if r["wrong_section"] and (r["faithfulness"] or 0) >= 0.9]
    print(f"\nCONFIDENTLY, FAITHFULLY WRONG — {len(flagged)} case(s) at "
          f"faithfulness >= 0.90 quoting a policy section the ticket is not "
          f"about")
    print("-" * 78)
    for r in flagged:
        print(f"\n  {r['case_id']}  faithfulness {r['faithfulness']:.2f}   "
              f"context precision {r['context_precision']:.2f}")
        print(f"  ticket asked: {r['question']}")
        for w in r["wrong_section"]:
            print(f"  quoted from : {w['quoted_from']}")
            print(f"    section   : {w['policy_section']}")
            print(f"    verbatim  : {w['verbatim_in_context']}")
            print(f"    claim     : {w['claim'][:150]}")

    json.dump(rows, open(os.path.join(HERE, "ragas_report.json"), "w"), indent=1)
    print(f"\n  wrote {os.path.join(HERE, 'ragas_report.json')}")


if __name__ == "__main__":
    main()
