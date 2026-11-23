import { DEFAULT_TIMEOUTS, request } from './client.js'

export function analyzeConflicts(
  { query, topK = 20, documentId = null },
  { signal, timeoutMs = DEFAULT_TIMEOUTS.search } = {},
) {
  const body = { query, top_k: topK }
  if (documentId) body.document_id = documentId
  return request('/api/conflicts', {
    method: 'POST',
    body,
    signal,
    timeoutMs,
  })
}
