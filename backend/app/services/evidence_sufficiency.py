"""Evidence sufficiency, question coverage and the abstention decision.

The contracts below are deterministic and inspectable. They answer three
questions, in order:

1. *Is there any evidence worth asking the model about?* (:meth:`precheck`)
2. *Which facts does the question ask for, and does the evidence establish
   them?* (:func:`analyse_coverage`)
3. *May the answer be shown, shown in part, or withheld?*
   (:meth:`EvidenceSufficiencyEngine.assess`)

Design rules that matter:

* **No sufficient evidence, no confident answer.** A high retrieval score never
  authorises an answer; claim verdicts from Phase 3.2 are the gate.
* **Coverage is derived lexically from a fixed slot vocabulary.** It is not a
  language-model decomposition: when no slot matches the question the coverage
  status is ``uncertain`` and the engine does not pretend to know what is
  missing.
* **NLI results are reused, never recomputed.** The engine consumes
  :class:`~app.services.citation_verifier.ClaimVerification` objects that the
  QA service already produced.
* **A contradiction is disclosed, never demoted to "insufficient".** Every
  contradicted claim becomes an entry in the gap report's ``conflicts`` list and
  blocks the answer.

Everything here is heuristic except the numeric checks, which are exact. The
phase report separates the two.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from app.services.bm25_service import tokenize
from app.services.citation_verifier import (
    ClaimVerification,
    EvidenceRecord,
    VerificationStatus,
    extract_numbers,
)
from app.services.retrieval_service import RetrievalResult

logger = logging.getLogger(__name__)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:])\s+|\n+")


# -- outcomes ---------------------------------------------------------------


class Decision(str, Enum):
    """What the engine permits the API to show."""

    ANSWER = "answer"
    PARTIAL_ANSWER = "partial_answer"
    ABSTAIN = "abstain"


class CoverageStatus(str, Enum):
    """State of one requested fact (a "slot") after verification."""

    SUPPORTED = "supported"
    UNVERIFIED = "unverified"
    MISSING = "missing"
    CONTRADICTED = "contradicted"
    INVALID_CITATION = "invalid_citation"
    CONDITION_MISSING = "condition_not_preserved"


# -- question coverage vocabulary -------------------------------------------


# A deliberately small, hand-written vocabulary. Each slot lists the phrasings
# it recognises in a question. Unknown topics produce no slot, which makes the
# coverage "uncertain" rather than inventing a requirement.
SLOT_PATTERNS: dict[str, tuple[str, ...]] = {
    "monthly_rent": (
        "monthly rent",
        "rent amount",
        "rental amount",
        "amount of rent",
        "monthly rental",
        "rent",
    ),
    "security_deposit": (
        "security deposit",
        "deposit amount",
        "advance payment",
        "deposit",
    ),
    "rent_due_date": (
        "rent due date",
        "due date",
        "rent due",
        "payment date",
        "day of the month",
        "when is the rent due",
    ),
    "landlord_income": (
        "annual income",
        "yearly income",
        "monthly income",
        "income of the landlord",
        "landlord's income",
        "landlord income",
        "income",
        "salary",
        "earnings",
    ),
    "notice_period": ("notice period", "termination notice", "notice"),
    "subletting": (
        "subletting",
        "sublet",
        "sublets",
        "assignment of the premises",
        "assign the premises",
    ),
    "late_payment": ("late fee", "late payment", "penalty", "interest"),
    "lease_term": (
        "lease term",
        "term of the lease",
        "duration of the lease",
        "tenancy period",
    ),
    "maintenance": ("maintenance", "repairs", "repair obligations"),
    "utilities": ("utilities", "electricity", "water charges", "utility bills"),
    "pets": ("pets", "pet policy", "keep a pet"),
    "governing_law": ("governing law", "jurisdiction", "which law"),
    "rent_increase": (
        "rent increase",
        "increase the rent",
        "escalation",
        "revision of rent",
    ),
    "occupants": ("occupants", "guests", "who may occupy"),
    "parking": ("parking", "parking space"),
    "termination": ("early termination", "termination", "terminate"),
}

SLOT_LABELS: dict[str, str] = {
    "monthly_rent": "the monthly rent",
    "security_deposit": "the security deposit",
    "rent_due_date": "the rent due date",
    "landlord_income": "the landlord's annual income",
    "notice_period": "the notice period",
    "subletting": "whether subletting is permitted",
    "late_payment": "late-payment charges",
    "lease_term": "the lease term",
    "maintenance": "maintenance obligations",
    "utilities": "utility charges",
    "pets": "the pet policy",
    "governing_law": "the governing law",
    "rent_increase": "rent increases",
    "occupants": "who may occupy the premises",
    "parking": "parking",
    "termination": "termination",
}

# Coverage matching vocabulary. Aliases above decide *what the question asks
# for*; these decide whether evidence or a claim *speaks about* the slot. They
# are matched as substrings of the normalised text, so "utilit" covers both
# "utility" and "utilities".
SLOT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "monthly_rent": ("rent", "rental"),
    "security_deposit": ("deposit", "advance"),
    "rent_due_date": ("due",),
    "landlord_income": ("income", "salary", "salaries", "earnings"),
    "notice_period": ("notice",),
    "subletting": ("sublet", "subletting", "assignment"),
    "late_payment": ("penalty", "interest", "late fee", "late payment"),
    "lease_term": ("lease term", "duration", "tenancy"),
    "maintenance": ("maintenance", "repair"),
    "utilities": ("utilit", "electricity", "water charge"),
    "pets": ("pet ", "pets"),
    "governing_law": ("governing law", "jurisdiction"),
    "rent_increase": ("escalation", "increase", "revision"),
    "occupants": ("occupant", "guest"),
    "parking": ("parking",),
    "termination": ("terminat",),
}

STOPWORDS = frozenset(
    """
    a about above after again all also am an and any are as at be been before
    between both but by can could did do does doing during each few for from
    further had has have having he her here hers him his how i if in into is it
    its itself may me might must my no nor not of off on once only or other our
    out over own same shall should so some such than that the their theirs them
    then there these they this those through to too under until up very was we
    were what when where which while who whom why will with would you your
    """.split()
)

# Words that make a clause a condition. The clause after the marker is what a
# faithful answer has to mention; see ``condition_not_preserved``.
CONDITION_MARKERS = (
    "conditioned on",
    "in the event that",
    "provided that",
    "prior written",
    "subject to",
    "only if",
    "without",
    "unless",
)

_MARKER_WORDS = frozenset(
    """
    without unless only if subject to provided that prior written conditioned
    on in the event shall must may will be is are of and or the a an any such
    """.split()
)

_ALIAS_CACHE: dict[str, re.Pattern[str]] = {}

MIN_RELEVANT_CHUNKS = 1
MIN_SEMANTIC_SCORE = 0.70
MAX_EVIDENCE_ITEMS = 8


def _alias_regex(alias: str) -> re.Pattern[str]:
    pattern = _ALIAS_CACHE.get(alias)
    if pattern is None:
        parts = [re.escape(part) for part in alias.split()]
        pattern = re.compile(r"(?<![a-z0-9])" + r"\s+".join(parts) + r"(?![a-z0-9])")
        _ALIAS_CACHE[alias] = pattern
    return pattern


def normalise_text(text: str) -> str:
    """Lower-case and collapse whitespace (matching the QA text handling)."""
    return " ".join((text or "").lower().split())


def phrase_present(text: str, alias: str) -> bool:
    """True when ``alias`` occurs in ``text`` as a whole phrase."""
    if not text or not alias:
        return False
    return _alias_regex(alias).search(normalise_text(text)) is not None


def slot_mentioned(text: str, slot: str) -> bool:
    """Does the text speak about ``slot``? (keyword-level coverage test)"""
    keywords = SLOT_KEYWORDS.get(slot, ())
    if not text or not keywords:
        return False
    lowered = normalise_text(text)
    return any(keyword in lowered for keyword in keywords)


def content_tokens(text: str) -> list[str]:
    """Tokens that carry meaning: no stopwords, no single stray letters."""
    return [
        token
        for token in tokenize(text)
        if token not in STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


def keyword_relevance(question_tokens: Sequence[str], chunk_text: str) -> float:
    """Share of the question's content tokens that the chunk also contains."""
    wanted = set(question_tokens)
    if not wanted:
        return 0.0
    present = set(content_tokens(chunk_text))
    if not present:
        return 0.0
    return len(wanted & present) / len(wanted)


def best_sentence(chunk_text: str, claim_text: str) -> str:
    """The sentence of ``chunk_text`` that shares most tokens with the claim."""
    if not chunk_text:
        return ""
    claim_terms = set(content_tokens(claim_text))
    best = ""
    best_score = -1
    for sentence in SENTENCE_SPLIT_RE.split(chunk_text):
        cleaned = sentence.strip()
        if not cleaned:
            continue
        score = len(claim_terms & set(content_tokens(cleaned)))
        if score > best_score:
            best, best_score = cleaned, score
    return best or chunk_text.strip()


def condition_not_preserved(claim_text: str, premise_text: str) -> bool:
    """True when the supporting sentence is conditional and the claim omits it.

    Heuristic: find a condition marker in the sentence that best matches the
    claim, take the distinctive words of the condition clause, and require at
    least one of them in the claim. "The tenant may sublet" against "shall not
    sublet without the Landlord's prior written consent" is flagged; "subletting
    requires the landlord's prior written consent" is not.
    """
    sentence = best_sentence(premise_text, claim_text)
    if not sentence:
        return False
    lowered = sentence.lower()
    claim_terms = set(content_tokens(claim_text))
    for marker in CONDITION_MARKERS:
        index = lowered.find(marker)
        if index == -1:
            continue
        clause = re.split(r"[.;\n]", sentence[index + len(marker) :])[0]
        distinctive = set(content_tokens(clause)) - _MARKER_WORDS
        # Fewer than two distinctive words means no usable condition: the chunk
        # often ends mid-clause ("... without the prio"), and flagging on that
        # fragment would reject a faithful answer. Measured live, Phase 3.3.
        if len(distinctive) < 2:
            continue
        return not (distinctive & claim_terms)
    return False


# -- question coverage ------------------------------------------------------


@dataclass(frozen=True)
class SlotMatch:
    name: str
    alias: str
    start: int
    end: int


def match_slots(question: str) -> list[SlotMatch]:
    """Slots named by the question, one match per slot (the longest alias).

    A match contained in a longer match of a different slot is discarded, so
    "when is the rent due" yields ``rent_due_date`` only, not ``rent`` too.
    """
    text = normalise_text(question)
    matches: list[SlotMatch] = []
    for name, aliases in SLOT_PATTERNS.items():
        best: tuple[str, re.Match[str]] | None = None
        for alias in aliases:
            found = _alias_regex(alias).search(text)
            if found is None:
                continue
            if best is None or (found.end() - found.start()) > (
                best[1].end() - best[1].start()
            ):
                best = (alias, found)
        if best is not None:
            alias, found = best
            matches.append(SlotMatch(name, alias, found.start(), found.end()))

    kept: list[SlotMatch] = []
    for match in matches:
        contained = any(
            other.name != match.name
            and other.start <= match.start
            and match.end <= other.end
            and (other.end - other.start) > (match.end - match.start)
            for other in matches
        )
        if not contained:
            kept.append(match)
    return kept


@dataclass(frozen=True)
class CitedSource:
    """A backend-owned source record, without the quotation."""

    chunk_id: str
    document_id: str
    filename: str
    page_number: int


@dataclass(frozen=True)
class ClaimView:
    """The part of a mapped claim the engine needs."""

    text: str
    verification: ClaimVerification | None = None
    sources: tuple[CitedSource, ...] = ()

    @property
    def status(self) -> VerificationStatus | None:
        return self.verification.status if self.verification is not None else None

    @property
    def is_supported(self) -> bool:
        return self.status is VerificationStatus.SUPPORTED


@dataclass(frozen=True)
class CoverageComponent:
    name: str
    label: str
    alias: str
    status: str
    claim_indices: tuple[int, ...] = ()
    evidence_chunk_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "matched_phrase": self.alias,
            "status": self.status,
            "evidence_chunk_ids": list(self.evidence_chunk_ids),
        }


@dataclass(frozen=True)
class QuestionCoverage:
    status: str  # "identified" | "uncertain"
    components: tuple[CoverageComponent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "components": [component.to_dict() for component in self.components],
        }


def _addressed_by(
    claim: ClaimView, slot: str, evidence_by_chunk: dict[str, EvidenceRecord]
) -> bool:
    """Does this claim speak about the slot?

    Either the claim text mentions it, or the sentence of a cited chunk that
    best matches the claim does (the model often says "it is due on the fifth"
    where the chunk says "due on the fifth day of each month").
    """
    if slot_mentioned(claim.text, slot):
        return True
    for source in claim.sources:
        record = evidence_by_chunk.get(source.chunk_id)
        if record is None:
            continue
        if slot_mentioned(best_sentence(record.text, claim.text), slot):
            return True
    return False


def analyse_coverage(
    question: str,
    evidence: Sequence[EvidenceRecord],
    claims: Sequence[ClaimView],
) -> QuestionCoverage:
    """Map the question's requested facts onto claim verdicts and evidence."""
    slots = match_slots(question)
    if not slots:
        return QuestionCoverage("uncertain")

    evidence_by_chunk = {record.chunk_id: record for record in evidence}
    components: list[CoverageComponent] = []
    for slot in slots:
        label = SLOT_LABELS.get(slot.name, slot.name.replace("_", " "))
        mentioned = [
            record.chunk_id
            for record in evidence
            if slot_mentioned(record.text, slot.name)
        ]
        addressed = [
            index
            for index, claim in enumerate(claims)
            if _addressed_by(claim, slot.name, evidence_by_chunk)
        ]
        addressed_claims = [claims[index] for index in addressed]
        statuses = [claim.status for claim in addressed_claims]

        if VerificationStatus.CONTRADICTED in statuses:
            status = CoverageStatus.CONTRADICTED
        elif any(claim.is_supported for claim in addressed_claims):
            conditional = any(
                condition_not_preserved(
                    claim.text,
                    evidence_by_chunk[source.chunk_id].text,
                )
                for claim in addressed_claims
                if claim.is_supported
                and claim.verification is not None
                and claim.verification.status is VerificationStatus.SUPPORTED
                for source in claim.sources
                if source.chunk_id in evidence_by_chunk
            )
            status = (
                CoverageStatus.CONDITION_MISSING
                if conditional
                else CoverageStatus.SUPPORTED
            )
        elif VerificationStatus.INVALID_CITATION in statuses:
            status = CoverageStatus.INVALID_CITATION
        elif addressed_claims:
            status = CoverageStatus.UNVERIFIED
        elif mentioned:
            status = CoverageStatus.UNVERIFIED
        else:
            status = CoverageStatus.MISSING

        components.append(
            CoverageComponent(
                name=slot.name,
                label=label,
                alias=slot.alias,
                status=status.value,
                claim_indices=tuple(addressed),
                evidence_chunk_ids=tuple(mentioned),
            )
        )
    return QuestionCoverage("identified", tuple(components))


# -- report structures ------------------------------------------------------


@dataclass(frozen=True)
class Conflict:
    kind: str
    claim_text: str
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    contradiction_score: float | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "claim_text": self.claim_text,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "contradiction_score": (
                round(self.contradiction_score, 6)
                if self.contradiction_score is not None
                else None
            ),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SupportingEvidence:
    description: str
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    claim_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "claim_text": self.claim_text,
        }


@dataclass(frozen=True)
class EvidenceGapReport:
    status: str
    reason: str
    missing_information: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = field(default_factory=list)
    coverage: QuestionCoverage = field(
        default_factory=lambda: QuestionCoverage("uncertain")
    )
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "missing_information": list(self.missing_information),
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
            "supporting_evidence": [
                evidence.to_dict() for evidence in self.supporting_evidence
            ],
            "coverage": self.coverage.to_dict(),
            "signals": dict(self.signals),
        }


@dataclass(frozen=True)
class SufficiencyAssessment:
    decision: Decision
    answer: str
    reason: str
    reason_text: str
    report: EvidenceGapReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "answer": self.answer,
            "reason": self.reason,
            "evidence_gap_report": self.report.to_dict(),
        }


@dataclass(frozen=True)
class PrecheckResult:
    """Outcome of the cheap, pre-generation relevance screen."""

    proceed: bool
    reason: str
    relevant_chunks: int = 0
    best_semantic_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proceed": self.proceed,
            "reason": self.reason,
            "relevant_chunks": self.relevant_chunks,
            "best_semantic_score": self.best_semantic_score,
        }


# -- messages ---------------------------------------------------------------

NO_EVIDENCE_MESSAGE = (
    "No relevant evidence was found in the indexed documents, so no answer "
    "can be given."
)

_MESSAGES: dict[str, str] = {
    "empty_corpus": NO_EVIDENCE_MESSAGE,
    "no_relevant_evidence": NO_EVIDENCE_MESSAGE,
    "no_claims": (
        "The generated answer contained no verifiable claim about the question, "
        "so no answer can be given."
    ),
    "insufficient_evidence": (
        "The available documents do not establish the requested information, so "
        "no answer can be given."
    ),
    "invalid_citations": (
        "The generated statements could not be tied to valid document citations, "
        "so no answer can be given."
    ),
    "contradictory_evidence": (
        "The generated answer conflicts with the cited evidence, so no answer is "
        "given. The conflict is listed in the evidence gap report."
    ),
    "conflicting_evidence": (
        "The retrieved documents state different values for the requested fact, "
        "so no single answer can be given."
    ),
    "qualification_not_preserved": (
        "The evidence states the answer only under a condition, and the "
        "generated answer did not preserve that condition, so no answer is given."
    ),
    "verification_unavailable": (
        "Claim verification is currently unavailable, so no verified answer can "
        "be given."
    ),
    "unverified_claims": (
        "The generated statements could not be verified against the evidence, so "
        "no answer can be given."
    ),
    "conservative_mode": (
        "Conservative mode is enabled and not every requested fact could be "
        "established, so no partial answer is shown."
    ),
}


def _reason_text(reason: str) -> str:
    return _MESSAGES.get(reason, "The available evidence is not sufficient to answer the question.")


def _join_labels(labels: list[str]) -> str:
    unique: list[str] = []
    for label in labels:
        if label and label not in unique:
            unique.append(label)
    if len(unique) <= 1:
        return unique[0] if unique else "the requested information"
    return ", ".join(unique[:-1]) + " and " + unique[-1]


def _missing_message(component: CoverageComponent) -> str:
    label = component.label
    status = component.status
    if status == CoverageStatus.MISSING.value:
        return f"The available documents do not establish {label}."
    if status == CoverageStatus.UNVERIFIED.value:
        return (
            f"The available documents mention {label}, but it could not be "
            "verified for this answer."
        )
    if status == CoverageStatus.INVALID_CITATION.value:
        return (
            f"The generated statement about {label} had no valid citation and was "
            "not accepted."
        )
    if status == CoverageStatus.CONTRADICTED.value:
        return f"The generated statement about {label} conflicts with the cited evidence."
    if status == CoverageStatus.CONDITION_MISSING.value:
        return (
            f"The evidence states {label} only under a condition that the "
            "generated answer did not preserve."
        )
    return f"The available documents do not establish {label}."


# -- engine -----------------------------------------------------------------


class EvidenceSufficiencyEngine:
    """Applies the decision policy to retrieval results and claim verdicts."""

    def __init__(
        self,
        *,
        min_relevant_chunks: int = MIN_RELEVANT_CHUNKS,
        min_semantic_score: float = MIN_SEMANTIC_SCORE,
        max_evidence: int = MAX_EVIDENCE_ITEMS,
        require_verification: bool = True,
        conservative_mode: bool = False,
    ) -> None:
        self._min_relevant_chunks = min_relevant_chunks
        self._min_semantic_score = min_semantic_score
        self._max_evidence = max_evidence
        self._require_verification = require_verification
        self._conservative_mode = conservative_mode

    # -- introspection -------------------------------------------------

    @property
    def min_relevant_chunks(self) -> int:
        return self._min_relevant_chunks

    @property
    def min_semantic_score(self) -> float:
        return self._min_semantic_score

    @property
    def require_verification(self) -> bool:
        return self._require_verification

    @property
    def conservative_mode(self) -> bool:
        return self._conservative_mode

    # -- stage 1: pre-generation screen --------------------------------

    def precheck(
        self, question: str, results: Sequence[RetrievalResult]
    ) -> PrecheckResult:
        """Decide whether there is anything worth generating from.

        Two independent gates: at least one chunk must share a content token
        with the question (or name a slot the question names), **and** it must
        not sit below the similarity floor. Abstaining here saves an LLM call;
        it never authorises an answer by itself.
        """
        if not results:
            return PrecheckResult(False, "empty_corpus")

        question_terms = content_tokens(question)
        slots = [slot.name for slot in match_slots(question)]
        best_semantic: float | None = None
        relevant = 0
        for result in results[: self._max_evidence]:
            if result.semantic_score is not None:
                best_semantic = (
                    result.semantic_score
                    if best_semantic is None
                    else max(best_semantic, result.semantic_score)
                )
            if keyword_relevance(question_terms, result.text) > 0:
                relevant += 1
            elif any(slot_mentioned(result.text, slot) for slot in slots):
                relevant += 1

        if relevant >= self._min_relevant_chunks:
            return PrecheckResult(True, "ok", relevant, best_semantic)

        if best_semantic is not None and best_semantic >= self._min_semantic_score:
            # High similarity without a single shared term is still suspicious,
            # but the final decision belongs to claim verification.
            return PrecheckResult(True, "ok", relevant, best_semantic)

        return PrecheckResult(False, "no_relevant_evidence", relevant, best_semantic)

    # -- stage 2: final decision ---------------------------------------

    def assess(
        self,
        question: str,
        *,
        evidence: Sequence[EvidenceRecord],
        claims: Sequence[ClaimView],
        verification_status: str,
        generated_answer: str | None,
        precheck: PrecheckResult | None = None,
    ) -> SufficiencyAssessment:
        """Apply the decision policy; the returned ``answer`` is what users see."""
        evidence = list(evidence)[: self._max_evidence]
        claims = list(claims)
        evidence_by_chunk = {record.chunk_id: record for record in evidence}

        if not evidence and not claims:
            reason = precheck.reason if precheck is not None else "no_claims"
            return self._abstain(
                question,
                reason,
                coverage=QuestionCoverage("uncertain"),
                evidence=evidence,
                claims=claims,
                verification_status=verification_status,
            )

        coverage = analyse_coverage(question, evidence, claims)
        conflicts = self._conflicts(claims, evidence_by_chunk, coverage)
        supported = [claim for claim in claims if claim.is_supported]
        components = list(coverage.components)
        supported_components = [
            component
            for component in components
            if component.status == CoverageStatus.SUPPORTED.value
        ]
        missing_components = [
            component
            for component in components
            if component.status
            in {
                CoverageStatus.MISSING.value,
                CoverageStatus.UNVERIFIED.value,
                CoverageStatus.INVALID_CITATION.value,
            }
        ]
        conditional = [
            component
            for component in components
            if component.status == CoverageStatus.CONDITION_MISSING.value
        ]
        contradicted_components = [
            component
            for component in components
            if component.status == CoverageStatus.CONTRADICTED.value
        ]

        supporting = [
            SupportingEvidence(
                description=claim.text,
                chunk_id=claim.sources[0].chunk_id,
                document_id=claim.sources[0].document_id,
                filename=claim.sources[0].filename,
                page_number=claim.sources[0].page_number,
                claim_text=claim.text,
            )
            for claim in supported
            if claim.sources
        ]

        def build(
            decision: Decision, answer: str, reason: str, *, signals: dict | None = None
        ) -> SufficiencyAssessment:
            missing_information = [_missing_message(c) for c in missing_components]
            if conditional:
                missing_information.extend(_missing_message(c) for c in conditional)
            if (
                coverage.status == "uncertain"
                and decision is not Decision.ANSWER
                and not missing_information
            ):
                missing_information.append(
                    "The requested information could not be matched to a specific "
                    "fact that the documents establish."
                )
            report = EvidenceGapReport(
                status=decision.value,
                reason=reason,
                missing_information=missing_information,
                conflicts=conflicts,
                supporting_evidence=supporting,
                coverage=coverage,
                signals={
                    "claims": len(claims),
                    "supported_claims": len(supported),
                    "contradicted_claims": sum(
                        1
                        for claim in claims
                        if claim.status is VerificationStatus.CONTRADICTED
                    ),
                    "invalid_claims": sum(
                        1
                        for claim in claims
                        if claim.status is VerificationStatus.INVALID_CITATION
                    ),
                    "unverified_claims": sum(
                        1 for claim in claims if claim.verification is None
                    ),
                    "coverage": coverage.status,
                    "relevant_chunks": (
                        precheck.relevant_chunks if precheck is not None else None
                    ),
                    "best_semantic_score": (
                        round(precheck.best_semantic_score, 6)
                        if precheck is not None
                        and precheck.best_semantic_score is not None
                        else None
                    ),
                    **(signals or {}),
                },
            )
            return SufficiencyAssessment(
                decision=decision,
                answer=answer,
                reason=reason,
                reason_text=_reason_text(reason),
                report=report,
            )

        # 1. Unverifiable answers are never shown as answers.
        if verification_status == "verification_unavailable" and self._require_verification:
            return build(
                Decision.ABSTAIN,
                _reason_text("verification_unavailable"),
                "verification_unavailable",
            )

        # 2. A disclosed contradiction always blocks the answer.
        if any(conflict.kind == "claim_contradiction" for conflict in conflicts):
            return build(
                Decision.ABSTAIN,
                self._contradiction_answer(conflicts),
                "contradictory_evidence",
            )

        # 3. A dropped qualification is not something to answer around.
        if conditional:
            return build(
                Decision.ABSTAIN,
                _reason_text("qualification_not_preserved"),
                "qualification_not_preserved",
            )

        # 4. Two documents giving different figures for one fact.
        if any(conflict.kind == "conflicting_amounts" for conflict in conflicts):
            return build(
                Decision.ABSTAIN,
                _reason_text("conflicting_evidence"),
                "conflicting_evidence",
            )

        if contradicted_components:
            return build(
                Decision.ABSTAIN,
                self._contradiction_answer(conflicts),
                "contradictory_evidence",
            )

        if not claims:
            return build(Decision.ABSTAIN, _reason_text("no_claims"), "no_claims")

        if not supported:
            all_invalid = all(
                claim.status is VerificationStatus.INVALID_CITATION for claim in claims
            )
            reason = "invalid_citations" if all_invalid else "insufficient_evidence"
            return build(Decision.ABSTAIN, _reason_text(reason), reason)

        if coverage.status == "uncertain":
            if len(supported) == len(claims):
                return build(
                    Decision.ANSWER,
                    (generated_answer or self._compose(supported)).strip(),
                    "all_claims_supported",
                    signals={"coverage_uncertain": True},
                )
            return self._partial_or_abstain(build, supported, missing_components, components)

        if not missing_components and len(supported_components) == len(components):
            return build(
                Decision.ANSWER,
                (generated_answer or self._compose(supported)).strip(),
                "all_requested_facts_supported",
            )

        if supported_components:
            return self._partial_or_abstain(
                build, supported, missing_components, components
            )

        reason = (
            "insufficient_evidence"
            if missing_components
            else "insufficient_evidence"
        )
        return build(Decision.ABSTAIN, _reason_text(reason), reason)

    # -- internals -----------------------------------------------------

    def _partial_or_abstain(
        self,
        build,
        supported: list[ClaimView],
        missing_components: list[CoverageComponent],
        components: list[CoverageComponent],
    ) -> SufficiencyAssessment:
        if self._conservative_mode:
            return build(
                Decision.ABSTAIN,
                _reason_text("conservative_mode"),
                "conservative_mode",
            )
        labels = [component.label for component in missing_components]
        answer = self._partial_answer(supported, labels)
        return build(
            Decision.PARTIAL_ANSWER,
            answer,
            "some_requested_facts_missing",
        )

    @staticmethod
    def _compose(claims: Sequence[ClaimView]) -> str:
        return " ".join(claim.text.strip() for claim in claims if claim.text.strip())

    @staticmethod
    def _partial_answer(claims: Sequence[ClaimView], labels: list[str]) -> str:
        body = " ".join(claim.text.strip() for claim in claims if claim.text.strip())
        if labels:
            addition = (
                f"The available documents do not establish {_join_labels(labels)}."
            )
            body = f"{body} {addition}".strip()
        return body

    @staticmethod
    def _contradiction_answer(conflicts: list[Conflict]) -> str:
        primary = next(
            (conflict for conflict in conflicts if conflict.kind == "claim_contradiction"),
            None,
        )
        text = _reason_text("contradictory_evidence")
        if primary is not None:
            text += (
                f" The claim \"{primary.claim_text}\" is contradicted by "
                f"{primary.filename} page {primary.page_number}."
            )
        return text

    def _conflicts(
        self,
        claims: Sequence[ClaimView],
        evidence_by_chunk: dict[str, EvidenceRecord],
        coverage: QuestionCoverage,
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []
        for claim in claims:
            if claim.status is not VerificationStatus.CONTRADICTED:
                continue
            strongest = None
            if claim.verification is not None and claim.verification.evidence:
                strongest = max(
                    claim.verification.evidence, key=lambda item: item.contradiction
                )
            source = None
            if strongest is not None:
                source = next(
                    (
                        candidate
                        for candidate in claim.sources
                        if candidate.chunk_id == strongest.chunk_id
                    ),
                    None,
                )
            if source is None and claim.sources:
                source = claim.sources[0]
            if source is None:
                continue
            conflicts.append(
                Conflict(
                    kind="claim_contradiction",
                    claim_text=claim.text,
                    chunk_id=source.chunk_id,
                    document_id=source.document_id,
                    filename=source.filename,
                    page_number=source.page_number,
                    contradiction_score=(
                        strongest.contradiction if strongest is not None else None
                    ),
                    detail=(
                        "The cited passage contradicts the generated statement."
                    ),
                )
            )

        for component in coverage.components:
            figures: list[tuple[ClaimView, CitedSource, set]] = []
            for claim in claims:
                if not claim.is_supported or not claim.sources:
                    continue
                if not _addressed_by(claim, component.name, evidence_by_chunk):
                    continue
                numbers = extract_numbers(claim.text)
                if not numbers:
                    continue
                figures.append((claim, claim.sources[0], numbers))
            document_ids = {source.document_id for _, source, _ in figures}
            if len(document_ids) < 2:
                continue
            first = figures[0][2]
            if all(numbers == first for _, _, numbers in figures[1:]):
                continue
            claim, source, _ = figures[0]
            conflicts.append(
                Conflict(
                    kind="conflicting_amounts",
                    claim_text=claim.text,
                    chunk_id=source.chunk_id,
                    document_id=source.document_id,
                    filename=source.filename,
                    page_number=source.page_number,
                    detail=(
                        f"Different documents state different figures for "
                        f"{component.label}."
                    ),
                )
            )

        seen: set[tuple[str, str, str]] = set()
        unique: list[Conflict] = []
        for conflict in conflicts:
            key = (conflict.kind, conflict.claim_text, conflict.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(conflict)
        return unique

    def _abstain(
        self,
        question: str,
        reason: str,
        *,
        coverage: QuestionCoverage,
        evidence: Sequence[EvidenceRecord],
        claims: Sequence[ClaimView],
        verification_status: str,
        signals: dict[str, Any] | None = None,
    ) -> SufficiencyAssessment:
        report = EvidenceGapReport(
            status=Decision.ABSTAIN.value,
            reason=reason,
            missing_information=[],
            conflicts=[],
            supporting_evidence=[],
            coverage=coverage,
            signals={
                "claims": len(claims),
                "verification_status": verification_status,
                **(signals or {}),
            },
        )
        return SufficiencyAssessment(
            decision=Decision.ABSTAIN,
            answer=_reason_text(reason),
            reason=reason,
            reason_text=_reason_text(reason),
            report=report,
        )


_engine: EvidenceSufficiencyEngine | None = None
_engine_lock = threading.Lock()


def get_evidence_sufficiency_engine() -> EvidenceSufficiencyEngine:
    """Process-wide engine configured from the environment."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from app.config import get_settings

                settings = get_settings()
                _engine = EvidenceSufficiencyEngine(
                    min_relevant_chunks=settings.evidence_min_relevant_chunks,
                    min_semantic_score=settings.evidence_min_semantic_score,
                    max_evidence=settings.evidence_max_items,
                    require_verification=settings.evidence_require_verification,
                    conservative_mode=settings.evidence_conservative_mode,
                )
    return _engine


def reset_evidence_sufficiency_engine() -> None:
    global _engine
    with _engine_lock:
        _engine = None


__all__ = [
    "ClaimView",
    "CitedSource",
    "Conflict",
    "CoverageComponent",
    "CoverageStatus",
    "Decision",
    "EvidenceGapReport",
    "EvidenceSufficiencyEngine",
    "PrecheckResult",
    "QuestionCoverage",
    "SLOT_KEYWORDS",
    "SLOT_LABELS",
    "SLOT_PATTERNS",
    "SufficiencyAssessment",
    "SupportingEvidence",
    "analyse_coverage",
    "best_sentence",
    "condition_not_preserved",
    "content_tokens",
    "get_evidence_sufficiency_engine",
    "keyword_relevance",
    "match_slots",
    "phrase_present",
    "reset_evidence_sufficiency_engine",
    "slot_mentioned",
]
