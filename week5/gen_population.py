"""Build a week's worth of support traffic MECHANICALLY from the corpus.

Why this file exists
--------------------
This deployment has no persistent trace log: `backend/app/chat.py` emits an
SSE `retrieval` trace to the browser and nothing writes it anywhere. So there
was no week of traffic to sample. Rather than invent traces, this script
invents QUESTIONS -- mechanically, from the corpus, under a fixed seed -- and
`run_traces.py` puts them through the real, unmodified assistant. Every trace
is then a genuine system output; only the population is synthetic.

The whole point is that the population is generated BLIND to outcomes:

  * Questions come from templates applied uniformly to every error-code row,
    every section heading and every prose sentence in all six articles. No
    question was chosen because it looked likely to fail.
  * Paraphrasing is applied per-word with probability P_PARAPHRASE from a
    fixed synonym map, so the population spans near-verbatim to heavily
    reworded rather than being uniformly hard or uniformly easy.
  * The template mix (MIX) is declared here, in advance. Frequencies in the
    taxonomy are frequencies WITH RESPECT TO THIS MIX and are only as
    representative as the mix is.
  * This file and its output are committed BEFORE run_traces.py is run, so
    git history shows the population was fixed before any result was seen.

Nothing here was edited after looking at a single trace.
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "..", "corpus")

SEED = 20260907          # today's date, so it is checkable, not cherry-picked
N_QUESTIONS = 180
P_PARAPHRASE = 0.5

# Declared template mix. These are proportions of the generated population.
MIX = {
    "code_lookup":       0.22,   # agent has the error code in front of them
    "symptom":           0.22,   # agent describes the cause, has no code
    "section_prose":     0.16,   # "how does X work"
    "detail_from_prose": 0.12,   # "tell me more about <prose subject>"
    "ticket_prose":      0.14,   # a real ticket, with the chatter left in
    "multi_hop":         0.07,   # two codes at once
    "out_of_scope":      0.07,   # adjacent billing topic the corpus lacks
}

# Applied per word, independently, with P_PARAPHRASE. Fixed before any run.
SYNONYMS = {
    "customer": "client", "customers": "clients",
    "workspace": "account", "workspaces": "accounts",
    "invoice": "bill", "invoices": "bills",
    "payment method": "card on file",
    "declined": "rejected", "decline": "reject",
    "migration": "move to the new billing engine",
    "migrated": "moved over", "migrate": "move over",
    "re-add": "add again", "re-run": "run again", "re-queue": "queue again",
    "revalidation": "re-checking", "revalidates": "re-checks",
    "subscription": "plan", "subscriptions": "plans",
    "tax id": "VAT number",
    "webhook": "callback", "webhooks": "callbacks",
    "endpoint": "URL", "endpoints": "URLs",
    "provider": "payment processor",
    "cutover": "switchover",
    "ticket": "case",
    "verification": "checking",
    "authorisation": "authorization",
    "tokenisation": "tokenization", "tokenised": "tokenized",
    "proration": "pro-rating", "prorates": "pro-rates",
}

# Chatter wrapped around a base question for the ticket_prose template.
WRAPPERS = [
    "Customer is furious about this. {q} They want an answer today.",
    "Escalated from tier 1. {q} Please advise.",
    "Hi team, quick one. {q} Thanks!",
    "This has been open four days. {q} Can someone confirm?",
    "Account manager is asking. {q} Need something I can paste to the client.",
    "Sorry if this is obvious. {q} I'm new on this queue.",
]

# Adjacent billing topics the six articles genuinely do not cover. Written by
# listing what a billing help centre usually has and removing what this one
# has; not written by watching the assistant fail.
OUT_OF_SCOPE = [
    "What is the refund window for an invoice issued on Ledger v2?",
    "How do I raise a chargeback dispute with the card network?",
    "What is the uptime SLA for the billing API?",
    "How do I roll a workspace back from Ledger v2 to Ledger v1?",
    "How do I apply a percentage discount coupon to a subscription?",
    "Which FX rate is used when a customer pays in a currency other than the plan currency?",
    "How do I put our company logo on the invoice PDF?",
    "What is the dunning email schedule for a failed payment?",
    "How do I export a customer's billing data for a GDPR request?",
    "How is seat-based pricing counted mid-period?",
    "Can a customer pay an invoice in instalments?",
    "How do I attach a purchase order number to an invoice?",
]


def read_articles() -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.md"))):
        raw = open(path).read()
        front = dict(re.findall(r"^(\w+):\s*(.+)$", raw.split("---")[1], re.M))
        body = raw.split("---", 2)[2]
        out.append({"file": os.path.basename(path), "front": front, "body": body})
    return out


def mine(articles: list[dict]) -> dict:
    """Pull every template ingredient out of the corpus. No selection."""
    codes, headings, prose = [], [], []
    for a in articles:
        area = a["front"].get("product_area", "")
        aid = a["front"].get("article_id", "")
        for line in a["body"].splitlines():
            s = line.strip()
            m = re.match(r"^\|\s*(ERR-\d+)\s*\|([^|]+)\|([^|]+)\|", s)
            if m:
                codes.append({"code": m.group(1), "cause": m.group(2).strip(),
                              "fix": m.group(3).strip(), "article": aid,
                              "product_area": area})
                continue
            if s.startswith("## "):
                headings.append({"heading": s[3:].strip(), "article": aid,
                                 "product_area": area})
        # prose sentences: paragraphs that are not tables, headings or blank
        blocks = [b for b in re.split(r"\n\s*\n", a["body"])
                  if b.strip() and not b.strip().startswith(("#", "|"))]
        for b in blocks:
            flat = re.sub(r"\s+", " ", b).strip()
            for sent in re.split(r"(?<=[.!?]) ", flat):
                if len(sent.split()) >= 8:
                    prose.append({"sentence": sent, "article": aid,
                                  "product_area": area})
    return {"codes": codes, "headings": headings, "prose": prose}


def paraphrase(text: str, rng: random.Random) -> str:
    """Substitute each eligible term independently with P_PARAPHRASE."""
    out = text
    for src, dst in SYNONYMS.items():
        if src in out.lower() and rng.random() < P_PARAPHRASE:
            out = re.sub(re.escape(src), dst, out, flags=re.I)
    return out


def build(rng: random.Random, ing: dict) -> list[dict]:
    counts = {k: round(v * N_QUESTIONS) for k, v in MIX.items()}
    rows: list[dict] = []

    for _ in range(counts["code_lookup"]):
        c = rng.choice(ing["codes"])
        q = rng.choice([
            f"What does {c['code']} mean and what should I do?",
            f"We are getting {c['code']} on a workspace. What is the fix?",
            f"{c['code']} - how do I resolve this?",
        ])
        rows.append({"template": "code_lookup", "question": paraphrase(q, rng),
                     "topic_article": c["article"], "topic_area": c["product_area"]})

    for _ in range(counts["symptom"]):
        c = rng.choice(ing["codes"])
        cause = c["cause"][0].lower() + c["cause"][1:]
        q = rng.choice([
            f"A customer has hit this: {cause}. What should I tell them?",
            f"Seeing a case where {cause}. How is that handled?",
            f"{cause[0].upper() + cause[1:]}. What is the correct fix?",
        ])
        rows.append({"template": "symptom", "question": paraphrase(q, rng),
                     "topic_article": c["article"], "topic_area": c["product_area"]})

    for _ in range(counts["section_prose"]):
        h = rng.choice(ing["headings"])
        q = rng.choice([
            f"How does {h['heading'].lower()} work?",
            f"Can you explain {h['heading'].lower()}?",
            f"What changes about {h['heading'].lower()} after the migration?",
        ])
        rows.append({"template": "section_prose", "question": paraphrase(q, rng),
                     "topic_article": h["article"], "topic_area": h["product_area"]})

    for _ in range(counts["detail_from_prose"]):
        p = rng.choice(ing["prose"])
        subject = " ".join(p["sentence"].split()[:7]).rstrip(",.")
        q = rng.choice([
            f"Can you tell me more about this: {subject}?",
            f"A client is asking about {subject}. What is the detail here?",
        ])
        rows.append({"template": "detail_from_prose", "question": paraphrase(q, rng),
                     "topic_article": p["article"], "topic_area": p["product_area"]})

    for _ in range(counts["ticket_prose"]):
        c = rng.choice(ing["codes"])
        base = rng.choice([
            f"What does {c['code']} mean?",
            f"How do I fix {c['code']}?",
            f"Customer hit {c['code']} during migration.",
        ])
        q = rng.choice(WRAPPERS).format(q=base)
        rows.append({"template": "ticket_prose", "question": paraphrase(q, rng),
                     "topic_article": c["article"], "topic_area": c["product_area"]})

    for _ in range(counts["multi_hop"]):
        a, b = rng.sample(ing["codes"], 2)
        q = rng.choice([
            f"We have {a['code']} on one workspace and {b['code']} on another. "
            f"Are these the same root cause?",
            f"Is {a['code']} related to {b['code']}?",
        ])
        rows.append({"template": "multi_hop", "question": paraphrase(q, rng),
                     "topic_article": f"{a['article']}+{b['article']}",
                     "topic_area": a["product_area"]})

    for _ in range(counts["out_of_scope"]):
        q = rng.choice(OUT_OF_SCOPE)
        rows.append({"template": "out_of_scope", "question": q,
                     "topic_article": None, "topic_area": None})

    rng.shuffle(rows)
    return rows


# Request parameters. A real request carries a mode toggle, a k and an optional
# product-area filter; the UI defaults to k=3, no filter. Sampled here, not
# chosen: most traffic is unfiltered, which is why None is weighted heavily.
AREAS = ["billing", "payments", "invoicing", "subscriptions",
         "tax-compliance", "developer-api"]


def attach_params(rows: list[dict], rng: random.Random) -> list[dict]:
    for i, r in enumerate(rows, start=1):
        r["trace_id"] = f"T-{i:04d}"
        r["k"] = rng.choices([3, 5], weights=[0.8, 0.2])[0]
        r["mode"] = rng.choices(["week4", "week3", None], weights=[0.7, 0.2, 0.1])[0]
        r["product_area"] = (rng.choice(AREAS)
                             if rng.random() < 0.30 else None)
        r["strategy"] = "structure_aware"
    return rows


def main() -> None:
    rng = random.Random(SEED)
    articles = read_articles()
    ing = mine(articles)
    rows = attach_params(build(rng, ing), rng)
    out = os.path.join(HERE, "population.jsonl")
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"seed={SEED} questions={len(rows)} -> {out}")
    print("ingredients: %d error-code rows, %d headings, %d prose sentences"
          % (len(ing["codes"]), len(ing["headings"]), len(ing["prose"])))


if __name__ == "__main__":
    main()
