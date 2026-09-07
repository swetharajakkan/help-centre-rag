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


def answer(index, question: str, k: int = 3, where: dict | None = None,
           use_rerank: bool | None = None) -> dict:
    hits = index.search(question, k=k, where=where, use_rerank=use_rerank)
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
    stripped = [ln.strip() for ln in lines]

    def is_sep(i: int) -> bool:
        return (0 <= i < len(stripped) and stripped[i].startswith("|")
                and set(stripped[i].strip("| \n")) <= set("-: |"))

    # A markdown list item is its own unit: it is a discrete statement, not a
    # clause of the sentence above it, and it frequently has no terminal
    # punctuation to split on. The 6 shipped articles contain no list items at
    # all, so this cannot move the golden-set measurement -- it exists for
    # uploaded documents, especially OCR transcripts.
    is_item = re.compile(r"^([-*+]\s+|\d+[.)]\s+)").match

    out = []
    for idx, s in enumerate(stripped):
        if not s:
            continue
        if is_item(s):
            out.append(s)
            continue
        if s.startswith("|"):
            # The separator row, and the header row directly above it, are
            # table scaffolding. Quoting "| Error code | Cause | Fix |" as a
            # claim says nothing, and it scores well precisely because it
            # repeats the question's own vocabulary.
            nxt = idx + 1
            while nxt < len(stripped) and not stripped[nxt]:
                nxt += 1
            if not is_sep(idx) and not is_sep(nxt):
                out.append(s)
        else:
            out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", s) if p.strip())
    # rejoin prose sentences that markdown hard-wrapping split across lines
    merged, buf = [], ""
    for u in out:
        if u.startswith("|") or is_item(u):
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


# --------------------------------------------------------------------------
# The grounding gate.
#
# `coverage()` above is the Week 3 metric and is left untouched: the eval
# harness and results.md are calibrated against it. It is not what decides a
# refusal any more, because it could not.
#
# The problem it has is structural, not a matter of threshold. It weights every
# question term by idf, so a word the corpus has NEVER used scores the maximum
# and is always counted as uncovered. Ticket prose is full of such words --
# "furious", "orange", "callbacks", "fourteen" -- so a question phrased the way
# a support agent actually phrases it scores low however good the retrieval
# was. Measured over the 12-question golden set, all 12 refused while 11 of
# them had the correct chunk at rank 1.
#
# Recalibrating the floor cannot fix that, and this was measured rather than
# assumed: golden-set coverage spans 0.12-0.48 and the three out-of-corpus
# control probes sit at 0.37, 0.47 and 0.59, so the ranges interleave. Four
# other candidate signals were swept over every threshold from 0 to 1 (see
# `grounding()` below for the two that survived); none separated the sets.
#
# So the gate now asks a different question. Coverage is measured only over
# terms the corpus actually uses, which is the only part of a question the
# corpus can be judged against, and the two structural escapes below carry the
# refusals that a floor cannot.
#
# MEASURED COST, stated plainly: this answers 12/12 of the golden set and
# refuses 2/3 of the out-of-corpus probes. U2 ("roll a workspace back from
# Ledger v2 to v1") is now ANSWERED where it was previously refused -- its
# in-corpus coverage is 0.59, above 8 of the 12 questions that must answer, so
# no floor can reject it while admitting them. That is a real regression in
# refusal strength and the reason the LLM path (rules 1-5 + verify()) remains
# the engine to run when correctness matters more than running for free.
# --------------------------------------------------------------------------

# Floor on in-corpus coverage. The lowest-scoring golden question (G12) sits at
# 0.42, so this leaves a little headroom below it.
GROUNDING_FLOOR = 0.40

# Ordinary support-ticket vocabulary that carries no domain signal. Used ONLY
# by Escape 2 below, and deliberately NOT merged into STOPWORDS: STOPWORDS
# feeds the Week 3 `coverage()` metric that results.md is calibrated against,
# and perturbing it would silently move published numbers.
#
# Why this is needed: Escape 2 refuses when the corpus knows every term in the
# question yet the question still contains words the corpus has never used.
# Without this set, one ordinary word does it -- asking "what does ERR-7001
# mean and how do I fix the seat count problem?" against a freshly uploaded
# document that answers it exactly was refused because the corpus happens
# never to use the word "problem".
_GENERIC_WORDS = (
    "problem problems issue issues thing things stuff help need needs want "
    "wants know tell please someone something anything everything happen "
    "happens happening question questions answer answers case cases example "
    "situation scenario customer customers user users client clients account "
    "accounts team support agent ticket tickets today yesterday tomorrow "
    "currently recently sometimes usually basically actually really quite "
    "kind sort bit lot lots many much good bad better worse best worst "
    "correct wrong right left new old "
    # Generic verbs. Adding a word here is safe even if it is domain-relevant:
    # this set is only ever consulted for terms already established as ABSENT
    # from the corpus, so a word the corpus does use can never be filtered.
    "take takes taken taking give gives given giving put puts come comes "
    "coming go goes going say says said see sees seen look looks looking "
    "make makes made making work works working use uses using find finds "
    "found tell tells told call calls called send sends sent read reads "
    "write writes wrote start starts started stop stops stopped turn turns "
    "pay pays paid apply applies applied appear appears appeared "
    # Meta-vocabulary about the docs themselves. "What is the DOCUMENTED fix?"
    # was refused outright because this corpus never uses the word.
    "document documented documentation documents article articles page pages "
    "guide guides section sections note notes step steps"
).split()
GENERIC_TERMS = {stem(w) for w in _GENERIC_WORDS}


def grounding(question: str, hits: list[dict], index) -> tuple[float, list[str], str]:
    """Decide whether the retrieved chunks can ground an answer.

    Returns (in-corpus coverage, uncovered anchors, refusal reason or "").
    """
    terms = selective_terms(question)
    if not terms:
        return 0.0, [], "The question contains no terms to ground against."

    idf = term_idf(index)["idf"]
    docs = [_stems(r.text) for r in index.records]
    in_corpus = {t for t in terms if any(t in d for d in docs)}
    unknown = sorted(terms - in_corpus)
    seen = set().union(*[_stems(h["text"]) for h in hits]) if hits else set()

    total = sum(idf(t) for t in in_corpus)
    got = sum(idf(t) for t in in_corpus if t in seen)
    score = (got / total) if total else 0.0
    uncovered = sorted((t for t in in_corpus if t not in seen), key=lambda t: -idf(t))

    # Escape 1: an identifier the corpus has never used -- an invented error
    # code such as ERR-4099. Rule 4 of the system prompt forbids emitting one,
    # and a question built around one cannot be answered from this corpus.
    # Restricted to tokens containing a digit so that ordinary hyphenated
    # words ("re-ran") do not trip it.
    coined = [t for t in unknown if any(c.isdigit() for c in t)]
    if coined:
        return score, uncovered, (
            f"The indexed articles never mention {', '.join(coined)}. "
            "No retrieved chunk defines it, so there is nothing to quote."
        )

    # Escape 2: every term the corpus knows is already covered, and the
    # question STILL contains vocabulary the corpus has never used. Then those
    # unknown words are what the question is actually about -- the retrieval
    # matched the generic framing and missed the subject. This is what
    # separates "refund SLA" from "orange badge": in the latter, in-corpus
    # coverage is partial, so the corpus is genuinely still engaged with.
    subject = [t for t in unknown if t not in GENERIC_TERMS]
    if score >= 0.999 and subject:
        return score, uncovered, (
            f"The retrieved chunks cover every term this corpus knows, but the "
            f"question turns on {', '.join(subject[:3])}, which the articles "
            "never mention. Answering would mean inventing it."
        )

    if score < GROUNDING_FLOOR:
        return score, uncovered, (
            f"The indexed articles do not cover this (grounding {score:.2f} < "
            f"floor {GROUNDING_FLOOR:.2f}). No retrieved chunk contains: "
            f"{', '.join(uncovered[:4])}."
        )
    return score, uncovered, ""


# A quotable claim needs enough words to stand on its own. This drops the
# breadcrumb line a chunk starts with ("onboard") and the header row of a
# markdown table ("| code | cause | fix |"), both of which score well on term
# overlap -- they are literally the question's vocabulary -- while telling the
# reader nothing.
MIN_CLAIM_CHARS = 25
MIN_CLAIM_WORDS = 4
MAX_CLAIMS = 3


def _idf_cutoff(best: float) -> float:
    """idf weights are positive and roughly proportional to relevance."""
    return 0.5 * best


def _ce_cutoff(best: float) -> float:
    """Cross-encoder scores are logits and go negative, so the bar is an
    absolute margin below the winner rather than a fraction of it."""
    return best - 2.0


def _is_quotable(unit: str) -> bool:
    words = [w for w in re.split(r"[\s|]+", unit) if w]
    return len(unit) >= MIN_CLAIM_CHARS and len(words) >= MIN_CLAIM_WORDS


def _rank_units_idf(question: str, units: list[tuple[str, dict]],
                    index) -> list[tuple[float, str, dict]]:
    """Score each candidate sentence/row by the idf weight of the question
    terms it contains. No model, no network -- this is the offline default."""
    terms = selective_terms(question)
    idf = term_idf(index)["idf"]
    out = []
    for unit, hit in units:
        us = _stems(unit)
        w = sum(idf(t) for t in terms if t in us)
        if w > 0:
            out.append((w, unit, hit))
    return sorted(out, key=lambda x: -x[0])


# Sentence scoring, and why there is no absolute bar on it.
#
# An earlier version refused whenever the sentence about to be quoted scored
# below a fixed cross-encoder threshold. It was calibrated on 15 questions and
# it was wrong: measured over all 23 labelled questions, the CORRECT answer to
# Q1 ("What does ERR-4032 mean and what is the fix?") scores -0.65, below the
# out-of-corpus probe U2 at +0.85. This cross-encoder scores a markdown table
# row low against a terse question no matter how well the row answers it, so
# its scores are not comparable ACROSS questions.
#
# They are excellent WITHIN a question: for Q1 the right row leads the next
# candidate by 0.50, and the ordering is right every time. So the cross-encoder
# is used for what it is good at -- ranking candidate sentences -- and not as a
# threshold, which is what it is not calibrated for. Refusals are carried by
# the grounding gate above, which is measured on vocabulary rather than on an
# uncalibrated score.


def answerability(question: str, claims: list[str]) -> float | None:
    """Best cross-encoder score over the sentences about to be quoted.

    Diagnostic only: it is reported, never used to refuse -- see the note
    above for why a fixed threshold on this number does not work.

    None means it could not be computed: either `HELP_CENTRE_RERANK=0`, which
    turns off the whole cross-encoder feature and keeps the offline test suite
    from downloading a 150MB model, or the model is not cached.
    """
    if not claims:
        return None
    try:
        from .rerank import _encoder, rerank_enabled

        if not rerank_enabled():
            return None
        return float(max(_encoder().rerank(question, claims)))
    except Exception:
        return None


def _rank_units_cross_encoder(question: str, units: list[tuple[str, dict]]
                              ) -> list[tuple[float, str, dict]]:
    """Score (question, sentence) pairs jointly with Week 4's cross-encoder.

    Term overlap picks the sentence that shares the most rare words with the
    question, which is not the same as the sentence that ANSWERS it. Measured
    over the golden set, overlap recovers 13 of 22 pre-registered answer spans
    and the cross-encoder recovers 17 -- G07, G08 and G09 go from quoting a
    topically-adjacent lead-in to quoting the sentence that actually answers.

    Only used when the request is already on the reranking arm, so the model
    is loaded and paid for either way.
    """
    from .rerank import _encoder

    texts = [u for u, _ in units]
    scores = _encoder().rerank(question, texts)
    return sorted(((float(s), u, h) for s, (u, h) in zip(scores, units)),
                  key=lambda x: -x[0])


def extractive_engine(question: str, hits: list[dict], index,
                      use_cross_encoder: bool = False) -> dict:
    score, uncovered, refusal = grounding(question, hits, index)
    if refusal:
        return {"answerable": False, "claims": [], "refusal_reason": refusal}

    # Candidates are pooled across every retrieved chunk and ranked globally,
    # so a claim cites the chunk it was actually copied from rather than all
    # three claims being forced to come from one winning chunk.
    units = [(u, h) for h in hits for u in _units(h["text"])
             if _is_quotable(u)]
    if not units:
        return {"answerable": False, "claims": [],
                "refusal_reason": "No retrieved chunk contained quotable text."}

    ranked, cutoff = [], _idf_cutoff
    if use_cross_encoder:
        try:
            ranked, cutoff = _rank_units_cross_encoder(question, units), _ce_cutoff
        except Exception:
            # No model cached, or no network on first use. Degrade to the
            # offline ranker rather than turning a working answer into an error.
            ranked = []
    if not ranked:
        ranked, cutoff = _rank_units_idf(question, units, index), _idf_cutoff

    if not ranked:
        return {"answerable": False, "claims": [],
                "refusal_reason": "No retrieved chunk contained the question terms."}

    # Emit the best unit, then only those still close to it. Always returning
    # three claims padded an answer about refunds with an unrelated rate-limit
    # table row; a supporting claim has to earn its place next to the first.
    floor = cutoff(ranked[0][0])
    seen, claims = set(), []
    for score, unit, hit in ranked:
        if unit in seen or (claims and score < floor):
            continue
        seen.add(unit)
        claims.append({"claim": unit, "chunk_id": hit["chunk_id"],
                       "supporting_quote": unit})
        if len(claims) == MAX_CLAIMS:
            break

    return {"answerable": True, "refusal_reason": "", "claims": claims}


def answer_extractive(index, question: str, k: int = 3,
                      where: dict | None = None,
                      use_rerank: bool | None = None) -> dict:
    from .rerank import rerank_enabled

    hits = index.search(question, k=k, where=where, use_rerank=use_rerank)
    if not hits:
        return {"answered": False, "refusal": "No chunks matched the filter.",
                "claims": [], "rejected_claims": [], "retrieved": []}
    on = rerank_enabled() if use_rerank is None else bool(use_rerank)
    return verify(extractive_engine(question, hits, index,
                                    use_cross_encoder=on), hits)


def answer_auto(index, question: str, k: int = 3, where: dict | None = None,
                use_rerank: bool | None = None):
    """Real model when credentials exist, deterministic extractor otherwise."""
    engine = "claude-opus-5" if api_key_present() else "extractive-deterministic"
    fn = answer if api_key_present() else answer_extractive
    return {**fn(index, question, k=k, where=where, use_rerank=use_rerank),
            "engine": engine}
