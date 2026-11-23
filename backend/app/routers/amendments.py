"""Read-only amendment-chain inspection and as-of-date resolution."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.amendment_service import build_amendment_report
from app.services.document_store import DocumentStore

router = APIRouter(prefix="/api/amendments", tags=["amendments"])


class AmendmentReportResponse(BaseModel):
    as_of_date: str | None = None
    amendments: list[dict[str, Any]] = Field(default_factory=list)
    chain_issues: list[dict[str, Any]] = Field(default_factory=list)
    resolutions: list[dict[str, Any]] = Field(default_factory=list)


@router.get(
    "",
    response_model=AmendmentReportResponse,
    summary="Inspect explicit amendment links",
    description=(
        "Returns amendment relationships only when source text explicitly names "
        "a target document. An as_of_date resolves a chain only when effective "
        "dates and links are unambiguous."
    ),
)
async def inspect_amendments(
    as_of_date: date | None = Query(
        default=None,
        description="Resolve each identified chain for this ISO calendar date.",
    ),
) -> AmendmentReportResponse:
    store = DocumentStore(get_settings().data_dir)
    documents = store.list_documents()
    chunks = {
        str(record["document_id"]): store.read_chunks(str(record["document_id"]))
        for record in documents
        if record.get("document_id")
    }
    report = build_amendment_report(
        documents,
        chunks,
        as_of_date=as_of_date,
    )
    return AmendmentReportResponse.model_validate(report)
