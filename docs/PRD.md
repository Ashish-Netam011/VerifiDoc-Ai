# VerifiDoc AI

## Product Requirements Document

**Document status:** Requirements and implementation baseline for the Hack-A-Sol 5.0 AIML Track, Problem Statement 02, Option B product

**Product name:** VerifiDoc AI

**Repository:** ProofLens

**Primary audience:** Project team, hackathon reviewers, evaluators, and prospective users

**Last updated:** 2026-11-23

**Source of truth for implementation status:** README and the verified Phase 5.2 final integration review

---

## 1. Executive Summary

VerifiDoc AI is a local, evidence-first document intelligence application for reviewing one or more PDF documents. It combines PDF extraction, semantic and keyword retrieval, bounded relevance reranking, local language-model generation, citation verification, abstention, contradiction analysis, amendment resolution, and structured table inspection.

Every answer is intended to lead to an inspectable source passage rather than rely only on model-generated prose. The system:

- Retrieves relevant text from uploaded PDFs.
- Drafts answer claims from retrieved evidence.
- Resolves citations to backend-owned document and page provenance.
- Uses an NLI model to verify claim support.
- Reranks a bounded RRF candidate pool with a separate local relevance model.
- Displays an answer, partial answer, or abstention based on evidence sufficiency.
- Presents candidate cross-document conflicts and amendment relationships as evidence aids.
- Keeps all document, model, and generated data on the local E: drive in the reference setup.

The product must remain conservative. It must not present unsupported, contradictory, or insufficient evidence as a verified answer. It is not a legal decision-making system and must not promise complete PDF coverage or legal correctness.

## 2. Problem Statement

Important details in agreements, policies, schedules, and amendments are often scattered across long PDFs. Existing document tools have several limitations:

- General-purpose AI answers may omit the exact source of a statement.
- Long documents make manual search slow and error-prone.
- Comparing multiple documents may miss changed terms or effective periods.
- A plausible response can appear confident even when supporting evidence is absent.
- Rule, table, and amendment data may be difficult to trace back to the original PDF.

VerifiDoc AI addresses these problems by making evidence retrieval and verification mandatory parts of the user workflow.

## 3. Product Goals

1. **Traceability:** Every displayed supported claim must identify the document, filename, page, chunk, and exact quotation.
2. **Zero guessing:** Unsupported, irrelevant, contradictory, or insufficient evidence must cause partial answer or abstention.
3. **Efficient review:** Semantic and keyword retrieval must help users find and compare relevant passages.
4. **Conflict visibility:** Candidate numeric, date, or eligibility conflicts must retain both source passages and remain unresolved when context is unclear.
5. **Version awareness:** Explicit amendment links and usable effective dates must support an as-of-date inspection.
6. **Table visibility:** Detectable tables must preserve page and cell provenance and must be searchable.
7. **Disclosed hosted inference:** Files and indexes remain local; when OpenRouter handles generation, question text and retrieved evidence are sent to OpenRouter/Google. Ollama fallback runs locally.
8. **Honest presentation:** MVP limitations and evidence uncertainty must be visible to users.

## 4. Success Metrics

The controlled acceptance targets are:

| Metric | Target |
|---|---|
| Valid PDF upload success | A valid text-based PDF is processed and listed successfully |
| Source-backed supported answer | Every claim in a supported answer resolves to a verified source quotation |
| Unsupported-answer abstention | Unsupported questions do not produce verified claims or unsupported conflicts |
| Global and scoped search | Search returns relevant results for the full corpus and a selected document |
| Conflict safety | Different subjects, conditions, periods, or missing provenance remain unresolved |
| Amendment safety | Explicit and unambiguous links resolve by effective date; ambiguous, missing, or circular links remain unresolved |
| Table provenance | Detectable tables expose page, table, row, and cell information |
| Local inference | Embedding, NLI, and generation run locally in the reference environment |
| Automated regression | The existing backend and frontend suites pass |
| Browser smoke quality | The reviewed workflows have no blocking console errors |

These metrics do not represent exhaustive PDF, legal, or natural-language correctness.

## 5. Target Users

### 5.1 Document Reviewer or Analyst

**Jobs to be done**

- Locate an amount, date, rule, condition, or requirement.
- Confirm the source passage before relying on the result.
- Compare statements across several PDFs.

**Requirements**

- Fast upload and search.
- Document-scoped and global retrieval.
- Clear citations and exact quotations.
- Explicit abstention and missing-information reports.

### 5.2 Policy or Contract Reviewer

**Jobs to be done**

- Inspect candidate conflicts.
- Determine whether an amendment applies on a selected date.
- Avoid assuming that upload recency means legal applicability.

**Requirements**

- Side-by-side source evidence.
- Preserved amendment chain evidence.
- Condition, period, and provenance context.
- Clear unresolved states.

### 5.3 Hackathon Demonstrator or Reviewer

**Jobs to be done**

- Demonstrate a working evidence-first workflow.
- Explain which results are implemented and verified.
- Communicate limitations without overstating AI capability.

**Requirements**

- Health and model availability.
- Controlled demo fixtures.
- Self-explanatory answer and evidence states.
- Clear documentation of verified and unimplemented features.

## 6. User Stories

| ID | User story | Priority |
|---|---|---|
| US-1 | As a reviewer, I can upload a PDF so that it is available for search and question answering. | Must |
| US-2 | As a reviewer, I can view uploaded documents and their metadata. | Must |
| US-3 | As a reviewer, I can search the full document corpus. | Must |
| US-4 | As a reviewer, I can restrict search or Q&A to one document. | Must |
| US-5 | As a reviewer, I can ask a question and receive an evidence-backed answer or abstention. | Must |
| US-6 | As a reviewer, I can inspect every supported claim and its exact source quotation. | Must |
| US-7 | As a reviewer, I can see when evidence is missing, partial, contradictory, or insufficient. | Must |
| US-8 | As a reviewer, I can compare candidate facts from two or more documents. | Must |
| US-9 | As a reviewer, I can inspect an explicit amendment chain. | Must |
| US-10 | As a reviewer, I can resolve an amendment chain for an ISO as-of date. | Must |
| US-11 | As a reviewer, I can inspect extracted PDF tables and review whether extraction is reliable. | Must |
| US-12 | As a reviewer, I can understand sentence-level faithfulness as evidence linkage, not legal correctness. | Must |
| US-13 | As a team lead, I can verify backend, OpenRouter, and model health before a demo. | Should |
| US-14 | As a presenter, I can clearly see upload, loading, empty, error, and validation states. | Should |
| US-15 | As a future administrator, I can configure model names and operating thresholds without code changes. | Should |

## 7. Scope

### 7.1 In Scope

- PDF upload and validation.
- Text extraction and page-aware chunking.
- Document metadata and chunk persistence.
- Embedding-based semantic retrieval.
- BM25 exact/keyword retrieval.
- Hybrid retrieval using Reciprocal Rank Fusion.
- Global and document-scoped search.
- Claim-level local LLM answer generation.
- Source quotation and provenance resolution.
- NLI citation verification.
- Deterministic abstention and partial-answer decisions.
- Evidence-gap reporting.
- Sentence-level evidence linkage/faithfulness.
- Conservative cross-document fact comparison.
- Explicit amendment-chain inspection.
- As-of-date amendment resolution.
- PDF table extraction and table text search.
- React document library, chat, search, comparison, amendment, and table views.
- Loopback-only local runtime.
- API and browser-oriented test coverage.

### 7.2 Explicitly Out of Scope

- Legal advice or legal correctness guarantees.
- Exhaustive detection of every conflict or amendment.
- Exhaustive interpretation of complex legal clauses.
- OCR for scanned PDF documents.
- Hindi-specific answer or verification workflow.
- PDF page-coordinate highlighting or visual citation overlays.
- Clause-based calculations or formula execution.
- Authentication, team accounts, roles, or document sharing.
- Multi-tenant deployment.
- Public hosting of the backend or locally hosted retrieval/verification services.
- Automatic legal applicability decisions based on upload recency.
- Guaranteed layout-independent extraction for every PDF.
- Cross-browser or exhaustive visual test automation.
- Guaranteed multi-document synthesis in Q&A.

## 8. Functional Requirements

### FR-1: PDF Upload

**Description:** Accept one PDF at a time and process it completely before making it searchable.

**Rules**

- A filename is required.
- Only `.pdf` files are accepted.
- Empty files are rejected.
- The file is limited by `MAX_UPLOAD_MB`; the default is 25 MB.
- The file must contain a PDF signature.
- Extractable text is required; scanned PDFs without OCR are rejected.
- Duplicate filenames produce independent document IDs and must never overwrite previous uploads.
- If embedding or indexing fails, partial upload data must be discarded.
- Successful uploads return document metadata and become visible in the library.

**Acceptance**

- Valid PDF: HTTP 201 with document ID, filename, page count, chunk count, size, status, and upload timestamp.
- Wrong extension: HTTP 415.
- Oversized file: HTTP 413.
- Empty file: HTTP 400.
- Invalid or textless PDF: HTTP 422.
- Embedding failure: HTTP 503.

### FR-2: Document Catalogue

**Description:** Expose document metadata, chunks, and extracted tables.

**Rules**

- Documents are listed newest upload first.
- A 32-character hexadecimal document ID identifies each document.
- Unknown document IDs return HTTP 404.
- Chunk reads return deterministic page and position order.
- Table reads return row/cell structure and review status.

### FR-3: PDF Extraction and Chunking

**Description:** Preserve page provenance during text extraction.

**Rules**

- Text and table extraction use PyMuPDF.
- Chunks do not cross page boundaries.
- Default chunk size is 800 characters with 120-character overlap.
- Each chunk identifies document ID, page number, start offset, end offset, and stable chunk ID.
- Detected table text remains available as extracted structure and as searchable text.

### FR-4: Semantic and Keyword Search

**Description:** Search the full corpus or one document using semantic and exact retrieval, followed by bounded relevance reranking.

**Rules**

- The default embedding model is `intfloat/multilingual-e5-small` with 384 dimensions.
- BM25 provides keyword retrieval.
- Reciprocal Rank Fusion combines semantic and keyword rankings.
- A dedicated local query-document relevance cross-encoder reranks a configurable RRF candidate pool; the NLI model is never used as a relevance model.
- `RETRIEVAL_CANDIDATE_K` and `RERANK_CANDIDATE_K` configure retrieval and rerank depths.
- Duplicate chunk IDs are deduplicated during fusion. Exact repeated text from the same document is removed from Q&A context while cross-document source evidence is retained.
- Search supports `top_k` from 1 to 50.
- Document-scoped search requires an existing document ID.
- Search results expose document ID, filename, page, text, chunk ID, retrieval scores, and the optional reranker score.

**Acceptance**

- Blank query: HTTP 422.
- Unknown scoped document: HTTP 404.
- Global and scoped searches return HTTP 200.

### FR-5: Evidence-Grounded Answering

**Description:** Answer questions only from retrieved document evidence.

**Rules**

- Questions are 1 to 1000 characters.
- Blank questions are rejected.
- Optional `document_id` restricts retrieval.
- OpenRouter is the primary generation provider and receives retrieved evidence for `google/gemini-3.7-flash`; eligible provider failures may send the same request to the configured local Ollama model.
- Context construction respects the configured application context budget, reserves output tokens, and uses UTF-8 byte length as a conservative prompt-token upper bound.
- The UI discloses that questions, retrieved evidence excerpts, and filename/page/chunk labels may be sent to OpenRouter; users must only use documents they are authorized to share.
- The model response must be strictly validated before use.
- Backend-owned chunk records must resolve all citations.
- Unknown chunk IDs and incorrect quotations invalidate citations.
- Claims must preserve exact source provenance.

**Aggregate result states**

| State | Meaning |
|---|---|
| `answer` | Every requested fact is supported by verified citations |
| `partial_answer` | Supported facts may be shown, but missing or unsupported facts are reported |
| `abstain` | No justified answer should be shown |

**Verification states**

- `verified`
- `partially_verified`
- `not_verified`
- `contradicted`
- `verification_unavailable`

The verification status must not be presented as calibrated probability or legal certainty.

### FR-6: Abstention and Evidence Sufficiency

**Description:** Prevent unsupported answers from passing the publication gate.

**Rules**

- The system assesses relevance before answer publication.
- Retrieved evidence must meet configured relevance thresholds.
- Claims require verified citations.
- Numeric mismatches invalidate unsupported numeric answers.
- Contradictions invalidate or block publication where appropriate.
- When verification is unavailable, no verified answer is produced.
- Abstention may include missing information and an evidence-gap report.
- Abstention must produce no unsupported claims or false conflict entries.

**Defaults**

| Setting | Default |
|---|---|
| Minimum relevant chunks | 1 |
| Minimum semantic score | 0.70 |
| NLI entailment threshold | 0.60 |
| NLI contradiction threshold | 0.60 |
| Verification required | true |
| Conservative mode | false |

Threshold values are operating points observed in testing, not calibrated probabilities.

### FR-7: Claim Citation Verification

**Description:** Verify claims against exact source chunks using NLI.

**Rules**

- Each claim may have one or more source records.
- Each source includes document ID, filename, page, chunk ID, and quotation.
- NLI checks entailment, neutrality, and contradiction.
- Citation integrity failures are reported separately.
- A quotation must exactly match the normalized backend source text.
- When the document catalogue is available, source document existence and page bounds are checked.
- Multiple cited passages may jointly support a claim only after their exact quotations pass integrity checks and their bounded combined NLI premise entails the claim.
- Numeric claims must not contradict or omit a numeric fact required by the claim.

### FR-8: Evidence Gap Reporting

**Description:** Explain why an answer is complete, partial, or abstained.

**Fields**

- Decision status: `answer`, `partial_answer`, or `abstain`.
- Decision reason.
- Missing information.
- Conflicts.
- Supporting evidence.
- Coverage components.
- Diagnostic signals.
- Supporting verified evidence.

Coverage components must distinguish supported, missing, uncertain, contradicted, invalid-citation, and condition-not-preserved states.

### FR-9: Sentence-Level Faithfulness

**Description:** Measure whether each answer sentence has an exact normalized link to a verified claim.

**Rules**

- Sentence support is separate from NLI confidence and evidence coverage.
- Each supported sentence must link to one or more verified claims.
- Abstentions and empty answers must not receive a misleading 100% percentage.
- The default exact-match implementation may undercount valid paraphrases.
- The result must display a note stating that it is not legal correctness.

### FR-10: Cross-Document Conflict Detection

**Description:** Compare explicit facts across candidate source passages.

**Rules**

- Only explicit numeric or date facts with matching subject and attribute are candidates.
- Retain document, filename, page, chunk, and quotation provenance.
- Preserve conditions and effective periods.
- Mismatched subjects, conditions, or periods remain unresolved.
- Missing provenance remains unresolved.
- Equivalent date formats must not become false conflicts.
- The result must not identify upload recency as legal precedence.

**Comparison types**

- Equal facts.
- Candidate numeric conflicts.
- Candidate date conflicts.
- Unresolved context mismatch.
- Missing or unparseable context.

### FR-11: Amendment Chain Inspection

**Description:** Read explicit amendment relationships across the document corpus.

**Rules**

- A relationship requires explicit source text identifying a target document.
- Effective dates must be usable and unambiguous.
- Upload recency is not an amendment precedence rule.
- Missing targets are reported.
- Ambiguous dates are reported.
- Circular chains are reported.
- Superseded documents resolve according to explicit evidence.

**As-of-date behavior**

- A base document may be selected before the amendment effective date.
- An amendment may be selected on or after its effective date.
- A future amendment does not apply before its effective date.
- An unresolved chain does not receive a definitive resolved version.

### FR-12: Structured Table Extraction

**Description:** Extract detectable PDF tables with provenance and expose incomplete structures safely.

**Rules**

- PyMuPDF table detection is used.
- Tables retain document ID, filename, page number, table ID, headers, and rows.
- Tables have `processed`, `review_required`, or `failed`-type status outcomes.
- Repeated headers and multi-row tables are preserved where possible.
- Lost or ambiguous cell text is flagged rather than silently trusted.
- Table text is included in ordinary searchable text.
- Ordinary text extraction remains the fallback.

**Limitations**

- Extraction is layout-dependent.
- Arbitrary PDF layouts are not guaranteed.
- Review-required tables must be checked against the original page.

### FR-13: API Health

**Description:** Report application and configured LLM provider readiness.

**Rules**

- Health must identify backend availability.
- OpenRouter key validity and model availability, and local Ollama model availability, must be inspectable.
- Health must report whether the configured primary provider or enabled fallback is ready.
- The configured model must be reported.
- Health checks must be safe for loopback use.
- Missing model services must cause a clear degraded or unavailable response.

### FR-14: Error Handling

**Rules**

- Do not expose internal paths, stack traces, secrets, or configuration internals.
- Return actionable HTTP status codes.
- Reject blank text and malformed IDs consistently.
- Provider failures return 502 where response data is unusable and 503 where the configured services are unavailable.
- Provider timeout returns 504.
- Validation failures return 422.

### FR-15: Standalone RAG Evaluation

**Description:** Evaluate the local pipeline separately from production request handling.

**Rules**

- A standalone CLI runs labeled cases against configured QA, embedding, and NLI services; QA uses the configured provider service and may incur hosted-provider usage.
- Cases include factual, multi-document, numeric, contradictory, amendment, insufficient-evidence, and multi-evidence questions.
- The report includes runtime claim faithfulness, E5 question-answer cosine similarity, NLI-based context precision/recall, and decision accuracy.
- E5 cosine similarity is a clearly labeled answer-relevance proxy, not the canonical RAGAS metric.
- Model and dataset limitations must be reported; evaluation must not run inside regular request handling.

## 9. API Requirements

### Root and Health

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | API identity and primary route discovery |
| GET | `/api/health` | Backend and configured LLM provider readiness |

### Documents

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/documents/upload` | Upload and index one PDF |
| GET | `/api/documents` | List processed documents |
| GET | `/api/documents/{document_id}` | Get document metadata |
| GET | `/api/documents/{document_id}/chunks` | Read page-aware chunks |
| GET | `/api/documents/{document_id}/tables` | Read extracted tables |

### Retrieval and Answering

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/search` | Hybrid global or document-scoped search |
| POST | `/api/ask` | Evidence-grounded Q&A with verification |

### Analysis

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/conflicts` | Compare candidate facts across documents |
| GET | `/api/amendments?as_of_date=YYYY-MM-DD` | Inspect amendment chains and optional resolution |

## 10. Frontend Requirements

### Navigation

The application must provide routes or equivalent navigation for:

- Library
- Ask / Chat
- Search
- Compare / Contradictions
- Amendments

### Library

- Upload one PDF at a time.
- Show upload progress and validation errors.
- List document metadata.
- Select a document for details or scoped search.
- Show document chunks and tables.
- Preserve narrow-screen usability.

### Ask / Chat

- Accept questions up to 1000 characters.
- Support optional document scope.
- Show loading and unavailable-model states.
- Display aggregate decision and verification status.
- Display claims and exact source quotations.
- Display missing information and evidence gaps.
- Display sentence-level faithfulness only with the metric disclaimer.
- Show abstention without misleading source or conflict claims.

### Search

- Support global and document-scoped search.
- Display filename, page, text, and relevant source metadata.
- Support loading, empty, and error states.

### Compare / Contradictions

- Accept a subject comparison query.
- Display candidate facts and comparisons.
- Distinguish confirmed differences from unresolved cases.
- Preserve both source passages and provenance.

### Amendments

- Show identified relationships and chain issues.
- Accept an optional ISO as-of date.
- Clearly label the base, amendment, and unresolved states.
- Show source evidence for each relationship.

### Responsive Design

- Desktop and approximately 390px mobile layouts must avoid blocking navigation or horizontal overflow.
- Source quotations and conflict evidence must remain legible.
- Loading, empty, error, and unresolved states must be visible.

## 11. Data and Storage Requirements

### Reference Layout

| Path | Contents |
|---|---|
| `data/pdfs/<document_id>/` | Stored PDF and extracted chunks |
| `data/indexes/documents.json` | Document catalogue |
| `data/indexes/vectors/vector_index.npz` | Vector index and metadata |
| `data/models_cache/` | Hugging Face model cache |
| `data/tmp/` | Throw-away test data |
| `backend/.venv/` | Python virtual environment |

### Persistence

- Document metadata remains durable.
- PDF, chunk, and table records survive backend restarts.
- Vector and BM25 indexes must be consistent with persisted document records.
- Partial uploads must not remain in the document catalogue.
- Test data must be isolated from user documents.

### Privacy

- Uploaded PDFs, indexes, embedding/reranker/NLI weights, and source catalogues remain local.
- Question text and retrieved excerpts may be sent to OpenRouter for inference; this external processing is disclosed in the question UI and documentation. Ollama fallback inference is local.
- OpenRouter credentials are stored only in local environment configuration and are never logged or returned by the API.
- The backend and frontend should bind only to loopback in the reference setup.

## 12. System Architecture

```text
React + Vite + Tailwind
        |
        | HTTP / REST
        v
FastAPI
  |- PDF ingestion
  |- Chunking and table extraction
  |- E5 embedding service
  |- NumPy exact vector store
  |- BM25 index
  |- Hybrid reciprocal rank fusion
  |- Bounded local relevance cross-encoder reranker
  |- Deduplicated, context-budgeted evidence construction
  |- Hybrid LLM service (OpenRouter primary; Ollama fallback)
  |- NLI citation verification
  |- Sufficiency and abstention policy
  |- Conflict and amendment services
        |
        v
Local JSON files, NumPy NPZ vectors, and PDF files
```

The architecture principle is:

**Evidence first. Generation second. Verification always.**

## 13. Technology Requirements

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite 7, Tailwind CSS 3 |
| Backend | Python 3.12, FastAPI |
| PDF extraction | PyMuPDF |
| Embeddings | `intfloat/multilingual-e5-small`, 384 dimensions |
| Vector search | NumPy exact cosine search |
| Keyword search | BM25 |
| Relevance reranking | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| LLM runtime | Hybrid provider service: OpenRouter primary, Ollama fallback |
| Primary language model | `google/gemini-3.7-flash` |
| Local fallback model | `qwen3.5:2b` via Ollama |
| NLI verification | `cross-encoder/nli-deberta-base` |
| Metadata and vector storage | Atomic JSON files and NumPy NPZ |
| Standalone evaluation | E5/NLI metrics via `python -m app.evaluation`; QA evaluation uses the configured provider service |

## 14. Non-Functional Requirements

### NFR-1: Evidence Integrity

- Document ID, filename, page, chunk, and exact quotation must survive retrieval and verification.
- The frontend must not rewrite backend citations.
- Invalid citations must not remain as verified claims.

### NFR-2: Privacy and Local Processing

- Questions and retrieved evidence sent to the hosted primary model must be disclosed to users; Ollama fallback inference is local.
- Local embedding, reranking, and verification models and document storage must not be publicly exposed.
- Data storage must follow the configured local data directory.
- OpenRouter credentials must be environment-configured, excluded from source control, and never logged or returned.

### NFR-3: Availability and Failure Safety

- Missing evidence must not return a verified answer.
- Provider, embedding, vector, and document-store failures must be explicit. LLM fallback is limited to one bounded request and eligible failures.
- Hybrid mode falls back for network failures, timeouts, HTTP 429/5xx, or malformed/incomplete responses; HTTP 401/403 does not fall back unless explicitly configured.
- A successful response is not retried based on answer quality; evidence verification and abstention remain the downstream quality gates.
- Partial upload state must be removed.
- BM25 indexing degradation must not corrupt document metadata or vector indexing.

### NFR-4: Performance and Resource Use

- The system should operate on CPU-only constrained hardware.
- Native BLAS/OpenMP thread pools should remain bounded.
- E5, reranker, and NLI model instances should be reused.
- Model-heavy tests should not run concurrently with live model workloads.
- The configured LLM timeout default is 45 seconds.

### NFR-5: Usability

- Users must understand answer, partial-answer, and abstention states.
- Uncertain comparisons must not appear as confirmed facts.
- Loading, empty, error, invalid, and unresolved states must be explicit.
- Legal and legal-correctness limitations must be discoverable.

### NFR-6: Compatibility

- Existing API response fields and answer behavior must be preserved when possible.
- Additive API changes must not weaken abstention or citation validation.
- Environment variables must remain validated and documented.

### NFR-7: Security

- Reject unsafe filenames.
- Enforce upload size limits.
- Reject malformed file signatures and unsupported formats.
- Do not echo internal exceptions to API clients.
- Restrict CORS to configured loopback origins in the reference setup.

### NFR-8: Observability

- Log startup configuration without secrets.
- Log upload, embedding, indexing, provider selection, fallback reason, provider timeout, validation, and retrieval failures without logging prompts, evidence, or credentials.
- Never expose secrets or internal configuration values in API responses.

## 15. Configuration Requirements

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `hybrid` | `hybrid`, `openrouter`, or `ollama` mode |
| `OPENROUTER_API_KEY` | Empty | Secret key; set only in ignored local environment; optional when local fallback is available |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base URL |
| `OPENROUTER_MODEL` | `google/gemini-3.7-flash` | Primary answer generation model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama API base URL |
| `OLLAMA_MODEL` | `qwen3.5:2b` | Local fallback model |
| `LLM_TIMEOUT_SECONDS` | `45` | Bounded timeout per provider request |
| `LLM_FALLBACK_ENABLED` | `true` | Enable one Ollama fallback after eligible primary failures |
| `LLM_FALLBACK_ON_AUTH_ERROR` | `false` | Explicitly allow Ollama fallback for OpenRouter HTTP 401/403 |
| `LLM_NUM_CTX` | `8192` | Ollama context window |
| `LLM_NUM_PREDICT` | `1024` | Maximum generated-token budget |
| `EMBED_MODEL` | `intfloat/multilingual-e5-small` | Embedding model |
| `EMBED_DIM` | `384` | Embedding dimensions |
| `EMBED_BATCH_SIZE` | `16` | Embedding batch size |
| `NLI_MODEL` | `cross-encoder/nli-deberta-base` | Claim verification model |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Separate relevance model |
| `RETRIEVAL_CANDIDATE_K` | `32` | Maximum candidate depth per retrieval method |
| `RERANK_CANDIDATE_K` | `32` | Maximum fused candidates scored by the reranker |
| `NLI_ENTAILMENT_THRESHOLD` | `0.60` | Entailment operating threshold |
| `NLI_CONTRADICTION_THRESHOLD` | `0.60` | Contradiction operating threshold |
| `TOP_K` | `6` | Default general retrieval count |
| `QA_TOP_K` | `5` | Default Q&A evidence count |
| `MAX_UPLOAD_MB` | `25` | Maximum PDF size |
| `CHUNK_SIZE` | `800` | Maximum character chunk size |
| `CHUNK_OVERLAP` | `120` | Page-local chunk overlap |
| `DATA_DIR` | `../data` | Local persisted data directory |
| `HF_HOME` | `../data/models_cache` | Hugging Face cache |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origin |

## 16. Release Acceptance Criteria

### 16.1 Core MVP

- A valid PDF uploads, extracts, chunks, embeds, and appears in the library.
- Global and document-scoped search return usable results.
- A supported question returns a verified answer with exact source quotation and page.
- An unsupported question abstains and has a null faithfulness percentage.
- Invalid and oversized uploads return the documented validation response.
- OpenRouter/model health is observable.
- Frontend routes render and API-backed flows work.
- Existing backend and frontend regression suites pass.
- No blocking browser console errors appear in the reviewed flows.

### 16.2 Contradictions

- A controlled numeric/date conflict can be shown with both source records.
- Equal facts remain consistent.
- Different subjects, conditions, periods, or missing provenance remain unresolved.
- Irrelevant evidence cannot create a false conflict in the Q&A path.

### 16.3 Amendments

- An explicit base/amendment relationship is inspectable.
- A base document resolves before an amendment effective date.
- The amendment resolves on or after its effective date.
- Missing target, ambiguous date, and circular chain states remain unresolved.
- Upload recency is not presented as legal precedence.

### 16.4 Tables

- Detectable table data is stored with page and table provenance.
- Cell data is searchable.
- Lost or incomplete cell structures are marked for review.
- Tables are not presented as reliable where recovery failed.

### 16.5 Faithfulness

- Supported sentences map to verified claim evidence.
- Unsupported sentences do not count as supported.
- Empty and abstention answers do not receive a percentage.
- The legal-correctness disclaimer is visible.

## 17. Verification Evidence

The latest final integration review provides the baseline verification status:

- 219 backend tests passed across 15 modules.
- 33 frontend tests passed.
- Frontend production build passed.
- Live upload, search, supported Q&A, abstention, conflicts, amendments, and table paths were exercised.
- Desktop and 390px mobile layouts were inspected for the reviewed flows.
- Browser console showed no errors in the reviewed flows.
- Controlled demo readiness was confirmed.

These are historical Phase 5.2 results. In the current worktree, the full backend suite passes **240 tests**, the frontend suite passes **33 tests**, and the frontend production build succeeds. These automated tests do not constitute live verification of the new reranker: its checkpoint must be cached before live inference can be exercised.

### 17.1 Implementation Validation Findings

The PRD was reconciled against the FastAPI routes and application configuration:

| PRD area | Implementation validation |
|---|---|
| Document upload and document metadata | The `/api/documents` router implements upload, list, metadata, chunks, and table endpoints |
| Search | The `/api/search` router implements retrieval with global and scoped search |
| Relevance reranking | RRF candidates are reranked by a separate local relevance CrossEncoder; no NLI entailment score is used as a relevance score |
| Evidence-grounded Q&A | The `/api/ask` router implements model output, citation, abstention, gap-report, and faithfulness response fields |
| Context budget | The prompt is bounded by the configured application context window, output reserve, and existing character cap |
| Multi-passage verification | Multiple exact cited quotations can jointly support a claim under a bounded combined NLI input; too-large combinations fail closed |
| Source citation checks | Citation references are checked against supplied evidence and, in the production verifier, catalogue document/page bounds |
| Standalone RAG evaluation | `python -m app.evaluation` reports decision accuracy, claim faithfulness, E5 cosine relevance proxy, and NLI context precision/recall; QA calls use the configured provider service |
| Conflict detection | The `/api/conflicts` router implements candidate fact retrieval and comparison |
| Amendment inspection | The `/api/amendments` router implements read-only chain inspection and optional as-of-date resolution |
| Health | The `/api/health` router exposes backend, primary provider, and fallback availability |
| Citation thresholds | Entailment and contradiction defaults match `0.60` |
| Evidence thresholds | Minimum semantic score, verification requirement, and conservative mode match the configured defaults |
| Hosted generation | OpenRouter Gemini 3.7 Flash is primary; retrieved excerpts leave the local application when it handles inference. Eligible failures use the configured local Ollama fallback. |

The evaluation dataset is a labeled baseline for the controlled demo corpus, not an exhaustive benchmark. E5 cosine is only a relevance proxy. The relevance reranker checkpoint is loaded local-only and must be cached before search and Q&A can run. Live multi-document synthesis, PDF highlighting, Hindi support, and clause calculations remain unimplemented or incompletely verified.

Detailed verification is maintained in:

- [Phase 5.2 final review](./PHASE_5_2_FINAL_REVIEW_REPORT.md)
- [Phase 5.1 must-have features report](./PHASE_5_1_MUST_HAVE_FEATURES_REPORT.md)
- [AIML-02 compliance audit](./PHASE_4_6_AIML02_COMPLIANCE_AUDIT_REPORT.md)
- [Existing slide-oriented PRD](./PROOFLENS_AI_PRD_PPT_8_SLIDES.md)

## 18. Roadmap

### Phase 1: Stabilize MVP

- Improve PDF layout coverage.
- Improve live multi-document Q&A synthesis verification.
- Expand failure-injection tests.
- Add broader browser and mobile automation.
- Improve model availability diagnostics.

### Phase 2: Expand Document Understanding

- Improve cross-document subject and attribute normalization.
- Broaden amendment relationship and effective-date detection.
- Improve table header and merged-cell recovery.
- Add broader language and multilingual verification coverage.

### Phase 3: Reviewer Experience

- Add PDF page rendering and citation highlighting.
- Add persistent review sessions.
- Add document annotations.
- Improve comparison and amendment timeline views.
- Add export of verified answers and source receipts.

### Phase 4: Enterprise or Product Readiness

- Authentication and authorization.
- Team workspaces and document sharing.
- Audit logs and answer history.
- Deployment and secret-management controls.
- Formal document retention and deletion.
- Cross-browser visual and accessibility testing.

### Bonus Features Not Currently Promised

- Hindi support.
- Clause-based calculations.
- PDF citation highlighting.

No roadmap item should weaken zero-guessing behavior or be described as implemented before verification.

## 19. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Retrieval misses relevant evidence | Unsupported answer or false abstention | Hybrid retrieval, scoped search, evidence-gap reporting, and abstention |
| Citation model makes an incorrect support decision | Unsupported claim appears verified | Strict citation integrity, numeric checks, NLI thresholds, and partial or abstain behavior |
| Conflict heuristic misclassifies facts | False conflict | Require matching subject/attribute, preserve context, and leave uncertain cases unresolved |
| Amendment wording is implicit or ambiguous | Incorrect version resolution | Detect only explicit links and usable dates; report missing, ambiguous, and circular chains |
| PDF layout prevents table extraction | Incomplete or misleading cells | Preserve ordinary text, flag review-required records, and require original-page review |
| Long or complex answers combine supported and unsupported facts | Partial information appears complete | Sentence/claim coverage and evidence-gap reporting; partial-answer state |
| Faithfulness is interpreted as legal correctness | User overtrust | Dedicated disclaimer and separate evidence score |
| CPU, memory, or VRAM limits affect inference | Slow or unavailable answers | CPU fallback, model reuse, 45-second timeout, bounded threads, and clear 503/504 handling |
| User interprets demos as exhaustive validation | Incorrect capability assumptions | Document verified scope and known limitations |

## 20. Product Guardrails

The following statements must not be made unless implemented and separately verified:

- “All PDFs are understood correctly.”
- “Every conflict was found.”
- “The amendment is legally valid.”
- “The answer is legally correct.”
- “Faithfulness means factual or legal correctness.”
- “Hindi workflows are supported.”
- “Clause calculations are supported.”
- “PDF citations are visually highlighted.”
- “All model questions are supported by evidence.”

Recommended public description:

> VerifiDoc AI is an evidence-oriented document review assistant that retrieves, cites, verifies, and abstains on PDF questions. It can expose candidate conflicts and amendments, but extracted facts and NLI verdicts are evidence aids that require source review and are not legal conclusions.

## 21. Open Decisions for Future Releases

1. How to represent confidence scores in a way that cannot be confused with legal probability.
2. Which OCR solution should be approved for scanned PDFs.
3. Whether and how to add authentication or multi-user document isolation.
4. Whether visual PDF page highlighting should use original PDF coordinates or an external annotation format.
5. Which languages should receive dedicated verification support before Hindi is added.
6. Whether clause calculations should be general rules or domain-specific templates.
7. How to measure retrieval completeness across more realistic document collections.
8. Whether future deployment needs additional providers or additional hosted-inference controls.
