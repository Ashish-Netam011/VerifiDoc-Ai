# VerifiDoc AI - Product Requirements Document

**Purpose:** Source content for an eight-slide product presentation
**Product:** VerifiDoc AI - Hack-A-Sol 5.0 AIML-02 Option B
**Audience:** Hackathon judges, reviewers, and prospective users
**Status basis:** Current implementation and Phase 5.2 verification; distinguishable from future work

## Product summary

VerifiDoc AI helps people review multiple PDF documents by answering questions
with source-backed claims, surfacing candidate conflicts, and abstaining when
the available evidence does not support a reliable answer. The product is an
evidence-oriented document review assistant, not a legal decision-maker.

## Problem and opportunity

Reviewers often need to find and compare important details across agreements,
policies, fee schedules, and amendments. Manual review is slow, while
general-purpose AI answers can omit source context or state unsupported
conclusions. VerifiDoc focuses on traceability: answers show the source
document, page, and quotation, and unsupported answers are withheld.

## Target users and primary jobs

1. **Document reviewer or analyst:** Find a specific rule, date, amount, or
   condition across an uploaded PDF collection; verify the returned passage.
2. **Policy or contract reviewer:** Compare explicit facts across documents
   and inspect potential conflicts or amendments without assuming that the
   newest upload is authoritative.
3. **Team demo presenter:** Show a transparent document workflow in which
   evidence, uncertainty, and missing capabilities are visible.

These are intended user profiles for product framing, not a claim that the
current application includes team accounts or collaboration.

## Product goals

- Make answers traceable to exact source passages and page provenance.
- Prefer abstention over unsupported claims.
- Reduce manual search through combined semantic and keyword retrieval.
- Make candidate conflicts, amendment timelines, and table data inspectable.
- Keep inference local and preserve the existing verification requirements.

## Non-goals and current boundaries

- The product does not provide legal advice or guarantee completeness or
  correctness of legal interpretation.
- Conflict, amendment, and table extraction are conservative MVPs; users must
  verify the cited source in the original PDF.
- Scanned-document OCR, Hindi workflows, PDF highlight overlays, and
  clause-based calculations are not included in the currently verified scope.
- The current Q&A live verification did not demonstrate synthesis across
  multiple documents in a single answer.

## Functional requirements

| ID | Requirement | Acceptance evidence | Current status |
|---|---|---|---|
| FR-1 | Upload PDFs, persist document metadata, and retain page-level text provenance. | A valid PDF upload returns success, appears in the library, and can be retrieved. | Implemented and exercised. |
| FR-2 | Search all documents or constrain retrieval to one document. | Global and document-scoped searches return results from the selected corpus. | Implemented and exercised. |
| FR-3 | Answer supported questions with claim-level source quotations; abstain on unsupported questions. | A supported answer has a verified quotation and provenance; an unsupported question has no unsupported claims. | Implemented and live-verified. |
| FR-4 | Compare candidate facts across independent documents and retain both source records. | A controlled conflict is shown with both sources; facts with differing conditions or periods remain unresolved. | Implemented as a heuristic MVP and exercised. |
| FR-5 | Identify explicit amendment links and resolve a version for an as-of date. | The base or amended version is selected for dates before or after an explicit effective date; ambiguous links remain unresolved. | Implemented as a heuristic MVP and exercised. |
| FR-6 | Extract detectable PDF tables with page and cell provenance and make table text searchable. | A detectable table is returned with its rows/cells and appears in search; incomplete extraction is flagged for review. | Implemented and exercised on controlled PDFs. |
| FR-7 | Report sentence-level faithfulness separately from NLI confidence and evidence coverage. | Supported and unsupported sentence counts are exposed; empty or abstention answers do not receive a misleading 100% score. | Implemented and regression-tested; live examples exercised. |

## Non-functional requirements

- **Privacy/local processing:** Run embedding, verification, and answer models
  locally. Do not expose Ollama or other local model services publicly.
- **Evidence integrity:** Preserve document ID, filename, page, chunk, and exact
  source quotation through ingestion, retrieval, verification, and display.
- **Safe failure:** Missing, irrelevant, contradictory, or unverified evidence
  must not be presented as a verified answer.
- **Compatibility:** Additive API changes should preserve existing API
  consumers and the established answer/abstention behavior.
- **Performance/resource use:** Support CPU-only inference within constrained
  local hardware; avoid loading duplicate E5/NLI models or running model-heavy
  tests concurrently with the live backend.
- **Usability:** Provide clear loading, empty, error, and unresolved states;
  present source comparisons legibly on desktop and narrow mobile screens.

## Eight-slide presentation outline

### Slide 1 - VerifiDoc AI

**Headline:** Evidence-first AI for reviewing documents

**On-slide points:**
- Ask questions across PDF collections.
- See the source behind each supported claim.
- Abstain when evidence is insufficient.

**Suggested visual:** Product screenshot with an answer and its source quotation.
**Presenter takeaway:** VerifiDoc is designed to show its evidence, not just its answer.

### Slide 2 - The problem

**Headline:** Document review is slow; unsupported AI answers are hard to trust

**On-slide points:**
- Important details are distributed across long PDFs.
- Manual comparison takes time and can miss changes.
- A plausible answer without an inspectable source is not enough.

**Suggested visual:** Several documents feeding into a reviewer’s search task.
**Presenter takeaway:** The product problem is reliable discovery and verification.

### Slide 3 - Who it helps

**Headline:** Built for people who need to check, compare, and cite

**On-slide points:**
- Reviewers locate amounts, dates, rules, and conditions.
- Analysts compare documents and investigate candidate conflicts.
- Every result should lead back to a source passage.

**Suggested visual:** Two user cards: “Find a rule” and “Compare versions.”
**Presenter takeaway:** The user remains responsible for reviewing the original evidence.

### Slide 4 - How it works

**Headline:** Upload -> retrieve -> answer -> verify

**On-slide points:**
1. Upload PDFs into the document library.
2. Search with semantic and keyword retrieval.
3. Draft an answer using retrieved passages.
4. Verify claims and citations; answer, partially answer, or abstain.

**Suggested visual:** Four-step pipeline with a final evidence gate.
**Presenter takeaway:** Verification and abstention are part of the core workflow.

### Slide 5 - Product capabilities

**Headline:** One workspace for evidence-backed review

**On-slide points:**
- Global and document-scoped search.
- Claim-level citations and unsupported-question abstention.
- Side-by-side candidate conflict evidence.
- Explicit amendment chains and as-of-date resolution.
- Searchable table extraction and sentence-level faithfulness.

**Suggested visual:** Feature grid or annotated product screenshots.
**Presenter takeaway:** Comparison and resolution features are MVPs and remain
  subject to source review.

### Slide 6 - Trust and architecture

**Headline:** Local models; source evidence stays visible

**On-slide points:**
- React interface and FastAPI backend.
- Local E5 embeddings, BM25 retrieval, local Ollama/Qwen generation, and NLI verification.
- Provenance is carried from PDF page/chunk to the displayed citation.
- Uncertain comparisons are marked unresolved; unsupported answers are withheld.

**Suggested visual:** Local-only architecture diagram, with no external model API.
**Presenter takeaway:** No score is a guarantee of legal correctness.

### Slide 7 - What has been verified

**Headline:** Core review paths passed integration checks

**On-slide points:**
- 219 backend tests passed across 15 test modules.
- 33 frontend tests passed; production build succeeded.
- Live loopback checks exercised upload, search, supported/unsupported Q&A,
  conflicts, amendments, and table extraction.
- Browser smoke checks found no console errors in the reviewed flows.

**Suggested visual:** Compact test/result dashboard plus one real source-backed answer.
**Presenter takeaway:** These are actual test and smoke-check results, not
  claims of exhaustive performance or legal accuracy.

### Slide 8 - Roadmap and close

**Headline:** Demonstrate what is verified; extend carefully

**On-slide points:**
- Demo the supported-answer and abstention paths first.
- Show one candidate conflict, one as-of-date amendment resolution, and one table.
- Next: broaden document-layout and multi-document Q&A validation.
- Future scope: PDF highlighting, Hindi support, and clause-based calculations.

**Suggested visual:** Demo checklist with “Available now” and “Future work” columns.
**Presenter takeaway:** VerifiDoc is ready for a controlled demo, with clear,
  honest product boundaries.

## Demo acceptance checklist

- The app runs with the backend and model services bound to loopback.
- A valid PDF can be uploaded, listed, and searched.
- A supported answer displays its verified source quotation and page.
- An unsupported question abstains rather than presenting an unsupported claim.
- A candidate conflict displays both documents and their source passages.
- As-of-date inspection distinguishes the base agreement from an explicit amendment.
- A detectable table is shown with its source page and searchable cell text.
- The presenter states that conflict, amendment, table, and faithfulness results
  are evidence aids, not legal guarantees.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Retrieval misses a relevant passage. | Show source evidence, retain scoped search, and abstain when evidence is insufficient. |
| Heuristics miss or misclassify a conflict or amendment. | Preserve both quotations, report uncertain cases as unresolved, and verify in the original documents. |
| PDF layout produces incomplete table cells. | Flag incomplete tables for review and retain ordinary text extraction as a fallback. |
| Users interpret faithfulness or NLI scores as legal certainty. | Label these as separate evidence measures and state that they are not legal correctness guarantees. |
| CPU and memory constraints affect inference. | Reuse model instances and avoid concurrent model-heavy test and server workloads. |

## Source of current implementation status

This PRD is grounded in the code and verification documented in
[Phase 5.2 Final Review](./PHASE_5_2_FINAL_REVIEW_REPORT.md). “Implemented”
describes current MVP behavior and does not imply complete coverage of arbitrary
PDFs, legal rules, or user questions.
