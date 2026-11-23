/**
 * POST /api/ask - the Phase 3.3 evidence-grounded answering endpoint.
 *
 * Request (backend/app/routers/qa.py AskRequest):
 *   { question, top_k <= 20 (default 5), document_id? }
 *
 * Response fields are returned unmodified. The UI must branch on `decision`
 * ("answer" | "partial_answer" | "abstain"), never on whether `answer` is
 * non-empty - see docs/PHASE_4_0_FRONTEND_AUDIT.md section 4.3.
 *
 * No Q&A interface is built in Phase 4.1; this is the transport only.
 */

import { DEFAULT_TIMEOUTS, request } from './client.js'

export function askQuestion(
  { question, topK = 5, documentId = null },
  { signal, timeoutMs = DEFAULT_TIMEOUTS.ask } = {},
) {
  const body = { question, top_k: topK }
  if (documentId) body.document_id = documentId

  return request('/api/ask', {
    method: 'POST',
    body,
    timeoutMs,
    signal,
  })
}
