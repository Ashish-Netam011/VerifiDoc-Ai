"""JSON-backed document catalogue and per-document chunk storage.

Deliberately file-based: one index file plus one chunk file per document. No
database is needed at this stage, and every write is atomic (temp file then
``os.replace``) so an interrupted process cannot leave a half-written index.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.services.chunking import Chunk

logger = logging.getLogger(__name__)

DocumentStatus = Literal["processed", "failed"]

INDEX_FILENAME = "documents.json"
CHUNKS_FILENAME = "chunks.json"
TABLES_FILENAME = "tables.json"


class DocumentStoreError(RuntimeError):
    """The on-disk catalogue is unreadable or inconsistent."""


def documents_dir(data_dir: Path) -> Path:
    """Directory holding one sub-directory per document."""
    return data_dir / "pdfs"


def index_dir(data_dir: Path) -> Path:
    return data_dir / "indexes"


def index_path(data_dir: Path) -> Path:
    return index_dir(data_dir) / INDEX_FILENAME


def document_dir(data_dir: Path, document_id: str) -> Path:
    return documents_dir(data_dir) / document_id


def utc_now_iso() -> str:
    """Timestamp with an explicit UTC offset.

    Microsecond resolution keeps "newest first" ordering unambiguous for
    uploads that happen within the same second.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


class DocumentStore:
    """Read/write access to the JSON catalogue."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._lock = threading.Lock()

    # -- index ---------------------------------------------------------

    def _read_index(self) -> dict[str, dict[str, Any]]:
        path = index_path(self.data_dir)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DocumentStoreError("The document index is unreadable.") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("documents"), list):
            raise DocumentStoreError("The document index has an unexpected shape.")
        records: dict[str, dict[str, Any]] = {}
        for entry in raw["documents"]:
            if isinstance(entry, dict) and entry.get("document_id"):
                records[str(entry["document_id"])] = entry
        return records

    def _write_index(self, records: dict[str, dict[str, Any]]) -> None:
        ordered = sorted(
            records.values(),
            key=lambda item: (str(item.get("uploaded_at", "")), str(item["document_id"])),
        )
        _atomic_write_json(
            index_path(self.data_dir),
            {"version": 1, "documents": ordered},
        )

    def list_documents(self) -> list[dict[str, Any]]:
        """Documents, newest first (uploaded_at desc, then document_id)."""
        records = self._read_index()
        return sorted(
            records.values(),
            key=lambda item: (
                str(item.get("uploaded_at", "")),
                str(item["document_id"]),
            ),
            reverse=True,
        )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self._read_index().get(document_id)

    def add_document(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert a record, refusing to replace an existing document ID."""
        document_id = str(record["document_id"])
        with self._lock:
            records = self._read_index()
            if document_id in records:
                raise DocumentStoreError("Document ID already exists.")
            records[document_id] = record
            self._write_index(records)
        return record

    # -- chunks --------------------------------------------------------

    def chunks_path(self, document_id: str) -> Path:
        return document_dir(self.data_dir, document_id) / CHUNKS_FILENAME

    def write_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        _atomic_write_json(
            self.chunks_path(document_id),
            {
                "document_id": document_id,
                "chunk_count": len(chunks),
                "chunks": [chunk.to_dict() for chunk in chunks],
            },
        )

    def read_chunks(self, document_id: str) -> list[dict[str, Any]]:
        path = self.chunks_path(document_id)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DocumentStoreError("The chunk file is unreadable.") from exc
        chunks = raw.get("chunks") if isinstance(raw, dict) else None
        if not isinstance(chunks, list):
            raise DocumentStoreError("The chunk file has an unexpected shape.")
        return [chunk for chunk in chunks if isinstance(chunk, dict)]

    def tables_path(self, document_id: str) -> Path:
        return document_dir(self.data_dir, document_id) / TABLES_FILENAME

    def write_tables(
        self, document_id: str, tables: list[dict[str, Any]]
    ) -> None:
        _atomic_write_json(
            self.tables_path(document_id),
            {"document_id": document_id, "table_count": len(tables), "tables": tables},
        )

    def read_tables(self, document_id: str) -> list[dict[str, Any]]:
        path = self.tables_path(document_id)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DocumentStoreError("The table extraction file is unreadable.") from exc
        tables = raw.get("tables") if isinstance(raw, dict) else None
        if not isinstance(tables, list):
            raise DocumentStoreError("The table extraction file has an unexpected shape.")
        return [table for table in tables if isinstance(table, dict)]
