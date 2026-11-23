# ProofLens AI — Phase 2.2: Embedding Engine & Vector Store

Date: 2026-11-23
Scope: embeddings for ingested chunks, a NumPy cosine vector store, persistence, and
ingestion integration. No BM25, retrieval API, question answering, citation
verification or frontend work.

Every result marked **Verified** was executed on this machine; anything else is
labelled as an assumption or a limitation.

---

## 1. Files created and modified

### Created

| File | Purpose |
|---|---|
| `backend/app/services/embedding_service.py` | Lazy E5 loader, `passage:`/`query:` prefixes, normalised 384-d output, async helpers |
| `backend/app/services/vector_store.py` | `VectorStore` interface + `NumpyVectorStore` cosine backend, atomic `.npz` persistence, shared store registry |
| `backend/tests/test_embeddings.py` | Real-model tests: dimension, normalisation, prefixes, empty input, ranking smoke check |
| `backend/tests/test_vector_store.py` | Synthetic-vector tests: top-k, validation, metadata, persistence, model mismatch, corruption |
| `backend/tests/test_embedding_integration.py` | Upload → vectors → search wiring, persistence, embedding-failure rollback |
| `docs/PHASE_2_2_EMBEDDING_REPORT.md` | This report |

### Modified

| File | Change |
|---|---|
| `backend/app/config.py` | Added `embed_model` (`EMBED_MODEL`), `embed_dim` (`EMBED_DIM`, 384), `embed_batch_size` (`EMBED_BATCH_SIZE`, 16), `model_cache_dir` (from `HF_HOME`), resolved against `backend/`; shared path validator |
| `backend/app/routers/documents.py` | After chunking: embed passages off the event loop, index vectors, persist, roll back vectors if the catalogue write fails; 503 on embedding failure; upload description updated |
| `backend/tests/conftest.py` | Autouse deterministic fake embedding service for API tests; vector-store registry reset per test |
| `backend/app/services/vector_store.py` | (during test fixes) rows are normalised on `add`, so stored dot products are true cosine similarities |

No existing endpoint contract, response schema, dependency or test was removed.
No package was installed; `sentence-transformers` 6.3.0, `torch` 2.15.0+cpu and
`numpy` 2.5.5 were already in `backend/.venv`.

---

## 2. Model loading details

- Model: `intfloat/multilingual-e5-small`, dimension **384**.
- Cache: `E:\Desktop\ProofLens\data\models_cache` (≈1.0 GB with the NLI model), snapshot
  `models--intfloat--multilingual-e5-small/snapshots/614241f6…` containing
  `model.safetensors`, `config.json`, `1_Pooling/`.
- Loaded with `SentenceTransformer(..., cache_folder=<absolute model_cache_dir>,
  device="cpu", local_files_only=True)`. `local_files_only=True` is deliberate: a missing
  cache raises `EmbeddingModelError` with the cache path instead of silently fetching
  another checkpoint. **Verified**: the model loaded with no network access and no download.
- Device: CPU. `torch.cuda.is_available()` is **False** because the installed wheel is
  `torch 2.15.0+cpu`; GPU inference is not configured and not needed at this scale.
- Dimension is checked twice: against `EMBED_DIM` at load, and on the shape of every
  batch of returned vectors.
- Loading is lazy and guarded by a lock; the service is a process-wide singleton
  (`get_embedding_service()`), so the ~4 s load happens once per process, not per request.
- Prefixes are applied inside the service (`passage: ` for chunks, `query: ` for
  questions). Callers pass plain text, which prevents prefix drift between phases.
- Output is `float32`, L2-normalised (`normalize_embeddings=True` plus a defensive
  re-normalisation). Empty input returns a `(0, 384)` array; blank text raises `ValueError`.
- There is no fallback path: no random vectors, no alternate model, no dimension padding.

---

## 3. Vector store implementation

`VectorStore` (ABC) fixes the contract — `add`, `search`, `save`, `load`,
`remove_document`, `__len__`, `dimension`, `model_name` — so a FAISS backend can be
added later without touching retrieval callers.

`NumpyVectorStore` is the only backend and does exact cosine search:

- matrix `(N, 384)` `float32`; rows normalised on insert;
- search = `matrix @ query_normalised`, then `np.argsort(-scores, kind="stable")` —
  deterministic ordering with stable ties;
- dimension and finiteness are validated for both vectors and queries; zero query and
  `top_k <= 0` are rejected; an empty index returns `[]` instead of raising;
- duplicate or empty chunk IDs in one batch are rejected, and metadata must match the
  vector count;
- every mutation is under an `RLock`; the shared store is cached per
  `(index directory, model, dimension)`.

FAISS is **not** used: this machine blocks `_swigfaiss.pyd` via Windows Smart App
Control, as diagnosed in Phase 0. No security setting was changed and no DLL workaround
was attempted.

### Persistence format

`data/indexes/vectors/vector_index.npz` — a single compressed NumPy archive:

| Key | Content |
|---|---|
| `matrix` | `float32` array `(N, 384)` |
| `meta` | JSON string: `{version: 1, backend: "numpy", model, dimension, count, chunk_ids[], metadata[]}` |

Each metadata entry is `{chunk_id, document_id, page_number, filename}`. Storing vectors
and metadata in one file removes any chance of them drifting apart; `save()` writes a
temporary file in the same directory and `os.replace()`s it, so a crash cannot leave a
half-written index. `load()` rejects a wrong version, a different dimension, a different
model name, mismatched counts, or an unreadable archive (each with a specific error).

The document catalogue (`data/indexes/documents.json`) and per-document `chunks.json`
files are untouched by this phase and are never rewritten by the vector store.

---

## 4. Ingestion integration

`POST /api/documents/upload` now runs: validate → store file → extract (PyMuPDF) →
page-aware chunk → **embed** → **index vectors** → write catalogue record.

- The response schema is unchanged; `chunk_count` still counts chunks, and every chunk
  has exactly one vector.
- Embedding runs via `asyncio.to_thread`, so CPU-bound encoding does not block the event
  loop.
- Failure handling:
  - embedding error → `503` ("The document could not be embedded, so the upload was
    discarded."), the new upload directory is removed, no catalogue record is written;
  - vector store error → `500`, same cleanup;
  - catalogue write failure after vectors were added → this upload's vectors are removed
    and the index re-saved before the directory is discarded (only newly created data is
    ever removed).
- Previously stored documents and vectors are never touched by this cleanup path.

---

## 5. Test results — Verified

Command:

```powershell
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

Result: **37 passed, 0 failed** (11.6 s), exit code 0. Only warning is the upstream
`fitz` deprecation notice.

| Requirement | Test | Result |
|---|---|---|
| 1. Dimension is 384 | `test_embedding_dimension_is_384` (real model) | pass — `(1, 384) float32` |
| 2. Empty input | `test_empty_input_is_safe`, `test_blank_text_is_rejected` | pass — `(0,384)`; blank raises |
| 3. Prefixes | `test_e5_prefixes_are_used` — service output equals manual `passage:`/`query:` encoding, and the two differ | pass |
| 4. Normalised | `test_embeddings_are_normalized` — per-row norms ≈ 1.0 | pass |
| 5. Related ranks above unrelated | `test_related_passage_ranks_above_unrelated` (5 legal sentences, real model) | pass — rent passage ranked first for a rent question |
| 6. Dimension validation | `test_vector_dimension_is_validated` — add and query dimension mismatches | pass |
| 7. Top-k | `test_add_and_top_k_search` — `top_k=2` and `top_k>N` | pass |
| 8. Empty index | `test_empty_index_returns_no_results` | pass — `[]`, no error |
| 9. Persistence/reload | `test_persistence_roundtrip`, `test_vectors_survive_reload`, `test_load_refuses_other_model`, `test_corrupted_index_is_reported` | pass |
| 10. Metadata and chunk IDs | `test_metadata_and_chunk_ids_preserved`, `test_upload_indexes_vectors` | pass — page, document and filename preserved through search |
| 11. Ingestion suite intact | all 17 Phase 2.1 tests, unchanged | pass |
| 12. Phase 1 endpoints intact | `test_phase1_endpoints_still_work` | pass — `/`, `/api/health`, `/docs`, OpenAPI paths |

Additional tests: duplicate chunk IDs rejected, `remove_document` scoped to one document,
zero query rejected, embedding failure discards the upload (503, catalogue and `pdfs/`
unchanged).

**Not claimed:** these tests show the pipeline works and that E5 ranks a tiny controlled
set sensibly. They are not an accuracy or benchmark claim for real case documents.

---

## 6. Performance observations — measured on this machine

Hardware: Intel Core 5 210H, 16 GB RAM, RTX 3050 Laptop (unused), CPU inference.

| Measurement | Value |
|---|---|
| Model load from cache, first use | 4.01 s |
| Encode 3 short passages | 0.063 s |
| 16 chunk-sized passages (~800 chars) | 0.69 s total ≈ **43 ms/chunk** |
| Upload of a 3-page, 2.7 KB PDF (server, cold) — extract + chunk + embed + index | 9.5 s total, of which ~4 s was the one-off model load |
| Query embed + top-3 cosine search over 3 vectors | 25–27 ms |
| Index file, 3 × 384 vectors | 4,996 bytes |

Search itself is trivial at this scale; brute force over 10k chunks was measured at
≈2 ms per query in Phase 0 (NumPy), so the current design has headroom well past the
expected document count. Memory: the E5 model plus torch costs roughly 400–600 MB RSS
when loaded (observed via the Phase 0 NLI/embedding runs), which is comfortable here.

---

## 7. End-to-end verification — Verified

Against the running backend (`127.0.0.1:8000`, real model, real data directory):

1. Generated a 3-page lease PDF (rent / amendments / notices) in a temp directory.
2. `POST /api/documents/upload` → **201**, `page_count: 3`, `chunk_count: 3`.
3. `data/indexes/vectors/vector_index.npz` created with 3 vectors, model
   `intfloat/multilingual-e5-small`, dimension 384.
4. Search from a **separate process** (index reloaded from disk) with real query
   embeddings:
   - "When must the rent be paid?" → page 1 (`1. RENT …`), score 0.8819
   - "How can this agreement be amended?" → page 2 (`2. AMENDMENTS …`), score 0.8730
   - "Where should notices be delivered?" → page 3 (`3. NOTICES …`), score 0.8716
5. `GET /api/health` → 200 (`status: ok`, Ollama available); `POST /api/test-llm` → 200.
6. The smoke document, its PDF directory, catalogue record and vectors were then removed,
   and the server restarted, leaving `GET /api/documents` at `{"count": 0, "documents": []}`
   and an empty vector index.

---

## 8. Known limitations

- **No FAISS backend.** Exact NumPy search is O(N·D) per query; fine for thousands of
  chunks, and the interface allows a FAISS implementation later on a machine without
  Smart App Control.
- **Single-process store.** The registry caches one store per index directory in memory;
  multiple uvicorn workers would each hold their own copy and could overwrite each other's
  saves. Run one worker, as configured here.
- **No backfill.** Documents ingested before this phase would have no vectors; the real
  data directory is currently empty, so nothing needs backfilling now.
- **No delete or re-index endpoint.** Removing a document still requires manual file work
  (as done for the smoke test).
- **Model binding is strict.** Changing `EMBED_MODEL` makes the existing index unreadable
  by design (`VectorStoreError`); it must be rebuilt.
- **No deduplication.** Re-uploading a PDF re-embeds and re-indexes it under a new ID.
- **CPU only.** GPU use would need a CUDA torch wheel; not attempted.
- Chunks longer than E5's 512-token limit are truncated by the tokenizer (800-character
  chunks are well inside that limit in practice).
- Embedding quality is measured only by a small controlled ranking check, not by a
  labelled legal benchmark.

---

## 9. Commands

```powershell
# tests
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m pytest tests -q

# run the API
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Swagger UI: `http://127.0.0.1:8000/docs`.

---

## 10. Recommended next milestone

**Phase 2.3 — Hybrid retrieval API.** Add BM25 over the same chunk store, combine it with
the vector store (`rank_bm25` is already installed), and expose a read-only
`POST /api/search` returning chunk text, document ID, page number and both scores. That
gives later phases (grounded answering, citation verification, contradiction detection) a
stable retrieval contract to build on.
