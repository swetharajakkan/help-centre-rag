"""Grounded answering with a forced refusal.

Two enforcement layers, neither of which is a suggestion to the model:

1. The system prompt forbids any claim that is not quoted from a chunk. There
   is deliberately no "use your best judgement" escape hatch.
2. Post-hoc verification: every claim must cite a chunk_id that is in the
   retrieved set, AND carry a supporting_quote that appears verbatim in that
   chunk. Claims failing either check are dropped by code, not by the model.
   If nothing survives, the answer is replaced with a refusal.

A retrieval-score floor is deliberately NOT used as the refusal gate. Measured
on this corpus the out-of-corpus question "how do I roll a workspace back to
Ledger v1" retrieves at cosine 0.798, higher than two genuinely answerable
questions (Q1 0.703, Q5 0.743). Any floor that rejects it also rejects them.
"""
from __future__ import annotations

import json
import math
import os
import re

MODEL = "claude-opus-5"

SYSTEM = """You answer help-centre questions using ONLY the numbered context \
chunks supplied in the user message.

Rules, in strict precedence order:
1. Every claim you output must be supported by one cited chunk, and you must \
reproduce the exact supporting sentence from that chunk in `supporting_quote`. \
Copy it character for character. If you cannot point at the words, you do not \
make the claim.
2. If the chunks do not contain the answer, set `answerable` to false, leave \
`claims` empty, and write one sentence in `refusal_reason` naming what is \
missing. A refusal is a correct answer, not a failure.
3. You have no other knowledge. Do not use anything you know about billing \
systems, payment providers, SLAs, or error-code conventions. Do not infer, \
extrapolate, generalise, or fill gaps. There is no best-judgement fallback.
4. Never output an error code, menu path, command-line flag, timeframe, \
percentage or SLA that is not written verbatim in a chunk.
5. A chunk that is merely on the same topic is not an answer. If the chunks \
discuss the area but not the specific thing asked, refuse."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "refusal_reason": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "chunk_id": {"type": "string"},
                    "supporting_quote": {"type": "string"},
                },
                "required": ["claim", "chunk_id", "supporting_quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answerable", "refusal_reason", "claims"],
    "additionalProperties": False,
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def build_prompt(question: str, hits: list[dict]) -> str:
    blocks = []
    for h in hits:
        blocks.append(
            f"[chunk_id: {h['chunk_id']}]\n"
            f"[article: {h['meta'].get('article_id')} | "
            f"product_area: {h['meta'].get('product_area')} | "
            f"last_updated: {h['meta'].get('last_updated')}]\n"
            f"{h['text']}"
        )
    context = "\n\n---\n\n".join(blocks)
    return (f"CONTEXT CHUNKS\n\n{context}\n\n"
            f"---\n\nQUESTION: {question}\n\n"
            f"Answer under the rules. Cite chunk_id values exactly as given.")


def call_model(question: str, hits: list[dict]) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": build_prompt(question, hits)}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def verify(raw: dict, hits: list[dict]) -> dict:
    """Drop unverifiable claims in code. Refuse if nothing survives."""
    by_id = {h["chunk_id"]: h for h in hits}
    kept, rejected = [], []
    for c in raw.get("claims") or []:
        chunk = by_id.get(c.get("chunk_id", ""))
        if chunk is None:
            rejected.append({**c, "reason": "chunk_id not in retrieved set"})
            continue
        if _norm(c.get("supporting_quote", "")) not in _norm(chunk["text"]):
            rejected.append({**c, "reason": "quote not verbatim in cited chunk"})
            continue
        kept.append({
            "claim": c["claim"],
            "chunk_id": c["chunk_id"],
            "supporting_quote": c["supporting_quote"],
            "article_id": chunk["meta"].get("article_id"),
            "source_file": chunk["meta"].get("source_file"),
            "section": chunk["meta"].get("section", ""),
        })

    if not raw.get("answerable") or not kept:
        return {
            "answered": False,
            "refusal": (
                raw.get("refusal_reason")
                or "The indexed articles do not contain this information."
            ) if not raw.get("answerable") else
            "Every proposed claim failed verification against its cited chunk, "
            "so the answer was withheld.",
            "claims": [],
            "rejected_claims": rejected,
            "retrieved": [h["chunk_id"] for h in hits],
        }
    return {
        "answered": True,
        "claims": kept,
        "rejected_claims": rejected,
        "retrieved": [h["chunk_id"] for h in hits],
    }


def answer(index, question: str, k: int = 3, where: dict | None = None) -> dict:
    hits = index.search(question, k=k, where=where)
    if not hits:
        return {"answered": False, "refusal": "No chunks matched the filter.",
                "claims": [], "rejected_claims": [], "retrieved": []}
    return verify(call_model(question, hits), hits)


def api_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# --------------------------------------------------------------------------
# Deterministic extractive engine (no LLM).
#
# Used when no API key is configured. It emits claims by COPYING text out of a
# retrieved chunk, so a citation can never point at a claim the chunk does not
# contain -- the supporting_quote is the chunk's own bytes. It runs through the
# identical verify() gate as the model path.
#
# Refusal rule, applied before anything is emitted: every "anchor" term in the
# question -- a content term that is selective in this corpus (document
# frequency <= 20% of chunks, or absent entirely) -- must appear in the cited
# chunk. A chunk that is merely on the same topic does not clear this.
# --------------------------------------------------------------------------

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "from",
    "is", "are", "was", "were", "be", "been", "do", "does", "did", "what",
    "how", "why", "when", "who", "which", "that", "this", "it", "its", "i",
    "we", "our", "my", "you", "your", "they", "their", "at", "by", "with",
    "as", "after", "before", "during", "there", "here", "can", "should",
    "would", "will", "have", "has", "had", "get", "gets", "got", "mean",
    "means", "meaning", "fix", "fixes", "s", "if", "not", "no", "but",
    "about", "into", "out", "up", "down", "over", "under", "again", "then",
    "so", "than", "too", "very", "just", "now", "any", "some", "all", "one",
    "another", "look", "looks", "long", "much", "many", "still", "even",
}
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ions",
             "ion", "ies", "ed", "es", "ly", "s")
# Calibrated on the 11 questions in questions.json: answerable questions score
# 0.70-1.00, out-of-corpus questions 0.15-0.59. The floor sits in that gap.
# The margin is thin (0.59 vs 0.70) - see results.md.
COVERAGE_FLOOR = 0.65


def stem(token: str) -> str:
    if "-" in token or any(ch.isdigit() for ch in token):
        return token
    for suf in _SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 3:
            token = token[: -len(suf)]
            break
    return token[:-1] if token.endswith("e") and len(token) > 3 else token


def _stems(text: str) -> set[str]:
    from .embeddings import tokenize

    return {stem(t) for t in tokenize(text)}


def _units(chunk_text: str) -> list[str]:
    """Table rows stay whole; prose is split into sentences.

    The leading breadcrumb line the structure-aware chunker prepends is not a
    sentence and must not be glued onto the first one."""
    lines = chunk_text.splitlines()
    if lines and " > " in lines[0] and not lines[0].rstrip().endswith((".", "!", "?", "|")):
        lines = lines[1:]
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("|"):
            if not set(s.strip("| \n")) <= set("-: |"):
                out.append(s)
        else:
            out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", s) if p.strip())
    # rejoin prose sentences that markdown hard-wrapping split across lines
    merged, buf = [], ""
    for u in out:
        if u.startswith("|"):
            if buf:
                merged.append(buf.strip()); buf = ""
            merged.append(u)
        else:
            buf = f"{buf} {u}".strip()
            if buf.endswith((".", "!", "?")):
                merged.append(buf); buf = ""
    if buf:
        merged.append(buf.strip())
    return merged


def selective_terms(question: str) -> set[str]:
    return {s for s in _stems(question) if s not in STOPWORDS and len(s) > 2}


def term_idf(index) -> dict:
    docs = [_stems(r.text) for r in index.records]
    n = len(docs)

    def idf(term: str) -> float:
        df = sum(1 for d in docs if term in d)
        return math.log(1 + (n + 1) / (df + 0.5))

    return {"idf": idf, "docs": docs}


def coverage(question: str, hits: list[dict], index) -> tuple[float, list[str]]:
    """idf-weighted fraction of the question's selective terms that the
    retrieved chunks actually contain. Rare terms dominate, so a question
    hinging on a word the corpus never uses (refund, SLA, ERR-4099) scores
    near zero however topically close the retrieved text looks."""
    terms = selective_terms(question)
    if not terms:
        return 0.0, []
    idf = term_idf(index)["idf"]
    seen = set().union(*[_stems(h["text"]) for h in hits]) if hits else set()
    total = sum(idf(t) for t in terms)
    got = sum(idf(t) for t in terms if t in seen)
    uncovered = sorted((t for t in terms if t not in seen), key=lambda t: -idf(t))
    return (got / total if total else 0.0), uncovered


def extractive_engine(question: str, hits: list[dict], index) -> dict:
    score, uncovered = coverage(question, hits, index)
    if score < COVERAGE_FLOOR:
        return {
            "answerable": False,
            "claims": [],
            "refusal_reason": (
                f"The indexed articles do not cover this "
                f"(grounding coverage {score:.2f} < floor {COVERAGE_FLOOR:.2f}). "
                f"No retrieved chunk contains: {', '.join(uncovered[:4])}. "
                "The retrieved chunks are on the same topic but do not state "
                "the thing asked for."
            ),
        }

    terms = selective_terms(question)
    idf = term_idf(index)["idf"]
    best, best_units = None, []
    for h in hits:
        scored = []
        for u in _units(h["text"]):
            us = _stems(u)
            w = sum(idf(t) for t in terms if t in us)
            if w > 0:
                scored.append((w, u))
        scored.sort(key=lambda x: -x[0])
        if scored and (best is None or scored[0][0] > best_units[0][0]):
            best, best_units = h, scored
    if not best:
        return {"answerable": False, "claims": [],
                "refusal_reason": "No retrieved chunk contained the question terms."}

    return {
        "answerable": True,
        "refusal_reason": "",
        "claims": [{"claim": u, "chunk_id": best["chunk_id"],
                    "supporting_quote": u} for _, u in best_units[:3]],
    }


def answer_extractive(index, question: str, k: int = 3,
                      where: dict | None = None) -> dict:
    hits = index.search(question, k=k, where=where)
    if not hits:
        return {"answered": False, "refusal": "No chunks matched the filter.",
                "claims": [], "rejected_claims": [], "retrieved": []}
    return verify(extractive_engine(question, hits, index), hits)


def answer_auto(index, question: str, k: int = 3, where: dict | None = None):
    """Real model when credentials exist, deterministic extractor otherwise."""
    engine = "claude-opus-5" if api_key_present() else "extractive-deterministic"
    fn = answer if api_key_present() else answer_extractive
    return {**fn(index, question, k=k, where=where), "engine": engine}
