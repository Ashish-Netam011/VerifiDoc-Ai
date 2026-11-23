"""Explicit document amendment-link extraction and conservative date resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

_RELATION = re.compile(
    r"\b(?:amendments?\s+to|amends?|amending|modifies?|supplements?)\b",
    re.IGNORECASE,
)
_EFFECTIVE = re.compile(
    r"\b(?:effective(?:\s+date)?|with effect from|takes effect|effective from)"
    r"\s*(?:on|from|as of)?\s*[:,-]?\s*"
    r"(?P<date>\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{4})",
    re.IGNORECASE,
)
_AMENDMENT_DATE = re.compile(
    r"\b(?:amendment\s+dated|amended\s+on|dated)\s*[:,-]?\s*"
    r"(?P<date>\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)
_CLAUSE = re.compile(
    r"\b(?:clause|section|article)\s+([A-Za-z0-9.-]+)", re.IGNORECASE
)
_SUBJECT = re.compile(
    r"\b(rent|deposit|payment|fee|interest|notice|eligibility|deadline|"
    r"term|duration|renewal|penalty|benefit)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?;])(?=\s|$)|\n+")


@dataclass(frozen=True)
class AmendmentEdge:
    amending_document_id: str
    amending_filename: str
    target_document_id: str | None
    target_reference: str
    effective_date: str | None
    effective_date_ambiguous: bool
    amendment_date: str | None
    affected_clause: str | None
    affected_subject: str | None
    source_document_id: str
    source_filename: str
    page_number: int
    chunk_id: str
    quotation: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "amending_document_id": self.amending_document_id,
            "amending_filename": self.amending_filename,
            "target_document_id": self.target_document_id,
            "target_reference": self.target_reference,
            "effective_date": self.effective_date,
            "effective_date_ambiguous": self.effective_date_ambiguous,
            "amendment_date": self.amendment_date,
            "affected_clause": self.affected_clause,
            "affected_subject": self.affected_subject,
            "source": {
                "document_id": self.source_document_id,
                "filename": self.source_filename,
                "page_number": self.page_number,
                "chunk_id": self.chunk_id,
                "quotation": self.quotation,
            },
            "status": self.status,
        }


@dataclass(frozen=True)
class AmendmentResolution:
    document_id: str
    document_filename: str | None
    applicable_document_id: str | None
    applicable_filename: str | None
    chain: list[str]
    chain_filenames: list[str]
    status: str
    superseded_clauses: dict[str, list[str]]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_filename": self.document_filename,
            "applicable_document_id": self.applicable_document_id,
            "applicable_filename": self.applicable_filename,
            "chain": self.chain,
            "chain_filenames": self.chain_filenames,
            "status": self.status,
            "superseded_clauses": self.superseded_clauses,
            "reason": self.reason,
        }


def _parse_date(raw: str | None) -> tuple[str | None, bool]:
    if not raw:
        return None, False
    value = raw.strip()
    formats = (
        "%Y-%m-%d", "%Y-%m-%d",
        "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
        "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
        "%d %B %Y", "%d %b %Y",
    )
    ambiguous = False
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", value):
        pieces = re.split(r"[/-]", value)
        first, second = int(pieces[0]), int(pieces[1])
        ambiguous = first <= 12 and second <= 12 and first != second
        if ambiguous:
            return None, True
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat(), ambiguous
        except ValueError:
            continue
    return None, ambiguous


def _document_targets(
    text: str, current_id: str, documents: list[dict[str, Any]]
) -> tuple[str | None, str]:
    match = _RELATION.search(text)
    if not match:
        return None, ""
    tail = text[match.end():].strip(" :,-")
    for document in documents:
        document_id = str(document.get("document_id") or "")
        filename = str(document.get("filename") or "")
        if not document_id or document_id == current_id:
            continue
        stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        for reference in (filename, stem, document_id):
            if reference and re.search(
                r"(?<![A-Za-z0-9])"
                + re.escape(reference)
                + r"(?![A-Za-z0-9])",
                tail,
                re.IGNORECASE,
            ):
                return document_id, reference

    reference = re.split(r"\b(?:with effect|effective|dated|on|from)\b|[,.;]", tail, maxsplit=1, flags=re.I)[0].strip()
    return None, reference


def extract_amendments(
    documents: list[dict[str, Any]],
    chunks_by_document: dict[str, list[dict[str, Any]]],
) -> list[AmendmentEdge]:
    """Find explicit amendment statements; filename recency is never sufficient."""
    edges: list[AmendmentEdge] = []
    for record in documents:
        amendment_id = str(record.get("document_id") or "")
        filename = str(record.get("filename") or "")
        for chunk in chunks_by_document.get(amendment_id, []):
            text = str(chunk.get("text") or "")
            relation_count = len(list(_RELATION.finditer(text)))
            amendment_dates = list(_AMENDMENT_DATE.finditer(text))
            for sentence in _SENTENCE.split(text):
                quote = sentence.strip()
                relation = _RELATION.search(quote)
                if not relation:
                    continue
                if (
                    re.search(r"\b[A-Za-z][A-Za-z0-9_]*_id\b", quote)
                    or re.search(r"\blinks?\s+an?\s+amendment\b", quote, re.I)
                ):
                    continue
                target_id, target_reference = _document_targets(
                    quote, amendment_id, documents
                )
                effective_match = _EFFECTIVE.search(quote)
                effective_date, effective_ambiguous = _parse_date(
                    effective_match.group("date") if effective_match else None
                )
                amendment_match = (
                    amendment_dates[0]
                    if relation_count == 1 and len(amendment_dates) == 1
                    else None
                )
                amendment_date, _ = _parse_date(
                    amendment_match.group("date") if amendment_match else None
                )
                clause_match = _CLAUSE.search(quote)
                subject_match = _SUBJECT.search(quote)
                status = (
                    "missing_target"
                    if not target_id
                    else "ambiguous_effective_date"
                    if effective_ambiguous
                    else "missing_effective_date"
                    if not effective_date
                    else "linked"
                )
                edges.append(
                    AmendmentEdge(
                        amending_document_id=amendment_id,
                        amending_filename=filename,
                        target_document_id=target_id,
                        target_reference=target_reference,
                        effective_date=effective_date,
                        effective_date_ambiguous=effective_ambiguous,
                        amendment_date=amendment_date,
                        affected_clause=clause_match.group(1) if clause_match else None,
                        affected_subject=(
                            subject_match.group(1).casefold()
                            if subject_match and not clause_match
                            else None
                        ),
                        source_document_id=amendment_id,
                        source_filename=filename,
                        page_number=int(chunk.get("page_number") or 0),
                        chunk_id=str(chunk.get("chunk_id") or ""),
                        quotation=quote,
                        status=status,
                    )
                )
    return edges


def _cycle_edges(edges: list[AmendmentEdge]) -> set[tuple[str, str]]:
    graph: dict[str, list[str]] = {}
    for edge in edges:
        if edge.target_document_id:
            graph.setdefault(edge.amending_document_id, []).append(
                edge.target_document_id
            )
    cyclic: set[tuple[str, str]] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            start = path.index(node)
            cycle = path[start:] + [node]
            cyclic.update(zip(cycle, cycle[1:]))
            return
        for target in graph.get(node, []):
            visit(target, path + [node])

    for node in graph:
        visit(node, [])
    return cyclic


def _resolve(
    document_id: str,
    as_of_date: date | None,
    edges: list[AmendmentEdge],
    cyclic: set[tuple[str, str]],
    filename_by_id: dict[str, str],
) -> AmendmentResolution:
    chain = [document_id]
    current = document_id
    seen = {current}
    superseded_clauses: dict[str, list[str]] = {}
    reason = ""

    while True:
        incoming = [
            edge for edge in edges
            if edge.target_document_id == current
        ]
        if any((edge.amending_document_id, current) in cyclic for edge in incoming):
            return AmendmentResolution(
                document_id=document_id,
                document_filename=filename_by_id.get(document_id, ""),
                applicable_document_id=None,
                applicable_filename=None,
                chain=chain,
                chain_filenames=[
                    filename_by_id.get(d, d) for d in chain
                ],
                status="circular_relationship",
                superseded_clauses=superseded_clauses,
                reason="Circular amendment relationship detected.",
            )

        undated = [
            edge for edge in incoming
            if edge.status in {"missing_effective_date", "ambiguous_effective_date"}
        ]
        if undated:
            return AmendmentResolution(
                document_id=document_id,
                document_filename=filename_by_id.get(document_id, ""),
                applicable_document_id=None,
                applicable_filename=None,
                chain=chain,
                chain_filenames=[
                    filename_by_id.get(d, d) for d in chain
                ],
                status="ambiguous_effective_date",
                superseded_clauses=superseded_clauses,
                reason="Effective date is missing or ambiguous.",
            )
        if as_of_date is not None:
            eligible = [
                edge for edge in incoming
                if edge.effective_date
                and date.fromisoformat(edge.effective_date) <= as_of_date
            ]
        else:
            eligible = [
                edge for edge in incoming
                if edge.effective_date
            ]

        # Check for overlapping amendments on the same clause
        if len(eligible) > 1:
            clause_groups: dict[str, list[AmendmentEdge]] = {}
            for edge in eligible:
                clause = edge.affected_clause or "document"
                clause_groups.setdefault(clause, []).append(edge)
            for clause, group in clause_groups.items():
                if len(group) > 1:
                    return AmendmentResolution(
                        document_id=document_id,
                        document_filename=filename_by_id.get(document_id, ""),
                        applicable_document_id=None,
                        applicable_filename=None,
                        chain=chain,
                        chain_filenames=[
                            filename_by_id.get(d, d) for d in chain
                        ],
                        status="overlapping_amendments",
                        superseded_clauses=superseded_clauses,
                        reason=(
                            f"Multiple amendments target clause '{clause}' "
                            f"with overlapping effective dates; cannot determine which applies."
                        ),
                    )

        if not eligible:
            return AmendmentResolution(
                document_id=document_id,
                document_filename=filename_by_id.get(document_id, ""),
                applicable_document_id=current,
                applicable_filename=filename_by_id.get(current, ""),
                chain=chain,
                chain_filenames=[
                    filename_by_id.get(d, d) for d in chain
                ],
                status="resolved" if len(chain) > 1 else "no_amendment",
                superseded_clauses=superseded_clauses,
                reason=(
                    "No applicable amendment found for this document."
                    if len(chain) == 1
                    else "Chain resolved; no further amendments apply."
                ),
            )

        latest_date = max(date.fromisoformat(edge.effective_date) for edge in eligible)
        latest = [
            edge for edge in eligible
            if date.fromisoformat(edge.effective_date) == latest_date
        ]
        if len(latest) != 1:
            return AmendmentResolution(
                document_id=document_id,
                document_filename=filename_by_id.get(document_id, ""),
                applicable_document_id=None,
                applicable_filename=None,
                chain=chain,
                chain_filenames=[
                    filename_by_id.get(d, d) for d in chain
                ],
                status="ambiguous_amendment",
                superseded_clauses=superseded_clauses,
                reason="Multiple amendments have the same effective date.",
            )

        next_id = latest[0].amending_document_id
        if next_id in seen:
            return AmendmentResolution(
                document_id=document_id,
                document_filename=filename_by_id.get(document_id, ""),
                applicable_document_id=None,
                applicable_filename=None,
                chain=chain + [next_id],
                chain_filenames=[
                    filename_by_id.get(d, d) for d in chain + [next_id]
                ],
                status="circular_relationship",
                superseded_clauses=superseded_clauses,
                reason="Circular amendment relationship detected.",
            )

        # Track superseded clauses from the current document
        if latest[0].affected_clause:
            superseded_clauses.setdefault(current, []).append(latest[0].affected_clause)

        chain.append(next_id)
        seen.add(next_id)
        current = next_id
        reason = f"Resolved as of {as_of_date.isoformat() if as_of_date else 'latest date'}."


def build_amendment_report(
    documents: list[dict[str, Any]],
    chunks_by_document: dict[str, list[dict[str, Any]]],
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    edges = extract_amendments(documents, chunks_by_document)
    cyclic = _cycle_edges(edges)
    edge_data = []
    for edge in edges:
        item = edge.to_dict()
        if edge.target_document_id and (
            edge.amending_document_id, edge.target_document_id
        ) in cyclic:
            item["status"] = "circular_relationship"
        edge_data.append(item)

    resolutions = []
    if as_of_date is not None:
        target_roots = {
                edge.target_document_id
                for edge in edges
                if edge.target_document_id
            }
        amending_documents = {
            edge.amending_document_id
            for edge in edges
            if edge.target_document_id
        }
        roots = sorted(
            target_roots
            | {
                str(doc.get("document_id"))
                for doc in documents
                if str(doc.get("document_id"))
                and str(doc.get("document_id")) not in amending_documents
            }
        )
        filename_by_id = {
            str(doc.get("document_id")): str(doc.get("filename") or "")
            for doc in documents
            if doc.get("document_id")
        }
        resolutions = [
            _resolve(document_id, as_of_date, edges, cyclic, filename_by_id)
            for document_id in roots
        ]
        resolutions = [r.to_dict() for r in resolutions]
    return {
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "amendments": edge_data,
        "chain_issues": [
            item for item in edge_data if item["status"] != "linked"
        ],
        "resolutions": resolutions,
    }


__all__ = [
    "AmendmentEdge",
    "build_amendment_report",
    "extract_amendments",
]
