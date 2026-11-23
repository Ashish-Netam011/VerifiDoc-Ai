/**
 * API layer tests. Run with `npm test` (Node's built-in test runner, no extra
 * packages). Every test here mocks fetch/XMLHttpRequest: these are unit tests
 * of transport, normalisation and timeouts, NOT live backend tests.
 *
 * The live checks against the running backend and the Vite proxy are reported
 * separately in docs/PHASE_4_1_API_INTEGRATION_REPORT.md.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { searchDocuments } from '../src/api/search.js'
import { API_BASE_URL, DEFAULT_TIMEOUTS, apiUrl, uploadFile } from '../src/api/client.js'
import { ApiError } from '../src/api/errors.js'
import { getHealth, parseHealth } from '../src/api/health.js'
import {
  getDocumentTables,
  listDocuments,
  uploadDocument,
} from '../src/api/documents.js'
import { askQuestion } from '../src/api/questions.js'
import { analyzeConflicts } from '../src/api/conflicts.js'
import { getAmendments } from '../src/api/amendments.js'

const HEALTH_PAYLOAD = {
  status: 'ok',
  backend: { status: 'ok', version: '0.2.0', uptime_s: 1262.328 },
  llm: {
    available: true,
    model: 'anthropic/claude-sonnet-5',
    model_present: true,
    detail: 'OpenRouter credentials and configured model are available.',
  },
}

const DOCUMENT = {
  document_id: 'a'.repeat(32),
  filename: 'lease.pdf',
  file_path: 'pdfs/lease.pdf',
  page_count: 1,
  uploaded_at: '2026-11-23T10:00:00Z',
  status: 'processed',
  chunk_count: 4,
  file_size_bytes: 1234,
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function stubFetch(handler) {
  const calls = []
  const original = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init })
    return handler(url, init)
  }
  return {
    calls,
    restore() {
      globalThis.fetch = original
    },
  }
}

// -- configuration ----------------------------------------------------------

test('defaults use relative /api URLs and the documented timeout budgets', () => {
  assert.equal(API_BASE_URL, '')
  assert.equal(apiUrl('/api/documents'), '/api/documents')
  assert.equal(
    apiUrl('/api/documents', { limit: 5, empty: '', missing: null }),
    '/api/documents?limit=5',
  )
  assert.deepEqual(DEFAULT_TIMEOUTS, {
    health: 10_000,
    documents: 30_000,
    search: 60_000,
    ask: 120_000,
    upload: 300_000,
  })
})

// -- health -----------------------------------------------------------------

test('parseHealth reports every signal from the payload', () => {
  const health = parseHealth(HEALTH_PAYLOAD)
  assert.equal(health.serviceStatus, 'ok')
  assert.equal(health.backendAvailable, true)
  assert.equal(health.providerAvailable, true)
  assert.equal(health.modelPresent, true)
  assert.equal(health.llmUsable, true)
  assert.equal(health.modelState, 'ready')
  assert.equal(health.model, 'anthropic/claude-sonnet-5')
  assert.equal(health.backendVersion, '0.2.0')
})

test('a 200 response with a degraded LLM is not treated as healthy', () => {
  const health = parseHealth({
    ...HEALTH_PAYLOAD,
    status: 'degraded',
    llm: {
      available: false,
      model: 'anthropic/claude-sonnet-5',
      model_present: false,
      detail: 'Model is not installed.',
    },
  })
  assert.equal(health.serviceStatus, 'degraded')
  assert.equal(health.backendAvailable, true)
  assert.equal(health.providerAvailable, false)
  assert.equal(health.modelPresent, false)
  assert.equal(health.llmUsable, false)
  assert.equal(health.modelState, 'provider_unavailable')
})

test('a configured model without provider availability is not ready', () => {
  const health = parseHealth({
    ...HEALTH_PAYLOAD,
    llm: { ...HEALTH_PAYLOAD.llm, available: false, model_present: true },
  })
  assert.equal(health.llmUsable, false)
  assert.equal(health.modelState, 'provider_unavailable')
})

test('an unreadable health payload becomes a parse error', () => {
  assert.throws(() => parseHealth({ status: 'ok' }), (error) => {
    assert.ok(error instanceof ApiError)
    assert.equal(error.kind, 'parse')
    return true
  })
})

test('getHealth calls GET /api/health and parses the payload', async () => {
  const fetchStub = stubFetch(() => jsonResponse(HEALTH_PAYLOAD))
  try {
    const health = await getHealth()
    assert.equal(fetchStub.calls.length, 1)
    assert.equal(fetchStub.calls[0].url, '/api/health')
    assert.equal(fetchStub.calls[0].init.method, 'GET')
    assert.equal(health.llmUsable, true)
  } finally {
    fetchStub.restore()
  }
})

// -- documents --------------------------------------------------------------

test('listDocuments returns the backend payload unchanged', async () => {
  const fetchStub = stubFetch(() => jsonResponse({ count: 1, documents: [DOCUMENT] }))
  try {
    const payload = await listDocuments()
    assert.equal(fetchStub.calls[0].url, '/api/documents')
    assert.equal(payload.count, 1)
    assert.deepEqual(payload.documents[0], DOCUMENT)
  } finally {
    fetchStub.restore()
  }
})

test('a document list without a documents array is rejected as a parse error', async () => {
  const fetchStub = stubFetch(() => jsonResponse({ count: 0 }))
  try {
    await assert.rejects(listDocuments(), (error) => error.kind === 'parse')
  } finally {
    fetchStub.restore()
  }
})

test('askQuestion posts the documented snake_case body', async () => {
  const fetchStub = stubFetch(() => jsonResponse({ decision: 'abstain' }))
  try {
    await askQuestion({ question: 'What is the rent?', topK: 3, documentId: DOCUMENT.document_id })
    const { url, init } = fetchStub.calls[0]
    assert.equal(url, '/api/ask')
    assert.equal(init.method, 'POST')
    assert.equal(init.headers['Content-Type'], 'application/json')
    assert.deepEqual(JSON.parse(init.body), {
      question: 'What is the rent?',
      top_k: 3,
      document_id: DOCUMENT.document_id,
    })
  } finally {
    fetchStub.restore()
  }
})


// -- search -----------------------------------------------------------------

const SEARCH_RESULT = {
  chunk_id: 'chunk-001',
  document_id: DOCUMENT.document_id,
  filename: 'lease.pdf',
  page_number: 1,
  text: 'The monthly rent is INR 15,000.',
  semantic_score: 0.89,
  bm25_score: 2.45,
  rrf_score: 0.032,
}

test('searchDocuments posts the documented snake_case body', async () => {
  const payload = {
    query: 'What is the monthly rent?',
    results: [SEARCH_RESULT],
    result_count: 1,
  }

  const fetchStub = stubFetch(() => jsonResponse(payload))

  try {
    const response = await searchDocuments({
      query: 'What is the monthly rent?',
      topK: 5,
      documentId: DOCUMENT.document_id,
    })

    const { url, init } = fetchStub.calls[0]

    assert.equal(url, '/api/search')
    assert.equal(init.method, 'POST')
    assert.deepEqual(JSON.parse(init.body), {
      query: 'What is the monthly rent?',
      top_k: 5,
      document_id: DOCUMENT.document_id,
    })
    assert.deepEqual(response, payload)
  } finally {
    fetchStub.restore()
  }
})

test('searchDocuments omits document_id for all-document searches', async () => {
  const fetchStub = stubFetch(() =>
    jsonResponse({ query: 'rent', results: [], result_count: 0 }),
  )

  try {
    await searchDocuments({ query: 'rent', topK: 10 })

    assert.deepEqual(JSON.parse(fetchStub.calls[0].init.body), {
      query: 'rent',
      top_k: 10,
    })
  } finally {
    fetchStub.restore()
  }
})

test('searchDocuments normalises backend errors', async () => {
  const fetchStub = stubFetch(() =>
    jsonResponse({ detail: 'Invalid search query.' }, 422),
  )

  try {
    await assert.rejects(
      searchDocuments({ query: 'rent' }),
      (error) => {
        assert.equal(error.status, 422)
        assert.equal(error.message, 'Invalid search query.')
        return true
      },
    )
  } finally {
    fetchStub.restore()
  }
})


// -- error normalisation ----------------------------------------------------

test('422 validation errors keep FastAPI details but drop the submitted input', async () => {
  const fetchStub = stubFetch(() =>
    jsonResponse(
      {
        detail: 'Invalid request payload.',
        errors: [
          {
            type: 'value_error',
            loc: ['body', 'question'],
            msg: 'Value error, question must not be empty or whitespace only',
            input: '   ',
            ctx: { error: {} },
          },
        ],
      },
      422,
    ),
  )
  try {
    await assert.rejects(askQuestion({ question: '   ' }), (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.kind, 'http')
      assert.equal(error.status, 422)
      assert.equal(error.message, 'Invalid request payload.')
      assert.equal(error.detail, 'Invalid request payload.')
      assert.match(error.fieldErrors.question, /question must not be empty/)
      assert.deepEqual(Object.keys(error.details[0]).sort(), ['field', 'message', 'type'])
      assert.equal(error.details[0].field, 'question')
      assert.ok(!JSON.stringify(error.details).includes('   '))
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

test('404 keeps the backend detail sentence', async () => {
  const fetchStub = stubFetch(() => jsonResponse({ detail: 'Document not found.' }, 404))
  try {
    await assert.rejects(listDocuments(), (error) => {
      assert.equal(error.status, 404)
      assert.equal(error.message, 'Document not found.')
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

test('415 keeps the backend detail sentence', async () => {
  const fetchStub = stubFetch(() =>
    jsonResponse({ detail: 'Only .pdf files are accepted.' }, 415),
  )
  try {
    await assert.rejects(listDocuments(), (error) => {
      assert.equal(error.status, 415)
      assert.equal(error.message, 'Only .pdf files are accepted.')
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

test('an HTML error page never leaks markup or internals to the message', async () => {
  const fetchStub = stubFetch(
    () =>
      new Response('<html><body>Traceback (most recent call last): boom</body></html>', {
        status: 500,
        headers: { 'content-type': 'text/html' },
      }),
  )
  try {
    await assert.rejects(getHealth(), (error) => {
      assert.equal(error.kind, 'http')
      assert.equal(error.status, 500)
      assert.equal(error.message, 'The backend failed while processing the request.')
      assert.ok(!error.message.includes('<'))
      assert.ok(!error.message.toLowerCase().includes('traceback'))
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

test('a network failure becomes a network error', async () => {
  const fetchStub = stubFetch(() => {
    throw new TypeError('Failed to fetch')
  })
  try {
    await assert.rejects(getHealth(), (error) => {
      assert.equal(error.kind, 'network')
      assert.equal(error.isNetwork, true)
      assert.match(error.message, /Could not reach the backend/)
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

test('the timeout budget aborts the request and reports a timeout', async () => {
  const fetchStub = stubFetch(
    (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => {
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
        })
      }),
  )
  try {
    await assert.rejects(getHealth({ timeoutMs: 30 }), (error) => {
      assert.equal(error.kind, 'timeout')
      assert.equal(error.isTimeout, true)
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

test('caller cancellation reports an abort, not a timeout', async () => {
  const fetchStub = stubFetch(
    (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => {
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
        })
      }),
  )
  try {
    const controller = new AbortController()
    const pending = getHealth({ signal: controller.signal })
    controller.abort()
    await assert.rejects(pending, (error) => {
      assert.equal(error.kind, 'aborted')
      assert.equal(error.isAborted, true)
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

test('an already-aborted signal never issues a request', async () => {
  const fetchStub = stubFetch(() => jsonResponse(HEALTH_PAYLOAD))
  try {
    const controller = new AbortController()
    controller.abort()
    await assert.rejects(getHealth({ signal: controller.signal }), (error) => {
      assert.equal(error.kind, 'aborted')
      return true
    })
  } finally {
    fetchStub.restore()
  }
})

// -- multipart upload -------------------------------------------------------

class FakeXMLHttpRequest {
  static instances = []

  constructor() {
    this.headers = {}
    this.upload = {}
    this.status = 0
    this.responseText = ''
    FakeXMLHttpRequest.instances.push(this)
  }

  open(method, url) {
    this.method = method
    this.url = url
  }

  setRequestHeader(name, value) {
    this.headers[name.toLowerCase()] = value
  }

  send(body) {
    this.body = body
  }

  abort() {
    this.aborted = true
    this.onabort?.()
  }

  respond(status, payload) {
    this.status = status
    this.responseText = payload === undefined ? '' : JSON.stringify(payload)
    this.onload?.()
  }
}

test('uploadDocument sends multipart FormData without a manual Content-Type', async () => {
  const original = globalThis.XMLHttpRequest
  globalThis.XMLHttpRequest = FakeXMLHttpRequest
  FakeXMLHttpRequest.instances = []
  const progress = []

  try {
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'lease.pdf', {
      type: 'application/pdf',
    })
    const pending = uploadDocument(file, {
      onProgress: (event) => progress.push(event),
    })
    const xhr = FakeXMLHttpRequest.instances.at(-1)

    assert.equal(xhr.method, 'POST')
    assert.equal(xhr.url, '/api/documents/upload')
    assert.ok(xhr.body instanceof FormData)
    assert.equal(xhr.body.get('file').name, 'lease.pdf')
    assert.equal(xhr.headers['content-type'], undefined)
    assert.equal(xhr.headers.accept, 'application/json')

    xhr.upload.onprogress({ lengthComputable: true, loaded: 50, total: 200 })
    xhr.respond(201, DOCUMENT)

    const created = await pending
    assert.equal(created.document_id, DOCUMENT.document_id)
    assert.equal(progress.length, 1)
    assert.equal(progress[0].ratio, 0.25)
  } finally {
    globalThis.XMLHttpRequest = original
  }
})

test('upload errors use the same normalisation as JSON requests', async () => {
  const original = globalThis.XMLHttpRequest
  globalThis.XMLHttpRequest = FakeXMLHttpRequest
  FakeXMLHttpRequest.instances = []

  try {
    const file = new File([new Uint8Array([1, 2, 3])], 'notes.txt', { type: 'text/plain' })
    const pending = uploadDocument(file)
    const xhr = FakeXMLHttpRequest.instances.at(-1)
    xhr.respond(415, { detail: 'Only .pdf files are accepted.' })

    await assert.rejects(pending, (error) => {
      assert.equal(error.kind, 'http')
      assert.equal(error.status, 415)
      assert.equal(error.message, 'Only .pdf files are accepted.')
      return true
    })
  } finally {
    globalThis.XMLHttpRequest = original
  }
})

test('uploadFile rejects immediately when the signal is already aborted', async () => {
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(
    uploadFile('/api/documents/upload', new FormData(), { signal: controller.signal }),
    (error) => error.kind === 'aborted',
  )
})

test('getDocumentTables parses the additive table endpoint response', async () => {
  const expected = {
    document_id: DOCUMENT.document_id,
    filename: DOCUMENT.filename,
    table_count: 0,
    tables: [],
  }
  const fetchStub = stubFetch(() => jsonResponse(expected))
  try {
    const result = await getDocumentTables(DOCUMENT.document_id)
    assert.deepEqual(result, expected)
    assert.equal(
      fetchStub.calls[0].url,
      `/api/documents/${DOCUMENT.document_id}/tables`,
    )
  } finally {
    fetchStub.restore()
  }
})

test('analyzeConflicts sends the documented query and top_k fields', async () => {
  const fetchStub = stubFetch(() =>
    jsonResponse({ query: 'rent', result_count: 1, facts: [], comparisons: [] }),
  )
  try {
    await analyzeConflicts({ query: 'rent', topK: 12 })
    assert.equal(fetchStub.calls[0].url, '/api/conflicts')
    assert.equal(fetchStub.calls[0].init.method, 'POST')
    assert.deepEqual(JSON.parse(fetchStub.calls[0].init.body), {
      query: 'rent',
      top_k: 12,
    })
  } finally {
    fetchStub.restore()
  }
})

test('getAmendments requests an as-of date without changing the existing API', async () => {
  const fetchStub = stubFetch(() =>
    jsonResponse({ as_of_date: '2025-01-01', amendments: [], resolutions: [] }),
  )
  try {
    await getAmendments({ asOfDate: '2025-01-01' })
    assert.equal(fetchStub.calls[0].url, '/api/amendments?as_of_date=2025-01-01')
    assert.equal(fetchStub.calls[0].init.method, 'GET')
  } finally {
    fetchStub.restore()
  }
})
