# Phase 4.5 - Hybrid Search Interface

**Scope:** `/search` route, Search page, document scoping, top-k selection,
hybrid search result rendering, navigation, and verification.

---

## 1. Implementation status

The hybrid search interface is implemented in the existing frontend:

| File | Status | Purpose |
| --- | --- | --- |
| `frontend/src/pages/SearchPage.jsx` | Present | Search form, scope/top-k controls, loading/error/empty states, and result cards |
| `frontend/src/App.jsx` | Present | `/search` route registered |
| `frontend/src/components/AppLayout.jsx` | Present | Search navigation item |
| `frontend/src/api/search.js` | Present | `POST /api/search` transport |
| `frontend/tests/api.test.mjs` | Present | Search request and error-normalisation coverage |

The UI follows the existing transport and state patterns. Search results are
cancelled on unmount, document selection is loaded from `GET /api/documents`,
and all values displayed in results come from `POST /api/search`.

---

## 2. Search behavior

- Query text is trimmed before submission.
- A blank query cannot be submitted.
- Search scope may be all documents or one of the uploaded PDFs.
- Available result limits are 3, 5, 10, 15, and 20.
- The API receives `query`, `top_k`, and optional `document_id`.
- Loading, backend/network errors, no-result, and result states are shown.
- Each result shows filename, page, passage text, semantic score, BM25 score,
  RRF score, and chunk ID.
- Retrieval scores are explicitly described as ranking signals, not answer
  confidence or factual verification.

---

## 3. Backend verification

The live backend was healthy and returned the expected catalogue and search
response.

### Health

`GET /api/health` returned:

- status: `ok`
- backend version: `0.2.0`
- Ollama available: `true`
- model: `qwen2.5:3b-instruct`
- model present: `true`

### Live search

`POST /api/search` with `{"query":"architecture","top_k":3}` returned
`result_count: 3` and passages from the uploaded documents. The response
included semantic, BM25, and RRF values for every hit.

The live document catalogue contained 5 processed documents, confirming that
document scoping has data available in the current environment.

---

## 4. Automated verification

Frontend verification completed successfully:

| Check | Result |
| --- | --- |
| `npm test` | 30 passed, 0 failed |
| `npm run build` | Passed; 1611 modules transformed |

The 30 tests include the existing API and upload suites plus search transport
tests for the snake_case request body, all-document searches, and backend error
normalisation.

### Browser verification

The Vite server was started at `http://127.0.0.1:5173` and `/search` was
opened in the browser.

- Header navigation rendered Documents, Ask, and Search.
- The backend health badge showed "Backend and model ready".
- All five processed documents appeared in the Search scope control.
- A live query for `architecture` returned 5 passages.
- Result cards showed filenames, page numbers, passage text, semantic score,
  BM25 score, RRF score, and chunk IDs.
- The first result was `Backend_Expert_Roadmap.pdf`, page 1, with semantic
  `0.8313`, BM25 `1.4600`, and RRF `0.0308`.
- A document-scoped query for `architecture` was run with
  `ProofLens AI System Architecture Document.pdf` selected.
- All 5 returned passages belonged only to that document, confirming the
  `document_id` scope was applied end-to-end.
- The first scoped result was page 12 with semantic `0.8210`, BM25 `1.4850`,
  and RRF `0.0315`.
- A nonsense-phrase query still returned hybrid semantic-ranked passages. This
  is expected behavior for this retrieval endpoint: it does not implement
  exact-string rejection and may return semantically similar or lower-ranked
  evidence.
- A forced `/api/search` network failure showed the normalized alert:
  `Could not reach the backend. Check that it is running.`
- Restoring the `/api/search` route and rerunning `architecture` recovered the
  normal 5-result state.

---

## 5. Known limitation

No implementation blocker is known. Browser verification showed the full live
search flow working, but no scoped-document search was exercised in the browser;
all-document search was used for the visual pass.
