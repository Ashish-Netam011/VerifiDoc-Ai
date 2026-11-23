"""Sentence-level evidence accounting based on verified QA claims."""

from __future__ import annotations

import re
from typing import Any, Sequence

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" \t\r\n\"'`")


def answer_sentences(answer: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY.split(answer or "")
        if sentence.strip()
    ]


def calculate_faithfulness(
    answer: str,
    claims: Sequence[Any],
    *,
    decision: str,
) -> dict[str, Any]:
    """Count only answer sentences matching a verified claim with source evidence.

    Matching is deliberately exact after whitespace/case normalisation. A
    paraphrased sentence that cannot be linked confidently remains unsupported.
    """
    sentences = answer_sentences(answer)
    sentence_results: list[dict[str, Any]] = []
    supported_count = 0

    for sentence_index, sentence in enumerate(sentences):
        normalized_sentence = _normalise(sentence)
        claim_indices: list[int] = []
        evidence: list[dict[str, Any]] = []
        if decision != "abstain":
            for claim_index, claim in enumerate(claims):
                claim_text = str(getattr(claim, "text", "") or "")
                if normalized_sentence != _normalise(claim_text):
                    continue
                verification = getattr(claim, "verification", None)
                status = getattr(verification, "status", None)
                status_value = getattr(status, "value", status)
                sources = list(getattr(claim, "sources", []) or [])
                if status_value != "supported" or not sources:
                    continue
                source_records = []
                for source in sources:
                    quotation = str(getattr(source, "quotation", "") or "")
                    if not quotation:
                        continue
                    source_records.append(
                        {
                            "chunk_id": getattr(source, "chunk_id", ""),
                            "document_id": getattr(source, "document_id", ""),
                            "filename": getattr(source, "filename", ""),
                            "page_number": getattr(source, "page_number", 0),
                            "quotation": quotation,
                        }
                    )
                if source_records:
                    claim_indices.append(claim_index)
                    evidence.extend(source_records)

        supported = bool(claim_indices)
        if supported:
            supported_count += 1
        sentence_results.append(
            {
                "sentence_index": sentence_index,
                "sentence": sentence,
                "supported": supported,
                "claim_indices": claim_indices,
                "evidence": evidence,
            }
        )

    total = len(sentences)
    unsupported_count = total - supported_count
    score = (
        round(100 * supported_count / total, 2)
        if total and decision != "abstain"
        else None
    )
    return {
        "percentage": score,
        "total_sentence_count": total,
        "supported_sentence_count": supported_count,
        "unsupported_sentence_count": unsupported_count,
        "sentences": sentence_results,
        "metric_note": (
            "This measures sentence-to-verified-evidence linkage, not legal correctness."
        ),
    }


__all__ = ["answer_sentences", "calculate_faithfulness"]
