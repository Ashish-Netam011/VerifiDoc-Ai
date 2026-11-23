from app.services.contradiction_service import (
    compare_facts,
    extract_candidate_facts,
)
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


def test_same_value_across_documents_is_consistent() -> None:
    facts = [
        *extract_candidate_facts(_result("a", "Monthly rent is INR 15,000.")),
        *extract_candidate_facts(_result("b", "Monthly rent is INR 15,000.00.")),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "consistent"
    assert comparisons[0].left.source.quotation in "Monthly rent is INR 15,000."
    assert comparisons[0].right.source.document_id == "b"


def test_different_numeric_values_with_same_context_are_conflicts() -> None:
    facts = [
        *extract_candidate_facts(_result("a", "Rent is INR 15,000 per month.")),
        *extract_candidate_facts(_result("b", "Rent is INR 18,000 per month.")),
    ]

    comparison = compare_facts(facts)[0]

    assert comparison.status == "confirmed_conflict"
    assert comparison.left.value != comparison.right.value
    assert comparison.left.source.quotation
    assert comparison.right.source.quotation


def test_monthly_rent_and_rent_share_the_same_subject() -> None:
    facts = [
        *extract_candidate_facts(
            _result("a", "Monthly rent is INR 15,000 per month.")
        ),
        *extract_candidate_facts(_result("b", "Rent is INR 18,000 per month.")),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "confirmed_conflict"


def test_different_deadline_dates_are_detected() -> None:
    facts = [
        *extract_candidate_facts(_result("a", "Payment deadline is 2025-03-01.")),
        *extract_candidate_facts(_result("b", "Payment deadline is 2025-04-01.")),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "confirmed_conflict"
    assert comparisons[0].left.unit == "date"


def test_same_deadline_in_different_date_formats_is_consistent() -> None:
    facts = [
        *extract_candidate_facts(
            _result("a", "Payment deadline is March 1, 2025.")
        ),
        *extract_candidate_facts(
            _result("b", "Payment deadline is 2025-03-01.")
        ),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "consistent"


def test_ambiguous_numeric_dates_remain_unresolved() -> None:
    facts = [
        *extract_candidate_facts(
            _result("a", "Payment deadline is 01/02/2025.")
        ),
        *extract_candidate_facts(
            _result("b", "Payment deadline is 02/01/2025.")
        ),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"


def test_different_explicit_eligibility_limits_are_detected() -> None:
    facts = [
        *extract_candidate_facts(
            _result("a", "Applicants must be at least 18 years old.")
        ),
        *extract_candidate_facts(
            _result("b", "Applicants must be at least 21 years old.")
        ),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "confirmed_conflict"
    assert comparisons[0].left.unit == "years"


def test_non_eligibility_uses_of_under_are_not_promoted_to_facts() -> None:
    facts = extract_candidate_facts(
        _result("a", "The model fits under 3 GB of memory.")
    )

    assert facts == []


def test_different_conditions_remain_unresolved() -> None:
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
    assert comparisons[0].left.conditions != comparisons[0].right.conditions


def test_leading_conditions_are_preserved_without_changing_subject() -> None:
    facts = [
        *extract_candidate_facts(
            _result("a", "If the tenant has one room, monthly rent is INR 15,000.")
        ),
        *extract_candidate_facts(
            _result("b", "If the tenant has two rooms, monthly rent is INR 18,000.")
        ),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"
    assert comparisons[0].left.conditions != comparisons[0].right.conditions


def test_different_relevant_periods_remain_unresolved() -> None:
    facts = [
        *extract_candidate_facts(
            _result("a", "Rent is INR 15,000 as of 2025-01-01.")
        ),
        *extract_candidate_facts(
            _result("b", "Rent is INR 18,000 as of 2026-01-01.")
        ),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"
    assert comparisons[0].left.relevant_date != comparisons[0].right.relevant_date


def test_amendment_effective_date_applies_to_fact_in_same_chunk() -> None:
    base_facts = extract_candidate_facts(
        _result("a", "Monthly rent is INR 15,000 per month.")
    )
    amendment_facts = extract_candidate_facts(
        _result(
            "b",
            "This amendment amends a.pdf, effective from 2025-01-01.\n"
            "Monthly rent is INR 18,000 per month.",
        )
    )

    assert amendment_facts[0].relevant_date == "2025-01-01"
    comparisons = compare_facts([*base_facts, *amendment_facts])

    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"


def test_equivalent_relevant_date_formats_are_same_period() -> None:
    facts = [
        *extract_candidate_facts(
            _result("a", "Rent is INR 15,000 as of 2025-01-01.")
        ),
        *extract_candidate_facts(
            _result("b", "Rent is INR 15,000 as of January 1, 2025.")
        ),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "consistent"


def test_different_subjects_are_not_compared() -> None:
    facts = [
        *extract_candidate_facts(_result("a", "Pet deposit is INR 1,000.")),
        *extract_candidate_facts(_result("b", "Parking deposit is INR 2,000.")),
    ]

    assert compare_facts(facts) == []


def test_missing_provenance_is_unresolved_not_a_confirmed_conflict() -> None:
    facts = [
        *extract_candidate_facts(
            _result("", "Rent is INR 15,000.", filename="", chunk_id="")
        ),
        *extract_candidate_facts(_result("b", "Rent is INR 18,000.")),
    ]

    comparisons = compare_facts(facts)

    assert len(comparisons) == 1
    assert comparisons[0].status == "unresolved"
