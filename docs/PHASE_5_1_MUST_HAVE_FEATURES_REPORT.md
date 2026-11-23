# Phase 5.1 — Must-Have Feature Integration Report

## Summary

Implemented conservative, evidence-grounded MVPs for cross-document fact comparison, amendment tracking, structured PDF table extraction, and sentence-level faithfulness. The additions reuse the existing document store, retrieval, citation verification, and abstention paths. Existing E5, NLI, and Qwen models, verification thresholds, and `/api/ask` behavior were preserved.

These features are not guarantees that every conflict, amendment, or table will be detected or interpreted correctly. Users should verify the source quotations against the original documents.

## Feature status

| Feature | Status | Implementation and limitations |
|---|---|---|
| Cross-document contradiction detection | MVP implemented and tested | Extracts explicit numeric/date candidate facts with document, filename, page, chunk, and quotation provenance. Compares facts grouped by subject and attribute, retaining both source records. Same values are consistent; clear differences can be confirmed conflicts; conditions, periods, units, or provenance that prevent a safe comparison remain unresolved. Extraction is heuristic and does not provide general rule/eligibility normalization. |
| Amendment tracking and as-of-date resolution | MVP implemented and tested | Detects explicit amendment links, records dates, clause/subject and source evidence, traverses chains, and resolves only where dates and relationships are unambiguous. Missing targets, incomplete chains, ambiguous dates, and cycles are surfaced. It does not infer applicability from upload recency and may miss passive wording such as “amended by.” |
| Structured PDF table extraction | MVP implemented and tested | Uses existing PyMuPDF table detection; stores row/cell structure and provenance in per-document table records; renders detectable table text into the existing searchable extraction path. Incomplete structures are flagged for review, and ordinary text extraction remains available. Arbitrary PDF layouts are not guaranteed to extract reliably. |
| Sentence-level faithfulness | Implemented conservatively and tested | Reports the percentage and supported/unsupported counts, mapping answer sentences to verified claims and exact quotations. Only exact normalized sentence-to-claim matches with supported verification count. Empty/abstention answers have a null percentage; paraphrases may be undercounted. This is separate from NLI probability and evidence coverage, and is not a guarantee of legal correctness. |

## API and UI

- Added `POST /api/conflicts` for candidate fact comparisons.
- Added `GET /api/amendments?as_of_date=YYYY-MM-DD` for explicit links and optional as-of-date resolution.
- Added `GET /api/documents/{document_id}/tables` for extracted table records.
- Extended `/api/ask` responses additively with sentence-level faithfulness details; the existing answer, verification, and abstention behavior is unchanged.
- Added Compare and Amendments navigation/pages, side-by-side source presentation for conflict pairs, amendment-chain and resolution views, table display in document details, and sentence-level evidence inspection in answer results.
- Resolution records now include document filenames so the UI does not expose opaque document IDs in the as-of-date summary.

## Files created

- `backend/app/routers/amendments.py`
- `backend/app/routers/conflicts.py`
- `backend/app/services/amendment_service.py`
- `backend/app/services/contradiction_service.py`
- `backend/app/services/faithfulness_service.py`
- `backend/tests/test_amendment_service.py`
- `backend/tests/test_contradiction_service.py`
- `backend/tests/test_faithfulness_service.py`
- `backend/tests/test_feature_routes.py`
- `frontend/src/api/amendments.js`
- `frontend/src/api/conflicts.js`
- `frontend/src/pages/Amendments.jsx`
- `frontend/src/pages/Contradictions.jsx`

## Files modified

- `README.md` — added the AIML-02 compliance matrix and limitations.
- `backend/app/main.py`
- `backend/app/routers/documents.py`
- `backend/app/routers/qa.py`
- `backend/app/services/document_store.py`
- `backend/app/services/pdf_service.py`
- `backend/app/services/qa_service.py`
- `backend/tests/test_ingestion.py`
- `backend/tests/test_qa.py`
- `frontend/src/App.jsx`
- `frontend/src/api/documents.js`
- `frontend/src/components/AnswerPanel.jsx`
- `frontend/src/components/AppLayout.jsx`
- `frontend/src/components/DocumentDetails.jsx`
- `frontend/src/hooks/useAsk.js`
- `frontend/src/hooks/useDocumentDetails.js`
- `frontend/tests/api.test.mjs`
- `frontend package manifests and lockfiles: unchanged`

The Phase 5.0 runtime configuration/model-loading changes and reports were already present in the worktree and were not part of this phase's changes.

## Verification

Test groups were run in isolated commands; counts below are group-specific and are not summed because some ingestion coverage overlaps:

| Group | Result |
|---|---|
| New feature and affected ingestion tests (`test_contradiction_service.py`, `test_amendment_service.py`, `test_faithfulness_service.py`, `test_feature_routes.py`, `test_ingestion.py`) | **53 passed, 0 failed, 0 skipped**; one existing PyMuPDF `fitz` deprecation warning. |
| Existing core retrieval, QA, evidence sufficiency, abstention, and citation verification tests | **120 passed** in the previously completed isolated run. |
| Cached real E5/NLI loading and inference tests | **17 passed** in the previously completed isolated run. |
| Frontend test suite | **33 passed, 0 failed, 0 skipped**. |
| Frontend production build | **Passed**; Vite transformed 1,615 modules. |
| Frontend lint | **Not run successfully**: `npm run lint` exits because `eslint` is not installed/available. No package was installed. |

The second and third groups were completed before the final filename-display adjustment; the affected amendment service tests were included in the later 53-test run.

## Live verification

The backend and frontend were run on loopback only. No public model endpoint was enabled.

| Check | Result |
|---|---|
| `GET /api/health` | HTTP 200; health `ok`, Ollama available, `qwen2.5:3b-instruct` present. |
| `GET /api/documents` | HTTP 200; 5 documents listed. |
| `POST /api/search` | HTTP 200; 3 results in the earlier smoke check. |
| `GET /api/documents/{id}/tables` | HTTP 200; 0 tables for the selected architecture PDF. Other table layouts were exercised by extraction tests. |
| `POST /api/conflicts` | HTTP 200; the live query produced no candidate facts or comparisons. This does not establish that the corpus contains no contradictions. |
| `GET /api/amendments?as_of_date=2025-01-01` | HTTP 200; 0 explicit amendment links and 5 base-document resolutions. The live UI showed filenames and single-document chains. |
| Supported `/api/ask` question | HTTP 200; a grounded answer passed existing verification. Its two-sentence output scored **50%** because only one sentence matched a verified claim. |
| Unsupported `/api/ask` question | HTTP 200; abstained; faithfulness percentage was null and the sentence remained unsupported. |
| Contradiction-shaped `/api/ask` probe | HTTP 200; abstained without making an unsupported claim. |
| Browser UI | Compare and Amendments routes rendered; after Recheck, the health badge showed backend/model ready. Amendment inspection displayed the five document filenames. No JavaScript errors were observed; two React Router future-flag warnings were present. |

The available live corpus contained no explicit amendment statements and the selected PDF had no detectable tables, so those live checks validate the API and honest empty-state handling, not successful extraction of those structures from the corpus.

## Environment, dependencies, and repository state

- No packages were installed and no dependency manifests or lockfiles changed.
- No model was replaced or downloaded for this work.
- Data/index/model directories were not modified by the verification requests; the Git status for tracked `data/` paths was clean.
- Branch remained `main` at `89917b1`; no commit, push, branch switch, or history rewrite was performed.
- Existing Phase 5.0 worktree changes were left intact.

## Remaining limitations

1. Candidate fact and amendment extraction depend on explicit text and conservative heuristics; passive amendment language and unnormalized rule/eligibility semantics can be missed.
2. Table detection is layout-dependent. Review-required flags and the plain-text fallback remain important.
3. Exact faithfulness matching is conservative and can undercount semantically supported paraphrases.
4. The live corpus provided no amendment links and no table in the selected document; those live results are empty, not positive examples.
5. ESLint could not run because the executable is unavailable in the existing frontend dependencies.

## Readiness

The feature MVPs and regression tests are integrated, and the existing core and real-model test groups passed in their isolated runs. ProofLens is ready for **careful feature development**, with the heuristic and extraction limitations above understood. Do not treat the new comparison, amendment, table, or faithfulness outputs as comprehensive legal conclusions.
