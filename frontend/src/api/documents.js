/**
 * Document endpoints. Request and response shapes are taken verbatim from
 * backend/app/routers/documents.py; nothing is renamed or invented here.
 *
 *   GET  /api/documents                  -> { count, documents: DocumentMetadata[] }
 *   GET  /api/documents/{id}             -> DocumentMetadata
 *   GET  /api/documents/{id}/chunks      -> { document_id, filename, page_count,
 *                                             chunk_count, chunks: ChunkModel[] }
 *   POST /api/documents/upload           -> 201 DocumentMetadata
 *
 * DocumentMetadata: document_id, filename, file_path, page_count, uploaded_at,
 *                   status ("processed" | "failed"), chunk_count, file_size_bytes
 * ChunkModel:       chunk_id, document_id, page_number, text, start_offset,
 *                   end_offset
 */

import { DEFAULT_TIMEOUTS, request, uploadFile } from './client.js'
import { ApiError } from './errors.js'

function requireObject(payload, url) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new ApiError({
      kind: 'parse',
      message: 'The backend returned a response this app could not read.',
      url,
    })
  }
  return payload
}

function documentPath(documentId, suffix = '') {
  return `/api/documents/${encodeURIComponent(documentId)}${suffix}`
}

/** @returns {Promise<{ count: number, documents: object[] }>} */
export async function listDocuments({
  signal,
  timeoutMs = DEFAULT_TIMEOUTS.documents,
} = {}) {
  const payload = requireObject(
    await request('/api/documents', { timeoutMs, signal }),
    '/api/documents',
  )
  if (!Array.isArray(payload.documents)) {
    throw new ApiError({
      kind: 'parse',
      message: 'The document list could not be read.',
      url: '/api/documents',
    })
  }
  return payload
}

/** @returns {Promise<object>} DocumentMetadata */
export async function getDocument(documentId, {
  signal,
  timeoutMs = DEFAULT_TIMEOUTS.documents,
} = {}) {
  const path = documentPath(documentId)
  return requireObject(await request(path, { timeoutMs, signal }), path)
}

/** @returns {Promise<{ document_id: string, filename: string, page_count: number,
 *                      chunk_count: number, chunks: object[] }>} */
export async function getDocumentChunks(documentId, {
  signal,
  timeoutMs = DEFAULT_TIMEOUTS.documents,
} = {}) {
  const path = documentPath(documentId, '/chunks')
  const payload = requireObject(await request(path, { timeoutMs, signal }), path)
  if (!Array.isArray(payload.chunks)) {
    throw new ApiError({
      kind: 'parse',
      message: 'The document chunks could not be read.',
      url: path,
    })
  }
  return payload
}

/**
 * Upload one PDF. The FormData field name must be `file` (backend signature)
 * and no Content-Type header is set, so the browser writes the boundary.
 *
 * @param {File} file
 * @param {{ signal?: AbortSignal, onProgress?: (p: { loaded: number, total: number, ratio: number | null }) => void, timeoutMs?: number }} [options]
 * @returns {Promise<object>} DocumentMetadata
 */
export function uploadDocument(file, {
  signal,
  onProgress,
  timeoutMs = DEFAULT_TIMEOUTS.upload,
} = {}) {
  const formData = new FormData()
  formData.append('file', file, file?.name ?? 'document.pdf')
  return uploadFile('/api/documents/upload', formData, {
    signal,
    onProgress,
    timeoutMs,
  })
}
