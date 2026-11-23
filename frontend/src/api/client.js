/**
 * Single transport for every backend call.
 *
 * - Relative `/api` URLs by default: the Vite dev server proxies them to
 *   http://127.0.0.1:8000, so the browser never needs CORS.
 * - `VITE_API_BASE_URL` is an explicit escape hatch (empty by default).
 * - Every request has a timeout budget and accepts an AbortSignal.
 * - Every failure becomes an `ApiError`; callers never see raw fetch errors.
 *
 * Multipart uploads use XMLHttpRequest because `fetch` cannot report upload
 * progress. The `Content-Type` header is never set for FormData: the browser
 * must generate the multipart boundary itself.
 */

import {
  isApiError,
  normalizeAbortError,
  normalizeHttpError,
  normalizeNetworkError,
  normalizeParseError,
  normalizeTimeoutError,
} from './errors.js'

export const DEFAULT_TIMEOUTS = Object.freeze({
  health: 10_000,
  documents: 30_000,
  search: 60_000,
  ask: 120_000,
  upload: 300_000,
})

function readEnv() {
  // `import.meta.env` exists under Vite and is undefined under plain Node
  // (used by the API tests), hence the guard.
  if (typeof import.meta !== 'undefined' && import.meta && import.meta.env) {
    return import.meta.env
  }
  return {}
}

const configuredBase = readEnv().VITE_API_BASE_URL

/** Base URL prefix for API calls. Empty string means "same origin". */
export const API_BASE_URL = typeof configuredBase === 'string'
  ? configuredBase.trim().replace(/\/+$/, '')
  : ''

export function apiUrl(path, query) {
  const suffix = path.startsWith('/') ? path : `/${path}`
  let url = `${API_BASE_URL}${suffix}`

  if (query && typeof query === 'object') {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      params.set(key, String(value))
    }
    const search = params.toString()
    if (search) url += `?${search}`
  }

  return url
}

function encodeBody(body) {
  if (body === undefined || body === null) return undefined
  if (typeof body === 'string') return body
  if (typeof FormData !== 'undefined' && body instanceof FormData) return body
  return JSON.stringify(body)
}

function buildHeaders(body, extraHeaders) {
  const headers = { Accept: 'application/json', ...extraHeaders }
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData
  const hasContentType = Object.keys(headers).some(
    (name) => name.toLowerCase() === 'content-type',
  )
  // Let the browser pick the multipart boundary for FormData.
  if (!isFormData && body !== undefined && !hasContentType) {
    headers['Content-Type'] = 'application/json'
  }
  return headers
}

function parseBodyText(text, url, status) {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    throw normalizeParseError(url, status)
  }
}

/**
 * @returns parsed JSON body, or null for an empty response.
 * @throws {ApiError}
 */
export async function request(path, options = {}) {
  const {
    method = 'GET',
    body,
    query,
    timeoutMs = DEFAULT_TIMEOUTS.documents,
    signal,
    headers: extraHeaders,
  } = options

  const url = apiUrl(path, query)
  // Never open a request that the caller has already cancelled.
  if (signal?.aborted) throw normalizeAbortError(url)

  const controller = new AbortController()
  let timedOut = false
  let abortedByCaller = false

  const timer = timeoutMs > 0
    ? setTimeout(() => {
        timedOut = true
        controller.abort()
      }, timeoutMs)
    : null

  const forwardAbort = () => {
    abortedByCaller = true
    controller.abort()
  }

  if (signal) {
    if (signal.aborted) {
      forwardAbort()
    } else {
      signal.addEventListener('abort', forwardAbort)
    }
  }

  try {
    let response
    try {
      response = await fetch(url, {
        method,
        headers: buildHeaders(body, extraHeaders),
        body: encodeBody(body),
        signal: controller.signal,
      })
    } catch (error) {
      if (timedOut) throw normalizeTimeoutError(url, timeoutMs)
      if (abortedByCaller || error?.name === 'AbortError') {
        throw normalizeAbortError(url)
      }
      throw normalizeNetworkError(error, url)
    }

    let text
    try {
      text = await response.text()
    } catch (error) {
      if (timedOut) throw normalizeTimeoutError(url, timeoutMs)
      if (abortedByCaller || error?.name === 'AbortError') {
        throw normalizeAbortError(url)
      }
      throw normalizeNetworkError(error, url)
    }

    let payload = null
    if (text) {
      try {
        payload = JSON.parse(text)
      } catch {
        payload = null
      }
    }

    if (!response.ok) {
      throw normalizeHttpError({ status: response.status, payload, url })
    }
    if (!text) return null
    if (payload === null) throw normalizeParseError(url, response.status)
    return payload
  } finally {
    if (timer) clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', forwardAbort)
  }
}

/**
 * Multipart upload with progress, timeout and cancellation.
 *
 * `formData` must be built by the caller; no Content-Type header is set so the
 * browser generates the boundary.
 *
 * @param {string} path
 * @param {FormData} formData
 * @param {{ timeoutMs?: number, signal?: AbortSignal, onProgress?: (p: { loaded: number, total: number, ratio: number | null }) => void }} [options]
 */
export function uploadFile(path, formData, options = {}) {
  const {
    timeoutMs = DEFAULT_TIMEOUTS.upload,
    signal,
    onProgress,
  } = options

  const url = apiUrl(path)

  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(normalizeAbortError(url))
      return
    }

    if (typeof XMLHttpRequest === 'undefined') {
      reject(
        normalizeNetworkError(
          new Error('XMLHttpRequest is not available in this environment.'),
          url,
        ),
      )
      return
    }

    const xhr = new XMLHttpRequest()
    let settled = false
    const finish = (fn, value) => {
      if (settled) return
      settled = true
      if (signal) signal.removeEventListener('abort', onAbortSignal)
      fn(value)
    }
    const onAbortSignal = () => {
      if (settled) return
      settled = true
      xhr.abort()
      reject(normalizeAbortError(url))
    }

    xhr.open('POST', url)
    if (timeoutMs > 0) xhr.timeout = timeoutMs
    xhr.setRequestHeader('Accept', 'application/json')

    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (!event?.lengthComputable) return
        const total = event.total
        onProgress({
          loaded: event.loaded,
          total,
          ratio: total > 0 ? Math.min(1, event.loaded / total) : null,
        })
      }
    }

    xhr.onload = () => {
      let payload = null
      if (xhr.responseText) {
        try {
          payload = JSON.parse(xhr.responseText)
        } catch {
          payload = null
        }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        finish(resolve, payload)
        return
      }
      finish(reject, normalizeHttpError({ status: xhr.status, payload, url }))
    }
    xhr.onerror = () => finish(reject, normalizeNetworkError(null, url))
    xhr.ontimeout = () => finish(reject, normalizeTimeoutError(url, timeoutMs))
    xhr.onabort = () => finish(reject, normalizeAbortError(url))

    if (signal) signal.addEventListener('abort', onAbortSignal)

    try {
      xhr.send(formData)
    } catch (error) {
      finish(reject, normalizeNetworkError(error, url))
    }
  })
}

export { isApiError }
