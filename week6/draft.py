"""Draft a customer-facing ticket reply from a retrieval+generation result.

This is the thing under evaluation. The retrieval and generation stages are
Week 3/4/5 code, unchanged; what is new here is the reply ENVELOPE -- the
greeting, the ticket-ID line, the refund sentence, the escalation tag and the
sign-off -- because a support agent pastes the envelope, not a claims array.

The envelope is where the four policy rules in week6/policy/SP-001 live, and
it is what week6/assertions.py checks. It is written the way it was written,
not the way the assertions want it; the assertion run reports what it found.
"""
from __future__ import annotations

import json
import os
import sys

# grounding() breaks idf ties in `sorted(set_of_terms, key=-idf)` by the set's
# iteration order, so the token list printed inside a refusal ("No retrieved
# chunk contains: tier, err-4036" vs "err-4036, tier") varies with the process
# hash seed. It never changes `answered`, never changes an assertion and never
# changes a judge verdict -- both orderings are the same refusal -- but it does
# make replies.jsonl differ byte-for-byte between runs. Pinned so the committed
# artifact is reproducible; the underlying tie-break is Week-5 code and is left
# alone rather than silently rewritten here.
if os.environ.get("PYTHONHASHSEED") != "0":
    os.execve(sys.executable, [sys.executable, *sys.argv],
              {**os.environ, "PYTHONHASHSEED": "0"})

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("HELP_CENTRE_RERANK", "1")

# Large refunds need manager sign-off, so they get the approval wording rather
# than a figure the agent is not authorised to commit to.
MANAGER_APPROVAL_THRESHOLD = 100.0


def _body_answered(claims: list[dict]) -> str:
    lines = []
    for c in claims:
        text = c["claim"].strip()
        # Error-code rows arrive as markdown table rows; unwrap them so the
        # customer sees a sentence rather than a pipe-delimited row.
        if text.startswith("|"):
            parts = [p.strip() for p in text.strip("|").split("|")]
            if len(parts) >= 3:
                text = f"{parts[0]} means {parts[1].rstrip('.')}. {parts[2]}"
            else:
                text = " ".join(parts)
        lines.append(text if text.endswith(".") else text + ".")
    return "\n\n".join(lines)


def _body_refused(refusal: str) -> str:
    """The cannot-resolve block. Written before the ticket-ID rule existed and
    never revisited, which is what the ticket-ID assertion reports on."""
    return ("I looked through our help-centre articles and could not find "
            "documentation covering your question.\n\n"
            f"Details: {refusal.strip()}")


def _refund_sentence(ticket: dict) -> str:
    if not ticket["refund_requested"]:
        return ""
    amount = ticket["refund_amount_usd"]
    if amount is not None and amount < MANAGER_APPROVAL_THRESHOLD:
        return f"We have approved a refund of USD {amount:.2f} for this charge."
    return ("We have approved a refund of the full amount you paid for this "
            "charge.")


def _escalation_tag(ticket: dict, answered: bool) -> str:
    """Escalate when the reply cannot resolve the issue."""
    return "" if answered else "[ESCALATED]"


def render(ticket: dict, answered: bool, claims: list[dict],
           refusal: str) -> str:
    parts = []
    if answered:
        parts.append(f"Hi, thanks for raising ticket {ticket['ticket_id']}.")
        parts.append(_body_answered(claims))
    else:
        parts.append("Hi, thanks for getting in touch about your recent case.")
        parts.append(_body_refused(refusal))

    refund = _refund_sentence(ticket)
    if refund:
        parts.append(refund)

    tag = _escalation_tag(ticket, answered)
    if tag:
        parts.append(tag)

    parts.append("Best regards,\nBilling Support")
    return "\n\n".join(p for p in parts if p)


def build_index_with_policy():
    """Index the six billing articles plus the Week-6 support policy.

    The policy lives under week6/policy/ rather than in corpus/, so the
    corpus_sha256 recorded in the Week-5 traces still matches and week5's
    replay harness keeps reproducing. The two directories are assembled into
    one index here.
    """
    from backend.app.ingest import load_articles, records_for
    from backend.app.store import Index

    articles = (load_articles(os.path.join(ROOT, "corpus"))
                + load_articles(os.path.join(HERE, "policy")))
    index = Index("structure_aware")
    index.build(records_for("structure_aware", articles))
    return index


def draft_one(case: dict, index) -> dict:
    """One reply. Verbatim regression cases are NOT regenerated."""
    ticket = case["ticket"]
    if case["replay_verbatim"]:
        res = case["frozen_result"]
        contexts = []
        source = f"verbatim replay of {case['source_trace']}"
    else:
        from backend.app.generation import answer_extractive
        where = ({"product_area": ticket["product_area"]}
                 if ticket["product_area"] else None)
        res = answer_extractive(index, ticket["question"], k=3, where=where,
                                use_rerank=True, fallback=False)
        # Same query, same filter, same k: the retrieved set the generator saw.
        # Recorded separately because answer_extractive returns chunk ids, and
        # RAGAS context precision needs the chunk TEXT.
        contexts = [{"chunk_id": h["chunk_id"], "text": h["text"],
                     "article_id": h["meta"].get("article_id", ""),
                     "section": h["meta"].get("section", "")}
                    for h in index.search(ticket["question"], k=3, where=where,
                                          use_rerank=True)]
        source = "generated"

    reply = render(ticket, res["answered"], res.get("claims", []),
                   res.get("refusal", ""))
    return {
        "case_id": case["case_id"],
        "mode": case["mode"],
        "ticket": ticket,
        "answered": res["answered"],
        "claims": res.get("claims", []),
        "refusal": res.get("refusal", ""),
        "contexts": contexts,
        "reply": reply,
        "reply_source": source,
    }


def main() -> None:
    cases = [json.loads(l) for l in
             open(os.path.join(HERE, "eval_set.jsonl")) if l.strip()]
    index = build_index_with_policy()
    out = os.path.join(HERE, "replies.jsonl")
    with open(out, "w") as fh:
        for case in cases:
            fh.write(json.dumps(draft_one(case, index)) + "\n")
    print(f"wrote {out}: {len(cases)} replies "
          f"({sum(c['replay_verbatim'] for c in cases)} verbatim)")


if __name__ == "__main__":
    main()
