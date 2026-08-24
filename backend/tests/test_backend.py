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

from backend.app import chunkers, generation, store
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
from backend.tests.conftest import REAL_EMBED

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

    def test_questions_hinging_on_absent_terms_are_refused(
            self, structure_index, questions):
        """U1 (refund/SLA) and U3 (ERR-4099) turn on words the corpus never
        uses, so no retrieval can cover them and the refusal is robust."""
        checked = 0
        for spec in questions["generation_unanswerable"]:
            hits = structure_index.search(spec["question"], k=5)
            _, uncovered = generation.coverage(spec["question"], hits, structure_index)
            if not uncovered:
                continue
            checked += 1
            out = generation.answer_auto(structure_index, spec["question"], k=5)
            assert out["answered"] is False, f"{spec['id']} should be refused"
            assert out["claims"] == []
            assert out["refusal"].strip()
        assert checked >= 2

    def test_the_refusal_names_what_is_missing(self, structure_index):
        out = generation.answer_auto(
            structure_index, "What is the refund SLA for a disputed invoice?", k=5)
        assert out["answered"] is False
        assert "grounding coverage" in out["refusal"]
        assert "refund" in out["refusal"] or "sla" in out["refusal"]

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

    def test_three_of_three_out_of_corpus_questions_are_refused(
            self, structure_index, questions):
        answered = [
            spec["id"] for spec in questions["generation_unanswerable"]
            if generation.answer_auto(
                structure_index, spec["question"], k=self.K)["answered"]
        ]
        assert not answered, f"{answered} were answered instead of refused"

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
