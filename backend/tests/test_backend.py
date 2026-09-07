"""End-to-end verification that the help-centre backend works.

Organised module by module, bottom up:

    TestChunkers      the two chunking strategies and their invariants
    TestIngest        chunk ids, required metadata, fail-loud validation
    TestEmbeddings    tokeniser, BM25, min-max normalisation
    TestIndex         hybrid search, metadata filtering, persistence
    TestVerification  verify() drops claims it cannot ground
    TestGeneration    the deterministic extractive engine: answers and refusals
    TestApi           every HTTP endpoint, including citation resolution

Run from the repo root:  pytest backend/tests -q
See conftest.py for what is stubbed (embeddings, API key, data dir).
"""
from __future__ import annotations

import json
import os
import re

import numpy as np
import pytest

from backend.app import chunkers, generation, ocr, store, uploads
from backend.app.chunkers import (
    FIXED_WINDOW_CHARS,
    STRUCTURE_TABLE_BUDGET,
    fixed_window,
    split_frontmatter,
    structure_aware,
)
from backend.app.embeddings import Bm25, minmax, tokenize
from backend.app.ingest import CHUNKERS, REQUIRED_META, build_index, validate
from backend.app.store import Index, Record
from backend.tests.conftest import EVAL_DIR, REAL_EMBED

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

CHUNK_ID_RE = re.compile(r"^(fixed_window|structure_aware)::[^:]+\.md::\d{3}$")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def is_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def is_separator(line: str) -> bool:
    return is_row(line) and set(line.strip("| \n")) <= set("-: |")


def table_pairs(body: str) -> list[tuple[str, str]]:
    """(header row, data row) for every data row of every markdown table.

    Deliberately re-detected here rather than reusing chunkers._blocks, so the
    table invariant is checked against an independent reading of the source.
    """
    lines = body.splitlines()
    pairs = []
    for i, line in enumerate(lines):
        if not (is_row(line) and i + 1 < len(lines) and is_separator(lines[i + 1])):
            continue
        j = i + 2
        while j < len(lines) and is_row(lines[j]):
            pairs.append((line.strip(), lines[j].strip()))
            j += 1
    return pairs


LONG_TABLE_DOC = "# Codes\n\n## Troubleshooting\n\n" + "\n".join(
    ["| Code | Meaning | Fix |", "| --- | --- | --- |"]
    + [f"| ERR-{4000 + n} | meaning number {n} of the legacy vault | "
       f"do remediation step {n} then re-run the migration for that workspace |"
       for n in range(40)]
)


# --------------------------------------------------------------------------
class TestChunkers:
    def test_split_frontmatter_parses_keys_and_returns_body(self):
        meta, body = split_frontmatter(
            "---\narticle_id: BM-001\nproduct_area: billing\n---\n# Title\n\nText.\n"
        )
        assert meta == {"article_id": "BM-001", "product_area": "billing"}
        assert body.startswith("# Title")

    def test_split_frontmatter_passes_through_when_absent(self):
        raw = "# No frontmatter\n\nBody.\n"
        assert split_frontmatter(raw) == ({}, raw)

    def test_every_article_has_frontmatter(self, articles):
        for source_file, front, body in articles:
            assert front, f"{source_file} has no frontmatter"
            assert body.strip(), f"{source_file} has an empty body"

    # -- fixed_window ------------------------------------------------------
    def test_fixed_window_respects_the_window_size(self, articles):
        for source_file, _, body in articles:
            for chunk in fixed_window(body, source_file):
                assert 0 < len(chunk.text) <= FIXED_WINDOW_CHARS

    def test_fixed_window_ordinals_are_sequential_from_zero(self, articles):
        for source_file, _, body in articles:
            ordinals = [c.ordinal for c in fixed_window(body, source_file)]
            assert ordinals == list(range(len(ordinals)))
            assert ordinals, f"{source_file} produced no chunks"

    def test_fixed_window_loses_no_words(self, articles):
        """Overlapping windows must cover the body, not skip past it."""
        for source_file, _, body in articles:
            covered = " ".join(c.text for c in fixed_window(body, source_file))
            covered_words = set(covered.split())
            missing = [w for w in body.split() if w not in covered_words]
            assert not missing, f"{source_file} dropped {missing[:5]}"

    def test_fixed_window_closes_on_a_whole_word(self, articles):
        """`_cut_at_whitespace` guarantees the trailing edge only."""
        for source_file, _, body in articles:
            words = set(body.split())
            for chunk in fixed_window(body, source_file):
                parts = chunk.text.split()
                if parts:
                    assert parts[-1] in words, chunk.text[-40:]

    def test_fixed_window_opens_mid_word_after_the_overlap_rewind(self, articles):
        """Documents a real wart: the next window starts at `end - overlap`,
        which is not re-aligned to whitespace, so every chunk after the first
        can begin with a word fragment ("ngines"). Nothing is lost — the whole
        word is in the preceding chunk — but the fragment is what gets embedded
        and BM25-tokenised. `structure_aware` has no equivalent edge."""
        fragments = []
        for source_file, _, body in articles:
            words = set(body.split())
            for chunk in fixed_window(body, source_file):
                parts = chunk.text.split()
                if parts and parts[0] not in words:
                    fragments.append((source_file, parts[0]))
        assert fragments, "overlap rewind unexpectedly landed on a boundary"

    def test_fixed_window_orphans_table_rows(self):
        """The motivating defect: a window longer than the budget emits rows
        whose header row is nowhere in the same chunk."""
        chunks = list(fixed_window(LONG_TABLE_DOC, "codes.md"))
        assert len(chunks) > 1
        orphans = [
            c for c in chunks
            if any(is_row(l) and not is_separator(l) for l in c.text.splitlines())
            and "| Code | Meaning | Fix |" not in c.text
        ]
        assert orphans, "expected fixed_window to separate rows from their header"

    # -- structure_aware ---------------------------------------------------
    def test_structure_aware_produces_chunks_for_every_article(self, articles):
        for source_file, _, body in articles:
            chunks = list(structure_aware(body, source_file))
            assert chunks, f"{source_file} produced no structure-aware chunks"
            assert [c.ordinal for c in chunks] == list(range(len(chunks)))
            assert all(c.strategy == "structure_aware" for c in chunks)
            assert all(c.meta["block_type"] in ("prose", "table") for c in chunks)

    def test_every_table_chunk_is_a_valid_standalone_table(self, articles):
        """Hard invariant: header row, then separator, then >=1 data row."""
        for source_file, _, body in articles:
            for chunk in structure_aware(body, source_file):
                if chunk.meta["block_type"] != "table":
                    continue
                lines = [l for l in chunk.text.splitlines() if l.strip()]
                rows = lines[next(i for i, l in enumerate(lines) if is_row(l)):]
                assert is_row(rows[0]) and not is_separator(rows[0]), chunk.text
                assert is_separator(rows[1]), chunk.text
                assert len(rows) >= 3, f"table chunk with no data row:\n{chunk.text}"
                assert all(is_row(r) for r in rows[2:]), chunk.text

    def test_no_table_row_is_ever_separated_from_its_header(self, articles):
        for source_file, _, body in articles:
            pairs = table_pairs(body)
            assert pairs, f"{source_file} was expected to contain a table"
            texts = [c.text for c in structure_aware(body, source_file)]
            for header, row in pairs:
                assert any(header in t and row in t for t in texts), (
                    f"{source_file}: row {row[:60]!r} lost its header"
                )

    def test_structure_aware_never_splits_a_paragraph(self, articles):
        for source_file, _, body in articles:
            texts = [c.text for c in structure_aware(body, source_file)]
            for _, _, lines in chunkers._sections(body):
                for kind, payload in chunkers._blocks(lines):
                    if kind != "prose":
                        continue
                    for para in re.split(r"\n\s*\n", payload):
                        para = para.strip()
                        if para:
                            assert any(para in t for t in texts), (
                                f"{source_file}: paragraph split {para[:60]!r}"
                            )

    def test_chunks_carry_their_section_breadcrumb(self, articles):
        for source_file, _, body in articles:
            for chunk in structure_aware(body, source_file):
                assert chunk.meta["section"], f"{source_file}: chunk with no section"

    def test_long_table_is_split_but_each_part_keeps_the_header(self):
        chunks = list(structure_aware(LONG_TABLE_DOC, "codes.md"))
        tables = [c for c in chunks if c.meta["block_type"] == "table"]
        assert len(tables) > 1, "a 40-row table should exceed one table chunk"
        for chunk in tables:
            assert "| Code | Meaning | Fix |" in chunk.text
            assert "| --- | --- | --- |" in chunk.text
        emitted = {l.strip() for c in tables for l in c.text.splitlines()}
        for _, row in table_pairs(LONG_TABLE_DOC):
            assert row in emitted, f"row dropped entirely: {row[:50]}"

    def test_table_chunk_budget_is_only_exceeded_by_one_row(self):
        for chunk in structure_aware(LONG_TABLE_DOC, "codes.md"):
            if chunk.meta["block_type"] != "table":
                continue
            rows = [l for l in chunk.text.splitlines() if is_row(l)][2:]
            if len(rows) > 1:
                without_last = len(chunk.text) - len(rows[-1])
                assert without_last <= STRUCTURE_TABLE_BUDGET + len(rows[-1])


# --------------------------------------------------------------------------
class TestIngest:
    def test_six_articles_are_indexed(self, articles):
        assert len(articles) == 6

    def test_both_strategies_are_registered(self):
        assert set(CHUNKERS) == {"fixed_window", "structure_aware"}

    @pytest.mark.parametrize("strategy", ["fixed_window", "structure_aware"])
    def test_records_carry_all_required_metadata(self, strategy, request):
        index = request.getfixturevalue(
            "fixed_index" if strategy == "fixed_window" else "structure_index")
        assert index.records
        for rec in index.records:
            missing = [f for f in REQUIRED_META if not rec.meta.get(f)]
            assert not missing, f"{rec.chunk_id} missing {missing}"
            assert rec.meta["source_file"] == rec.source_file
            assert rec.text.strip()

    @pytest.mark.parametrize("strategy", ["fixed_window", "structure_aware"])
    def test_chunk_ids_are_well_formed_and_unique(self, strategy, request):
        index = request.getfixturevalue(
            "fixed_index" if strategy == "fixed_window" else "structure_index")
        ids = [r.chunk_id for r in index.records]
        assert len(ids) == len(set(ids))
        for chunk_id in ids:
            assert CHUNK_ID_RE.match(chunk_id), chunk_id
            assert chunk_id.startswith(f"{strategy}::")

    def test_article_ids_look_like_the_corpus(self, structure_index):
        article_ids = {r.meta["article_id"] for r in structure_index.records}
        assert article_ids == {f"BM-00{n}" for n in range(1, 7)}

    def test_validate_rejects_a_chunk_with_no_provenance(self):
        bad = Record(chunk_id="x::y::000", text="t", source_file="y",
                     meta={"source_file": "y", "article_id": "BM-001",
                           "product_area": "", "last_updated": "2026-07-14"})
        with pytest.raises(ValueError, match="product_area"):
            validate([bad])

    def test_validate_accepts_a_complete_chunk(self):
        good = Record(chunk_id="x::y::000", text="t", source_file="y",
                      meta={f: "v" for f in REQUIRED_META})
        validate([good])  # must not raise

    def test_build_index_only_reads_the_directory_it_is_given(self, tmp_path):
        (tmp_path / "solo.md").write_text(
            "---\narticle_id: T-1\nproduct_area: testing\n"
            "last_updated: 2026-01-01\n---\n# Solo\n\n## S\n\nOne paragraph.\n"
        )
        index = build_index("structure_aware", corpus_dir=str(tmp_path))
        assert index.records
        assert {r.source_file for r in index.records} == {"solo.md"}
        assert {r.meta["product_area"] for r in index.records} == {"testing"}


# --------------------------------------------------------------------------
class TestEmbeddings:
    def test_tokenize_lowercases_and_keeps_error_codes_whole(self):
        assert tokenize("Fix ERR-4032 now") == ["fix", "err-4032", "now"]

    def test_tokenize_drops_punctuation(self):
        assert tokenize("Settings > Billing, then Advanced.") == [
            "settings", "billing", "then", "advanced"]

    def test_minmax_maps_to_unit_range(self):
        out = minmax(np.array([2.0, 4.0, 6.0], dtype=np.float32))
        assert out.min() == pytest.approx(0.0) and out.max() == pytest.approx(1.0)

    def test_minmax_of_a_constant_vector_is_zero_not_nan(self):
        out = minmax(np.array([3.0, 3.0, 3.0], dtype=np.float32))
        assert np.all(out == 0.0)

    def test_minmax_of_empty_is_empty(self):
        assert minmax(np.array([], dtype=np.float32)).size == 0

    def test_bm25_ranks_the_document_containing_the_term_first(self):
        bm25 = Bm25([tokenize("the payment token was issued by the legacy vault"),
                     tokenize("tax identifier revalidation failed for the customer"),
                     tokenize("nothing relevant at all here")])
        scores = bm25.scores("legacy vault token")
        assert int(np.argmax(scores)) == 0
        assert scores[2] == 0.0

    def test_bm25_ignores_terms_absent_from_the_corpus(self):
        bm25 = Bm25([tokenize("alpha beta"), tokenize("beta gamma")])
        assert np.all(bm25.scores("err-4099") == 0.0)

    def test_bm25_rewards_rare_terms_over_common_ones(self):
        docs = [tokenize("common word here")] * 9 + [tokenize("common word unicorn")]
        bm25 = Bm25(docs)
        assert bm25.scores("unicorn")[9] > bm25.scores("common")[9]


# --------------------------------------------------------------------------
class TestIndex:
    def test_search_on_an_empty_index_returns_nothing(self):
        assert Index("empty").search("anything") == []

    @pytest.mark.parametrize("k", [1, 3, 5])
    def test_search_returns_k_ranked_hits(self, structure_index, k):
        hits = structure_index.search("dual-write phase minimum", k=k)
        assert len(hits) == k
        assert [h["rank"] for h in hits] == list(range(1, k + 1))
        scores = [h["score"] for h in hits]
        assert scores == sorted(scores, reverse=True)

    def test_hits_expose_both_score_components_and_metadata(self, structure_index):
        hit = structure_index.search("ERR-4032 payment token", k=1)[0]
        assert {"chunk_id", "score", "dense", "bm25", "source_file", "text",
                "meta"} <= set(hit)
        assert hit["meta"]["article_id"]
        assert hit["source_file"].endswith(".md")

    def test_lexical_signal_finds_a_verbatim_error_code(self, structure_index):
        hits = structure_index.search("What does ERR-4032 mean?", k=5)
        assert any("ERR-4032" in h["text"] for h in hits)

    def test_search_never_returns_more_than_the_corpus_holds(self, structure_index):
        assert len(structure_index.search("billing", k=10_000)) == len(
            structure_index.records)

    def test_filter_restricts_results_to_the_matching_area(self, structure_index):
        area = structure_index.records[0].meta["product_area"]
        hits = structure_index.search("migration", k=5, where={"product_area": area})
        assert hits
        assert all(h["meta"]["product_area"] == area for h in hits)

    def test_filter_that_matches_nothing_returns_nothing(self, structure_index):
        assert structure_index.search(
            "migration", k=5, where={"product_area": "no-such-area"}) == []

    def test_filter_is_applied_before_ranking_not_after(self, structure_index):
        """Scores are renormalised over the filtered subset, so a filtered
        search can surface chunks that the unfiltered top-k never reached."""
        area = structure_index.records[0].meta["product_area"]
        unfiltered = {h["chunk_id"] for h in structure_index.search("invoice", k=3)}
        filtered = structure_index.search(
            "invoice", k=3, where={"product_area": area})
        assert len(filtered) == 3
        assert filtered[0]["score"] == pytest.approx(
            max(h["score"] for h in filtered))
        assert unfiltered  # both ran; filtered set is drawn from the subset only
        assert all(h["meta"]["product_area"] == area for h in filtered)

    def test_get_resolves_a_known_chunk_id(self, structure_index):
        chunk_id = structure_index.records[3].chunk_id
        assert structure_index.get(chunk_id).chunk_id == chunk_id

    def test_get_returns_none_for_an_unknown_chunk_id(self, structure_index):
        assert structure_index.get("structure_aware::nope.md::999") is None

    def test_every_searched_chunk_id_resolves(self, structure_index):
        for hit in structure_index.search("cutover phases", k=5):
            assert structure_index.get(hit["chunk_id"]) is not None

    def test_save_writes_the_records_as_json(self, structure_index):
        structure_index.save()
        path = os.path.join(store.DATA_DIR, "structure_aware.json")
        with open(path) as fh:
            rows = json.load(fh)
        assert len(rows) == len(structure_index.records)
        assert set(rows[0]) == {"chunk_id", "text", "source_file", "meta"}

    def test_the_two_strategies_produce_different_chunkings(
            self, fixed_index, structure_index):
        assert len(fixed_index.records) != len(structure_index.records)


# --------------------------------------------------------------------------
class TestVerification:
    HITS = [
        {"chunk_id": "structure_aware::a.md::000",
         "text": "A workspace stays in Phase 2 for a minimum of seven days.",
         "meta": {"article_id": "BM-001", "source_file": "a.md",
                  "product_area": "billing", "section": "Cutover phases"}},
        {"chunk_id": "structure_aware::a.md::001",
         "text": "Phase 3 disables Ledger v1 writes entirely.",
         "meta": {"article_id": "BM-001", "source_file": "a.md",
                  "product_area": "billing", "section": "Cutover phases"}},
    ]

    def test_a_verbatim_quote_is_kept_and_attributed(self):
        out = generation.verify({
            "answerable": True, "refusal_reason": "",
            "claims": [{"claim": "Minimum seven days.",
                        "chunk_id": "structure_aware::a.md::000",
                        "supporting_quote": "a minimum of seven days"}],
        }, self.HITS)
        assert out["answered"] is True
        assert out["rejected_claims"] == []
        claim = out["claims"][0]
        assert claim["article_id"] == "BM-001"
        assert claim["source_file"] == "a.md"
        assert claim["section"] == "Cutover phases"
        assert out["retrieved"] == [h["chunk_id"] for h in self.HITS]

    def test_quote_matching_ignores_whitespace_and_case(self):
        out = generation.verify({
            "answerable": True, "refusal_reason": "",
            "claims": [{"claim": "c", "chunk_id": "structure_aware::a.md::000",
                        "supporting_quote": "A MINIMUM\n  of   seven days"}],
        }, self.HITS)
        assert out["answered"] is True

    def test_a_quote_that_is_not_in_the_chunk_is_dropped(self):
        out = generation.verify({
            "answerable": True, "refusal_reason": "",
            "claims": [{"claim": "Support can waive it.",
                        "chunk_id": "structure_aware::a.md::000",
                        "supporting_quote": "support may waive the floor"}],
        }, self.HITS)
        assert out["answered"] is False
        assert out["claims"] == []
        assert out["rejected_claims"][0]["reason"] == "quote not verbatim in cited chunk"
        assert "failed verification" in out["refusal"]

    def test_a_citation_outside_the_retrieved_set_is_dropped(self):
        out = generation.verify({
            "answerable": True, "refusal_reason": "",
            "claims": [{"claim": "c", "chunk_id": "structure_aware::zzz.md::042",
                        "supporting_quote": "a minimum of seven days"}],
        }, self.HITS)
        assert out["answered"] is False
        assert out["rejected_claims"][0]["reason"] == "chunk_id not in retrieved set"

    def test_a_good_claim_survives_alongside_a_bad_one(self):
        out = generation.verify({
            "answerable": True, "refusal_reason": "",
            "claims": [
                {"claim": "good", "chunk_id": "structure_aware::a.md::001",
                 "supporting_quote": "disables Ledger v1 writes entirely"},
                {"claim": "bad", "chunk_id": "structure_aware::a.md::001",
                 "supporting_quote": "rolls the workspace back to v1"},
            ],
        }, self.HITS)
        assert out["answered"] is True
        assert [c["claim"] for c in out["claims"]] == ["good"]
        assert [c["claim"] for c in out["rejected_claims"]] == ["bad"]

    def test_a_declared_refusal_is_passed_through_with_its_reason(self):
        out = generation.verify(
            {"answerable": False, "refusal_reason": "No article states a refund SLA.",
             "claims": []}, self.HITS)
        assert out["answered"] is False
        assert out["refusal"] == "No article states a refund SLA."

    def test_refusal_without_a_reason_gets_a_default(self):
        out = generation.verify(
            {"answerable": False, "refusal_reason": "", "claims": []}, self.HITS)
        assert out["answered"] is False
        assert out["refusal"]

    def test_build_prompt_labels_every_chunk_with_its_provenance(self):
        prompt = generation.build_prompt("How long is phase 2?", self.HITS)
        for hit in self.HITS:
            assert f"[chunk_id: {hit['chunk_id']}]" in prompt
            assert hit["text"] in prompt
        assert "product_area: billing" in prompt
        assert "QUESTION: How long is phase 2?" in prompt


# --------------------------------------------------------------------------
class TestGeneration:
    def test_the_suite_runs_the_deterministic_engine(self):
        assert generation.api_key_present() is False

    def test_units_keep_table_rows_whole_and_drop_the_breadcrumb(self):
        text = ("Payment errors > Troubleshooting\n\n"
                "| Code | Fix |\n| --- | --- |\n"
                "| ERR-4032 | Re-add the payment method. Then retry |")
        units = generation._units(text)
        assert "Payment errors > Troubleshooting" not in units
        assert "| --- | --- |" not in units
        assert "| ERR-4032 | Re-add the payment method. Then retry |" in units

    def test_units_split_prose_into_sentences(self):
        units = generation._units("First sentence here. Second sentence here.")
        assert units == ["First sentence here.", "Second sentence here."]

    def test_units_rejoin_a_hard_wrapped_sentence(self):
        units = generation._units("A sentence that markdown\nwrapped across lines.")
        assert units == ["A sentence that markdown wrapped across lines."]

    def test_selective_terms_drop_stopwords(self):
        terms = generation.selective_terms("What does ERR-4032 mean and how do I fix it?")
        assert "err-4032" in terms
        assert not {"what", "does", "and", "how", "fix"} & terms

    def test_stem_leaves_codes_alone(self):
        assert generation.stem("err-4032") == "err-4032"
        assert generation.stem("migrations") == generation.stem("migration")

    def test_coverage_is_high_for_a_question_the_corpus_answers(
            self, structure_index):
        question = "What does ERR-4032 mean and what is the fix?"
        hits = structure_index.search(question, k=5)
        score, uncovered = generation.coverage(question, hits, structure_index)
        assert score >= generation.COVERAGE_FLOOR, uncovered

    def test_coverage_is_low_for_a_question_the_corpus_never_addresses(
            self, structure_index):
        question = "What is the refund SLA for a disputed invoice during the migration?"
        hits = structure_index.search(question, k=5)
        score, uncovered = generation.coverage(question, hits, structure_index)
        assert score < generation.COVERAGE_FLOOR
        assert uncovered

    def test_an_answer_is_always_fully_attributed(
            self, structure_index, questions):
        """Whatever the engine chooses to answer, every claim it emits must
        cite a retrieved chunk and quote it verbatim."""
        for qid in questions["generation_answerable"]:
            spec = next(q for q in questions["questions"] if q["id"] == qid)
            out = generation.answer_auto(structure_index, spec["question"], k=5)
            assert out["engine"] == "extractive-deterministic"
            for claim in out["claims"]:
                assert claim["chunk_id"] in out["retrieved"]
                rec = structure_index.get(claim["chunk_id"])
                assert rec is not None
                assert norm(claim["supporting_quote"]) in norm(rec.text)
                assert claim["article_id"] and claim["source_file"]

    def test_a_coined_error_code_is_refused_whatever_was_retrieved(
            self, structure_index, questions):
        """U3's escape is the only refusal that does not depend on retrieval:
        ERR-4099 is absent from the corpus, so no set of chunks can define it.
        That makes it the one refusal this stubbed-embedder suite can assert.

        U1's refusal depends on the real scorer putting the right chunks in
        front of the gate, so it lives in TestShippedCalibration instead."""
        spec = next(q for q in questions["generation_unanswerable"]
                    if q["id"] == "U3")
        for k in (3, 5):
            out = generation.answer_auto(structure_index, spec["question"], k=k)
            assert out["answered"] is False, f"U3 should be refused at k={k}"
            assert out["claims"] == []
            assert "err-4099" in out["refusal"].lower()

    def test_u2_is_the_known_gap_in_the_grounding_gate(
            self, structure_index, questions):
        """U2 ("roll a workspace back from Ledger v2 to v1") is ANSWERED.

        This is a deliberate, measured regression, not an oversight. Its
        in-corpus coverage is 0.59, above 8 of the 12 golden-set questions that
        must answer, so no floor rejects it while admitting them; a sweep of
        five candidate signals over every threshold found no separator. Pinned
        here so that if a future change fixes it, this test fails loudly and
        the fix gets recorded rather than passing unnoticed."""
        spec = next(q for q in questions["generation_unanswerable"]
                    if q["id"] == "U2")
        out = generation.answer_auto(structure_index, spec["question"], k=3)
        assert out["answered"] is True, (
            "U2 now refuses -- the grounding gate improved. Update this test, "
            "results_week4.md and frontend/UI.md to claim 3/3 refusals."
        )

    def test_the_refusal_names_what_is_missing(self, structure_index):
        out = generation.answer_auto(
            structure_index, "What does error ERR-4099 mean and how do I fix it?",
            k=5)
        assert out["answered"] is False
        assert "err-4099" in out["refusal"].lower()

    def test_every_claim_for_every_question_is_verifiable(
            self, structure_index, questions):
        """The citation audit, over all 8 pre-registered questions."""
        for spec in questions["questions"]:
            out = generation.answer_extractive(
                structure_index, spec["question"], k=5)
            for claim in out["claims"]:
                rec = structure_index.get(claim["chunk_id"])
                assert rec is not None, claim["chunk_id"]
                assert norm(claim["supporting_quote"]) in norm(rec.text)

    def test_a_filter_that_matches_nothing_refuses_rather_than_guesses(
            self, structure_index):
        out = generation.answer_auto(
            structure_index, "What does ERR-4032 mean?", k=3,
            where={"product_area": "no-such-area"})
        assert out["answered"] is False
        assert out["refusal"] == "No chunks matched the filter."
        assert out["retrieved"] == []

    def test_answer_auto_reports_the_model_engine_when_a_key_is_present(
            self, structure_index, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert generation.api_key_present() is True
        called = {}

        def fake_call_model(question, hits):
            called["hits"] = hits
            return {"answerable": True, "refusal_reason": "",
                    "claims": [{"claim": hits[0]["text"][:40],
                                "chunk_id": hits[0]["chunk_id"],
                                "supporting_quote": hits[0]["text"][:40]}]}

        monkeypatch.setattr(generation, "call_model", fake_call_model)
        out = generation.answer_auto(structure_index, "cutover phases", k=2)
        assert out["engine"] == "claude-opus-5"
        assert len(called["hits"]) == 2
        assert out["answered"] is True


# --------------------------------------------------------------------------
@pytest.mark.skipif(
    not REAL_EMBED,
    reason="Reproduces the numbers in results.md, which are a property of the "
           "frozen bge-small-en-v1.5 scorer, not of the code. The stubbed "
           "embedder retrieves a different top-k and lands elsewhere. Run "
           "with HELP_CENTRE_TEST_REAL_EMBED=1.")
class TestShippedCalibration:
    """The generation audit from `run_generation.py`, at its K of 3."""

    K = 3

    def test_three_of_three_answerable_questions_are_answered(
            self, structure_index, questions):
        unanswered = [
            qid for qid in questions["generation_answerable"]
            if not generation.answer_auto(
                structure_index,
                next(q for q in questions["questions"] if q["id"] == qid)["question"],
                k=self.K)["answered"]
        ]
        assert not unanswered, f"{unanswered} stopped answering"

    @pytest.mark.parametrize("k", [3, 5])
    def test_u1_refuses_under_the_real_scorer(self, structure_index, questions, k):
        """The refund/SLA probe is caught by the perfect-coverage escape, which
        needs the retrieval to actually cover the corpus terms in the question.
        That is a property of bge-small-en-v1.5, not of the gate's arithmetic,
        so it is asserted here rather than against the hashed stub."""
        spec = next(q for q in questions["generation_unanswerable"]
                    if q["id"] == "U1")
        out = generation.answer_auto(structure_index, spec["question"], k=k)
        assert out["answered"] is False
        assert "refund" in out["refusal"].lower() or "sla" in out["refusal"].lower()

    def test_two_of_three_out_of_corpus_questions_are_refused(
            self, structure_index, questions):
        """Was 3/3 under the Week 3 coverage floor, which also refused all 12
        golden-set questions. The gate that answers 12/12 refuses 2/3 -- see
        TestGeneration.test_u2_is_the_known_gap_in_the_grounding_gate."""
        answered = [
            spec["id"] for spec in questions["generation_unanswerable"]
            if generation.answer_auto(
                structure_index, spec["question"], k=self.K)["answered"]
        ]
        assert answered == ["U2"], f"expected only U2 to answer, got {answered}"

    @pytest.mark.parametrize("qid,expected", [
        ("U1", 0.47), ("U2", 0.59), ("U3", 0.15)])
    def test_coverage_scores_match_results_md(
            self, structure_index, questions, qid, expected):
        spec = next(q for q in questions["generation_unanswerable"]
                    if q["id"] == qid)
        hits = structure_index.search(spec["question"], k=self.K)
        score, _ = generation.coverage(spec["question"], hits, structure_index)
        assert score == pytest.approx(expected, abs=0.01)

    def test_the_refusal_gate_is_sensitive_to_k(self, structure_index, questions):
        """U2 clears the floor at k=5. The gate's 0.06 margin at k=3 is spent
        by two extra chunks that happen to contain 'back' and 'complete', so
        `/api/ask` with k>=5 answers a question results.md reports as refused.
        Pinned here so the regression is visible rather than silent."""
        spec = next(q for q in questions["generation_unanswerable"]
                    if q["id"] == "U2")
        at_3, _ = generation.coverage(
            spec["question"], structure_index.search(spec["question"], k=3),
            structure_index)
        at_5, _ = generation.coverage(
            spec["question"], structure_index.search(spec["question"], k=5),
            structure_index)
        assert at_3 < generation.COVERAGE_FLOOR <= at_5


# --------------------------------------------------------------------------
class TestApi:
    def test_health_reports_a_live_index_for_both_strategies(self, client):
        body = client.get("/api/health").json()
        assert body["ok"] is True
        assert body["articles_indexed"] == 6
        assert body["historical_corpus_reindexed"] is False
        assert set(body["strategies"]) == {"fixed_window", "structure_aware"}
        assert all(n > 0 for n in body["strategies"].values())
        assert body["generation_engine"] == "extractive-deterministic"

    def test_product_areas_are_sorted_and_unique(self, client):
        areas = client.get("/api/product_areas").json()["product_areas"]
        assert areas
        assert areas == sorted(set(areas))
        assert "" not in areas

    @pytest.mark.parametrize("strategy", ["fixed_window", "structure_aware"])
    def test_search_returns_ranked_hits(self, client, strategy):
        r = client.post("/api/search", json={
            "query": "How long is the dual-write phase?", "strategy": strategy, "k": 4})
        assert r.status_code == 200
        body = r.json()
        assert body["query"] == "How long is the dual-write phase?"
        assert body["strategy"] == strategy and body["filter"] is None
        hits = body["results"]
        assert len(hits) == 4
        assert [h["rank"] for h in hits] == [1, 2, 3, 4]
        assert all(h["chunk_id"].startswith(f"{strategy}::") for h in hits)

    def test_search_uses_the_structure_aware_default(self, client):
        body = client.post("/api/search", json={"query": "invoice"}).json()
        assert body["strategy"] == "structure_aware"

    def test_search_honours_the_product_area_filter(self, client):
        area = client.get("/api/product_areas").json()["product_areas"][0]
        body = client.post("/api/search", json={
            "query": "migration", "k": 5, "product_area": area}).json()
        assert body["filter"] == {"product_area": area}
        assert body["results"]
        assert all(h["meta"]["product_area"] == area for h in body["results"])

    def test_search_with_an_unknown_strategy_is_rejected(self, client):
        r = client.post("/api/search", json={"query": "x", "strategy": "bogus"})
        assert r.status_code == 400
        assert "bogus" in r.json()["detail"]

    def test_search_requires_a_query(self, client):
        assert client.post("/api/search", json={}).status_code == 422

    def test_compare_runs_both_chunkers_over_the_same_query(self, client):
        body = client.post("/api/compare", json={"query": "ERR-4032", "k": 3}).json()
        by_strategy = body["by_strategy"]
        assert set(by_strategy) == {"fixed_window", "structure_aware"}
        for strategy, hits in by_strategy.items():
            assert len(hits) == 3
            assert all(h["chunk_id"].startswith(f"{strategy}::") for h in hits)

    def test_ask_answers_with_resolvable_citations(self, client):
        body = client.post("/api/ask", json={
            "question": "What does ERR-4032 mean and what is the fix?", "k": 5}).json()
        assert body["engine"] == "extractive-deterministic"
        assert body["answered"] is True
        assert body["claims"]
        for claim in body["claims"]:
            assert claim["chunk_id"] in body["retrieved"]
            chunk = client.get(f"/api/chunk/{claim['chunk_id']}")
            assert chunk.status_code == 200
            assert norm(claim["supporting_quote"]) in norm(chunk.json()["text"])

    def test_ask_refuses_what_the_corpus_does_not_cover(self, client):
        body = client.post("/api/ask", json={
            "question": "What does error ERR-4099 mean and how do I fix it?",
            "k": 5}).json()
        assert body["answered"] is False
        assert body["claims"] == []
        assert body["refusal"].strip()

    @pytest.mark.parametrize("k", [0, 11, -1])
    def test_ask_rejects_an_out_of_range_k(self, client, k):
        r = client.post("/api/ask", json={"question": "anything", "k": k})
        assert r.status_code == 422

    def test_ask_with_an_unknown_strategy_is_rejected(self, client):
        r = client.post("/api/ask", json={"question": "x", "strategy": "bogus"})
        assert r.status_code == 400

    def test_every_retrieved_chunk_id_resolves(self, client):
        for strategy in ("fixed_window", "structure_aware"):
            hits = client.post("/api/search", json={
                "query": "reconciliation rounding difference",
                "strategy": strategy, "k": 5}).json()["results"]
            for hit in hits:
                chunk = client.get(f"/api/chunk/{hit['chunk_id']}").json()
                assert chunk["chunk_id"] == hit["chunk_id"]
                assert chunk["text"] == hit["text"]
                assert chunk["meta"]["article_id"]

    def test_an_unresolvable_chunk_id_is_a_404(self, client):
        r = client.get("/api/chunk/structure_aware::missing.md::999")
        assert r.status_code == 404
        assert r.json()["detail"] == "chunk_id does not resolve"

    def test_a_chunk_id_from_an_unknown_strategy_is_a_400(self, client):
        assert client.get("/api/chunk/bogus::a.md::000").status_code == 400

    def test_cors_is_open_for_the_frontend(self, client):
        r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers["access-control-allow-origin"] == "*"


# ==========================================================================
# The streaming chat surface, and the per-request week3/week4 arm switch that
# replaces "restart the server with a different HELP_CENTRE_RERANK".
# ==========================================================================


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Split a text/event-stream body into (event_name, payload) pairs."""
    out = []
    for frame in body.split("\n\n"):
        name, data = None, []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if name:
            out.append((name, json.loads("\n".join(data))))
    return out


CHAT_QUESTION = "What does ERR-4032 mean and what is the fix?"


@pytest.fixture(scope="module")
def stream(client):
    """One week-3 chat stream, parsed once and asserted on from several angles."""
    res = client.post("/api/chat",
                      json={"question": CHAT_QUESTION, "k": 3, "mode": "week3"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    return parse_sse(res.text)


class TestChatStream:
    QUESTION = CHAT_QUESTION

    def test_the_stream_opens_with_meta_and_closes_with_done(self, stream):
        names = [n for n, _ in stream]
        assert names[0] == "meta"
        assert names[-1] == "done"
        assert "error" not in names

    def test_retrieval_is_emitted_before_any_answer_text(self, stream):
        """The evidence has to be on screen before the claim it supports."""
        names = [n for n, _ in stream]
        assert "retrieval" in names
        first_text = next((i for i, n in enumerate(names)
                           if n in ("delta", "claim_start")), len(names))
        assert names.index("retrieval") < first_text

    def test_every_streamed_delta_reassembles_into_the_verified_answer(self, stream):
        """Nothing is streamed that verify() did not keep -- concatenating the
        deltas must reproduce the final payload exactly, with no extra text."""
        events = dict()
        claims, current, refusal = [], None, ""
        stage = None
        for name, data in stream:
            if name == "status":
                stage = data["stage"]
            elif name == "claim_start":
                current = ""
            elif name == "delta":
                if stage == "refusing":
                    refusal += data["text"]
                else:
                    current += data["text"]
            elif name == "claim_end":
                claims.append(current)
                current = None
            elif name == "done":
                events["done"] = data

        done = events["done"]
        if done["answered"]:
            assert [c.strip() for c in claims] == [c["claim"].strip()
                                                   for c in done["claims"]]
        else:
            assert refusal.strip() == done["refusal"].strip()

    def test_meta_names_the_arm_the_request_asked_for(self, client):
        for mode, reranking in (("week3", False), ("week4", True)):
            res = client.post("/api/chat",
                              json={"question": self.QUESTION, "mode": mode})
            meta = parse_sse(res.text)[0][1]
            assert meta["mode"] == mode
            assert meta["reranking"] is reranking

    def test_an_unknown_mode_is_rejected_before_the_stream_opens(self, client):
        res = client.post("/api/chat",
                          json={"question": self.QUESTION, "mode": "week9"})
        assert res.status_code == 400
        assert "week9" in res.json()["detail"]

    def test_done_carries_the_same_shape_as_the_non_streaming_ask(self, client):
        pairs = parse_sse(client.post(
            "/api/chat", json={"question": self.QUESTION, "k": 3, "mode": "week3"}).text)
        done = next(d for n, d in pairs if n == "done")
        asked = client.post(
            "/api/ask", json={"question": self.QUESTION, "k": 3, "mode": "week3"}).json()
        assert done["answered"] == asked["answered"]
        assert done["retrieved"] == asked["retrieved"]
        assert [c["chunk_id"] for c in done["claims"]] == \
               [c["chunk_id"] for c in asked["claims"]]

    def test_a_filter_that_matches_nothing_streams_a_refusal_not_a_crash(self, client):
        res = client.post("/api/chat", json={"question": self.QUESTION,
                                             "product_area": "no-such-area"})
        pairs = parse_sse(res.text)
        done = next(d for n, d in pairs if n == "done")
        assert done["answered"] is False
        assert done["retrieved"] == []

    def test_top_k_controls_how_many_chunks_are_retrieved(self, client):
        for k in (1, 5):
            pairs = parse_sse(client.post(
                "/api/chat", json={"question": self.QUESTION, "k": k,
                                   "mode": "week3"}).text)
            retrieval = next(d for n, d in pairs if n == "retrieval")
            assert len(retrieval["hits"]) == k
            assert [h["rank"] for h in retrieval["hits"]] == list(range(1, k + 1))

    @pytest.mark.parametrize("k", [0, 11])
    def test_chat_rejects_an_out_of_range_k(self, client, k):
        assert client.post("/api/chat",
                           json={"question": self.QUESTION, "k": k}).status_code == 422

    def test_examples_serve_the_scored_golden_set(self, client):
        served = client.get("/api/examples").json()["examples"]
        with open(os.path.join(EVAL_DIR, "golden_set.jsonl")) as fh:
            gold = [json.loads(line) for line in fh if line.strip()]
        assert [e["id"] for e in served] == [g["id"] for g in gold]
        assert [e["question"] for e in served] == [g["question"] for g in gold]

    def test_week3_and_week4_are_selectable_without_restarting_the_server(
            self, structure_index, monkeypatch):
        """The arm is a per-call argument now, not process state.

        The env default is pinned to 0 for this suite, so the point being
        checked is that `use_rerank=True` still reaches the cross-encoder and
        `use_rerank=False` still skips it. The encoder itself is spied on
        rather than run, so no 150MB model is downloaded.
        """
        q = "What does ERR-4032 mean and what is the fix?"
        calls = []

        def spy(query, hits):
            calls.append(query)
            return hits

        monkeypatch.setattr(store, "rerank", spy)

        week3 = structure_index.search(q, k=3, use_rerank=False)
        assert calls == []
        assert all(h.get("rerank_score") is None for h in week3)

        week4 = structure_index.search(q, k=3, use_rerank=True)
        assert calls == [q]
        # Stage 1 hands the reranker a deeper candidate list than k.
        assert len(week4) == 3

    def test_omitting_the_mode_keeps_the_process_default(self, structure_index,
                                                         monkeypatch):
        calls = []
        monkeypatch.setattr(store, "rerank",
                            lambda query, hits: calls.append(query) or hits)
        # conftest pins HELP_CENTRE_RERANK=0, so no mode means no reranking.
        structure_index.search("ERR-4032", k=3)
        assert calls == []

    def test_the_stream_and_the_plain_endpoint_give_the_same_claims(self, client):
        """Regression: chat_stream called extractive_engine directly and did
        not forward the cross-encoder flag, so /api/chat quietly answered with
        the weaker ranker while /api/ask used the better one."""
        for mode in ("week3", "week4"):
            body = {"question": CHAT_QUESTION, "k": 3, "mode": mode}
            done = next(d for n, d in parse_sse(
                client.post("/api/chat", json=body).text) if n == "done")
            asked = client.post("/api/ask", json=body).json()
            assert [c["claim"] for c in done["claims"]] == \
                   [c["claim"] for c in asked["claims"]], mode

    def test_health_advertises_both_selectable_modes(self, client):
        modes = client.get("/api/health").json()["modes"]
        assert set(modes) == {"week3", "week4"}


# ==========================================================================
# Drag-and-drop document ingest.
# ==========================================================================


class TestDocuments:
    def upload(self, client, name, content):
        blob = content if isinstance(content, bytes) else content.encode()
        return client.post("/api/documents",
                           files=[("files", (name, blob, "application/octet-stream"))])

    def test_a_csv_becomes_a_markdown_table_so_rows_keep_their_header(self):
        out, engine = uploads.extract_text("codes.csv", b"code,cause,fix\n"
                                                        b"ERR-9001,disk full,free space\n")
        assert engine == "", "a text format needs no extraction engine"
        assert out.splitlines()[0] == "| code | cause | fix |"
        assert out.splitlines()[1] == "| --- | --- | --- |"
        assert "| ERR-9001 | disk full | free space |" in out

    def test_json_is_flattened_to_one_leaf_per_line(self):
        out, _ = uploads.extract_text(
            "e.json", b'{"errors":[{"code":"ERR-9001","fix":"free space now"}]}')
        assert "errors[0].code: ERR-9001" in out
        assert "errors[0].fix: free space now" in out

    def test_markup_is_stripped_to_its_text(self):
        out, _ = uploads.extract_text(
            "p.html", b"<html><body><h1>Refund policy</h1>"
                      b"<p>Refunds are paid within ten working days.</p></body></html>")
        assert "<" not in out
        assert "Refunds are paid within ten working days." in out

    @pytest.mark.parametrize("name,blob,fragment", [
        ("archive.bin", b"\x00\x00\x00binary payload", "binary"),
        ("empty.txt", b"", "empty"),
        ("tiny.txt", b"hello", "characters"),
    ])
    def test_unusable_files_are_rejected_with_a_reason(self, name, blob, fragment):
        with pytest.raises(uploads.Rejected) as exc:
            uploads.extract_text(name, blob)
        assert fragment in str(exc.value)

    def test_a_corrupt_image_is_rejected_not_stored(self):
        """It is detected as an image by its magic bytes, so it reaches OCR --
        and OCR failing must still be a clean rejection."""
        with pytest.raises(uploads.Rejected) as exc:
            uploads.extract_text("x.png", b"\x89PNG\r\n\x1a\n\x00\x00garbage")
        assert "image" in str(exc.value).lower()

    def test_an_upload_is_indexed_and_immediately_answerable(self, client):
        body = self.upload(client, "seats.csv",
                           "code,cause,fix\n"
                           "ERR-7001,Seat count exceeds the plan allowance,"
                           "Upgrade the plan or remove seats then retry\n").json()
        assert [a["filename"] for a in body["accepted"]] == ["seats.csv"]
        assert body["accepted"][0]["stored_as"] == "seats.md"
        assert body["accepted"][0]["chunks"] >= 1

        hits = client.post("/api/search", json={
            "query": "ERR-7001 seat count exceeds plan allowance", "k": 3,
            "mode": "week3"}).json()["results"]
        assert any(h["chunk_id"].endswith("seats.md::000") for h in hits)

    def test_a_rejected_file_does_not_stop_the_others(self, client):
        res = client.post("/api/documents", files=[
            ("files", ("ok.txt", b"Escalation policy: page the on-call engineer "
                                 b"after fifteen minutes without an ack.",
                       "text/plain")),
            ("files", ("bad.bin", b"\x00\x00\x00binary", "application/octet-stream")),
        ])
        body = res.json()
        assert [a["filename"] for a in body["accepted"]] == ["ok.txt"]
        assert [r["filename"] for r in body["rejected"]] == ["bad.bin"]

    def test_a_request_where_everything_is_rejected_is_a_422(self, client):
        res = self.upload(client, "bad.bin", b"\x00\x00binary only")
        assert res.status_code == 422

    def test_re_uploading_the_same_name_replaces_rather_than_duplicates(self, client):
        first = self.upload(client, "dup.txt",
                            "The first version of this policy document text.").json()
        after_first = first["total_chunks"]
        second = self.upload(client, "dup.txt",
                             "The second version of this policy document text.").json()
        assert second["total_chunks"] == after_first
        listed = client.get("/api/documents").json()["documents"]
        assert sum(1 for d in listed if d["source_file"] == "dup.md") == 1

    def test_uploads_are_listed_and_flagged_apart_from_the_shipped_corpus(self, client):
        self.upload(client, "notes.txt",
                    "Escalation notes for the billing migration rollout window.")
        docs = client.get("/api/documents").json()["documents"]
        shipped = [d for d in docs if not d["uploaded"]]
        dropped = [d for d in docs if d["uploaded"]]
        assert len(shipped) == 6
        assert "notes.md" in {d["source_file"] for d in dropped}
        assert all(d["chunks"] >= 1 for d in docs)

    def test_deleting_an_upload_removes_its_chunks(self, client):
        self.upload(client, "gone.txt",
                    "This document exists only to be deleted again shortly.")
        before = client.get("/api/health").json()["indexed_chunks"]
        body = client.delete("/api/documents/gone.md").json()
        assert body["chunks_removed"] >= 1
        assert body["total_chunks"] == before - body["chunks_removed"]
        assert "gone.md" not in {d["source_file"]
                                 for d in client.get("/api/documents").json()["documents"]}

    def test_a_shipped_article_cannot_be_deleted(self, client):
        res = client.delete("/api/documents/BM-001-billing-migration-overview.md")
        assert res.status_code == 404

    def test_an_upload_survives_a_restart(self, client, tmp_path):
        """The normalised markdown on disk is the durable record: re-ingesting
        it from scratch reproduces the same chunks."""
        self.upload(client, "durable.txt",
                    "Dual-write phase lasts a minimum of seven days for every "
                    "workspace in the pilot cohort.")
        from backend.app.ingest import load_uploads, records_for
        articles = [a for a in load_uploads() if a[0] == "durable.md"]
        assert articles, "the upload was not written to disk"
        rebuilt = records_for("structure_aware", articles)
        assert rebuilt and all(r.meta["article_id"] for r in rebuilt)


# ==========================================================================
# The week3/week4 answer split. Needs the real scorer AND the cross-encoder,
# so it is opt-in:
#
#   HELP_CENTRE_TEST_REAL_EMBED=1 HELP_CENTRE_RERANK=1 python -m pytest -k ArmSplit
# ==========================================================================

ARM_SPLIT_ENABLED = REAL_EMBED and os.environ.get("HELP_CENTRE_RERANK") == "1"


@pytest.fixture(scope="module")
def golden():
    with open(os.path.join(EVAL_DIR, "golden_set.jsonl")) as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.mark.skipif(not ARM_SPLIT_ENABLED,
                    reason="needs HELP_CENTRE_TEST_REAL_EMBED=1 and "
                           "HELP_CENTRE_RERANK=1")
class TestArmSplit:
    """What the two arms answer, and what neither can.

    These numbers are the demo the UI shows, so they are pinned. They fall out
    of retrieval quality alone: on the baseline arm the term-overlap ranker
    finds no quotable sentence at all for some questions, while the reranked
    arm surfaces one. No threshold is involved.
    """

    K = 3

    def answers(self, index, question, on):
        return generation.answer_extractive(
            index, question, k=self.K, use_rerank=on)["answered"]

    def test_the_reranked_arm_answers_every_golden_question(self, structure_index,
                                                            golden):
        refused = [g["id"] for g in golden
                   if not self.answers(structure_index, g["question"], True)]
        assert refused == [], refused

    def test_the_baseline_arm_answers_eleven_of_twelve(self, structure_index,
                                                       golden):
        answered = [g["id"] for g in golden
                    if self.answers(structure_index, g["question"], False)]
        assert len(answered) == 11, answered

    def test_g11_answers_only_on_the_reranked_arm(self, structure_index, golden):
        """The visible payoff of reranking, and it needs no threshold to show.

        On the baseline arm the term-overlap ranker finds no sentence in the
        retrieved chunks that contains any of the question's terms, so there is
        nothing to quote and it declines. Reranking retrieves the trial chunk,
        and the answer is a sentence in it.
        """
        q = next(g["question"] for g in golden if g["id"] == "G11")
        assert self.answers(structure_index, q, False) is False, "G11 week3"
        assert self.answers(structure_index, q, True) is True, "G11 week4"

    def test_g12_answers_from_the_wrong_chunk_on_both_arms(self, structure_index,
                                                           golden):
        """G12 is the known bad case, pinned so it cannot drift unnoticed.

        Its gold chunk is outside the top 3 on BOTH arms -- min-max fusion
        buries it at rank 9 and reranking cannot reach what retrieval never
        hands it (results_week4.md section 8). Both arms therefore quote a
        related-but-wrong sentence and present it as an answer.

        Making it decline was tried and reverted: every threshold that rejects
        G12's week-3 sentence also rejects the CORRECT answer to Q1, which
        results.md guarantees is answerable. Fixing this needs the retrieval
        change in results_week4.md section 9 item 2 (RRF), not a generation
        threshold.
        """
        q = next(g["question"] for g in golden if g["id"] == "G12")
        assert self.answers(structure_index, q, False) is True
        assert self.answers(structure_index, q, True) is True

    def test_the_published_week3_answerable_set_still_answers(
            self, structure_index, questions):
        """results.md guarantees Q1, Q3 and Q5 are answered. Any change to the
        gating has to keep that true on both arms."""
        for qid in questions["generation_answerable"]:
            q = next(x for x in questions["questions"]
                     if x["id"] == qid)["question"]
            for on in (False, True):
                assert self.answers(structure_index, q, on), f"{qid} arm={on}"

    def test_a_refusal_always_explains_itself(self, structure_index, golden):
        """Whatever declines, it must say why in words the reader can act on."""
        for g in golden:
            for on in (False, True):
                out = generation.answer_extractive(structure_index, g["question"],
                                                   k=self.K, use_rerank=on)
                if not out["answered"]:
                    assert len(out["refusal"].split()) >= 6, g["id"]
                    assert out["claims"] == []


# ==========================================================================
# Image uploads. OCR needs an engine, so these skip where none is available
# (a Linux box with no ANTHROPIC_API_KEY, for instance).
# ==========================================================================

def render_text_png(lines: list[str]) -> bytes:
    """A screenshot-like PNG, rendered at a size OCR can actually read."""
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 26)
    img = Image.new("RGB", (1000, 60 + 42 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    y = 25
    for line in lines:
        draw.text((28, y), line, font=font, fill="black")
        y += 42
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


HAS_OCR = bool(ocr.available_engines())
HAS_ARIAL = os.path.exists("/System/Library/Fonts/Supplemental/Arial.ttf")


class TestImageUploads:
    def test_images_are_recognised_by_magic_bytes_not_just_extension(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        assert ocr.is_image("screenshot.png", png) is True
        assert ocr.is_image("mystery.dat", png) is True, "a PNG is a PNG"
        assert ocr.is_image("notes.txt", b"plain text here") is False

    @pytest.mark.parametrize("name,blob,mime", [
        ("a.png", b"\x89PNG\r\n\x1a\n", "image/png"),
        ("a.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"),
        ("a.gif", b"GIF89a", "image/gif"),
        ("a.webp", b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
        ("a.heic", b"\x00\x00\x00\x18ftypheic", "image/heic"),
    ])
    def test_common_image_formats_are_sniffed(self, name, blob, mime):
        assert ocr.sniff_mime(name, blob) == mime

    @pytest.mark.skipif(not (HAS_OCR and HAS_ARIAL),
                        reason="needs an OCR engine and a TrueType font")
    def test_text_inside_an_image_becomes_searchable(self, client):
        png = render_text_png([
            "Billing Migration Error Codes",
            "ERR-7700 Seat count exceeds the plan allowance",
            "ERR-7701 SSO domain is not verified",
        ])
        body = client.post("/api/documents", files=[
            ("files", ("shot.png", png, "image/png"))]).json()
        assert body["accepted"], body
        accepted = body["accepted"][0]
        assert accepted["stored_as"] == "shot.md"
        assert accepted["extracted_by"], "the OCR engine must be recorded"

        # The error code exists ONLY inside the pixels of the uploaded image.
        hits = client.post("/api/search", json={
            "query": "ERR-7700 seat count exceeds plan allowance",
            "k": 3, "mode": "week3"}).json()["results"]
        assert any(h["chunk_id"].endswith("shot.md::000") for h in hits)

    @pytest.mark.skipif(not (HAS_OCR and HAS_ARIAL),
                        reason="needs an OCR engine and a TrueType font")
    def test_the_original_image_is_kept_beside_its_transcript(self, client):
        png = render_text_png(["Escalation policy for the billing rollout",
                               "Page the on-call engineer after fifteen minutes"])
        client.post("/api/documents",
                    files=[("files", ("keep.png", png, "image/png"))])

        stored = os.listdir(uploads.UPLOAD_DIR)
        assert "keep.md" in stored
        assert "keep.png" in stored, "the original must stay checkable"

        docs = client.get("/api/documents").json()["documents"]
        row = next(d for d in docs if d["source_file"] == "keep.md")
        assert row["extracted_by"]
        assert row["original_file"] == "keep.png"

    @pytest.mark.skipif(not (HAS_OCR and HAS_ARIAL),
                        reason="needs an OCR engine and a TrueType font")
    def test_deleting_an_image_upload_removes_the_original_too(self, client):
        png = render_text_png(["Temporary notes about the migration window",
                               "This document exists only to be deleted"])
        client.post("/api/documents",
                    files=[("files", ("bye.png", png, "image/png"))])
        assert "bye.png" in os.listdir(uploads.UPLOAD_DIR)

        client.delete("/api/documents/bye.md")
        left = os.listdir(uploads.UPLOAD_DIR)
        assert "bye.md" not in left
        assert "bye.png" not in left, "the original was orphaned"

    @pytest.mark.skipif(not (HAS_OCR and HAS_ARIAL),
                        reason="needs an OCR engine and a TrueType font")
    def test_an_image_with_no_text_is_refused(self, client):
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (400, 300), "white").save(buf, format="PNG")
        res = client.post("/api/documents", files=[
            ("files", ("blank.png", buf.getvalue(), "image/png"))])
        assert res.status_code == 422
        assert "blank.md" not in os.listdir(uploads.UPLOAD_DIR)

    def test_health_reports_which_ocr_engines_exist(self, client):
        body = client.get("/api/health").json()
        assert isinstance(body["ocr_engines"], list)
        assert body["ocr_engines"] == ocr.available_engines()
