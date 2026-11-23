"""Document ingestion API: upload, extraction, chunking and catalogue reads."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Path as PathParam, UploadFile, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.bm25_service import get_bm25_index
from app.services.chunking import Chunk, chunk_pages
from app.services.document_store import (
    DocumentStore,
    document_dir,
    utc_now_iso,
)
from app.services.embedding_service import (
    EmbeddingModelError,
    get_embedding_service,
)
from app.services.pdf_service import PDFExtractionError, extract_pdf
from app.services.vector_store import VectorStoreError, get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOCUMENT_ID_PATTERN = r"^[0-9a-f]{32}$"
READ_BLOCK_BYTES = 1 << 20  # 1 MiB streaming reads
SIGNATURE_HEAD_BYTES = 1024
MAX_FILENAME_LENGTH = 120

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")


# -- schemas -----------------------------------------------------------------


class ChunkModel(BaseModel):
    chunk_id: str = Field(description="Stable ID: <document_id>:p<page>:c<index>.")
    document_id: str
    page_number: int = Field(ge=1, description="1-indexed page the chunk came from.")
    text: str
    start_offset: int = Field(ge=0, description="Start offset within the page text.")
    end_offset: int = Field(ge=0, description="End offset within the page text.")


class DocumentMetadata(BaseModel):
    document_id: str
    filename: str = Field(description="Original filename as supplied by the client.")
    file_path: str = Field(description="Stored path relative to the data directory.")
    page_count: int
    uploaded_at: str = Field(description="ISO-8601 UTC upload timestamp.")
    status: str = Field(description="Processing status: 'processed' or 'failed'.")
    chunk_count: int
    file_size_bytes: int


class DocumentListResponse(BaseModel):
    count: int
    documents: list[DocumentMetadata]


class DocumentChunksResponse(BaseModel):
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    chunks: list[ChunkModel]


# -- helpers -----------------------------------------------------------------


def _original_basename(raw_name: str) -> str:
    """Strip any directory component, both separators, and control characters."""
    name = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch >= " " and ch != "\x7f").strip()
    return name


def _safe_stored_name(base_name: str) -> str:
    """Reduce a name to a harmless on-disk filename that always ends in .pdf."""
    stem = base_name[:-4] if base_name.lower().endswith(".pdf") else base_name
    stem = _UNSAFE_FILENAME_CHARS.sub("_", stem).strip(" ._")
    if not stem:
        stem = "document"
    if len(stem) > MAX_FILENAME_LENGTH - 4:
        stem = stem[: MAX_FILENAME_LENGTH - 4]
    return f"{stem}.pdf"


def _discard(directory: Path) -> None:
    """Remove a partially written upload directory (never pre-existing data)."""
    shutil.rmtree(directory, ignore_errors=True)


def _looks_like_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            head = stream.read(SIGNATURE_HEAD_BYTES)
    except OSError:
        return False
    return b"%PDF-" in head


def _store(data_dir: Path) -> DocumentStore:
    return DocumentStore(data_dir)


def _to_metadata(record: dict[str, object]) -> DocumentMetadata:
    return DocumentMetadata(**record)  # type: ignore[arg-type]


def _require_document(document_id: str) -> tuple[DocumentStore, dict[str, object]]:
    data_dir = get_settings().data_dir
    store = _store(data_dir)
    record = store.get_document(document_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return store, record


# -- endpoints ---------------------------------------------------------------


@router.post(
    "/upload",
    response_model=DocumentMetadata,
    status_code=status.HTTP_201_CREATED,
    summary="Upload, extract, chunk and embed a PDF",
    description=(
        "Stores the PDF under the data directory, extracts text page by page "
        "with PyMuPDF, splits each page into overlapping chunks, embeds the "
        "chunks with the cached E5 model and indexes them in the vector store. "
        "Existing documents are never overwritten: every upload gets a fresh "
        "document ID and directory. If embedding or indexing fails, nothing "
        "from that upload is kept."
    ),
    responses={
        400: {"description": "Empty file or missing filename."},
        413: {"description": "File exceeds MAX_UPLOAD_MB."},
        415: {"description": "File is not a .pdf."},
        422: {"description": "Not a valid PDF, or no extractable text."},
        503: {"description": "The embedding model is unavailable."},
    },
)
async def upload_document(
    file: Annotated[UploadFile, File(description="A single PDF document.")],
) -> DocumentMetadata:
    settings = get_settings()
    data_dir = settings.data_dir

    original_name = _original_basename(file.filename or "")
    if not original_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A filename is required.",
        )
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only .pdf files are accepted.",
        )

    stored_name = _safe_stored_name(original_name)
    document_id = uuid4().hex
    target_dir = document_dir(data_dir, document_id)
    target_dir.mkdir(parents=True, exist_ok=False)
    target_path = target_dir / stored_name

    limit_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        try:
            with target_path.open("xb") as sink:
                while True:
                    block = await file.read(READ_BLOCK_BYTES)
                    if not block:
                        break
                    written += len(block)
                    if written > limit_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=(
                                "File exceeds the maximum upload size of "
                                f"{settings.max_upload_mb} MB."
                            ),
                        )
                    sink.write(block)
        finally:
            await file.close()

        if written == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file is empty.",
            )
        if not _looks_like_pdf(target_path):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The uploaded file is not a valid PDF (bad signature).",
            )

        try:
            extracted = extract_pdf(target_path, document_id, original_name)
        except PDFExtractionError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        if not extracted.has_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "The PDF contains no extractable text. Scanned documents "
                    "need OCR, which is not part of this phase."
                ),
            )

        chunks: list[Chunk] = chunk_pages(
            document_id,
            list(extracted.pages),
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No chunks could be produced from this PDF.",
            )

        store = _store(data_dir)
        store.write_chunks(document_id, chunks)

        embedding_service = get_embedding_service()
        try:
            vectors = await embedding_service.aembed_passages(
                [chunk.text for chunk in chunks]
            )
        except EmbeddingModelError as exc:
            logger.error("Embedding failed for %s: %s", document_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "The document could not be embedded, so the upload was "
                    f"discarded. {exc}"
                ),
            ) from exc

        vector_store = get_vector_store(
            data_dir,
            model_name=embedding_service.model_name,
            dimension=embedding_service.expected_dimension,
        )
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        chunk_metadata = [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": document_id,
                "page_number": chunk.page_number,
                "filename": original_name,
            }
            for chunk in chunks
        ]
        try:
            await asyncio.to_thread(
                vector_store.add, vectors, chunk_ids, chunk_metadata
            )
        except VectorStoreError as exc:
            logger.error("Vector indexing failed for %s: %s", document_id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The document embeddings could not be indexed.",
            ) from exc

        record = {
            "document_id": document_id,
            "filename": original_name,
            "file_path": target_path.relative_to(data_dir).as_posix(),
            "page_count": extracted.page_count,
            "uploaded_at": utc_now_iso(),
            "status": "processed",
            "chunk_count": len(chunks),
            "file_size_bytes": written,
        }
        try:
            store.add_document(record)
        except Exception:
            # Undo only the vectors this upload just added, then re-raise so
            # the upload directory is discarded as well.
            await asyncio.to_thread(vector_store.remove_document, document_id)
            await asyncio.to_thread(vector_store.save)
            raise

        # Keyword index last: the document is already durable, so a BM25 failure
        # degrades keyword search only and is fixed by the next process restart.
        try:
            get_bm25_index().add_records(
                [
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_id": document_id,
                        "filename": original_name,
                        "page_number": chunk.page_number,
                        "text": chunk.text,
                    }
                    for chunk in chunks
                ]
            )
        except Exception:  # noqa: BLE001 - never fail a stored upload for this
            logger.exception(
                "BM25 indexing failed for %s; keyword search will miss it until restart",
                document_id,
            )
    except HTTPException:
        _discard(target_dir)
        raise
    except OSError as exc:
        _discard(target_dir)
        logger.exception("Failed to store upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document could not be stored.",
        ) from exc
    except Exception:
        _discard(target_dir)
        raise

    logger.info(
        "Stored document %s (%s pages, %s chunks, %s vectors)",
        document_id,
        extracted.page_count,
        len(chunks),
        len(chunk_ids),
    )
    return _to_metadata(record)


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
    description="All processed documents, newest upload first.",
)
async def list_documents() -> DocumentListResponse:
    store = _store(get_settings().data_dir)
    records = store.list_documents()
    return DocumentListResponse(
        count=len(records),
        documents=[_to_metadata(record) for record in records],
    )


@router.get(
    "/{document_id}",
    response_model=DocumentMetadata,
    summary="Document metadata",
    responses={404: {"description": "Unknown document ID."}},
)
async def get_document(
    document_id: Annotated[str, PathParam(pattern=DOCUMENT_ID_PATTERN)],
) -> DocumentMetadata:
    _, record = _require_document(document_id)
    return _to_metadata(record)


@router.get(
    "/{document_id}/chunks",
    response_model=DocumentChunksResponse,
    summary="Document chunks",
    description="Chunks in deterministic order: page, then position on the page.",
    responses={404: {"description": "Unknown document ID."}},
)
async def get_document_chunks(
    document_id: Annotated[str, PathParam(pattern=DOCUMENT_ID_PATTERN)],
) -> DocumentChunksResponse:
    store, record = _require_document(document_id)
    chunks = store.read_chunks(document_id)
    return DocumentChunksResponse(
        document_id=document_id,
        filename=str(record.get("filename", "")),
        page_count=int(record.get("page_count", 0)),  # type: ignore[arg-type]
        chunk_count=len(chunks),
        chunks=[ChunkModel(**chunk) for chunk in chunks],  # type: ignore[arg-type]
    )
