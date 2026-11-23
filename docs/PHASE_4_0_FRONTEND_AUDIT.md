# Phase 4.0 — Frontend Audit and Integration Plan

**Status:** audit complete, no frontend behaviour changed in this phase.
**Scope:** the React app in `frontend/` and its integration with the Phase 3.x backend in `backend/`.
**Evidence:** source read of every frontend file, the OpenAPI-facing schemas in
`backend/app/routers/*.py`, a real `npm run build`, a live `GET /api/health`, and the measured
latencies recorded in `docs/PHASE_3_3_ABSTENTION_REPORT.md`.

---

## 1. Summary

The frontend is a **scaffold, not an application**. It builds and serves, but it contains no API
client, no state, no upload path and no answer rendering. Both pages are static placeholders, and
the one nested route it declares can never render because the parent layout does not render its
`<Outlet />`.

The backend is far ahead of it: `/api/ask` already returns a backend-owned decision
(`answer` / `partial_answer` / `abstain`) with claims, per-claim NLI verdicts, conflicts, missing
information and a structured evidence gap report. **The frontend's job in Phase 4 is to display
that contract faithfully, not to re-derive it.**

Two integration risks need a decision before 4.4 (citation viewer):

1. There is **no endpoint that returns a page's full text or an image of a page**. Citations can
   only be rendered from the `quotation` the backend already extracted, plus
   `GET /api/documents/{id}/chunks` for surrounding context.
2. There is **no document deletion endpoint**, so "remove from library" cannot be implemented
   frontend-only.

Both are handled in this plan by scoping the UI to what the backend guarantees rather than adding
backend endpoints (4.0 does not authorise backend changes).

---

## 2. What exists today

| Item | Current state |
| --- | --- |
| Runtime | Vite `7.3.8`, React `18.3.1`, `react-router-dom` `6.28`, Tailwind `3.4.17`, `lucide-react` `0.468` (dev-dependency) |
| Install | `frontend/node_modules` present (100 top-level packages), lockfile committed |
| Build | `npm run build` → **passes**, 34 modules, `dist/assets/index-*.js` 159.33 kB (52.17 kB gzip), 2.71 s |
| Dev server | `npm run dev` → `http://localhost:5173`; **no proxy configured** in `vite.config.js` |
| Pages | `src/pages/Library.jsx`, `src/pages/Chat.jsx` — both static `<Card>` placeholders |
| UI primitives | `src/components/ui.jsx` — `Container`, `Card`, `CardHeader`, `CardTitle`, `CardContent` only |
| API access | none — no `fetch`, no axios, no client module, no base-URL config |
| State | none — no context, no store, no query cache |
| Routing | `App.jsx` declares `/` → `Library`, with `Chat` as its index child, but `Library` never renders `<Outlet />` |
| Env config | only `vite.config.js` alias `@` → `src`; no `.env`, no `VITE_*` usage |
| Styling | Tailwind with `Inter`/`Georgia` font stacks; no base layer, no focus styles, no dark mode |
| Static assets | `index.html` points at `/vite.svg`, which does not exist (`frontend/public/` is absent) |

The backend surface verified live: `GET /api/health` → `status: ok`, model
`qwen2.5:3b-instruct` present.

---

## 3. Audit findings

Severity: **blocker** (must fix before the feature can work), **high** (wrong or misleading UX),
**medium** (needed for a usable product), **low** (polish).

| # | Sev | Finding | Where | Consequence |
| --- | --- | --- | --- | --- |
| F1 | blocker | `Chat` is declared as the index child of `Library`, but `Library` renders no `<Outlet />`; nothing in the app ever renders `Chat`. | `src/App.jsx:10-14`, `src/pages/Library.jsx` | The Q&A screen is unreachable even by URL structure. |
| F2 | blocker | No API client, no base URL, no error handling. Every future page would invent its own `fetch`. | whole `src/` | Blocks 4.1–4.5. |
| F3 | blocker | No dev proxy. CORS allows exactly `http://localhost:5173`; `http://127.0.0.1:5173` or another port is rejected by the browser, and the misconfiguration surfaces as an opaque `TypeError: Failed to fetch`. | `vite.config.js`, `backend/app/config.py:24` | Flaky local development, hard-to-diagnose failures. |
| F4 | blocker | No upload UI, no `FormData` path, no progress feedback. Backend upload embeds the whole PDF before responding, which is the slowest call in the system. | — | Blocks 4.2. |
| F5 | high | No answer-state model on the client. `decision`, `missing_information`, `conflicts`, `coverage` and `verification` are simply absent from the frontend vocabulary. | — | Would tempt a naive implementation to key off `answer != ""`, silently publishing partial or abstained results as if they were answers. |
| F6 | high | No timeout / cancellation strategy. Measured latency: `/api/ask` 2.29–4.00 s warm, first request 3.51 s, pre-check abstention 1.12 s; `/api/documents/upload` runs extraction + embedding + indexing synchronously. | — | Without explicit budgets and `AbortController`, requests hang and double-submits duplicate work. |
| F7 | high | Backend errors are not normalised. FastAPI returns `{"detail": "..."}` (4xx/5xx) and `{"detail", "errors"}` for validation failures; `/api/ask` can also return 502/503/504. | `backend/app/main.py:113-124` | A single generic "something went wrong" would hide actionable states like "Ollama unavailable" vs "PDF has no extractable text". |
| F8 | high | `frontend/dist/` is a stale build artifact and is **not** in `.gitignore` (`frontend/node_modules/` and `frontend/.vite/` are). | `.gitignore` | Risk of committing generated output; confusing diffs. |
| F9 | medium | No document-scope selector, even though `/api/ask` and `/api/search` both accept `document_id`. | — | Users cannot restrict a question to one document, which is the main way to reduce spurious retrievals. |
| F10 | medium | No pagination or search over the library; `GET /api/documents` returns everything. | — | Acceptable at current scale; must not be "fixed" client-side with fake filtering that hides server truth. |
| F11 | medium | No accessible interaction baseline: no visible focus rings, no `aria-live` region for async answers, no keyboard path for the question form. | `src/index.css`, pages | Answers arrive asynchronously; screen readers would miss them. |
| F12 | low | Missing `/vite.svg` favicon → 404 on every load. | `index.html:4` | Console noise, unpolished tab. |
| F13 | low | No `frontend/.env.example` documenting `VITE_API_BASE_URL`. | — | Onboarding gap for 4.1. |
| F14 | low | `lucide-react` is in `devDependencies` but is a runtime dependency if imported by shipped components. | `package.json` | Would break a production install with `--omit=dev`; move when first used. |

---

## 4. Backend contract the frontend must respect

### 4.1 Endpoints

| Endpoint | Request | Success | Notable failures |
| --- | --- | --- | --- |
| `GET /api/health` | — | `200` `{status, backend{status,version,uptime_s}, llm{available,model,model_present,detail}}` | — |
| `GET /api/documents` | — | `200` `{count, documents[]}` (newest first) | — |
| `GET /api/documents/{id}` | 32-hex id | `200` `DocumentMetadata` | `404`, `422` bad id |
| `GET /api/documents/{id}/chunks` | 32-hex id | `200` `{document_id, filename, page_count, chunk_count, chunks[]}` | `404` |
| `POST /api/documents/upload` | multipart `file` (PDF, ≤ `MAX_UPLOAD_MB` = 25) | `201` `DocumentMetadata` | `400` empty/missing name, `413` too large, `415` not `.pdf`, `422` bad PDF / no text, `503` embedding model unavailable |
| `POST /api/search` | `{query, top_k≤50, document_id?}` | `200` `{query, results[], result_count}` | `404`, `422`, `503` |
| `POST /api/ask` | `{question ≤1000 chars, top_k≤20 (default 5), document_id?}` | `200` `AskResponse` | `404` unknown doc, `422` blank question/bad top_k, `502` unusable LLM response, `503` Ollama/embedding down, `504` LLM timeout |

`DocumentMetadata`: `document_id, filename, file_path, page_count, uploaded_at (ISO-8601 UTC),
status ("processed"|"failed"), chunk_count, file_size_bytes`.

### 4.2 `/api/ask` response — the fields that matter

```
question, answer, claims[], limitations[], retrieval.result_count, model,
verification_status, decision, missing_information[], conflicts[], evidence_gap_report
```

- `decision`: `answer` | `partial_answer` | `abstain` — **the only authority on whether an answer
  was published.**
- `verification_status`: `verified` | `partially_verified` | `not_verified` | `contradicted` |
  `verification_unavailable`.
- `claims[]`: `{text, sources[{chunk_id, document_id, filename, page_number, quotation}],
  verification{status, reason, entailment_score, neutral_score, contradiction_score,
  integrity_failures[], evidence[]} | null}`.
  `verification.status` ∈ `supported` | `contradicted` | `insufficient` | `invalid_citation`.
- `conflicts[]`: `{kind: "claim_contradiction"|"conflicting_amounts", claim_text, chunk_id,
  document_id, filename, page_number, contradiction_score, detail}`.
- `missing_information[]`: backend-authored user-facing sentences — render **verbatim**.
- `evidence_gap_report`: `{status, reason, missing_information[], conflicts[],
  supporting_evidence[{description, chunk_id, document_id, filename, page_number, claim_text}],
  coverage{status: "identified"|"uncertain", components[{name, label, matched_phrase, status,
  evidence_chunk_ids[]}]}, signals{}}`.
  Component `status` ∈ `supported` | `unverified` | `missing` | `contradicted` |
  `invalid_citation` | `condition_not_preserved`.
  `signals` is diagnostic data (`precheck_*`, `semantic_*`, thresholds); it must not be presented
  as confidence to end users.

### 4.3 Non-negotiable rendering rules

These follow directly from Phase 3.3 and must be encoded in the UI, not re-implemented per screen:

1. **Never infer the state from `answer`.** Use `decision`. An abstention can carry an empty or a
   replacement string; a partial answer deliberately omits unsupported claims from `answer`.
2. **Unsupported claims stay visible.** For `partial_answer`, `answer` contains only supported
   claims, but `claims[]` still lists the unsupported ones with their verdicts. The UI must show
   them clearly as *not established*, never as supporting text.
3. **Conflicts are always disclosed.** If `conflicts[]` is non-empty, a conflict panel is
   mandatory — including inside abstentions (`claim_contradiction` / contested amounts). It is not
   an "insufficient evidence" footnote.
4. **`missing_information` and `limitations` render as backend sentences**, no client-side
   paraphrasing or "did you mean" suggestions.
5. **`coverage.status == "uncertain"`** means the backend could not decompose the question. Show
   "the requested facts could not be isolated" rather than inventing per-fact rows.
6. **Scores are diagnostics.** `entailment_score`, `contradiction_score`, `numeric_conflict` and
   `signals` may be shown in an expandable "why" section labelled as NLI scores, never as
   confidence percentages or legal certainty.
7. **`verification_unavailable` is not an answer.** When `verification_status ==
   "verification_unavailable"`, the UI shows an abstention with a neutral explanation (the backend
   already decided this), never the raw model text.

---

## 5. Target architecture for Phase 4.1

```
frontend/src/
  api/
    client.js        # fetch wrapper: base URL, JSON, timeout, abort, error normalisation
    errors.js        # ApiError { status, detail, errors[] }, ApiUnavailable (network/abort)
    health.js        # getHealth()
    documents.js     # listDocuments(), uploadDocument(file, onProgress), getChunks(id)
    ask.js           # askQuestion({question, topK, documentId}, {signal})
  hooks/
    useHealth.js     # polled once on load + manual retry; drives the degraded banner
    useDocuments.js  # list + refresh after upload
    useAsk.js        # idle -> asking -> answered|abstained|failed; holds last AskResponse
  components/
    ui.jsx           # existing primitives (extended only as needed)
    DecisionBadge.jsx, ConflictPanel.jsx, ClaimList.jsx, GapReport.jsx,
    UploadDropzone.jsx, DocumentList.jsx, CitationCard.jsx, AsyncState.jsx
  pages/
    AppShell.jsx     # top bar: product name, backend/LLM status, topic nav
    LibraryPage.jsx  # upload + document list (4.2)
    AskPage.jsx      # question form + answer states (4.3)
  lib/
    format.js        # bytes, dates, page labels
```

Decisions, with reasons:

- **Vite dev proxy for `/api` → `http://127.0.0.1:8000`.** Removes CORS and
  `localhost` vs `127.0.0.1` mismatches from local development (F3) without touching backend
  config. `VITE_API_BASE_URL` remains an escape hatch for non-proxied deployments; default `''`
  (same-origin, i.e. the proxy in dev).
- **Hand-written `fetch` wrapper, no new dependency.** The contract is small and the project has no
  HTTP library; adding axios/react-query would be an unrequested dependency. `AbortController`
  covers timeout and cancellation.
- **`XMLHttpRequest` for upload progress only**, because `fetch` cannot report upload progress and
  the upload is the one call long enough to need it. Isolated inside `documents.js`.
- **`useAsk` owns the state machine**, so every answer surface receives the same
  `AskResponse` and the same rendering rules.
- **Routing:** `/` → `LibraryPage`, `/ask` → `AskPage`, with `AppShell` as the shared layout that
  renders `<Outlet />` (fixes F1). `document_id` and question travel via route state/query so a
  citation can link back to its answer.

### Timeouts and concurrency budget

| Call | Client budget | Why |
| --- | --- | --- |
| `/api/health` | 5 s | Local probe; failing fast enables the degraded banner. |
| `/api/documents` | 10 s | Disk read of the catalogue. |
| `/api/ask` | 120 s | Measured 2.3–4.0 s warm, 3.5 s cold; 120 s leaves room for a cold Ollama load without hiding a hang. |
| `/api/documents/upload` | 300 s | Extraction + E5 embedding + indexing for up to 25 MB. |

One in-flight ask at a time (the form is disabled while asking). Uploads queue sequentially; the
library refreshes on each success.

### Error normalisation

| Failure | UI treatment |
| --- | --- |
| `400/413/415/422` on upload | Inline error under the dropzone, verbatim `detail` (e.g. "Only .pdf files are accepted."). |
| `404` unknown `document_id` | Clear the scope selector and show "that document is no longer available"; refresh the list. |
| `422` on `/api/ask` | Inline form validation message; never a toast, since the user must fix input. |
| `502` | "The language model returned an unusable response." + Retry. |
| `503` | Distinguish "answers unavailable (LLM offline)" from "search unavailable (embeddings)"; suggest checking `/api/health`. |
| `504` | "The model timed out." + Retry; keep the question text. |
| Network/abort | `ApiUnavailable` — "cannot reach the backend at <base>" with the resolved base URL. |

---

## 6. Milestone plan

### 4.1 — Connect frontend to backend APIs
1. Vite proxy + `VITE_API_BASE_URL` + `frontend/.env.example`.
2. `api/client.js`, `errors.js`, `health.js`, `documents.js`, `ask.js` per §5.
3. `AppShell` with `<Outlet />`; routes `/` and `/ask`.
4. Health banner: `ok` → quiet; `degraded` → persistent notice naming the model state from
   `llm.detail`; unreachable → "backend offline".
5. Remove the `Chat.jsx` placeholder in favour of `AskPage`, so no dead route remains.
6. `.gitignore`: add `frontend/dist/`.

**Acceptance:** app loads against a running backend; banner reflects stopping/starting Ollama;
no CORS errors from `localhost:5173`; `npm run build` passes.

### 4.2 — PDF upload and document library
1. Drag-and-drop + file picker, `.pdf` and 25 MB validated client-side *as a hint only* — the
   server remains authoritative.
2. `XMLHttpRequest` progress with per-file state: `queued → uploading (n%) → processing → done |
   failed (detail)`.
3. Document list: filename, pages, chunks, size, uploaded date, `status`; select-to-scope; empty
   state that points at the upload panel.
4. Refresh the list after each successful upload; keep failures visible until dismissed.

**Acceptance:** a real PDF uploads through the UI and appears in the list; an oversized file and a
non-PDF each show the backend `detail`; a failed upload leaves no phantom row.

### 4.3 — Q&A interface and answer states
1. Question form: textarea, optional document scope, `top_k` control (default 5, range 1–20),
   submit disabled while asking.
2. Answer header driven solely by `decision`: **Answer** (green), **Partial answer** (amber),
   **Abstained** (slate) with the reason.
3. Partial: `answer` block + "not established" list built from `missing_information` and the
   unsupported `claims[]`.
4. Abstain: `answer` shown as the backend explanation, plus `missing_information`; no invented
   "no information found" copy.
5. `limitations` list; `aria-live="polite"` on the result region.
6. Loading state must survive 4 s without a spinner-only screen (skeleton + elapsed hint).

**Acceptance:** replaying the Phase 3.3 live scenario set — rent (answer), deposit (abstain),
rent+deposit (partial), rent+income (contradiction abstain), sublet (answer) — produces the
matching state in the UI with no client-side inference.

### 4.4 — Citation viewer and Evidence Gap Report
1. `CitationCard` per source: filename, page, backend `quotation`, claim text, verdict chip.
2. Clicking a citation fetches `GET /api/documents/{id}/chunks` once per document (cached in
   memory) and shows the cited chunk's text with the quotation highlighted. **This is the ceiling
   of what the backend supports**: no page image, no page-level text endpoint.
3. Gap report panel from `evidence_gap_report`: coverage components with matched phrase and
   status, supporting evidence, missing information, conflicts, and a collapsed "diagnostics"
   section for `signals`.
4. Coverage `uncertain` → a single explanatory line instead of component rows.

**Acceptance:** every citation opens the exact cited chunk; component statuses match the payload;
no page-image affordance exists that the backend cannot satisfy.

### 4.5 — Conflict visualisation and UI polish
1. Conflict panel variant per `kind`, quoting claim + filename/page; conflict chip on the answer
   header whenever `conflicts[]` is non-empty.
2. Contradicted claims rendered in place inside `claims[]`, not only in the summary.
3. Keyboard/focus/contrast pass; responsive layout down to 390 px.
4. Empty/error/loading states reviewed on every surface.

---

## 7. Gaps, assumptions and risks

| Item | Decision for Phase 4 |
| --- | --- |
| No document delete endpoint | Library is **append-only** in Phase 4; no delete affordance. Adding `DELETE /api/documents/{id}` (with vector, BM25 and directory cleanup) is a backend milestone, not a frontend workaround. |
| No page text or page image endpoint | Citation viewer shows the backend `quotation` plus the cited chunk from `/chunks`. It must not imply a full-page document viewer. |
| No pagination on `/api/documents` | Accepted; the list is small. No client-side fake paging. |
| No auth / multi-user | Out of scope; the app is single-user local. |
| Uploads are synchronous | Progress is honest (upload % then "processing"); no job polling exists to fake. |
| LLM latency variability | 120 s ask budget; state survives slow cold starts without changing thresholds. |
| Scores could be read as confidence | All numeric scores only inside a labelled diagnostics disclosure. |
| `frontend/dist/` currently untracked | Add to `.gitignore` in 4.1; the directory stays on disk as a build output. |

---

## 8. Verification strategy for Phase 4

- **Per milestone:** `npm run build` must pass, and the affected screen must render against the
  live backend on `localhost:5173`.
- **Contract tests by replay, not by inference:** use the recorded Phase 3.3 scenario set (rent,
  deposit, rent+deposit, rent+income, sublet, wrong-amount) and confirm the rendered state matches
  `decision`, `conflicts` and `missing_information` exactly.
- **Failure paths:** stop Ollama → `503`/degraded banner; upload a non-PDF → verbatim `detail`;
  ask with a deleted `document_id` → `404` handling.
- **Not automated in Phase 4:** no Playwright/unit-test harness is added; this matches the project's
  existing Python-only test suite. Any addition would be a separate, explicit decision.

---

## 9. Definition of done for Phase 4

1. `/` lists documents and accepts PDFs; `/ask` asks questions scoped to all or one document.
2. Answer, partial answer and abstention are visually and semantically distinct, and every one of
   them is derived from `decision` and its companion fields only.
3. Conflicts, missing information and the evidence gap report are always reachable from the answer
   that produced them.
4. No screen claims more than the backend established: no confidence percentages, no full-page
   viewer, no fabricated empty-state reasoning.
5. `npm run build` passes and the app runs against the live backend with no console errors.
