# Phase 4.6 - AIML-02 Option B Compliance Audit

**Scope:** evidence-based audit of the repository against the official
HACK-A-SOL 5.0 AIML-02 Option B problem statement.

**Constraint:** read-only audit. No source files were modified. No packages
were installed. No Git history or branches were changed. No existing files or
data were deleted.

---

## 1. Executive assessment

ProofLens has a strong evidence-grounded retrieval, citation, verification,
abstention, and web-application foundation. Its main must-have strengths are
multi-document retrieval, exact source provenance, claim-level citation
verification, conservative abstention, and a live React interface.

It does not yet provide the complete official AIML-02 product:

- amendment resolution is described in architecture documentation but has no
  implemented chain or as-of-date engine;
- the faithfulness requirement is missing from the API and UI;
- PDF text extraction exists, but table-specific extraction and table-preserving
  structured parsing are not implemented;
- there is no rendered-PDF page viewer or highlight overlay;
- Hindi is documented as a future pipeline, not implemented;
- clause-based calculations are not implemented;
- contradiction detection exists for claim-versus-evidence and numeric
  mismatches, but not as a complete fact grouping and cross-document
  contradiction engine;
- live `/api/ask` is currently blocked at runtime, and the full backend suite
  is degraded by missing model runtime support/paging resources.

---

## 2. Status scale

- **COMPLETE AND VERIFIED** - implementation and live or credible automated
  verification demonstrate the requirement.
- **IMPLEMENTED, NOT FULLY VERIFIED** - the code path exists and tests cover
  important behavior, but cross-document or live end-to-end evidence is limited.
- **PARTIALLY IMPLEMENTED** - meaningful code exists but significant required
  behavior is absent or unverified.
- **MISSING** - no implementation path was found.
- **BLOCKED** - implementation may exist, but a concrete runtime environment
  dependency prevents verification or operation.

---

## 3. Requirement-by-requirement audit

| Requirement | Status | Evidence and rationale |
| --- | --- | --- |
| 1. Multi-document Evidence Retrieval | IMPLEMENTED, NOT FULLY VERIFIED | Hybrid semantic + BM25 retrieval and RRF are implemented. Retrieval can search all documents or filter by document ID. Unit/integration tests cover fusion, RRF, document filtering, and live search. However, no live test demonstrated one answer intentionally combining and citing evidence from several documents. PDF extraction is text-only in `pdf_service.py`; no table-specific extraction path was found. |
| 2. Exact Citations | COMPLETE AND VERIFIED | The answer API maps model evidence labels to backend-owned filename, document ID, page number, chunk ID, and a verbatim quotation. Citation integrity verifies chunk, document, filename, page, and exact quotation substring. `ClaimList` shows filename, page, quotation, and verification chip. Live and automated checks are documented. |
| 3. Contradiction Detection | PARTIALLY IMPLEMENTED | Claim contradictions and conflicting numeric figures are implemented and disclosed by the evidence sufficiency engine. Tests cover contradictory and conflicting claims. The UI shows conflict cards. Missing: fact extraction/grouping, NLI vs text across document pairs, dates/rules/eligibility normalization, and side-by-side source quotation presentation for independent document facts. |
| 4. Amendment Chains | MISSING | The architecture document contains a planned amendment-resolution design, and `questions.py` mentions amendments, but no amendment engine, document-link model, effective-date model, chain traversal, or as-of-date resolution exists in executable backend code. No tests or UI demonstrate a resolved amendment chain. |
| 5. Zero-Guessing Abstention | COMPLETE AND VERIFIED | A pre-generation relevance screen, strict JSON parsing, citation mapping, NLI verification, deterministic sufficiency policy, partial-answer filtering, and fixed abstention answers are implemented. Unit/API tests cover empty evidence, irrelevant evidence, missing facts, invalid citations, contradictions, and NLI failure. Real live-model behavior is documented in Phase 3 reports. |
| 6. Faithfulness Score | MISSING | No sentence-level faithfulness calculation or percentage field exists in the response contract, sufficiency engine, or UI. Coverage and claim-verification statuses are not a faithfulness score and must not be counted as one. |
| Bonus: PDF Highlighting | MISSING | No PDF.js, page-image renderer, page coordinate storage, highlight overlay, or citation-to-rendered-page interaction exists. `DocumentDetails` renders extracted text only. |
| Bonus: Hindi Support | MISSING | No Hindi-specific prompt, translation step, Hindi response handling, or Hindi UI language support was found. The project architecture document only proposes verify-in-English then translate. |
| Bonus: Clause-Based Calculations | MISSING | No EMI, penalty, fee, formula, arithmetic, or calculation working engine is implemented. Numeric extraction exists only as a citation-verification guard, not as a user-facing calculator. |

---

## 4. Deliverable audit

| Deliverable | Status | Findings |
| --- | --- | --- |
| Working web application | IMPLEMENTED, NOT FULLY VERIFIED | React/Vite and FastAPI routes are implemented and the frontend search flow was live-verified. The live `/api/ask` probe returned 502 because the real model runtime is not usable in the current environment. |
| Live multi-document Q&A | BLOCKED | The execution path supports an all-document retrieval call, and the corpus contains multiple PDFs, but no live cross-document answer was verified. `/api/ask` returned 502 in the current run. |
| Side-by-side contradiction alerts | PARTIALLY IMPLEMENTED | UI conflict cards exist, and API conflicts include filename/page and detail, but only one conflicting source record is consistently modeled for a contradiction. Independent side-by-side quotations across two source documents are not demonstrated. |
| Amendment tracking | MISSING | No amendment UI or backend chain. |
| Safe abstention | COMPLETE AND VERIFIED | Deterministic answer/partial/abstain behavior and fixed abstention text are implemented and tested. |
| README verification pipeline explanation | COMPLETE AND VERIFIED | README describes Evidence First, local/open-source models, architecture principle, retrieval/verification stack, setup, and local execution. |
| README models explanation | COMPLETE AND VERIFIED | README identifies E5, BM25, NumPy fallback, Ollama/Qwen, NLI, and related storage. |

---

## 5. Evidence quality

### Multi-document retrieval

The retrieval service performs semantic + BM25 candidate retrieval, Reciprocal Rank
Fusion, chunk hydration, and optional `document_id` filtering. The live search
endpoint returned hits across uploaded PDFs and a scoped query remained confined to
the selected document. This is strong evidence that the corpus can be searched across
documents.

However, the verifier architecture has a known limitation: citation verification
requires a single cited chunk to entail a claim. It explicitly does not concatenate
two chunks into a synthetic premise. A question requiring facts from two documents
can only be answered if the model makes each fact a separate claim with a valid
source, and the sufficiency engine supports both; this is not the same as verified
cross-document synthesis.

### Tables

PDF ingestion calls PyMuPDF `get_text("text")` page-by-page. It preserves page
boundaries and chunk offsets, but it does not invoke `pdfplumber.extract_tables`,
preserve table structure, or convert table rows to structured fact records. Tables
may appear as plain extracted text and still be retrievable, but the system does not
genuinely parse, normalize, or verify table cells as tables.

### Citations

Citation mapping and integrity verification are the strongest implemented area.
Backend-owned source records prevent the model from inventing document name/page
metadata. The exact quotation is checked against the stored raw chunk. One limitation
is that `best_quotation()` is heuristic (claim-token overlap); it does not prove that
the selected sentence is the best semantic support.

### Contradictions

The system detects:

- a claim contradicted by a cited premise according to NLI;
- numeric mismatch between a claim and cited evidence;
- conflicting figures extracted from claims/evidence;
- condition omissions.

It does not build normalized facts or compare independent document facts absent
from a generated claim. The UI renders conflict cards, but not a two-column
side-by-side source comparison.

### Abstention

The system has more than one publication gate. Unsupported, contradicted, invalid,
or unverified claims are excluded or the answer is abstained. Live model evidence
from prior reports shows real supported, partial, and abstained cases. The current
live `/api/ask` run is blocked with 502, so this audit does not classify the live
runtime as fully verified today.

### Faithfulness

No faithful sentence percentage is produced. The available verification statuses
are claim-level, and coverage statuses are slot-level. Neither is the required
share of answer sentences backed by a matching verbatim quotation.

---

## 6. Test and runtime evidence

### Automated frontend

`frontend/npm test`: **30 passed, 0 failed**.

The suite covers API transport, search request shape, error normalization,
timeouts, aborts, document APIs, and upload validation.

`frontend/npm run build`: passed, transforming 1611 modules.

Browser verification:

- `/search` rendered and reached the live backend health service.
- all-document and document-scoped searches returned real passage cards.
- forced network failure showed normalized error text.
- route recovery restored results.

### Automated backend

Core compliance backend selection (`test_retrieval.py`, `test_qa.py`,
`test_abstention.py`, `test_evidence_sufficiency.py`): **95 passed, 0 failed**
in 3.03 seconds.

Full backend suite: **164 passed, 12 failed** in the latest run.
All 12 failures concern unavailable model runtime behavior:

- 5 embedding model tests failed because `sentence-transformers` could not load
  in the active environment and/or PyTorch hit a Windows paging-file issue;
- 7 NLI model tests failed because `sentence-transformers` was unavailable.

The core retrieval/QA/sufficiency suites remain passing.

### Live runtime

- `/api/health`: backend and model reported available.
- `/api/search`: live hybrid search passed, including scoped retrieval.
- `/api/ask`: live probe returned HTTP 502 in this audit run.
- No live amendment, Hindi, calculation, faithfulness, or PDF-highlight behavior
  was found or exercised.

---

## 7. Documentation and deliverables

The README is a useful high-level deliverable and identifies the verification
pipeline, local models, architecture, setup, storage, and known limitations.
It still states some earlier environment limitations that are not necessarily
current; the audit relied on live checks where possible.

The repository contains extensive phase reports, but there is no:

- official compliance matrix;
- amendment-resolution sample corpus and acceptance test;
- table extraction report;
- faithfulness metric specification;
- Hindi acceptance test;
- calculation acceptance test;
- PDF highlighting implementation or report;
- side-by-side cross-document contradiction demo.

---

## 8. Prioritized implementation roadmap

### P0 - Current live reliability

1. Stabilize the model runtime so `/api/ask` is not degraded to 502:
   - diagnose the Windows paging/PyTorch loading issue;
   - confirm `sentence-transformers` is installed and imports successfully;
   - verify local E5 and NLI caches;
   - rerun real-model tests and live Q&A.
2. Add a live end-to-end smoke test for answer, abstain, partial, and conflict
   paths with real Ollama/NLI.
3. Restore or document the full backend suite result: target 176/176 or higher.

### P1 - Must-have gaps

4. Implement structured fact extraction:
   - subject/attribute, value/unit, condition, date, document, page, chunk,
     amendment target, and effective date.
5. Implement contradiction pairing:
   - group facts by normalized subject/attribute;
   - compare numbers, dates, rules, and eligibility conditions;
   - compare independent documents and show both exact quotations side by side.
6. Implement amendment chains:
   - document relations (`C amends B amends A`);
   - effective/as-of dates;
   - chain completeness validation;
   - latest applicable fact resolution;
   - abstain on missing targets or dates.
7. Implement table parsing:
   - preserve table identity and cell/row/column structure;
   - store table context in chunks or structured records;
   - cite the originating page and verbatim table cell/row text.
8. Implement sentence-level faithfulness:
   - split the displayed answer into sentences;
   - attach or search one or more exact source quotations per sentence;
   - calculate the share of backed sentences;
   - expose a numeric percentage and sentence evidence.

### P2 - Bonus features

9. Add PDF highlighting:
   - use a page renderer or PDF.js;
   - preserve word/line/block coordinates;
   - link citations to page and highlighted rectangle.
10. Add Hindi support:
    - prompt localization and answer output;
    - verify English facts before translation;
    - re-check numbers, dates, and conditions after translation.
11. Add clause-based calculations:
    - structured formula/rate extraction;
    - deterministic calculation engine;
    - show inputs, substitutions, units, formula, and supporting clauses.

### P3 - Demo hardening

12. Add demo fixtures for:
    - multi-document synthesis;
    - two-document contradiction;
    - amendment chain;
    - abstention;
    - table calculations;
    - scoped and all-document retrieval.
13. Add an official compliance matrix to the README.
14. Add browser/component tests for answer, partial, abstention, conflict,
    amendment, faithfulness, highlighting, Hindi, and calculation states.

---

## 9. Final grade summary

| Status | Count |
| --- | --- |
| Complete and verified | 3 |
| Implemented, not fully verified | 2 |
| Partially implemented | 1 |
| Missing | 5 |
| Blocked | 1 |

Counts above cover must-have and bonus requirements plus live deliverable
assessment, not every deliverable line independently.
