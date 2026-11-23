"""Evidence-grounded question answering endpoint."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.services.document_store import DocumentStore, DocumentStoreError
from app.services.embedding_service import EmbeddingModelError
from app.services.llm_provider import (
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.services.qa_service import QAResponseError, get_qa_service
from app.services.reranker_service import RerankerError
from app.services.vector_store import VectorStoreError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["qa"])

DOCUMENT_ID_PATTERN = r"^[0-9a-f]{32}$"
MAX_TOP_K = 20
MAX_QUESTION_CHARS = 1000


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARS,
        description="Question to answer from the indexed documents.",
        examples=["What is the monthly rent?"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=MAX_TOP_K,
        description=f"Evidence items to retrieve (1-{MAX_TOP_K}).",
    )
    document_id: str | None = Field(
        default=None,
        pattern=DOCUMENT_ID_PATTERN,
        description="Restrict evidence to one document.",
    )

    @field_validator("question")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty or whitespace only")
        return value


class AskSource(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int = Field(ge=0, description="1-indexed source page.")
    quotation: str = Field(
        description="Exact excerpt of the retrieved chunk; chosen by the backend."
    )


class AskEvidenceAssessment(BaseModel):
    chunk_id: str
    entailment_score: float
    neutral_score: float
    contradiction_score: float
    numeric_conflict: bool = Field(
        description="The claim states a number this chunk does not contain."
    )


class AskVerification(BaseModel):
    status: Literal["supported", "contradicted", "insufficient", "invalid_citation"]
    reason: str
    entailment_score: float | None = None
    neutral_score: float | None = None
    contradiction_score: float | None = None
    integrity_failures: list[str] = Field(default_factory=list)
    evidence: list[AskEvidenceAssessment] = Field(default_factory=list)
    combined_evidence_chunk_ids: list[str] = Field(default_factory=list)


class AskClaim(BaseModel):
    text: str
    sources: list[AskSource] = Field(default_factory=list)
    verification: AskVerification | None = Field(
        default=None,
        description="NLI-based verdict for this claim, or null when unavailable.",
    )


class AskSupportingEvidence(BaseModel):
    description: str = Field(description="What the verified claim establishes.")
    chunk_id: str
    document_id: str
    filename: str
    page_number: int = Field(ge=0)
    claim_text: str


class AskConflict(BaseModel):
    kind: Literal["claim_contradiction", "conflicting_amounts"]
    claim_text: str
    chunk_id: str
    document_id: str
    filename: str
    page_number: int = Field(ge=0)
    contradiction_score: float | None = None
    detail: str = ""


class AskCoverageComponent(BaseModel):
    name: str
    label: str
    matched_phrase: str
    status: Literal[
        "supported",
        "unverified",
        "missing",
        "contradicted",
        "invalid_citation",
        "condition_not_preserved",
    ]
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class AskCoverage(BaseModel):
    status: Literal["identified", "uncertain"]
    components: list[AskCoverageComponent] = Field(default_factory=list)


class AskEvidenceGapReport(BaseModel):
    status: Literal["answer", "partial_answer", "abstain"]
    reason: str
    missing_information: list[str] = Field(default_factory=list)
    conflicts: list[AskConflict] = Field(default_factory=list)
    supporting_evidence: list[AskSupportingEvidence] = Field(default_factory=list)
    coverage: AskCoverage
    signals: dict[str, int | float | str | bool | None] = Field(
        default_factory=dict,
        description="Backend diagnostics used to reach the decision.",
    )


class AskSentenceEvidence(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    quotation: str


class AskFaithfulnessSentence(BaseModel):
    sentence_index: int
    sentence: str
    supported: bool
    claim_indices: list[int] = Field(default_factory=list)
    evidence: list[AskSentenceEvidence] = Field(default_factory=list)


class AskFaithfulness(BaseModel):
    percentage: float | None = None
    total_sentence_count: int = 0
    supported_sentence_count: int = 0
    unsupported_sentence_count: int = 0
    sentences: list[AskFaithfulnessSentence] = Field(default_factory=list)
    metric_note: str = (
        "This measures sentence-to-verified-evidence linkage, not legal correctness."
    )


class AskRetrieval(BaseModel):
    result_count: int = Field(description="Retrieved evidence items used for this answer.")


class AskResponse(BaseModel):
    question: str
    answer: str
    claims: list[AskClaim]
    limitations: list[str]
    retrieval: AskRetrieval
    model: str
    verification_status: Literal[
        "verified",
        "partially_verified",
        "not_verified",
        "contradicted",
        "verification_unavailable",
    ] = Field(
        default="not_verified",
        description=(
            "Aggregate NLI verdict. 'verified' means every claim was supported "
            "by its cited chunk; NLI scores are not calibrated legal confidence."
        ),
    )
    decision: Literal["answer", "partial_answer", "abstain"] = Field(
        default="abstain",
        description=(
            "Backend decision. 'answer' is shown only when every requested fact is "
            "supported by verified citations; 'partial_answer' contains only the "
            "supported claims; 'abstain' means no answer is justified."
        ),
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Requested facts the evidence does not establish.",
    )
    conflicts: list[AskConflict] = Field(
        default_factory=list,
        description="Contradictions found between a claim and its cited evidence.",
    )
    evidence_gap_report: AskEvidenceGapReport | None = Field(
        default=None,
        description="Structured explanation of the decision and its evidence.",
    )
    faithfulness: AskFaithfulness = Field(
        default_factory=AskFaithfulness,
        description=(
            "Sentence-level linkage to claims that passed citation integrity and NLI "
            "verification; this is not a legal correctness score."
        ),
    )


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Answer a question from retrieved document evidence",
    description=(
        "Retrieves evidence with the hybrid engine, sends selected evidence to "
        "the configured OpenRouter model, "
        "reranks a bounded RRF candidate set with a separate local relevance "
        "cross-encoder, answers using only that evidence, validates the model's "
        "JSON strictly, "
        "resolves the cited evidence labels to backend-owned source records "
        "(document, filename, page, exact excerpt), verifies each claim with the "
        "cached NLI model and applies the deterministic evidence-sufficiency "
        "policy: the answer is returned only when the retrieved evidence justifies "
        "it, otherwise a partial answer or an abstention with an evidence gap "
        "report is returned. Verdicts are NLI-based, not legal conclusions."
    ),
    responses={
        404: {"description": "The requested document_id does not exist."},
        422: {"description": "Blank question, bad top_k or malformed document_id."},
        502: {"description": "The language model returned an unusable response."},
        503: {
            "description": (
                "OpenRouter, embedding, or relevance-reranker model is unavailable."
            )
        },
        504: {"description": "The language model timed out."},
    },
)
async def ask(payload: AskRequest) -> AskResponse:
    settings = get_settings()

    if payload.document_id is not None:
        record = DocumentStore(settings.data_dir).get_document(payload.document_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            )

    service = get_qa_service()
    try:
        result = await service.answer(
            payload.question,
            top_k=payload.top_k,
            document_id=payload.document_id,
        )
    except LLMUnavailableError as exc:
        logger.warning("QA model unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMTimeoutError as exc:
        logger.warning("QA model timeout: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except LLMError as exc:
        logger.error("QA model error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The language model failed to produce a usable answer.",
        ) from exc
    except QAResponseError as exc:
        logger.warning("QA response rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The language model returned an unusable response. {exc}",
        ) from exc
    except EmbeddingModelError as exc:
        logger.error("QA embedding failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Retrieval is unavailable. {exc}",
        ) from exc
    except RerankerError as exc:
        logger.error("QA reranker unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Relevance reranking is unavailable. {exc}",
        ) from exc
    except (VectorStoreError, DocumentStoreError) as exc:
        logger.error("QA retrieval failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The indexed documents could not be searched.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return AskResponse(
        question=result.question,
        answer=result.answer,
        claims=[
            AskClaim(
                text=claim.text,
                sources=[
                    AskSource(
                        chunk_id=source.chunk_id,
                        document_id=source.document_id,
                        filename=source.filename,
                        page_number=source.page_number,
                        quotation=source.quotation,
                    )
                    for source in claim.sources
                ],
                verification=(
                    AskVerification.model_validate(claim.verification.to_dict())
                    if claim.verification is not None
                    else None
                ),
            )
            for claim in result.claims
        ],
        limitations=result.limitations,
        retrieval=AskRetrieval(result_count=len(result.retrieval)),
        model=result.model,
        verification_status=result.verification_status,
        decision=result.decision,
        missing_information=result.missing_information,
        conflicts=[
            AskConflict.model_validate(conflict) for conflict in result.conflicts
        ],
        evidence_gap_report=(
            AskEvidenceGapReport.model_validate(result.evidence_gap_report)
            if result.evidence_gap_report is not None
            else None
        ),
        faithfulness=AskFaithfulness.model_validate(result.faithfulness),
    )
