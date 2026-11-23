/**
 * POST /api/search - hybrid semantic + BM25 retrieval.
 *
 * Request (backend/app/routers/search.py SearchRequest):
 *   { query, top_k <= 50 (default 5), document_id? }
 *
 * Response: { query, results[], result_count } where each result is
 * { chunk_id, document_id, filename, page_number, text, semantic_score,
 *   bm25_score, rrf_score }.
 */

import { DEFAULT_TIMEOUTS, request } from './client.js'

export function searchDocuments(
  { query, topK = 5, documentId = null },
  { signal, timeoutMs = DEFAULT_TIMEOUTS.search } = {},
) {
  const body = { query, top_k: topK }
  if (documentId) body.document_id = documentId

  return request('/api/search', {
    method: 'POST',
    body,
    timeoutMs,
    signal,
  })
}
