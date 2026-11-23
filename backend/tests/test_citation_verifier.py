"""Citation integrity and claim verification tests with a scripted NLI stub."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.citation_verifier import (
    CitationRecord,
    CitationVerifier,
    ClaimVerification,
    EvidenceRecord,
    IntegrityFailure,
    VerificationStatus,
    check_citation,
    extract_numbers,
    numeric_conflict,
)
from app.services.nli_service import NLIScores

TEXT = (
    "The Tenant shall pay a monthly rent of INR 15,000, due on the fifth day of "
    "each calendar month. A late payment attracts interest of 2% per month."
)
OTHER_TEXT = "Any notice under this lease must be delivered by registered post to the address stated in Schedule 2."

ENTAILS = NLIScores(entailment=0.95, neutral=0.03, contradiction=0.02)
CONTRADICTS = NLIScores(entailment=0.01, neutral=0.02, contradiction=0.97)
NEUTRAL = NLIScores(entailment=0.02, neutral=0.96, contradiction=0.02)
WEAK = NLIScores(entailment=0.55, neutral=0.40, contradiction=0.05)


class ScriptedNLI:
    """Returns preset scores for the first mapping key found in the premise.

    Premise matches take priority over hypothesis matches, so two different
    chunks scored against one claim can return different verdicts.
    """

    def __init__(self, mapping: dict[str, NLIScores], default: NLIScores = NEUTRAL) -> None:
        self.mapping = mapping
        self.default = default
        self.calls: list[list[tuple[str, str]]] = []

    def _match(self, text: str) -> NLIScores | None:
        for key, scores in self.mapping.items():
            if key.lower() in text.lower():
                return scores
        return None

    def score_pairs(self, pairs):
        self.calls.append(list(pairs))
        results = []
        for premise, hypothesis in pairs:
            scores = self._match(premise) or self._match(hypothesis)
            results.append(scores if scores is not None else self.default)
        return results


EVIDENCE = [
    EvidenceRecord(
        chunk_id="c1",
        document_id="d1",
        filename="lease.pdf",
        page_number=1,
        text=TEXT,
    ),
    EvidenceRecord(
        chunk_id="c2",
        document_id="d2",
        filename="notices.pdf",
        page_number=2,
        text=OTHER_TEXT,
    ),
]


def citation(**overrides) -> CitationRecord:
    values = {
        "chunk_id": "c1",
        "document_id": "d1",
        "filename": "lease.pdf",
        "page_number": 1,
        "quotation": "monthly rent of INR 15,000",
    }
    values.update(overrides)
    return CitationRecord(**values)


def verifier(nli: ScriptedNLI | None = None, **kwargs) -> CitationVerifier:
    return CitationVerifier(nli or ScriptedNLI({}), **kwargs)


# -- integrity --------------------------------------------------------------


def test_valid_citation_passes_integrity() -> None:
    by_chunk = {item.chunk_id: item for item in EVIDENCE}
    assert check_citation(citation(), by_chunk).valid is True


def test_unknown_chunk_is_invalid() -> None:
    by_chunk = {item.chunk_id: item for item in EVIDENCE}
    result = check_citation(citation(chunk_id="nope"), by_chunk)
    assert result.valid is False
    assert IntegrityFailure.UNKNOWN_CHUNK.value in result.failures


@pytest.mark.parametrize(
    "overrides, failure",
    [
        ({"document_id": "d-other"}, IntegrityFailure.DOCUMENT_MISMATCH),
        ({"filename": "other.pdf"}, IntegrityFailure.FILENAME_MISMATCH),
        ({"page_number": 9}, IntegrityFailure.PAGE_MISMATCH),
        ({"quotation": "   "}, IntegrityFailure.EMPTY_QUOTATION),
        ({"quotation": "The rent is EUR 9,000."}, IntegrityFailure.QUOTATION_NOT_IN_CHUNK),
    ],
)
def test_integrity_failures_are_reported(overrides, failure) -> None:
    by_chunk = {item.chunk_id: item for item in EVIDENCE}
    result = check_citation(citation(**overrides), by_chunk)
    assert result.valid is False
    assert failure.value in result.failures


def test_invalid_citation_wins_over_validation() -> None:
    verdict = verifier(ScriptedNLI({"rent": ENTAILS})).verify_claim(
        "The monthly rent is INR 15,000.",
        [citation(quotation="fabricated text not in the chunk")],
        EVIDENCE,
    )
    assert verdict.status is VerificationStatus.INVALID_CITATION
    assert verdict.reason == "citation_integrity_failed"
    assert IntegrityFailure.QUOTATION_NOT_IN_CHUNK.value in verdict.integrity_failures


def test_claim_without_citations_is_invalid() -> None:
    verdict = verifier().verify_claim("Some claim.", [], EVIDENCE)
    assert verdict.status is VerificationStatus.INVALID_CITATION
    assert verdict.reason == "no_citations"


def test_one_broken_citation_blocks_the_claim() -> None:
    verdict = verifier(ScriptedNLI({"rent": ENTAILS})).verify_claim(
        "The monthly rent is INR 15,000.",
        [citation(), citation(chunk_id="missing")],
        EVIDENCE,
    )
    assert verdict.status is VerificationStatus.INVALID_CITATION
    assert IntegrityFailure.UNKNOWN_CHUNK.value in verdict.integrity_failures


# -- numeric safeguards ----------------------------------------------------


def test_numeric_extraction_normalises_amounts() -> None:
    assert extract_numbers("INR 15,000") == {Decimal("15000")}
    assert extract_numbers("15,000.00 and 2%") == {Decimal("15000.00"), Decimal("2")}
    assert extract_numbers("no figures here") == set()


def test_numeric_conflict_detects_wrong_amount() -> None:
    assert numeric_conflict("The rent is INR 18,000.", TEXT) is True
    assert numeric_conflict("The rent is INR 15,000.", TEXT) is False
    assert numeric_conflict("The rent is due monthly.", TEXT) is False


def test_wrong_amount_is_never_supported_even_if_nli_is_wrong() -> None:
    # NLI (unrealistically) says "entails"; the numeric guard must still block support.
    verdict = verifier(ScriptedNLI({"18,000": ENTAILS})).verify_claim(
        "The monthly rent is INR 18,000.", [citation()], EVIDENCE
    )
    assert verdict.status is VerificationStatus.INSUFFICIENT
    assert verdict.reason == "numeric_mismatch"
    assert verdict.evidence[0].numeric_conflict is True


def test_wrong_amount_with_contradicting_nli_is_contradicted() -> None:
    verdict = verifier(ScriptedNLI({"18,000": CONTRADICTS})).verify_claim(
        "The monthly rent is INR 18,000.", [citation()], EVIDENCE
    )
    assert verdict.status is VerificationStatus.CONTRADICTED


def test_correct_amount_is_supported() -> None:
    verdict = verifier(ScriptedNLI({"15,000": ENTAILS})).verify_claim(
        "The monthly rent is INR 15,000.",
        [citation()],
        EVIDENCE,
    )
    assert verdict.status is VerificationStatus.SUPPORTED
    assert verdict.entailment_score == pytest.approx(0.95)
    assert verdict.contradiction_score == pytest.approx(0.02)


# -- semantic classes ------------------------------------------------------


def test_neutral_evidence_is_insufficient() -> None:
    verdict = verifier(ScriptedNLI({"rent": NEUTRAL})).verify_claim(
        "The monthly rent is INR 15,000.", [citation()], EVIDENCE
    )
    assert verdict.status is VerificationStatus.INSUFFICIENT
    assert verdict.reason == "neutral_or_weak_evidence"


def test_contradicting_evidence_is_contradicted() -> None:
    verdict = verifier(ScriptedNLI({"German": CONTRADICTS})).verify_claim(
        "The lease is governed by German law.", [citation()], EVIDENCE
    )
    assert verdict.status is VerificationStatus.CONTRADICTED
    assert verdict.contradiction_score == pytest.approx(0.97)


def test_negation_mismatch_is_contradicted() -> None:
    premise = "The Tenant may not sublet the premises without written consent."
    evidence = [
        EvidenceRecord("c9", "d9", "lease.pdf", 1, premise)
    ]
    verdict = verifier(ScriptedNLI({"sublet": CONTRADICTS})).verify_claim(
        "The Tenant may sublet the premises.",
        [citation(chunk_id="c9", document_id="d9", quotation="may not sublet")],
        evidence,
    )
    assert verdict.status is VerificationStatus.CONTRADICTED


def test_below_threshold_entailment_is_insufficient() -> None:
    verdict = verifier(ScriptedNLI({"rent": WEAK})).verify_claim(
        "The monthly rent is INR 15,000.", [citation()], EVIDENCE
    )
    assert verdict.status is VerificationStatus.INSUFFICIENT


def test_thresholds_are_configurable() -> None:
    relaxed = verifier(ScriptedNLI({"rent": WEAK}), entailment_threshold=0.5)
    verdict = relaxed.verify_claim(
        "The monthly rent is INR 15,000.", [citation()], EVIDENCE
    )
    assert verdict.status is VerificationStatus.SUPPORTED


# -- multiple evidence -----------------------------------------------------


def test_multiple_evidence_is_assessed_individually() -> None:
    nli = ScriptedNLI({"rent": ENTAILS, "notice": NEUTRAL})
    verdict = verifier(nli).verify_claim(
        "The monthly rent is INR 15,000.",
        [
            citation(),
            citation(
                chunk_id="c2",
                document_id="d2",
                filename="notices.pdf",
                page_number=2,
                quotation="registered post",
            ),
        ],
        EVIDENCE,
    )
    assert len(verdict.evidence) == 2
    assert verdict.status is VerificationStatus.SUPPORTED
    assert verdict.reason == "single_chunk_entails_claim"
    # one NLI call for the whole claim
    assert len(nli.calls) == 1


class _ConjunctionStub:
    """Neither chunk alone entails a two-fact claim; the pieces are not combined."""

    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def score_pairs(self, pairs):
        self.calls.append(list(pairs))
        return [NLIScores(entailment=0.30, neutral=0.65, contradiction=0.05) for _ in pairs]


def test_claim_spanning_two_chunks_is_not_supported() -> None:
    """Support must come from one chunk; separate facts are never combined."""
    nli = _ConjunctionStub()
    verdict = verifier(nli).verify_claim(
        "The monthly rent is INR 15,000 and notices go to Schedule 2.",
        [
            citation(),
            citation(
                chunk_id="c2",
                document_id="d2",
                filename="notices.pdf",
                page_number=2,
                quotation="registered post",
            ),
        ],
        EVIDENCE,
    )
    assert verdict.status is VerificationStatus.INSUFFICIENT


def test_contradiction_beats_entailment() -> None:
    nli = ScriptedNLI({"rent": ENTAILS, "notice": CONTRADICTS})
    verdict = verifier(nli).verify_claim(
        "Rent is 15,000 and notices go by email.",
        [
            citation(),
            citation(
                chunk_id="c2",
                document_id="d2",
                filename="notices.pdf",
                page_number=2,
                quotation="registered post",
            ),
        ],
        EVIDENCE,
    )
    assert verdict.status is VerificationStatus.CONTRADICTED
    assert verdict.reason == "evidence_contradicts_claim"


def test_nli_pairs_are_whitespace_normalised() -> None:
    """PDF line breaks must not hide a verbatim claim from the NLI model."""

    class RecordingNLI:
        def __init__(self) -> None:
            self.pairs: list[tuple[str, str]] = []

        def score_pairs(self, pairs):
            self.pairs.extend(pairs)
            return [ENTAILS for _ in pairs]

    nli = RecordingNLI()
    evidence = [
        EvidenceRecord(
            "c3",
            "d3",
            "lease.pdf",
            1,
            "The rent is INR 15,000,\ndue on the fifth day of each\ncalendar month.",
        )
    ]
    verdict = verifier(nli).verify_claim(
        "The rent is INR 15,000, due on the fifth day of each calendar month.",
        [citation(chunk_id="c3", document_id="d3", quotation="INR 15,000")],
        evidence,
    )

    assert nli.pairs == [
        (
            "The rent is INR 15,000, due on the fifth day of each calendar month.",
            "The rent is INR 15,000, due on the fifth day of each calendar month.",
        )
    ]
    assert verdict.status is VerificationStatus.SUPPORTED


def test_claims_are_verified_in_one_batch() -> None:
    nli = ScriptedNLI({"rent": ENTAILS, "German": CONTRADICTS})
    verdicts = verifier(nli).verify_claims(
        [
            ("The monthly rent is INR 15,000.", [citation()]),
            (
                "The lease is governed by German law.",
                [
                    citation(
                        chunk_id="c2",
                        document_id="d2",
                        filename="notices.pdf",
                        page_number=2,
                        quotation="registered post",
                    )
                ],
            ),
        ],
        EVIDENCE,
    )
    assert [verdict.status for verdict in verdicts] == [
        VerificationStatus.SUPPORTED,
        VerificationStatus.CONTRADICTED,
    ]
    assert len(nli.calls) == 1
    assert len(nli.calls[0]) == 2
    assert all(isinstance(verdict, ClaimVerification) for verdict in verdicts)

