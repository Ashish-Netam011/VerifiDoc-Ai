# Phase 4.2 — PDF Upload and Document Library

**Scope:** upload interface, document library, document details (metadata + extracted chunks),
integration with the 4.1 API layer, verification, cleanup.
**Constraints honoured:** backend untouched, no packages installed, no branch/history changes, no
delete UI, no Q&A, no invented fields, existing 4.1 behaviour preserved.

---

## 1. Files

### Created

| File | Purpose |
| --- | --- |
| `frontend/src/components/AppLayout.jsx` | Product shell: brand, Documents/Ask navigation, live `HealthBadge` |
| `frontend/src/components/UploadPanel.jsx` | Drag-and-drop + file picker, per-file states, real progress, retry |
| `frontend/src/components/DocumentLibrary.jsx` | Catalogue from `GET /api/documents`: skeleton, empty, error, refresh, cards |
| `frontend/src/components/DocumentDetails.jsx` | Metadata + chunks grouped by page, loading/error/retry |
| `frontend/src/components/Toast.jsx` | Transient success/failure notification in a persistent `aria-live` region |
| `frontend/src/hooks/useUploadQueue.js` | Multi-file upload queue, per-item state, progress, retry, duplicate guard |
| `frontend/src/hooks/useDocumentDetails.js` | Metadata + chunks fetched together, cancellable, retryable |
| `frontend/src/lib/format.js` | `formatBytes`, `formatDateTime`, `pluralize`, `shortId` |
| `frontend/src/lib/uploadValidation.js` | Client-side PDF hints: extension, empty, size, `%PDF-` signature |
| `frontend/tests/upload-validation.test.mjs` | 7 validation tests (Node's built-in runner) |
| `docs/PHASE_4_2_DOCUMENT_LIBRARY_REPORT.md` | This report |

### Modified

| File | Change |
| --- | --- |
| `frontend/src/pages/Library.jsx` | Was the 4.1 shell; now the Documents page (upload + library + details + toast) |
| `frontend/src/App.jsx` | `AppLayout` route wrapper; `/` → `Library`, `/chat` → `Chat` (still reachable) |
| `frontend/package.json` | `lucide-react` moved to `dependencies` (it is now imported by shipped components); test script runs both test files |

No API module changed: `documents.js` already provided `listDocuments`, `getDocument`,
`getDocumentChunks` and `uploadDocument` exactly as the backend defines them.

### Routing note

Phase 4.1 used `Library` as a layout with `Chat` as its index child. With a real Documents page
that is no longer possible without rendering both at `/`, so the shell moved into `AppLayout` and
`Chat` now lives at `/chat` (linked from the header). No 4.1 behaviour was lost: health, API layer,
proxy, errors and timeouts are unchanged, and `Chat` remains reachable.

---

## 2. Upload implementation

`useUploadQueue` owns all upload state; the panel only renders it.

- **Multiple files:** each `File` becomes an item with `{ id, file, name, size, status, progress,
  message, document }`. Status is `queued | uploading | success | error | rejected`.
- **Scheduling:** files are sent one at a time. The embedding step is CPU-bound locally, so
  serialising keeps latency predictable; every item still has independent progress, outcome and
  retry.
- **Validation (hints only):** `validatePdfFile` rejects a missing `.pdf` extension, an empty file, a
  file over the mirrored 25 MB limit, and a file whose first 1024 bytes lack `%PDF-` — the same
  signature check the backend performs. Rejected items never reach the backend and are marked
  `rejected` with the reason.
- **MIME type is not trusted:** an `application/pdf` type with a `.txt` name is rejected on the
  extension, and a `.pdf` name with text content is rejected on the signature.
- **Progress:** `uploadDocument` reports `xhr.upload.onprogress`; the panel renders a real
  `role="progressbar"` with `aria-valuenow` and the percentage. Nothing is simulated — the value
  comes from the XHR event.
- **Success only after the backend answers:** the item becomes `success` only when
  `/api/documents/upload` returns `201` with `DocumentMetadata`. The returned `page_count` and
  `chunk_count` are shown in the row.
- **Duplicates:** an identical file (same name and size) already `queued` or `uploading` is rejected
  with “This file is already uploading.”, within one batch and across batches.
- **Retry:** only for `error` items (backend/network/timeout failures). Client rejections are
  deterministic — retrying them would send a request that must fail again.
- **Clear finished:** removes finished rows; in-flight rows cannot be dismissed.

Backend errors are shown through the 4.1 `ApiError.message`, so the user sees the server's own
sentence (for example “Only .pdf files are accepted.” or “The uploaded file is not a valid PDF
(bad signature).”), never a stack trace.

---

## 3. Document library implementation

- **Source:** `GET /api/documents`, via `useDocuments` (refresh keeps the last list visible).
- **Fields displayed, all backend-provided:** `filename`, `uploaded_at` (formatted), `page_count`,
  `chunk_count`, `file_size_bytes`, `document_id` (short form on cards, full in details) and
  `status` as a pill. Nothing is synthesised; a missing field renders as “—”.
- **States:** two skeleton cards while loading; “No documents yet” with an upload hint when the
  list is empty; a rose error panel with Retry when the first load fails; an amber inline banner
  with Retry when a refresh fails but documents are already loaded.
- **Refresh:** header button, spin state, disabled while refreshing; the list also refreshes
  automatically after each successful upload.
- **Selection:** clicking a card selects it (visible ring, `aria-pressed`); the newly uploaded
  document is selected automatically.
- **No delete action:** the backend has no delete endpoint (documented in the Phase 4.0 audit).

---

## 4. Document details implementation

- Both endpoints are required: `GET /api/documents/{id}` and `GET /api/documents/{id}/chunks`, run in
  parallel through `useDocumentDetails`; the panel is `ready` only when both succeed.
- Metadata shown: pages, chunks, size, uploaded, status, pages extracted (from the chunks response),
  full document ID and stored file path.
- **Extracted text:** chunks grouped by `page_number` in ascending order, each chunk rendered with
  `whitespace-pre-wrap` and its `chunk_id` and `start_offset`–`end_offset`.
- **No page rendering:** there is no page-image or page-text endpoint, so the panel shows only the
  stored chunks and says so implicitly by labelling the section “Extracted text”.
- States: idle (“No document selected”), skeleton, error with Retry, ready, and a “no chunks”
  message if the backend returns an empty chunk list.
- Requests are cancelled when the selection changes or the panel unmounts.

---

## 5. UI verification

Verified in the local browser against the live backend (desktop 1440×900, mobile 390×844):

| Check | Result |
| --- | --- |
| Header, navigation, live health badge | Renders; “Backend and model ready · qwen2.5:3b-instruct” |
| Empty library | “No documents yet” with upload hint; details panel “No document selected” |
| Desktop layout | Two columns: content 552 px + details 416 px; cards and metadata aligned |
| Mobile layout (390 px) | Single column, `scrollWidth` 374 px ≤ 390 px — **no horizontal overflow** |
| Visual polish | Full-page screenshot inspected: clear hierarchy, consistent slate palette, no gradients or gratuitous animation; only the progress bar has a transition |
| Accessibility | Buttons are real `<button>`s with focus-visible rings, progressbar has ARIA values, toasts use `aria-live`, cards expose `aria-pressed` |
| `Chat` route | Still reachable at `/chat` |

Not captured: the success toast. It is triggered by the same `onUploaded` callback whose visible
effects (list refresh, auto-selection, “Uploaded” row) were observed, but it auto-dismisses after
6 s and no snapshot caught it on screen.

---

## 6. Real upload test results

Temporary fixture: `frontend/tests/fixtures/phase42_lease.pdf` (2 pages, 1 935 bytes, generated with
PyMuPDF; contains rent, deposit, sublet and notice clauses).

| Step | Observed |
| --- | --- |
| Select the PDF via the real file input | Row appears: name, 1.9 KB, progress bar |
| Progress during upload | “100% uploaded · the server is indexing the PDF” with `aria-valuenow=100` |
| Backend response | `201` metadata: `document_id f375eea36ce5463e9a420cdaf20f189b`, `page_count 2`, `chunk_count 2`, `file_size_bytes 1935`, `status processed` |
| Row state | “Uploaded · 2 pages · 2 chunks”; library refreshed to “1 document indexed” |
| Library card | Filename, upload date, 2 pages, 2 chunks, 1.9 KB, short ID, “Processed” pill |
| Auto-selection | New document selected; details loaded |
| Details | Metadata matches the API exactly; Page 1 and Page 2 chunks with full text and offsets |
| Browser reload | Document persisted (“1 document”), re-selected, details and chunks reloaded |

### Validation and failure scenarios (live)

| Scenario | Result |
| --- | --- |
| Plain text named `notes.txt` | Rejected client-side: “Only PDF files are accepted.” |
| Text content named `fake.pdf` | Rejected: “This file is not a valid PDF (no PDF signature), even though its name ends in .pdf.” |
| 0-byte `empty.pdf` | Rejected: “This file is empty.” |
| Same PDF twice in one batch | First uploaded, second rejected: “This file is already uploading.” |
| Oversized file | Not exercised with a 25 MB upload; covered by an automated test using an injected `maxBytes`. The backend's `413` is normalised by the 4.1 layer. |
| Network failure (library refresh) | `window.fetch` forced to reject → amber banner: “Refresh failed: Could not reach the backend. Check that it is running. Showing the last loaded list.” + Retry; restoring `fetch` and clicking that Retry recovered the list |
| Backend rejection shown verbatim | Retrying a `.pdf`-named text file (before the retry rule was tightened) produced the backend's `422` message “The uploaded file is not a valid PDF (bad signature).” in the row |

### Defects found by this live testing and fixed

1. **File picker did nothing.** `handleInput` captured `event.target.files` and then cleared
   `event.target.value`; the captured `FileList` is live, so it became empty before `addFiles` read
   it. Fixed by copying to an array first, so the same file can also be re-selected later.
2. **Retry on a client-rejected item bypassed validation.** Retrying a duplicate-rejected row
   re-uploaded the file and created a second document, because retry requeued without re-running
   `validatePdfFile`. Retry is now offered only for `error` items; client rejections are final.
3. **Double period in the refresh-failure banner** (“…is running.. Showing…”). Fixed by not
   appending a second full stop.

---

## 7. Automated test results

- `npm test` → **27 passed, 0 failed** (≈0.32 s)
  - 20 existing API tests (Phase 4.1) — unchanged and still passing.
  - 7 new upload-validation tests: valid signature, non-PDF extension with PDF MIME, `.pdf` without
    signature, empty file, over-limit with limit named, exactly-at-limit, default limit equals 25 MB.
- `npm run build` → **passes**: 1 600 modules, JS 201.70 kB (64.65 kB gzip), CSS 17.27 kB
  (3.99 kB gzip), 3.17 s.

Automated tests are **mocked/unit** (Node `node:test`, no DOM); the UI states were verified in the
browser as described above. There is no jsdom or component-test harness, and none was installed.

---

## 8. Cleanup

- All three test documents created in this milestone (`f375eea3…`, `979a929e…`, `0adb93ff…`) were
  removed by stopping the backend, clearing `data/pdfs/`, `data/indexes/` and `data/tmp/`, and
  restarting it — the corpus was empty before this milestone, so nothing of the user's was touched.
  There is no delete endpoint, so an API-level delete was not possible.
- The temporary fixture `frontend/tests/fixtures/phase42_lease.pdf` was deleted.
- Backend restarted on `127.0.0.1:8000` (PID 27804), `/api/health` → `ok`, `/api/documents` →
  `{"count":0,"documents":[]}`, UI shows the empty state again.
- The Vite dev server on `localhost:5173` was left running.

---

## 9. Known limitations

1. **Upload size limit is mirrored, not fetched.** The API does not expose `MAX_UPLOAD_MB`; the
   client uses 25 MB to match the backend default. If the backend limit changes, the client hint
   drifts (the backend still enforces the real limit and its `413` is displayed).
2. **Uploads are sequential.** A batch uploads one file at a time; large batches take proportionally
   longer. There is no cancel button for an in-flight upload.
3. **No upload retry for client-rejected items.** Deliberate: those rejections are deterministic.
   Backend/network failures are retryable.
4. **Intermediate progress was not observed.** The fixture uploads in well under a second, so the
   progress UI was captured at 100% while the server indexed; the percentage is wired to real XHR
   events, but no mid-transfer percentage was observed in this run.
5. **Success toast not captured visually** (auto-dismisses after 6 s).
6. **No delete or rename.** The backend exposes neither.
7. **Details are chunk-level only.** No page images and no page-text endpoint; a long page is shown
   as one or more chunks, not as a page.
8. **`file_path` is shown** in the details panel exactly as the API returns it; it is an internal
   storage path, not a downloadable link.
9. **No pagination or search in the library.** The endpoint returns every document; acceptable at
   current scale and deliberately not faked client-side.
10. **UI verification is manual.** The empty, loading, error and success states were inspected in a
    browser; component-level tests would require adding a DOM test stack, which was not authorised.
11. **Duplicate detection is heuristic** (name + size against in-flight uploads only). The backend
    intentionally creates a new document for every upload, so identical files uploaded at different
    times remain separate documents.
