"""Phase 5.2: Contradiction evidence tests with side-by-side evidence pairs."""

from app.services.contradiction_service import compare_facts, extract_candidate_facts
from app.services.retrieval_service import RetrievalResult


def _result(
    document_id: str,
    text: str,
    *,
    filename: str | None = None,
    page_number: int = 1,
    chunk_id: str | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id if chunk_id is not None else f"{document_id}-chunk",
        document_id=document_id,
        filename=filename if filename is not None else f"{document_id}.pdf",
        page_number=page_number,
        text=text,
        semantic_score=0.9,
        bm25_score=1.0,
        rrf_score=0.03,
    )


def test_different_interest_rates_confirmed_conflict():
    facts = [
        *extract_candidate_facts(
            _result("a", "The applicable interest rate shall be 8%.")
        ),
        *extract_candidate_facts(
            _result("b", "The applicable interest rate shall be 10%.")
        ),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    assert comparisons[0].status == "confirmed_conflict"
    assert comparisons[0].conflict_type == "conflicting_amounts"
    assert comparisons[0].evidence_a.document_id == "a"
    assert comparisons[0].evidence_a.filename == "a.pdf"
    assert comparisons[0].evidence_a.page_number == 1
    assert comparisons[0].evidence_a.quote == "The applicable interest rate shall be 8%."
    assert comparisons[0].evidence_b.document_id == "b"
    assert comparisons[0].evidence_b.quote == "The applicable interest rate shall be 10%."
    assert comparisons[0].contradiction_score is None


def test_identical_interest_rates_consistent():
    facts = [
        *extract_candidate_facts(
            _result("a", "The interest rate is 5% per annum.")
        ),
        *extract_candidate_facts(
            _result("b", "The interest rate is 5% per annum.")
        ),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    assert comparisons[0].status == "consistent"


def test_different_dates_different_years():
    facts = [
        *extract_candidate_facts(
            _result("a", "The policy expires on 2025-12-31.")
        ),
        *extract_candidate_facts(
            _result("b", "The policy expires on 2026-12-31.")
        ),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    assert comparisons[0].status == "confirmed_conflict"
    assert comparisons[0].conflict_type == "conflicting_dates"


def test_different_amounts_different_entities():
    facts = [
        *extract_candidate_facts(
            _result("a", "The security deposit for tenants is INR 15,000.")
        ),
        *extract_candidate_facts(
            _result("b", "The security deposit for landlords is INR 18,000.")
        ),
    ]
    comparisons = compare_facts(facts)
    # Both have subject "security deposit" and attribute "deposit"
    # Different entities in conditions should still surface as potential conflict
    assert len(comparisons) == 1
    assert comparisons[0].status == "confirmed_conflict"
    assert comparisons[0].conflict_type == "conflicting_amounts"


def test_original_policy_and_amendment():
    facts = [
        *extract_candidate_facts(
            _result("a", "Monthly rent is INR 15,000 per month.")
        ),
        *extract_candidate_facts(
            _result(
                "b",
                "This amendment amends a.pdf, effective from 2025-01-01. "
                "Monthly rent is INR 18,000 per month.",
            )
        ),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"
    assert comparisons[0].conflict_type == "potential_amendment"


def test_three_documents_conflicting_values():
    facts = [
        *extract_candidate_facts(
            _result("a", "The rent is INR 10,000 per month.")
        ),
        *extract_candidate_facts(
            _result("b", "The rent is INR 15,000 per month.")
        ),
        *extract_candidate_facts(
            _result("c", "The rent is INR 20,000 per month.")
        ),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 3
    for comp in comparisons:
        assert comp.status == "confirmed_conflict"
        assert comp.conflict_type == "conflicting_amounts"


def test_missing_quotation():
    facts = [
        *extract_candidate_facts(
            _result("", "Rent is INR 15,000.", filename="", chunk_id="")
        ),
        *extract_candidate_facts(_result("b", "Rent is INR 18,000.")),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"
    assert comparisons[0].conflict_type == "missing_provenance"


def test_missing_page_metadata():
    facts = [
        *extract_candidate_facts(
            _result("a", "Rent is INR 15,000.", page_number=0)
        ),
        *extract_candidate_facts(_result("b", "Rent is INR 18,000.", page_number=1)),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"
    assert comparisons[0].conflict_type == "missing_provenance"


def test_ambiguous_subject():
    facts = [
        *extract_candidate_facts(_result("a", "The pet deposit is INR 1,000.")),
        *extract_candidate_facts(_result("b", "The parking deposit is INR 2,000.")),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 0


def test_contradictory_conditions_unresolved():
    facts = [
        *extract_candidate_facts(
            _result("a", "Rent is INR 15,000 if the tenant occupies one room.")
        ),
        *extract_candidate_facts(
            _result("b", "Rent is INR 18,000 if the tenant occupies two rooms.")
        ),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"
    assert comparisons[0].conflict_type == "conflicting_conditions"


def test_side_by_side_evidence_preserves_quotations():
    facts = [
        *extract_candidate_facts(
            _result("a", "Monthly rent is INR 15,000.", page_number=12)
        ),
        *extract_candidate_facts(
            _result("b", "Monthly rent is INR 18,000.", page_number=7)
        ),
    ]
    comparisons = compare_facts(facts)
    assert len(comparisons) == 1
    comp = comparisons[0]
    assert comp.evidence_a.quote == "Monthly rent is INR 15,000."
    assert comp.evidence_b.quote == "Monthly rent is INR 18,000."
    assert comp.evidence_a.page_number == 12
    assert comp.evidence_b.page_number == 7
    assert comp.evidence_a.filename == "a.pdf"
    assert comp.evidence_b.filename == "b.pdf"
    assert comp.analysis is not None and len(comp.analysis) > 0