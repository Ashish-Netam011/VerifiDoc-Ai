"""Evidence sufficiency and coverage tests (deterministic, no model inference)."""

from __future__ import annotations

import json

import pytest

from app.services.citation_verifier import (
    ClaimVerification,
    EvidenceAssessment,
    EvidenceRecord,
    VerificationStatus,
)
from app.services.evidence_sufficiency import (
    ClaimView,
    CitedSource,
    CoverageStatus,
    Decision,
    EvidenceSufficiencyEngine,
    PrecheckResult,
    analyse_coverage,
    best_sentence,
    condition_not_preserved,
    content_tokens,
    keyword_relevance,
    match_slots,
)
from app.services.retrieval_service import RetrievalResult

LEASE_TEXT = (
    "The Tenant shall pay a monthly rent of INR 15,000, due on the fifth day of "
    "each calendar month. The Tenant shall pay a security deposit of INR 30,000, "
    "refundable on vacating. The Tenant shall not sublet the premises without the "
    "Landlord's prior written consent."
)
RENT_CLAIM = "The monthly rent is INR 15,000."
DEPOSIT_CLAIM = "The security deposit is INR 30,000."
INCOME_CLAIM = "The landlord's annual income is INR 900,000."
SUBLET_PRESERVED = "Subletting requires the Landlord's prior written consent."
SUBLET_OMITTED = "The Tenant may sublet the premises."


def evidence(
    chunk_id: str = "c1",
    text: str = LEASE_TEXT,
    *,
    document_id: str = "d1",
    filename: str = "lease.pdf",
    page: int = 1,
) -> EvidenceRecord:
    return EvidenceRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        filename=filename,
        page_number=page,
        text=text,
    )


def verdict(
    status: VerificationStatus,
    *,
    chunk_id: str | None = None,
    entailment: float | None = None,
    contradiction: float | None = None,
) -> ClaimVerification:
    assessments: list[EvidenceAssessment] = []
    if chunk_id is not None:
        assessments.append(
            EvidenceAssessment(
                chunk_id=chunk_id,
                entailment=entailment if entailment is not None else 0.97,
                neutral=0.01,
                contradiction=contradiction if contradiction is not None else 0.02,
                numeric_conflict=False,
            )
        )
    return ClaimVerification(
        status=status,
        reason="test",
        entailment_score=entailment,
        neutral_score=0.01,
        contradiction_score=contradiction,
        evidence=assessments,
    )


def claim(
    text: str,
    status: VerificationStatus = VerificationStatus.SUPPORTED,
    *,
    source: CitedSource | None = None,
    chunk_id: str | None = None,
    contradiction: float | None = None,
) -> ClaimView:
    source = source or CitedSource(
        chunk_id=chunk_id or "c1",
        document_id="d1",
        filename="lease.pdf",
        page_number=1,
    )
    return ClaimView(
        text=text,
        verification=verdict(
            status,
            chunk_id=source.chunk_id,
            contradiction=contradiction,
        ),
        sources=(source,),
    )


def result(
    chunk_id: str = "c1",
    text: str = LEASE_TEXT,
    *,
    semantic: float | None = 0.9,
    bm25: float | None = 1.0,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id="d1",
        filename="lease.pdf",
        page_number=1,
        text=text,
        semantic_score=semantic,
        bm25_score=bm25,
        rrf_score=0.03,
    )


ENGINE = EvidenceSufficiencyEngine()


# -- question coverage ------------------------------------------------------


def test_two_requested_facts_are_identified() -> None:
    slots = match_slots("What is the monthly rent and the security deposit?")
    assert [slot.name for slot in slots] == ["monthly_rent", "security_deposit"]


def test_specific_slot_absorbs_generic_alias() -> None:
    slots = match_slots("When is the rent due?")
    assert [slot.name for slot in slots] == ["rent_due_date"]


def test_unknown_topic_gives_uncertain_coverage() -> None:
    assert match_slots("What does the lease say about bicycles?") == []
    coverage = analyse_coverage("What does the lease say about bicycles?", [evidence()], [])
    assert coverage.status == "uncertain"
    assert coverage.components == ()


def test_coverage_marks_supported_and_missing_components() -> None:
    coverage = analyse_coverage(
        "What is the monthly rent and the landlord's annual income?",
        [evidence()],
        [claim(RENT_CLAIM)],
    )
    assert coverage.status == "identified"
    by_name = {component.name: component for component in coverage.components}
    assert by_name["monthly_rent"].status == CoverageStatus.SUPPORTED.value
    assert by_name["landlord_income"].status == CoverageStatus.MISSING.value


def test_coverage_marks_mention_without_verification_as_unverified() -> None:
    text = "The Landlord's income from other sources is described in Schedule 3."
    coverage = analyse_coverage(
        "What is the landlord's annual income?",
        [evidence(text=text)],
        [],
    )
    component = coverage.components[0]
    assert component.status == CoverageStatus.UNVERIFIED.value
    assert component.evidence_chunk_ids == ("c1",)


def test_coverage_matches_claim_through_its_cited_sentence() -> None:
    # The claim itself never says "rent due"; the cited sentence does.
    coverage = analyse_coverage(
        "When is the rent due?",
        [evidence()],
        [claim("It is payable on the fifth day of each calendar month.")],
    )
    assert coverage.components[0].status == CoverageStatus.SUPPORTED.value


# -- relevance screen -------------------------------------------------------


def test_precheck_abstains_on_empty_corpus() -> None:
    assert ENGINE.precheck("What is the rent?", []) is not None
    check = ENGINE.precheck("What is the rent?", [])
    assert check.proceed is False
    assert check.reason == "empty_corpus"


def test_precheck_rejects_unrelated_low_similarity_evidence() -> None:
    check = ENGINE.precheck(
        "What is the monthly rent?",
        [result(text="Parking spaces are allocated by the Landlord.", semantic=0.31)],
    )
    assert check.proceed is False
    assert check.reason == "no_relevant_evidence"


def test_precheck_accepts_shared_vocabulary() -> None:
    check = ENGINE.precheck(
        "What is the monthly rent?",
        [result(text="The monthly rent is INR 15,000.", semantic=0.55)],
    )
    assert check.proceed is True
    assert check.relevant_chunks == 1


def test_precheck_uses_slot_alias_not_only_tokens() -> None:
    check = ENGINE.precheck(
        "Can the tenant sublet?",
        [result(text="Assignment: no subletting is allowed.", semantic=0.4)],
    )
    assert check.proceed is True


def test_keyword_relevance_ignores_question_words() -> None:
    tokens = content_tokens("What is the monthly rent and the security deposit?")
    assert "the" not in tokens
    assert "monthly" in tokens
    assert keyword_relevance(tokens, "The monthly rent is INR 15,000.") > 0
    assert keyword_relevance(tokens, "Parking is allocated by the Landlord.") == 0


# -- condition detection ----------------------------------------------------


def test_best_sentence_selects_the_relevant_sentence() -> None:
    assert "written consent" in best_sentence(LEASE_TEXT, SUBLET_PRESERVED)


def test_condition_is_preserved_when_the_claim_states_it() -> None:
    assert condition_not_preserved(SUBLET_PRESERVED, LEASE_TEXT) is False


def test_condition_is_flagged_when_the_claim_omits_it() -> None:
    assert condition_not_preserved(SUBLET_OMITTED, LEASE_TEXT) is True


def test_unconditional_evidence_is_never_flagged() -> None:
    assert condition_not_preserved("The rent is INR 15,000.", "Rent is INR 15,000.") is False


# -- decisions --------------------------------------------------------------


def test_answer_when_every_requested_fact_is_supported() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent and the security deposit?",
        evidence=[evidence()],
        claims=[claim(RENT_CLAIM), claim(DEPOSIT_CLAIM)],
        verification_status="verified",
        generated_answer="The monthly rent is INR 15,000 and the security deposit is INR 30,000.",
    )
    assert assessment.decision is Decision.ANSWER
    assert assessment.report.missing_information == []
    assert assessment.report.status == "answer"


def test_partial_answer_when_one_requested_fact_is_missing() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent and the landlord's annual income?",
        evidence=[evidence()],
        claims=[
            claim(RENT_CLAIM),
            claim(INCOME_CLAIM, VerificationStatus.INSUFFICIENT),
        ],
        verification_status="partially_verified",
        generated_answer="The monthly rent is INR 15,000. The landlord earns INR 900,000.",
    )
    assert assessment.decision is Decision.PARTIAL_ANSWER
    assert RENT_CLAIM in assessment.answer
    assert INCOME_CLAIM not in assessment.answer
    assert any("annual income" in item for item in assessment.report.missing_information)


def test_partial_answer_only_contains_supported_claims() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent and the landlord's annual income?",
        evidence=[evidence()],
        claims=[
            claim(RENT_CLAIM),
            claim(INCOME_CLAIM, VerificationStatus.INSUFFICIENT),
        ],
        verification_status="partially_verified",
        generated_answer=None,
    )
    assert assessment.decision is Decision.PARTIAL_ANSWER
    assert assessment.answer.startswith(RENT_CLAIM)
    assert "do not establish" in assessment.answer


def test_abstain_when_the_model_produced_no_claims() -> None:
    assessment = ENGINE.assess(
        "What is the landlord's annual income?",
        evidence=[evidence()],
        claims=[],
        verification_status="not_verified",
        generated_answer="I could not find this information.",
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "no_claims"
    assert any("annual income" in item for item in assessment.report.missing_information)


def test_abstain_when_every_claim_is_insufficient() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent?",
        evidence=[evidence()],
        claims=[claim(RENT_CLAIM, VerificationStatus.INSUFFICIENT)],
        verification_status="not_verified",
        generated_answer=RENT_CLAIM,
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "insufficient_evidence"
    assert RENT_CLAIM not in assessment.answer


def test_abstain_when_every_citation_is_invalid() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent?",
        evidence=[evidence()],
        claims=[claim(RENT_CLAIM, VerificationStatus.INVALID_CITATION)],
        verification_status="not_verified",
        generated_answer=RENT_CLAIM,
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "invalid_citations"


def test_contradiction_is_disclosed_and_blocks_the_answer() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent?",
        evidence=[evidence()],
        claims=[claim("The monthly rent is INR 18,000.", VerificationStatus.CONTRADICTED, contradiction=0.98)],
        verification_status="contradicted",
        generated_answer="The monthly rent is INR 18,000.",
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "contradictory_evidence"
    assert len(assessment.report.conflicts) == 1
    conflict = assessment.report.conflicts[0]
    assert conflict.kind == "claim_contradiction"
    assert conflict.chunk_id == "c1"
    assert conflict.page_number == 1
    assert conflict.contradiction_score == pytest.approx(0.98)
    assert "contradicted by" in assessment.answer


def test_verification_unavailable_abstains_by_default() -> None:
    unverified = ClaimView(text=RENT_CLAIM, verification=None)
    assessment = ENGINE.assess(
        "What is the monthly rent?",
        evidence=[evidence()],
        claims=[unverified],
        verification_status="verification_unavailable",
        generated_answer=RENT_CLAIM,
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "verification_unavailable"
    assert RENT_CLAIM not in assessment.answer


def test_verification_can_be_optional_but_still_never_yields_an_answer() -> None:
    relaxed = EvidenceSufficiencyEngine(require_verification=False)
    assessment = relaxed.assess(
        "What is the monthly rent?",
        evidence=[evidence()],
        claims=[ClaimView(text=RENT_CLAIM, verification=None)],
        verification_status="verification_unavailable",
        generated_answer=RENT_CLAIM,
    )
    assert assessment.decision is Decision.ABSTAIN


def test_preserved_condition_allows_an_answer() -> None:
    assessment = ENGINE.assess(
        "Is subletting permitted?",
        evidence=[evidence()],
        claims=[claim(SUBLET_PRESERVED)],
        verification_status="verified",
        generated_answer=SUBLET_PRESERVED,
    )
    assert assessment.decision is Decision.ANSWER


def test_dropped_condition_blocks_the_answer() -> None:
    assessment = ENGINE.assess(
        "Can the tenant sublet freely?",
        evidence=[evidence()],
        claims=[claim(SUBLET_OMITTED)],
        verification_status="verified",
        generated_answer=SUBLET_OMITTED,
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "qualification_not_preserved"
    assert assessment.report.coverage.components[0].status == (
        CoverageStatus.CONDITION_MISSING.value
    )


def test_conflicting_amounts_across_documents_abstain() -> None:
    other = evidence(
        chunk_id="c2",
        document_id="d2",
        filename="amendment.pdf",
        page=2,
        text="The monthly rent is INR 18,000.",
    )
    other_source = CitedSource(
        chunk_id="c2", document_id="d2", filename="amendment.pdf", page_number=2
    )
    assessment = ENGINE.assess(
        "What is the monthly rent?",
        evidence=[evidence(), other],
        claims=[
            claim(RENT_CLAIM),
            claim("The monthly rent is INR 18,000.", source=other_source),
        ],
        verification_status="verified",
        generated_answer=RENT_CLAIM,
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "conflicting_evidence"
    assert any(conflict.kind == "conflicting_amounts" for conflict in assessment.report.conflicts)


def test_conservative_mode_downgrades_partial_answers() -> None:
    conservative = EvidenceSufficiencyEngine(conservative_mode=True)
    assessment = conservative.assess(
        "What is the monthly rent and the landlord's annual income?",
        evidence=[evidence()],
        claims=[
            claim(RENT_CLAIM),
            claim(INCOME_CLAIM, VerificationStatus.INSUFFICIENT),
        ],
        verification_status="partially_verified",
        generated_answer=None,
    )
    assert assessment.decision is Decision.ABSTAIN
    assert assessment.reason == "conservative_mode"


def test_uncertain_coverage_with_a_failed_claim_is_partial() -> None:
    assessment = ENGINE.assess(
        "Summarise the obligations described in the document.",
        evidence=[evidence()],
        claims=[
            claim(RENT_CLAIM),
            claim("The document mentions a bicycle shed.", VerificationStatus.INSUFFICIENT),
        ],
        verification_status="partially_verified",
        generated_answer=None,
    )
    assert assessment.decision is Decision.PARTIAL_ANSWER
    assert assessment.report.coverage.status == "uncertain"


def test_uncertain_coverage_with_all_claims_supported_is_an_answer() -> None:
    assessment = ENGINE.assess(
        "Summarise the payment obligations.",
        evidence=[evidence()],
        claims=[claim(RENT_CLAIM), claim(DEPOSIT_CLAIM)],
        verification_status="verified",
        generated_answer="Rent and deposit are stated.",
    )
    assert assessment.decision is Decision.ANSWER


def test_gap_report_references_real_evidence_records() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent and the landlord's annual income?",
        evidence=[evidence()],
        claims=[claim(RENT_CLAIM), claim(INCOME_CLAIM, VerificationStatus.INSUFFICIENT)],
        verification_status="partially_verified",
        generated_answer=None,
    )
    supporting = assessment.report.supporting_evidence
    assert len(supporting) == 1
    assert supporting[0].chunk_id == "c1"
    assert supporting[0].filename == "lease.pdf"
    assert supporting[0].page_number == 1
    assert supporting[0].claim_text == RENT_CLAIM


def test_gap_report_has_no_filesystem_paths() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent and the landlord's annual income?",
        evidence=[evidence()],
        claims=[claim(RENT_CLAIM), claim(INCOME_CLAIM, VerificationStatus.INSUFFICIENT)],
        verification_status="partially_verified",
        generated_answer=None,
    )
    payload = json.dumps(assessment.report.to_dict())
    assert "\\\\" not in payload
    assert ":\\" not in payload
    assert "data/" not in payload


def test_assessment_serialises_decision_and_report() -> None:
    assessment = ENGINE.assess(
        "What is the monthly rent?",
        evidence=[evidence()],
        claims=[claim(RENT_CLAIM)],
        verification_status="verified",
        generated_answer=RENT_CLAIM,
    )
    payload = assessment.to_dict()
    assert payload["decision"] == "answer"
    assert payload["evidence_gap_report"]["status"] == "answer"
    assert payload["evidence_gap_report"]["signals"]["supported_claims"] == 1


def test_precheck_result_is_reported_for_empty_retrieval() -> None:
    assessment = ENGINE.assess(
        "What is the rent?",
        evidence=[],
        claims=[],
        verification_status="not_verified",
        generated_answer=None,
        precheck=PrecheckResult(False, "no_relevant_evidence"),
    )
    assert assessment.decision is Decision.ABSTAIN
    assert "No relevant evidence" in assessment.answer
    assert assessment.report.reason == "no_relevant_evidence"
