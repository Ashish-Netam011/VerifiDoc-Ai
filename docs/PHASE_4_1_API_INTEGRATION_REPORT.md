# Phase 4.1 — Frontend API Integration Foundation

**Scope:** routing fix, API client layer, Vite dev proxy, normalised errors, health integration,
document API functions, `.gitignore`, verification.
**Constraint honoured:** no backend file was modified; no package was installed; no template was
applied; the Q&A interface and document library UI are **not** built yet.

---

## 1. Files

### Created

| File | Purpose |
| --- | --- |
| `frontend/src/api/errors.js` | `ApiError`, error kinds, HTTP/validation/timeout/abort/parse normalisers, safe-`detail` filtering |
| `frontend/src/api/client.js` | Single transport: base URL, JSON, timeouts, `AbortSignal`, `fetch` requests, `XMLHttpRequest` upload with progress |
| `frontend/src/api/health.js` | `getHealth()` + `parseHealth()` view model |
| `frontend/src/api/documents.js` | `listDocuments()`, `getDocument()`, `getDocumentChunks()`, `uploadDocument()` |
| `frontend/src/api/questions.js` | `askQuestion()` transport for `POST /api/ask` (no UI yet) |
| `frontend/src/api/search.js` | `searchDocuments()` transport for `POST /api/search` |
| `frontend/src/hooks/useHealth.js` | Health state machine + refresh + unmount cancellation |
| `frontend/src/hooks/useDocuments.js` | Document catalogue state + refresh, keeps last list during refresh |
| `frontend/src/components/HealthBadge.jsx` | Minimal live backend/model status with a Recheck button |
| `frontend/tests/api.test.mjs` | 20 `node:test` tests (mocked transport) |
| `frontend/.env.example` | Documents `VITE_API_BASE_URL` (empty by default) |
| `docs/PHASE_4_1_API_INTEGRATION_REPORT.md` | This report |

### Modified

| File | Change |
| --- | --- |
| `frontend/src/pages/Library.jsx` | Now renders the header + `<Outlet />`, which fixes the unreachable nested route; placeholder card removed |
| `frontend/vite.config.js` | `/api` proxy to `http://127.0.0.1:8000`; plugins and `@` alias preserved |
| `frontend/package.json` | Added `"test": "node --test tests/api.test.mjs"` (Node's built-in runner, no dependency) |
| `.gitignore` | Added `frontend/dist/` |

### Untouched

`frontend/src/App.jsx` needed no change: the route tree was already correct, only the parent layout
failed to render its child. `Chat.jsx`, `ui.jsx`, `index.html`, Tailwind/PostCSS configs and the
entire `backend/` tree are unchanged.

---

## 2. Routing fix

Before (`Library` never rendered its child, so `Chat` was dead code):

```jsx
<Route path="/" element={<Library />}>      {/* renders a Card, no <Outlet /> */}
  <Route index element={<Chat />} />        {/* never mounted */}
</Route>
```

Now:

```jsx
// App.jsx - unchanged
<Route path="/" element={<Library />}>
  <Route index element={<Chat />} />
</Route>

// Library.jsx - the fix
export function Library() {
  return (
    <>
      <header>… ProofLens AI + <HealthBadge /> …</header>
      <main><Outlet /></main>
    </>
  )
}
```

- `Library` is now the application shell; its document list arrives in 4.2.
- `Chat` renders at `/` as the index child.
- No route was added, renamed or removed, so no broken or unnecessary URLs exist.

---

## 3. API architecture

```
components/pages  ->  hooks/          ->  api/*.js          ->  api/client.js  ->  /api/*
                      (React state)      (schema-aware fns)     (transport)
```

- **Base URL:** `API_BASE_URL` is `''` unless `VITE_API_BASE_URL` is set. All calls therefore use
  relative paths (`/api/health`), which go through the Vite proxy in development. No hard-coded
  `http://127.0.0.1:8000` appears in frontend code.
- **JSON:** objects are stringified and `Content-Type: application/json` is set automatically.
  `Accept: application/json` is always sent.
- **Multipart:** `uploadDocument(file)` builds `FormData` and appends the file under the backend's
  field name `file`; `Content-Type` is deliberately **not** set, so the browser writes the
  boundary. This is asserted by a test (`xhr.headers['content-type'] === undefined`).
- **Progress:** uploads use `XMLHttpRequest` because `fetch` cannot report upload progress;
  `onProgress({ loaded, total, ratio })` is called from `xhr.upload.onprogress`.
- **Separation:** API functions contain no React code; hooks contain no `fetch`; components contain
  no URLs. Query keys are translated to the backend's snake_case only at the API-function boundary
  (`top_k`, `document_id`).
- **No invented fields:** `listDocuments` returns the backend payload unchanged, and the chunk /
  document functions pass through the documented schemas in `backend/app/routers/documents.py`.

### Timeout budgets (`DEFAULT_TIMEOUTS`)

| Call | Budget |
| --- | --- |
| Health | 10 s |
| Document list / detail / chunks | 30 s |
| Search | 60 s |
| Ask | 120 s |
| Upload | 300 s |

---

## 4. Proxy configuration

```js
server: {
  port: 5173,
  proxy: {
    '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
  },
}
```

Backend CORS was **not** widened. `backend/app/config.py` still allows only
`http://localhost:5173`, and the app does not depend on it because requests are same-origin through
the proxy. `changeOrigin: false` keeps the original `Host` header, which the backend does not
inspect.

---

## 5. Error handling

Every failure reaches components as `ApiError` with `{ kind, status, message, detail, fieldErrors,
details, url }`.

| Case | `kind` | Message source |
| --- | --- | --- |
| 400 / 404 / 413 / 415 | `http` | backend `detail`, else a status fallback |
| 422 validation | `http` | `detail` ("Invalid request payload.") + `fieldErrors` from `errors[]` |
| 422 path/query validation | `http` | same handler; `loc` prefix (`path`/`query`/`body`) stripped |
| 500 | `http` | status fallback unless `detail` is a short, ordinary sentence |
| 502 / 503 / 504 | `http` | backend `detail` (e.g. "Ollama is not reachable…", "…timed out") |
| Non-JSON body (HTML error page, proxy error) | `http` | status fallback; markup never reaches the message |
| 2xx with unparseable body | `parse` | "The backend returned a response this app could not read." |
| Network failure | `network` | "Could not reach the backend. Check that it is running." |
| Timeout | `timeout` | "The request timed out after N seconds." |
| Caller cancellation | `aborted` | "The request was cancelled." |

Rules implemented:

- **No stack traces or internals:** `safeDetail()` rejects details longer than 300 characters,
  multi-line text, `Traceback`, `File "…", line N`, `node_modules` or `.py` references.
- **Validation details preserved, input not:** each entry keeps `{ field, message, type }`; the
  rejected `input` value and `ctx` are dropped.
- **Distinguishable cancellations:** a timeout aborts the internal controller with a flag, so it is
  reported as `timeout`; an external `AbortSignal` is reported as `aborted`. Hooks use
  `isAbortError()` to ignore their own unmount cancellations instead of rendering an error.

Verified against real backend responses (see §7.3): the live 422 uses
`{"detail":"Invalid request payload.","errors":[{"type","loc":["path","document_id"],"msg","input","ctx"}]}`,
which normalises to `fieldErrors["document_id"] = "String should match pattern '^[0-9a-f]{32}$'"`.

---

## 6. Timeout and cancellation implementation

- `request()` creates an `AbortController`, starts `setTimeout(timeoutMs)`, and forwards any
  caller signal into it. On timeout the controller aborts and the promise rejects with
  `kind: "timeout"`; on caller abort it rejects with `kind: "aborted"`. The timer and the abort
  listener are always cleaned up in `finally`.
- An **already-aborted** signal rejects before `fetch` is called, so no request is opened at all.
- `uploadFile()` uses `xhr.timeout` for the budget, `xhr.abort()` for caller cancellation, and
  rejects immediately when the signal is already aborted.
- Hooks pass their own `AbortController` and abort on unmount (React 18 StrictMode double-mount is
  therefore safe), and ignore aborted rejections.

Two defects were found by the tests and fixed before completion:

1. An upload with an already-aborted signal reported `network` instead of `aborted`, because the
   `XMLHttpRequest` availability check ran first. Abort is now checked first.
2. An already-aborted signal still issued the `fetch` call; it now short-circuits.

---

## 7. Verification

### 7.1 Mocked unit tests — `npm test` → **20 passed, 0 failed** (≈0.26 s)

`frontend/tests/api.test.mjs`, Node's built-in runner (`node --test`), no new package.

| Area | Tests |
| --- | --- |
| Configuration | relative URLs, query building, exact timeout budgets |
| Health | full parse, 200-but-degraded, model-missing, unreadable payload, `GET /api/health` |
| Documents | list passthrough, missing `documents[]` rejected as `parse` |
| Ask transport | URL, method, JSON content type, snake_case body |
| Errors | 422 field errors without input leakage, 404 detail, 415 detail, HTML 500 body, network |
| Timeouts | timeout kind, caller abort kind, pre-aborted signal makes no request |
| Upload | `FormData` field `file`, no manual Content-Type, progress ratio, 415 normalisation, pre-aborted |

These are **mocked** tests of transport/normalisation. They do not prove the backend behaves as
mocked; that is covered separately below.

### 7.2 Build — `npm run build` → **passes**

Vite 7.3.8, 39 modules, `dist/assets/index-CaAcEfUj.js` 167.72 kB (55.40 kB gzip),
`dist/assets/index-B8WGmh4x.css` 8.24 kB (2.25 kB gzip), 1.26 s.

### 7.3 Live integration (backend on `127.0.0.1:8000`, Vite dev server on `localhost:5173`)

All requests went through the Vite proxy, i.e. relative `/api` paths as the browser would send them.

| Check | Result |
| --- | --- |
| `GET http://localhost:5173/api/health` | `200`, real payload (`status: ok`, `qwen2.5:3b-instruct` present) |
| `parseHealth()` on that payload | `serviceStatus: "ok"`, `backendAvailable: true`, `ollamaAvailable: true`, `modelPresent: true`, `modelState: "ready"`, `llmUsable: true` |
| `GET http://localhost:5173/api/documents` | `200` `{"count":0,"documents":[]}` (cleaned-up corpus, so an empty list is the correct live result) |
| `GET …/api/documents/aaaaaaaa…` (32 hex) | `404` `{"detail":"Document not found."}` |
| `GET …/api/documents/not-a-valid-id` | `422` with `detail` + `errors[]` exactly as the normaliser expects |
| Browser render of `http://localhost:5173/` | Header shows **"Backend and model ready" · "Ready · qwen2.5:3b-instruct"**, and `main` contains **"Chat Interface"** — the previously unreachable route now renders |
| Console | No errors; only React Router v7 future-flag warnings (pre-existing, unrelated) |

Not exercised live: `/api/ask` (120 s budget, would spend model time and there is no UI yet),
`/api/search`, and a real PDF upload. The upload and ask transports are covered only by mocked
tests and by live schema confirmation from the routers.

### 7.4 Git / hygiene

- `frontend/dist/` is ignored: `git check-ignore` reports `.gitignore:29:frontend/dist/`, and it no
  longer appears in `git status`.
- No branch, commit, stash or history change was made.

---

## 8. Known limitations

1. **`llm.available` is already ANDed with model presence by the backend.** An Ollama outage and a
   missing model both arrive as `available: false`. `modelPresent` distinguishes the missing-model
   case and `llm.detail` carries the backend's explanation; the client cannot separate an outage
   from a missing model beyond that, and the badge says "Ollama is not reachable" only when neither
   signal is positive.
2. **Health is not polled.** The badge probes on mount and on Recheck only; no interval polling, so
   a mid-session model outage is not surfaced until the next health check or request failure.
3. **No UI consumes `useDocuments`, `askQuestion` or `searchDocuments` yet.** They are the 4.2/4.3
   foundation; an unused-hook lint warning is expected until then.
4. **Upload progress is untested in a real browser.** Progress, timeout and abort wiring is
   verified only against a fake `XMLHttpRequest`; a live upload test needs a real PDF and is
   deferred to 4.2 when the UI exists.
5. **No automated routing test.** There is no jsdom/testing-library in the project and none was
   installed; routing was verified by rendering `http://localhost:5173/` in the local browser and
   checking the rendered tree.
6. **`VITE_API_BASE_URL` is untested.** The escape hatch exists but is not exercised; the default
   empty value (proxy) is what was verified.
7. **React Router v7 future flags** still warn in the console. Left as-is: opt-in flags would be an
   unrequested behaviour change.
8. **`lucide-react` is still a devDependency** (Phase 4.0 finding F14). Nothing imports it yet, so
   it was not moved.
9. **`frontend/dist/` remains on disk** as a build output; only its ignore rule was added.
