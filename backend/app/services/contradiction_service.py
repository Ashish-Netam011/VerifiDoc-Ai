"""Conservative, provenance-preserving comparison of retrieved document facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import combinations

from app.services.retrieval_service import RetrievalResult

_SENTENCES = re.compile(r"(?<=[.!?;])(?=\s|$)|\n+")
_NUMBER = re.compile(r"(?<!\w)(?:[$€£]\s*)?\d[\d,]*(?:\.\d+)?\s*%?")
_DATE_PATTERN = (
    r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4})"
)
_DATE = re.compile(
    r"\b" + _DATE_PATTERN + r"\b",
    re.IGNORECASE,
)
_CONDITION = re.compile(
    r"\b(?:if|unless|provided that|subject to|only when|when|where|until)\b",
    re.IGNORECASE,
)
_AS_OF = re.compile(
    r"\b(?:as of|effective from|effective on|with effect from)\s+"
    r"(?P<date>" + _DATE_PATTERN + r")",
    re.IGNORECASE,
)
_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rent", re.compile(r"\brent\b", re.I)),
    ("deposit", re.compile(r"\bdeposit\b", re.I)),
    ("fee", re.compile(r"\b(?:fee|charge|fine|penalty|price|cost|salary|amount)\b", re.I)),
    ("rate", re.compile(r"\b(?:interest rate|rate|percentage)\b", re.I)),
    ("duration", re.compile(r"\b(?:notice period|duration|term|within)\b", re.I)),
    (
        "eligibility_limit",
        re.compile(
            r"\b(?:eligible|eligibility|applicants?|age|maximum|minimum|"
            r"qualification)\b",
            re.I,
        ),
    ),
    (
        "eligibility_limit",
        re.compile(
            r"\b(?:under|over|at least|no more than|not less than)\s+"
            r"\d+(?:\.\d+)?\s+(?:years?|yrs?)\b",
            re.I,
        ),
    ),
    ("effective_date", re.compile(r"\b(?:effective date|commencement date|valid from|expires on)\b", re.I)),
    ("deadline", re.compile(r"\b(?:deadline|due date|payable by|no later than)\b", re.I)),
)
_LEADING_FILLER = re.compile(
    r"^(?:(?:the|a|an|this|that|monthly|annual|yearly|total)(?:\s+|$))+",
    re.I,
)


@dataclass(frozen=True)
class FactSource:
    document_id: str
    filename: str
    page_number: int
    chunk_id: str
    quotation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "chunk_id": self.chunk_id,
            "quotation": self.quotation,
        }


@dataclass(frozen=True)
class CandidateFact:
    subject: str
    attribute: str
    value: str
    unit: str | None
    conditions: str | None
    relevant_date: str | None
    source: FactSource

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "attribute": self.attribute,
            "value": self.value,
            "unit": self.unit,
            "conditions": self.conditions,
            "relevant_date": self.relevant_date,
            "document_id": self.source.document_id,
            "filename": self.source.filename,
            "page_number": self.source.page_number,
            "chunk_id": self.source.chunk_id,
            "quotation": self.source.quotation,
        }


@dataclass(frozen=True)
class EvidencePair:
    document_id: str
    filename: str
    page_number: int
    quote: str

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class FactComparison:
    status: str
    conflict_id: str
    conflict_type: str
    subject: str
    evidence_a: EvidencePair
    evidence_b: EvidencePair
    analysis: str
    contradiction_score: float | None
    left: CandidateFact
    right: CandidateFact
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "conflict_id": self.conflict_id,
            "conflict_type": self.conflict_type,
            "subject": self.subject,
            "evidence_a": self.evidence_a.to_dict(),
            "evidence_b": self.evidence_b.to_dict(),
            "analysis": self.analysis,
            "contradiction_score": self.contradiction_score,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "reason": self.reason,
        }


def _normalise_condition(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.casefold().split())


def _subject_before(sentence: str, position: int) -> str:
    prefix_text = sentence[:position]
    condition_match = _CONDITION.search(prefix_text)
    if condition_match:
        comma = prefix_text.find(",", condition_match.end())
        prefix_text = (
            prefix_text[comma + 1:]
            if comma >= 0
            else prefix_text[condition_match.end():]
        )
    prefix = re.sub(r"[^A-Za-z0-9 ]", " ", prefix_text).casefold()
    prefix = _LEADING_FILLER.sub("", prefix.strip())
    words = prefix.split()
    while words and words[0] in {
        "the", "a", "an", "this", "that", "if", "unless", "when",
    }:
        words.pop(0)
    if not words:
        return "document terms"
    return " ".join(words[-3:])


def _unit(sentence: str, match: re.Match[str]) -> str | None:
    token = match.group(0)
    if "%" in token or re.search(r"\bpercent(?:age)?\b", sentence, re.I):
        return "%"
    if any(symbol in token for symbol in "$€£"):
        return next(symbol for symbol in "$€£" if symbol in token)
    currency = re.search(r"\b(INR|USD|EUR|GBP|rupees?|dollars?|euros?)\b", sentence, re.I)
    if currency:
        return currency.group(1).upper()
    duration = re.search(r"\b(days?|weeks?|months?|years?)\b", sentence, re.I)
    return duration.group(1).casefold() if duration else None


def extract_candidate_facts(result: RetrievalResult) -> list[CandidateFact]:
    """Extract only explicit dates and numeric statements from retrieved text."""
    facts: list[CandidateFact] = []
    chunk_date_matches = list(_AS_OF.finditer(result.text))
    chunk_relevant_date = None
    if len(chunk_date_matches) == 1:
        raw_date = chunk_date_matches[0].group("date")
        chunk_relevant_date = _normalise_date(raw_date) or raw_date

    for raw_sentence in _SENTENCES.split(result.text):
        sentence = raw_sentence.strip()
        if not sentence:
            continue

        date_match = _DATE.search(sentence)
        cue = next(
            ((name, pattern.search(sentence)) for name, pattern in _CUES if pattern.search(sentence)),
            None,
        )
        if cue:
            attribute, cue_match = cue
            assert cue_match is not None
            if attribute in {"effective_date", "deadline"} and date_match:
                value = date_match.group(0)
                unit = "date"
                value_position = date_match.start()
            else:
                value_match = _NUMBER.search(sentence, cue_match.end())
                if value_match is None:
                    value_match = _NUMBER.search(sentence, 0, cue_match.start())
                if value_match is None:
                    continue
                value = value_match.group(0).strip()
                unit = _unit(sentence, value_match)
                value_position = value_match.start()
        else:
            continue

        if not result.document_id or not result.chunk_id or result.page_number < 1:
            provenance = FactSource(
                result.document_id or "",
                result.filename or "",
                result.page_number,
                result.chunk_id or "",
                sentence,
            )
        else:
            provenance = FactSource(
                result.document_id, result.filename, result.page_number,
                result.chunk_id, sentence,
            )
        condition_match = _CONDITION.search(sentence)
        condition = (
            sentence[condition_match.start():].strip(" .;")
            if condition_match
            else None
        )
        as_of = _AS_OF.search(sentence)
        relevant_date = (
            (_normalise_date(as_of.group("date")) or as_of.group("date"))
            if as_of
            else chunk_relevant_date
        )
        facts.append(
            CandidateFact(
                subject=_subject_before(sentence, cue_match.start()),
                attribute=attribute,
                value=value,
                unit=unit,
                conditions=condition,
                relevant_date=relevant_date,
                source=provenance,
            )
        )
    return facts


def compare_facts(facts: list[CandidateFact]) -> list[FactComparison]:
    """Compare same-subject/attribute facts only across independent documents.

    Produces FactComparison objects with evidence_a/evidence_b pairs for
    side-by-side contradiction visualization.
    """
    comparisons: list[FactComparison] = []
    groups: dict[tuple[str, str], list[CandidateFact]] = {}
    for fact in facts:
        groups.setdefault(
            (fact.subject.casefold(), fact.attribute.casefold()), []
        ).append(fact)

    conflict_index = 0
    for grouped in groups.values():
        for left, right in combinations(grouped, 2):
            conflict_index += 1
            conflict_id = _generate_conflict_id(conflict_index)

            evidence_a = EvidencePair(
                document_id=left.source.document_id,
                filename=left.source.filename,
                page_number=left.source.page_number,
                quote=left.source.quotation,
            )
            evidence_b = EvidencePair(
                document_id=right.source.document_id,
                filename=right.source.filename,
                page_number=right.source.page_number,
                quote=right.source.quotation,
            )

            if (
                left.source.document_id
                and left.source.document_id == right.source.document_id
            ):
                comparisons.append(FactComparison(
                    status="consistent",
                    conflict_id=conflict_id,
                    conflict_type="same_document",
                    subject=left.subject,
                    evidence_a=evidence_a,
                    evidence_b=evidence_b,
                    analysis="Both facts are from the same document.",
                    contradiction_score=None,
                    left=left,
                    right=right,
                    reason="Same document; no cross-document conflict possible.",
                ))
                continue

            if not all(
                (
                    left.source.document_id,
                    right.source.document_id,
                    left.source.filename,
                    right.source.filename,
                    left.source.chunk_id,
                    right.source.chunk_id,
                )
            ) or left.source.page_number < 1 or right.source.page_number < 1:
                comparisons.append(FactComparison(
                    status="unresolved",
                    conflict_id=conflict_id,
                    conflict_type="missing_provenance",
                    subject=left.subject,
                    evidence_a=evidence_a,
                    evidence_b=evidence_b,
                    analysis="Cannot establish complete provenance for one or both documents.",
                    contradiction_score=None,
                    left=left,
                    right=right,
                    reason="Source provenance is incomplete.",
                ))
                continue

            is_amendment = _likely_amendment(left, right)

            if (
                _normalise_condition(left.conditions)
                != _normalise_condition(right.conditions)
                or not _same_relevant_period(
                    left.relevant_date, right.relevant_date
                )
            ):
                if is_amendment:
                    comparisons.append(FactComparison(
                        status="unresolved",
                        conflict_id=conflict_id,
                        conflict_type="potential_amendment",
                        subject=left.subject,
                        evidence_a=evidence_a,
                        evidence_b=evidence_b,
                        analysis=(
                            "The facts may represent an amendment relationship "
                            "(different effective dates or amendment indicators detected). "
                            "Cannot confirm a genuine contradiction without explicit amendment links."
                        ),
                        contradiction_score=None,
                        left=left,
                        right=right,
                        reason="Potential amendment relationship; conditions or periods differ.",
                    ))
                else:
                    comparisons.append(FactComparison(
                        status="unresolved",
                        conflict_id=conflict_id,
                        conflict_type="conflicting_conditions",
                        subject=left.subject,
                        evidence_a=evidence_a,
                        evidence_b=evidence_b,
                        analysis=(
                            "The conditions or relevant periods differ; "
                            "a conflict cannot be confirmed."
                        ),
                        contradiction_score=None,
                        left=left,
                        right=right,
                        reason="The conditions or relevant periods differ; a conflict cannot be confirmed.",
                    ))
                continue

            elif left.unit == right.unit == "date":
                left_date = _normalise_date(left.value)
                right_date = _normalise_date(right.value)
                if left_date is None or right_date is None:
                    comparisons.append(FactComparison(
                        status="unresolved",
                        conflict_id=conflict_id,
                        conflict_type="ambiguous_date",
                        subject=left.subject,
                        evidence_a=evidence_a,
                        evidence_b=evidence_b,
                        analysis="At least one date is ambiguous or could not be normalized.",
                        contradiction_score=None,
                        left=left,
                        right=right,
                        reason="At least one date is ambiguous or could not be normalized.",
                    ))
                elif left_date == right_date:
                    comparisons.append(FactComparison(
                        status="consistent",
                        conflict_id=conflict_id,
                        conflict_type="consistent_dates",
                        subject=left.subject,
                        evidence_a=evidence_a,
                        evidence_b=evidence_b,
                        analysis="Both documents state the same date.",
                        contradiction_score=None,
                        left=left,
                        right=right,
                        reason="Both documents state the same date.",
                    ))
                else:
                    comparisons.append(FactComparison(
                        status="confirmed_conflict",
                        conflict_id=conflict_id,
                        conflict_type="conflicting_dates",
                        subject=left.subject,
                        evidence_a=evidence_a,
                        evidence_b=evidence_b,
                        analysis=(
                            f"Documents state different dates for '{left.subject}': "
                            f"{left.value} vs {right.value}."
                        ),
                        contradiction_score=None,
                        left=left,
                        right=right,
                        reason="Documents state different dates for the same subject and attribute.",
                    ))
            elif _equivalent_value(left.value, right.value) and left.unit == right.unit:
                comparisons.append(FactComparison(
                    status="consistent",
                    conflict_id=conflict_id,
                    conflict_type="consistent_values",
                    subject=left.subject,
                    evidence_a=evidence_a,
                    evidence_b=evidence_b,
                    analysis="Both documents state the same value.",
                    contradiction_score=None,
                    left=left,
                    right=right,
                    reason="Both documents state the same value.",
                ))
            elif left.unit != right.unit or left.unit is None:
                comparisons.append(FactComparison(
                    status="unresolved",
                    conflict_id=conflict_id,
                    conflict_type="unit_mismatch",
                    subject=left.subject,
                    evidence_a=evidence_a,
                    evidence_b=evidence_b,
                    analysis=(
                        "The values use different or unknown units and cannot be safely compared."
                    ),
                    contradiction_score=None,
                    left=left,
                    right=right,
                    reason="The values use different or unknown units and cannot be safely compared.",
                ))
            else:
                if is_amendment:
                    comparisons.append(FactComparison(
                        status="unresolved",
                        conflict_id=conflict_id,
                        conflict_type="potential_amendment",
                        subject=left.subject,
                        evidence_a=evidence_a,
                        evidence_b=evidence_b,
                        analysis=(
                            "Different values detected but amendment indicators present. "
                            "This may represent an amendment rather than a genuine contradiction. "
                            "Verify against explicit amendment links before treating as conflict."
                        ),
                        contradiction_score=None,
                        left=left,
                        right=right,
                        reason="Potential amendment relationship; different values with amendment indicators.",
                    ))
                else:
                    comparisons.append(FactComparison(
                        status="confirmed_conflict",
                        conflict_id=conflict_id,
                        conflict_type="conflicting_amounts",
                        subject=left.subject,
                        evidence_a=evidence_a,
                        evidence_b=evidence_b,
                        analysis=(
                            f"Documents state different values for '{left.subject}': "
                            f"{left.value} {left.unit or ''} vs {right.value} {right.unit or ''}."
                        ),
                        contradiction_score=None,
                        left=left,
                        right=right,
                        reason="Documents state different explicit values for the same subject and attribute.",
                    ))
    return comparisons


def _same_relevant_period(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    left_date = _normalise_date(left)
    right_date = _normalise_date(right)
    return left_date is not None and left_date == right_date


def _equivalent_value(left: str, right: str) -> bool:
    try:
        left_number = Decimal(re.sub(r"[^\d.-]", "", left.replace(",", "")))
        right_number = Decimal(re.sub(r"[^\d.-]", "", right.replace(",", "")))
        return left_number == right_number
    except (InvalidOperation, ValueError):
        return left.casefold().strip() == right.casefold().strip()


def _normalise_date(value: str) -> str | None:
    value = value.strip()
    numeric = re.fullmatch(r"(\d{1,4})[/-](\d{1,2})[/-](\d{1,4})", value)
    if numeric:
        first, second, third = (int(part) for part in numeric.groups())
        if first >= 1000:
            formats = ("%Y-%m-%d", "%Y/%m/%d")
        else:
            if first <= 12 and second <= 12 and first != second:
                return None
            formats = (
                ("%d/%m/%Y", "%d-%m-%Y")
                if first > 12
                else ("%m/%d/%Y", "%m-%d-%Y")
                if second > 12
                else ("%d/%m/%Y", "%d-%m-%Y")
            )
    else:
        formats = (
            "%B %d, %Y",
            "%b %d, %Y",
            "%B %d %Y",
            "%b %d %Y",
            "%d %B %Y",
            "%d %b %Y",
        )

    for date_format in formats:
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _generate_conflict_id(index: int) -> str:
    return f"conflict_{index:03d}"


def _is_amendment_indicator(sentence: str) -> bool:
    amendment_keywords = [
        "amend", "amends", "amended", "amendment", "modifies", "supplements",
        "replaces", "supersedes", "repeals", "voids", "cancels",
    ]
    lower = sentence.casefold()
    return any(keyword in lower for keyword in amendment_keywords)


def _likely_amendment(fact_a: CandidateFact, fact_b: CandidateFact) -> bool:
    if fact_a.relevant_date != fact_b.relevant_date:
        if fact_a.relevant_date is not None or fact_b.relevant_date is not None:
            return True
    if _is_amendment_indicator(fact_a.source.quotation) or _is_amendment_indicator(fact_b.source.quotation):
        return True
    return False


def analyze_retrieval(results: list[RetrievalResult]) -> dict[str, object]:
    facts = [
        fact
        for result in results
        for fact in extract_candidate_facts(result)
    ]
    return {
        "facts": [fact.to_dict() for fact in facts],
        "comparisons": [item.to_dict() for item in compare_facts(facts)],
    }


__all__ = [
    "CandidateFact",
    "FactComparison",
    "FactSource",
    "analyze_retrieval",
    "compare_facts",
    "extract_candidate_facts",
]
