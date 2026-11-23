/**
 * POST /api/ask
 *
 * Sends an evidence-grounded question to the backend.
 *
 * Request:
 * {
 *   question,
 *   top_k,
 *   document_id?
 * }
 *
 * Response: AskResponse
 *
 * The UI must branch on `decision`:
 * answer | partial_answer | abstain
 */

import { DEFAULT_TIMEOUTS, request } from './client.js'

export function askQuestion(
  { question, topK = 5, documentId = null },
  { signal, timeoutMs = DEFAULT_TIMEOUTS.ask } = {},
) {
  const body = {
    question,
    top_k: topK,
  }

  if (documentId) {
    body.document_id = documentId
  }

  return request('/api/ask', {
    method: 'POST',
    body,
    timeoutMs,
    signal,
  })
}

export function ask(
  question,
  { topK = 5, documentId, signal, timeoutMs } = {},
) {
  return askQuestion(
    { question, topK, documentId },
    { signal, timeoutMs: timeoutMs ?? DEFAULT_TIMEOUTS.ask },
  )
}