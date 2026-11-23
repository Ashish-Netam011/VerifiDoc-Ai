"""Citation integrity checks and NLI-based claim verification.

Two layers, deliberately separate:

1. **Integrity** (deterministic): does the citation point at a chunk the QA
   service actually supplied, with matching document, filename and page, and a
   quotation that really occurs in that chunk?
2. **Verification** (model-based): does the cited chunk, read as a premise,
   entail the generated claim as a hypothesis?

A citation that passes integrity is *real*; only the NLI step speaks to whether
it *supports* the claim. Neither step proves legal correctness.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable

from app.services.nli_service import NLIScores, NLIService, get_nli_service

logger = logging.getLogger(__name__)

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


class VerificationStatus(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    INVALID_CITATION = "invalid_citation"


class IntegrityFailure(str, Enum):
    UNKNOWN_CHUNK = "unknown_chunk"
    DOCUMENT_MISMATCH = "document_mismatch"
    FILENAME_MISMATCH = "filename_mismatch"
    PAGE_MISMATCH = "page_mismatch"
    EMPTY_QUOTATION = "empty_quotation"
    QUOTATION_NOT_IN_CHUNK = "quotation_not_in_chunk"


@dataclass(frozen=True)
class CitationRecord:
    """A citation as returned by the API (backend-built, but re-checked here)."""

    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    quotation: str


@dataclass(frozen=True)
class EvidenceRecord:
    """A chunk that was actually supplied to the language model."""

    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    text: str


@dataclass(frozen=True)
class IntegrityResult:
    valid: bool
    failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceAssessment:
    chunk_id: str
    entailment: float
    neutral: float
    contradiction: float
    numeric_conflict: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "entailment_score": round(self.entailment, 6),
            "neutral_score": round(self.neutral, 6),
            "contradiction_score": round(self.contradiction, 6),
            "numeric_conflict": self.numeric_conflict,
        }


@dataclass(frozen=True)
class ClaimVerification:
    status: VerificationStatus
    reason: str
    entailment_score: float | None = None
    neutral_score: float | None = None
    contradiction_score: float | None = None
    integrity_failures: list[str] = field(default_factory=list)
    evidence: list[EvidenceAssessment] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "entailment_score": (
                round(self.entailment_score, 6)
                if self.entailment_score is not None
                else None
            ),
            "neutral_score": (
                round(self.neutral_score, 6)
                if self.neutral_score is not None
                else None
            ),
            "contradiction_score": (
                round(self.contradiction_score, 6)
                if self.contradiction_score is not None
                else None
            ),
            "integrity_failures": list(self.integrity_failures),
            "evidence": [item.to_dict() for item in self.evidence],
        }


# -- deterministic helpers --------------------------------------------------


def extract_numbers(text: str) -> set[Decimal]:
    """Numeric literals in a text, normalised for comparison.

    Handles thousands separators and decimals: ``INR 15,000`` and ``15,000.00``
    both yield ``Decimal("15000")``. Percentages and clause numbers come through
    as their numeric part (``2%`` -> 2, ``4.2`` -> 4.2).
    """
    values: set[Decimal] = set()
    for match in NUMBER_RE.finditer(text or ""):
        raw = match.group(0).replace(",", "")
        try:
            values.add(Decimal(raw))
        except InvalidOperation:  # pragma: no cover - regex prevents this
            continue
    return values


def _normalise(text: str) -> str:
    """Collapse whitespace before NLI scoring.

    PDF extraction often breaks words across lines (``calendar m\\nonth``),
    which makes a verbatim claim look unrelated to its own chunk. Measurement
    on the live lease: raw chunk entailment 0.0026, whitespace-normalised
    0.9794. Citations and quotations are still checked against the raw text.
    """
    return " ".join(text.split())


def numeric_conflict(claim_text: str, premise_text: str) -> bool:
    """True when the claim states a number that the premise does not contain.

    This is intentionally conservative: a claim may not introduce figures that
    its cited evidence does not mention. It cannot catch numbers written as
    words ("fifth" vs "third"); NLI covers some of those cases.
    """
    claim_numbers = extract_numbers(claim_text)
    if not claim_numbers:
        return False
    return bool(claim_numbers - extract_numbers(premise_text))


def check_citation(
    citation: CitationRecord, evidence_by_chunk: dict[str, EvidenceRecord]
) -> IntegrityResult:
    """Validate a citation against the evidence actually supplied to the model."""
    record = evidence_by_chunk.get(citation.chunk_id)
    if record is None:
        return IntegrityResult(False, [IntegrityFailure.UNKNOWN_CHUNK.value])

    failures: list[str] = []
    if citation.document_id != record.document_id:
        failures.append(IntegrityFailure.DOCUMENT_MISMATCH.value)
    if citation.filename != record.filename:
        failures.append(IntegrityFailure.FILENAME_MISMATCH.value)
    if int(citation.page_number) != int(record.page_number):
        failures.append(IntegrityFailure.PAGE_MISMATCH.value)

    quotation = (citation.quotation or "").strip()
    if not quotation:
        failures.append(IntegrityFailure.EMPTY_QUOTATION.value)
    elif quotation not in record.text:
        failures.append(IntegrityFailure.QUOTATION_NOT_IN_CHUNK.value)

    return IntegrityResult(not failures, failures)


# -- verifier ---------------------------------------------------------------


class CitationVerifier:
    """Checks citation integrity, then verifies claims with NLI.

    Aggregation (documented, deterministic):

    * no citations, or any citation failing integrity -> ``invalid_citation``;
    * any cited chunk whose contradiction score >= threshold -> ``contradicted``;
    * any cited chunk whose entailment score >= threshold, without a numeric
      conflict and below the contradiction threshold -> ``supported``;
    * otherwise -> ``insufficient`` (neutral is never treated as support).

    A claim that needs several chunks combined must be supported by one of them
    on its own; pieces are never concatenated into a synthetic premise.
    """

    def __init__(
        self,
        nli: NLIService,
        *,
        entailment_threshold: float = 0.60,
        contradiction_threshold: float = 0.60,
    ) -> None:
        self._nli = nli
        self._entailment_threshold = entailment_threshold
        self._contradiction_threshold = contradiction_threshold

    @property
    def entailment_threshold(self) -> float:
        return self._entailment_threshold

    @property
    def contradiction_threshold(self) -> float:
        return self._contradiction_threshold

    def verify_claims(
        self,
        claims: Iterable[tuple[str, list[CitationRecord]]],
        evidence: Iterable[EvidenceRecord],
    ) -> list[ClaimVerification]:
        """Verify several claims in one NLI batch."""
        evidence_by_chunk = {item.chunk_id: item for item in evidence}
        claim_list = [(text, list(citations)) for text, citations in claims]

        # 1. Integrity + numeric checks (no model needed).
        integrity: list[list[IntegrityResult]] = []
        workers: list[tuple[int, int, EvidenceRecord]] = []
        conflicts: dict[tuple[int, int], bool] = {}
        for claim_index, (text, citations) in enumerate(claim_list):
            results: list[IntegrityResult] = []
            for citation_index, citation in enumerate(citations):
                result = check_citation(citation, evidence_by_chunk)
                results.append(result)
                record = evidence_by_chunk.get(citation.chunk_id)
                if result.valid and record is not None:
                    workers.append((claim_index, citation_index, record))
                    conflicts[(claim_index, citation_index)] = numeric_conflict(
                        text, record.text
                    )
            integrity.append(results)

        # 2. One NLI call for every valid (premise, hypothesis) pair.
        scores: dict[tuple[int, int], NLIScores] = {}
        if workers:
            pairs = [
                (_normalise(record.text), _normalise(claim_list[c][0]))
                for c, _, record in workers
            ]
            for (claim_index, citation_index, _), result in zip(
                workers, self._nli.score_pairs(pairs)
            ):
                scores[(claim_index, citation_index)] = result

        # 3. Aggregate per claim.
        return [
            self._aggregate(
                text,
                citations,
                integrity[claim_index],
                {
                    index: scores[(claim_index, index)]
                    for index in range(len(citations))
                    if (claim_index, index) in scores
                },
                conflicts,
                claim_index,
            )
            for claim_index, (text, citations) in enumerate(claim_list)
        ]

    def verify_claim(
        self, claim_text: str, citations: list[CitationRecord], evidence: Iterable[EvidenceRecord]
    ) -> ClaimVerification:
        return self.verify_claims([(claim_text, citations)], evidence)[0]

    # -- internals -----------------------------------------------------

    def _aggregate(
        self,
        claim_text: str,
        citations: list[CitationRecord],
        results: list[IntegrityResult],
        scores: dict[int, NLIScores],
        conflicts: dict[tuple[int, int], bool],
        claim_index: int,
    ) -> ClaimVerification:
        if not citations:
            return ClaimVerification(
                VerificationStatus.INVALID_CITATION, reason="no_citations"
            )

        failures = [
            failure for result in results for failure in result.failures
        ]
        if failures:
            return ClaimVerification(
                VerificationStatus.INVALID_CITATION,
                reason="citation_integrity_failed",
                integrity_failures=failures,
            )

        assessments: list[EvidenceAssessment] = []
        for index, citation in enumerate(citations):
            result = scores.get(index)
            if result is None:
                continue
            assessments.append(
                EvidenceAssessment(
                    chunk_id=citation.chunk_id,
                    entailment=result.entailment,
                    neutral=result.neutral,
                    contradiction=result.contradiction,
                    numeric_conflict=conflicts.get((claim_index, index), False),
                )
            )

        if not assessments:
            return ClaimVerification(
                VerificationStatus.INSUFFICIENT,
                reason="no_evidence_scored",
            )

        contradiction = max(
            assessments, key=lambda item: item.contradiction
        )
        if contradiction.contradiction >= self._contradiction_threshold:
            return self._with_scores(
                VerificationStatus.CONTRADICTED,
                reason="evidence_contradicts_claim",
                scores=contradiction,
                assessments=assessments,
            )

        entailing = [
            item
            for item in assessments
            if item.entailment >= self._entailment_threshold
            and item.contradiction < self._contradiction_threshold
            and not item.numeric_conflict
        ]
        if entailing:
            best = max(entailing, key=lambda item: item.entailment)
            return self._with_scores(
                VerificationStatus.SUPPORTED,
                reason="single_chunk_entails_claim",
                scores=best,
                assessments=assessments,
            )

        numeric = [item for item in assessments if item.numeric_conflict]
        if numeric:
            detail = "numeric_mismatch"
        else:
            detail = "neutral_or_weak_evidence"
        return self._with_scores(
            VerificationStatus.INSUFFICIENT,
            reason=detail,
            scores=max(assessments, key=lambda item: item.entailment),
            assessments=assessments,
        )

    @staticmethod
    def _with_scores(
        status: VerificationStatus,
        *,
        reason: str,
        scores: EvidenceAssessment,
        assessments: list[EvidenceAssessment],
    ) -> ClaimVerification:
        return ClaimVerification(
            status=status,
            reason=reason,
            entailment_score=scores.entailment,
            neutral_score=scores.neutral,
            contradiction_score=scores.contradiction,
            evidence=assessments,
        )


_verifier: CitationVerifier | None = None
_verifier_lock = threading.Lock()


def get_citation_verifier() -> CitationVerifier:
    """Process-wide verifier wired to the cached NLI model and config thresholds."""
    global _verifier
    if _verifier is None:
        with _verifier_lock:
            if _verifier is None:
                from app.config import get_settings

                settings = get_settings()
                _verifier = CitationVerifier(
                    get_nli_service(),
                    entailment_threshold=settings.nli_entailment_threshold,
                    contradiction_threshold=settings.nli_contradiction_threshold,
                )
    return _verifier


def reset_citation_verifier() -> None:
    global _verifier
    with _verifier_lock:
        _verifier = None


__all__ = [
    "CitationRecord",
    "CitationVerifier",
    "ClaimVerification",
    "EvidenceAssessment",
    "EvidenceRecord",
    "IntegrityFailure",
    "IntegrityResult",
    "VerificationStatus",
    "check_citation",
    "extract_numbers",
    "get_citation_verifier",
    "numeric_conflict",
    "reset_citation_verifier",
]
