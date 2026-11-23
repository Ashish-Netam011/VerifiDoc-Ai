# ProofLens AI — Phase 2.3: Hybrid Retrieval Engine

Date: 2026-11-23
Scope: BM25 keyword search, semantic search reuse, Reciprocal Rank Fusion, and
`POST /api/search`. No answer generation, no citation verification, no frontend.

Results marked **Verified** were executed on this machine; anything else is stated
as an assumption or limitation.

---

## 1. Architecture

```
                    POST /api/search
                           |
                  RetrievalService.search
                    /                 \
        EmbeddingService            BM25Index
        (E5, query: prefix)      (rank_bm25, chunk text)
                    |                    |
           NumpyVectorStore        keyword ranking
          (cosine, persisted)
                    \                   /
                     ReciprocalRankFusion
                     score = Σ 1/(k+rank)
                              |
        chunk hydration from data/pdfs/<id>/chunks.json
                              |
            [{chunk_id, document_id, filename,
              page_number, text, semantic_score,
              bm25_score, rrf_score}]
```

Retrievers stay independent: each returns its own ranked chunk IDs and native
scores. Only the *ranks* are fused, so a bounded cosine similarity and an
unbounded BM25 score never need rescaling, and neither can dominate by scale.

## 2. Files created and modified

### Created

| File | Purpose |
|---|---|
| `backend/app/services/bm25_service.py` | Tokenizer, `BM25Index` (add/search/filter/remove/rebuild), process-wide lazy index |
| `backend/app/services/retrieval_service.py` | `RetrievalService`, `RetrievalResult`, `reciprocal_rank_fusion` |
| `backend/app/routers/search.py` | `POST /api/search` with request/response models |
| `backend/tests/test_bm25.py` | 9 keyword tests |
| `backend/tests/test_retrieval.py` | 15 fusion/API tests |
| `docs/PHASE_2_3_RETRIEVAL_REPORT.md` | This report |

### Modified

| File | Change |
|---|---|
| `backend/app/config.py` | `rrf_k` setting (`RRF_K`, default 60) |
| `backend/app/routers/documents.py` | After a successful catalogue write, the new chunks are added to the BM25 index; a BM25 failure is logged and never fails a stored upload |
| `backend/app/main.py` | Registers the search router, adds the `retrieval` tag, updates the API description and `/` links |
| `backend/tests/conftest.py` | Also patches the retrieval module's embedding getter and resets BM25/retrieval singletons per test |
| `backend/.env`, `backend/.env.example` | `RRF_K=60` |

No dependency was installed (`rank_bm25` was already present). No existing
endpoint contract, storage format or test was removed.

## 3. BM25 implementation

`BM25Index` keeps, per chunk: `chunk_id`, `document_id`, `filename`,
`page_number`, `text`, plus the token list. `rank_bm25.BM25Okapi` is rebuilt
lazily whenever the collection changes (`k1=1.5`, `b=0.75` defaults).

- `add_records()` skips blank or already-present chunk IDs, so the same chunk can
  never enter twice.
- `search(query, top_k, document_id=None)` scores the whole corpus, keeps only
  chunks that share at least one token with the query, filters by document when
  asked, then sorts by `(-score, chunk_id)` for deterministic output.
- Queries without usable tokens, or an empty index, return `[]`; a blank query
  raises `ValueError`.
- `remove_document()` removes only that document's chunks.
- `load_from_store()` rebuilds everything from the persisted chunk files.

### Tokenization

`(?:\d+(?:\.\d+)*)|(?:[a-z]+(?:'[a-z]+)?)` applied to lower-cased text:

| Input | Tokens |
|---|---|
| `Section 3.2, § 4.1.2, 1,200 EUR.` | `section`, `3.2`, `4.1.2`, `1`, `200`, `eur` |
| `RENT — Due!` | `rent`, `due` |

- Case, punctuation, `§`, currency symbols and dashes are separators, so
  "Rent", "rent" and "rent." match each other.
- Clause and section numbers keep their dotted form (`3.2`, `4.1.2`), which makes
  clause-number queries work exactly.
- Numbers stay searchable; thousands separators split (`1,200` → `1`, `200`),
  which is a deliberate simplicity trade-off, documented as a limitation.
- No stopword list: IDF already discounts frequent terms, and removing "the"
  would not help exact legal phrases.

## 4. RRF

```
rrf(chunk) = Σ_methods 1 / (RRF_K + rank_method(chunk))
```

- `rank` is 1-based; a chunk missing from a method simply contributes nothing.
- A chunk repeated inside one method's list contributes once, at its best rank.
- `RRF_K` is configurable (`RRF_K` env var, settings `rrf_k`, default **60**);
  the service accepts `rrf_k` per instance so tests can pin it.
- Final ordering: `rrf_score` desc → semantic rank → `chunk_id`, so equal scores
  never produce arbitrary ordering.
- Raw cosine and BM25 scores are preserved per hit and returned to the client.

## 5. Index synchronization

- **BM25** is in memory and rebuilt from the persisted chunk files on first use
  after any process start (lazy, single-process). No new BM25 file format is
  introduced; `chunks.json` stays the only source of truth, so the index cannot
  disagree with the stored text.
- **New uploads** are added incrementally after the catalogue write succeeds, so
  a failed upload (validation, extraction, embedding or vector indexing) never
  leaves a keyword-searchable entry. A BM25 add failure is logged and only
  degrades keyword search until the next restart, because the document is
  already durable and semantically indexed.
- **Vectors** continue to load from `data/indexes/vectors/vector_index.npz` on
  first use (Phase 2.2 behaviour, unchanged).
- **Removal** is scoped: `remove_document()` exists on both stores and touches
  only the given document. There is still no delete API (unchanged scope).
- Duplicate chunk IDs cannot produce duplicate hits: BM25 rejects them at insert
  time and retrieval de-duplicates by ID before fusing.

## 6. API

`POST /api/search`

```json
{
  "query": "What is the monthly rent payment?",
  "top_k": 5,
  "document_id": "fb480558b0514e159287950606ae065d"
}
```

`top_k` is optional (default 5, 1–50), `document_id` is optional (32-hex). Response:

```json
{
  "query": "What is the monthly rent payment?",
  "results": [
    {
      "chunk_id": "fb4805…:p0001:c0000",
      "document_id": "fb4805…",
      "filename": "commercial_lease.pdf",
      "page_number": 1,
      "text": "1. RENT\nThe Tenant shall pay the monthly rent of 1,450 EUR …",
      "semantic_score": 0.897277,
      "bm25_score": 4.457895,
      "rrf_score": 0.032787
    }
  ],
  "result_count": 1
}
```

Status codes: `200` (including an empty `results` list), `404` for an unknown
`document_id`, `422` for a blank query, `top_k` outside 1–50 or a malformed ID,
`503` when the embedding model is unavailable, `500` for index read failures.
No filesystem paths are returned; only chunk IDs, document IDs, filenames, page
numbers, text and scores.

## 7. Test results — Verified

```powershell
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

**64 passed, 0 failed** (12.1 s), exit code 0. Only warning: upstream `fitz`
deprecation.

| Requirement | Test(s) | Result |
|---|---|---|
| 1. Exact keyword matching | `test_exact_keyword_match` | pass — "monthly rent" → the rent chunk |
| 2. Clause-number retrieval | `test_clause_number_retrieval`, `test_search_by_clause_number` (API) | pass — `3.2` / `4.2` return the clause page only |
| 3. Semantic integration | `test_semantic_path_works_without_keyword_overlap`, `test_semantic_only_results_keep_bm25_score_null`, RRF service tests | pass |
| 4. RRF correctness | `test_rrf_scores_follow_the_formula`, `test_rrf_deduplicates_within_one_ranking`, `test_fusion_ranks_chunk_found_by_both_methods_first` | pass — exact `1/(k+rank)` sums |
| 5. Duplicate removal | `test_duplicate_chunks_appear_once_with_both_scores`, `test_duplicate_chunk_ids_are_ignored` | pass |
| 6. Empty query validation | service `ValueError` tests, `test_search_validation` (422) | pass |
| 7. Empty collection | `test_empty_corpus_returns_empty_list`, `test_empty_index_returns_no_results` | pass — `[]`, no error |
| 8. One method empty | `test_keyword_only_results_keep_semantic_score_null`, `test_semantic_only_results_keep_bm25_score_null` | pass |
| 9. Document filtering | `test_document_filter`, `test_document_filter_applies_to_both_methods`, `test_document_filter_via_api` | pass |
| 10. Persistence / restart | `test_rebuild_from_persisted_chunks`, `test_search_survives_restart` | pass |
| 11. New upload searchable | `test_search_returns_exact_phrase_hit` (upload → search) | pass |
| 12. Earlier suites intact | all 37 Phase 2.1/2.2 tests | pass |
| 13. Health / LLM intact | `test_phase1_endpoints_still_work` | pass |

Three test expectations were wrong on my side and were corrected, not worked
around: RRF for a chunk at rank 2 + rank 1 is `1/61 + 1/62` (not `2/61`), the
fusion fixture needed a per-document filename, and API tests now embed a unique
marker per upload because the shared test data directory accumulates documents
from other tests, so rank-1 assertions on keyword hits were measuring noise from
earlier uploads. API-level tests assert the keyword chunk is present with the
highest BM25 score in its document, rather than a global position that random
fake embeddings can disturb.

## 8. Live verification — Verified

Real model, real BM25, real data directory, 3-page commercial lease
(rent page, `4.2 Amendments`, `9. NOTICES`), uploaded through the API.

| Query | Result | Latency |
|---|---|---|
| `late payment attracts interest of 1% per month` (exact phrase) | page 1, rrf 0.03279, semantic 0.897, BM25 4.458 | 256 ms |
| `How much extra do I owe if I pay the rent late?` (paraphrase, no shared keywords with "interest") | page 1, rrf 0.03279, semantic 0.875, BM25 1.703 | 260 ms |
| `4.2` (clause number) | page 2, rrf 0.03279, semantic 0.812, BM25 0.562 | 279 ms |

Upload (extract → chunk → embed → vectors → BM25) took 10.0 s on a cold server,
including the one-off 4 s model load.

**Restart check:** the backend was stopped and restarted; the same three queries
returned the same pages and document ID, with identical scores (first search
9.8 s because the model loads again, then 285 ms / 280 ms). `/api/health` and
`/api/test-llm` both returned 200 afterwards. The test document, its vectors,
catalogue entry and temp files were then removed; the catalogue is empty and the
server was restarted clean.

## 9. Performance observations

Measured on this machine (CPU inference, 3-document chunk set):

| Operation | Value |
|---|---|
| Query embedding + semantic search + BM25 + fusion + hydration (warm) | 255–285 ms per request over HTTP |
| Same work in-process in Phase 2.2 (embedding + vector search) | ~26 ms |
| First search after restart | ~9.8 s (E5 load; BM25 rebuild over 3 chunks is negligible) |
| Upload incl. cold model load | ~10 s; ~5.5 s warm in Phase 2.2 measurement |

The gap between 26 ms in-process and ~270 ms over HTTP is not fully attributed;
likely contributors are a longer rewritten query, single-item encode overhead,
thread startup in `asyncio.to_thread`, and HTTP/test-client overhead. It is
recorded as measured, not explained further.

BM25 is O(N·terms) per query and vector search is O(N·D); both are trivially fast
at this corpus size and adequate for thousands of chunks.

## 10. Known limitations

- **BM25 is rebuilt in memory** at startup; there is no persisted BM25 file. Fine
  for thousands of chunks, and it guarantees the index matches the chunk files.
- **Single process only.** Two uvicorn workers would each hold their own BM25 and
  vector caches and could overwrite each other's vector index.
- **"1,200" is tokenized as `1` + `200`**, so a query for `1200` will not match it
  by keyword (semantic search still can).
- **No stemming or synonyms** in BM25; plural/singular rely on the semantic side.
- **No reranking or score thresholds.** Semantic search always returns its nearest
  neighbours, even for unrelated queries, so retrieval can return irrelevant
  chunks (with low scores) rather than an empty list.
- **No delete/re-index API.** Removal requires manual file work, as done in the
  verification for the test document.
- **Document filter over-fetches the whole vector index** when applied; correct but
  linear, and irrelevant at current scale.
- **Accuracy is not benchmarked.** Tests use small controlled corpora plus one
  three-page lease; they show the pipeline behaves as designed, not how well it
  performs on real case files.

## 11. Commands

```powershell
# tests
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m pytest tests -q

# run the API
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Swagger UI: `http://127.0.0.1:8000/docs` → `POST /api/search`.

---

## 12. Recommended next milestone

**Phase 2.4 — Evidence-grounded answering.** Take the top fused chunks, build a
strictly grounded prompt (question + numbered passages + page references) for
Qwen 2.5 3B, and return an answer with per-claim citations that point back to
`chunk_id`, document and page. Keep the retrieval response as the audit trail so
citation verification can be added as its own step.
