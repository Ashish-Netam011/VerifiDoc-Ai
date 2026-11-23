from types import SimpleNamespace

import pytest

from app.services.faithfulness_service import calculate_faithfulness


def _claim(text: str, status: str, source_count: int = 1):
    sources = [
        SimpleNamespace(
            chunk_id=f"chunk-{index}",
            document_id=f"doc-{index}",
            filename=f"source-{index}.pdf",
            page_number=index + 1,
            quotation=f"Exact evidence {index}",
        )
        for index in range(source_count)
    ]
    return SimpleNamespace(
        text=text,
        verification=SimpleNamespace(status=status),
        sources=sources,
    )


def test_all_answer_sentences_link_to_verified_claims() -> None:
    answer = "Rent is 100. Deposit is 200."
    claims = [
        _claim("Rent is 100.", "supported"),
        _claim("Deposit is 200.", "supported"),
    ]

    result = calculate_faithfulness(answer, claims, decision="answer")

    assert result["percentage"] == 100
    assert result["total_sentence_count"] == 2
    assert result["supported_sentence_count"] == 2
    assert all(item["evidence"] for item in result["sentences"])


def test_partially_supported_answer_counts_only_supported_sentences() -> None:
    result = calculate_faithfulness(
        "Rent is 100. The tenant owns a car.",
        [_claim("Rent is 100.", "supported")],
        decision="partial_answer",
    )

    assert result["percentage"] == 50
    assert result["supported_sentence_count"] == 1
    assert result["unsupported_sentence_count"] == 1
    assert result["sentences"][1]["supported"] is False


@pytest.mark.parametrize("status", ["contradicted", "insufficient", "invalid_citation"])
def test_unverified_or_invalid_claim_is_not_counted(status: str) -> None:
    result = calculate_faithfulness(
        "Rent is 100.", [_claim("Rent is 100.", status)], decision="answer"
    )

    assert result["percentage"] == 0
    assert result["supported_sentence_count"] == 0
    assert result["unsupported_sentence_count"] == 1
    assert result["sentences"][0]["evidence"] == []


def test_empty_answer_has_no_misleading_score() -> None:
    result = calculate_faithfulness("", [], decision="answer")

    assert result["percentage"] is None
    assert result["total_sentence_count"] == 0
    assert result["supported_sentence_count"] == 0
    assert result["unsupported_sentence_count"] == 0


def test_abstention_is_never_scored_as_fully_faithful() -> None:
    result = calculate_faithfulness(
        "No answer can be given.",
        [_claim("No answer can be given.", "supported")],
        decision="abstain",
    )

    assert result["percentage"] is None
    assert result["supported_sentence_count"] == 0
    assert result["unsupported_sentence_count"] == 1


def test_sentence_can_show_multiple_evidence_sources() -> None:
    result = calculate_faithfulness(
        "Rent is 100.",
        [_claim("Rent is 100.", "supported", source_count=2)],
        decision="answer",
    )

    assert len(result["sentences"][0]["evidence"]) == 2


def test_paraphrase_without_exact_claim_mapping_stays_unsupported() -> None:
    result = calculate_faithfulness(
        "The monthly rent comes to 100.",
        [_claim("Rent is 100.", "supported")],
        decision="answer",
    )

    assert result["percentage"] == 0
    assert result["sentences"][0]["claim_indices"] == []
