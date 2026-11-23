/**
 * Normalised error model shared by every API call.
 *
 * Components never see a raw fetch failure, an HTML error page or a stack
 * trace. They see an `ApiError` with:
 *
 *   kind        one of API_ERROR_KINDS
 *   status      HTTP status for `kind: "http"`, otherwise null
 *   message     safe, user-facing sentence
 *   detail      the server's own `detail` string, when it is safe to show
 *   fieldErrors { fieldName: message } built from FastAPI validation errors
 *   details     [{ field, message, type }] - validation entries only, never
 *               the rejected input value or any server internals
 *   url         request path (no credentials, no query secrets)
 */

export const API_ERROR_KINDS = Object.freeze({
  HTTP: 'http',
  NETWORK: 'network',
  TIMEOUT: 'timeout',
  ABORTED: 'aborted',
  PARSE: 'parse',
})

// Fallbacks used when the backend sends no usable `detail`. Messages for
// 502/503/504 mirror the backend's documented failure modes.
const STATUS_MESSAGES = Object.freeze({
  400: 'The server rejected the request.',
  401: 'Authentication is required.',
  403: 'The server refused the request.',
  404: 'The requested resource was not found.',
  405: 'The server does not allow this operation.',
  409: 'The request conflicts with the current state of the server.',
  413: 'The file is larger than the server accepts.',
  415: 'The server does not accept this file type.',
  422: 'The request contains invalid values.',
  429: 'Too many requests. Please wait and try again.',
  500: 'The backend failed while processing the request.',
  502: 'The language model returned an unusable response.',
  503: 'A required backend service is unavailable.',
  504: 'The language model did not respond in time.',
})

const LOCATION_PREFIXES = new Set(['body', 'query', 'path', 'header', 'cookie'])
const MAX_SAFE_DETAIL_CHARS = 300

export class ApiError extends Error {
  constructor({
    kind = API_ERROR_KINDS.HTTP,
    message,
    status = null,
    detail = null,
    fieldErrors = {},
    details = [],
    url = null,
    cause = null,
  } = {}) {
    super(message || 'The request failed.')
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.detail = detail
    this.fieldErrors = fieldErrors
    this.details = details
    this.url = url
    if (cause) this.cause = cause
  }

  get isHttp() {
    return this.kind === API_ERROR_KINDS.HTTP
  }

  get isNetwork() {
    return this.kind === API_ERROR_KINDS.NETWORK
  }

  get isTimeout() {
    return this.kind === API_ERROR_KINDS.TIMEOUT
  }

  get isAborted() {
    return this.kind === API_ERROR_KINDS.ABORTED
  }

  toJSON() {
    return {
      kind: this.kind,
      status: this.status,
      message: this.message,
      detail: this.detail,
      fieldErrors: this.fieldErrors,
      details: this.details,
      url: this.url,
    }
  }
}

export function isApiError(value) {
  return value instanceof ApiError
}

export function isAbortError(value) {
  return isApiError(value) && value.kind === API_ERROR_KINDS.ABORTED
}

function isRecord(value) {
  return typeof value === 'object' && value !== null
}

/**
 * The backend's global RequestValidationError handler returns
 * `{ detail: "Invalid request payload.", errors: [...] }`; FastAPI's default
 * shape is `{ detail: [{ loc, msg, type, ... }] }`. Both are handled here.
 * `input` and `ctx` are deliberately dropped.
 */
function validationSummary(payload) {
  const raw = Array.isArray(payload?.errors)
    ? payload.errors
    : Array.isArray(payload?.detail)
      ? payload.detail
      : []

  const fieldErrors = {}
  const details = []

  for (const entry of raw) {
    if (!isRecord(entry)) continue
    const loc = Array.isArray(entry.loc)
      ? entry.loc.filter((part) => !LOCATION_PREFIXES.has(String(part)))
      : []
    const field = loc.length ? loc.join('.') : null
    const message =
      typeof entry.msg === 'string' && entry.msg.trim()
        ? entry.msg.trim()
        : 'The value is not valid.'
    const type = typeof entry.type === 'string' ? entry.type : null
    details.push({ field, message, type })
    if (field && !fieldErrors[field]) fieldErrors[field] = message
  }

  return { fieldErrors, details }
}

/**
 * Accept a server `detail` only when it reads like a sentence the backend
 * wrote for a client. Anything that smells like an internal error is replaced
 * by the status fallback.
 */
function safeDetail(payload) {
  const value = isRecord(payload) && typeof payload.detail === 'string'
    ? payload.detail.trim()
    : ''
  if (!value) return null
  if (value.length > MAX_SAFE_DETAIL_CHARS) return null
  if (/traceback|File ".+"|node_modules|\.py", line \d/i.test(value)) return null
  if (value.includes('\n')) return null
  return value
}

export function normalizeHttpError({ status, payload, url = null }) {
  const { fieldErrors, details } = validationSummary(payload)
  const detail = safeDetail(payload)
  const fallback =
    STATUS_MESSAGES[status] ||
    (status >= 500
      ? 'The backend could not complete the request.'
      : 'The request was rejected.')

  return new ApiError({
    kind: API_ERROR_KINDS.HTTP,
    status,
    message: detail || fallback,
    detail,
    fieldErrors,
    details,
    url,
  })
}

export function normalizeNetworkError(cause, url = null) {
  return new ApiError({
    kind: API_ERROR_KINDS.NETWORK,
    message: 'Could not reach the backend. Check that it is running.',
    url,
    cause,
  })
}

export function normalizeTimeoutError(url, timeoutMs) {
  const seconds = Math.max(1, Math.round(timeoutMs / 1000))
  return new ApiError({
    kind: API_ERROR_KINDS.TIMEOUT,
    message: `The request timed out after ${seconds} second${seconds === 1 ? '' : 's'}.`,
    url,
  })
}

export function normalizeAbortError(url = null) {
  return new ApiError({
    kind: API_ERROR_KINDS.ABORTED,
    message: 'The request was cancelled.',
    url,
  })
}

export function normalizeParseError(url, status = null) {
  return new ApiError({
    kind: API_ERROR_KINDS.PARSE,
    status,
    message: 'The backend returned a response this app could not read.',
    url,
  })
}
