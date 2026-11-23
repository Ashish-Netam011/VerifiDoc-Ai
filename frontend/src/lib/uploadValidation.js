/**
 * Client-side upload hints. The backend remains authoritative: it re-checks the
 * filename, the size limit (MAX_UPLOAD_MB), the PDF signature and whether the
 * PDF has extractable text, and its error is what the UI shows on failure.
 *
 * The size limit mirrors the backend default (backend/app/config.py
 * `max_upload_mb = 25`). It is not exposed through the API, so if the backend
 * limit is changed this constant must be updated with it; a mismatch only
 * changes which layer rejects an oversized file, never whether it is accepted.
 */
import { formatBytes } from './format.js'

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024
export const MAX_UPLOAD_LABEL = formatBytes(MAX_UPLOAD_BYTES)

const PDF_SIGNATURE = '%PDF-'
const SIGNATURE_HEAD_BYTES = 1024

function hasPdfSignature(head) {
  return head.includes(PDF_SIGNATURE)
}

/**
 * @param {File} file
 * @param {{ maxBytes?: number }} [options] - maxBytes exists so tests do not
 *   need to allocate a 25 MB file.
 * @returns {Promise<{ ok: true } | { ok: false, message: string }>}
 */
export async function validatePdfFile(file, { maxBytes = MAX_UPLOAD_BYTES } = {}) {
  if (!file) return { ok: false, message: 'No file was selected.' }

  const name = typeof file.name === 'string' ? file.name : ''
  if (!name.toLowerCase().endsWith('.pdf')) {
    return { ok: false, message: 'Only PDF files are accepted.' }
  }

  if (file.size === 0) {
    return { ok: false, message: 'This file is empty.' }
  }

  if (file.size > maxBytes) {
    return {
      ok: false,
      message: `This file is ${formatBytes(file.size)}; the server accepts up to ${formatBytes(maxBytes)}.`,
    }
  }

  // MIME type is not trusted (browsers and OSes disagree, and it is trivial to
  // fake). Check the same signature the backend checks.
  let head = ''
  try {
    const buffer = await file.slice(0, SIGNATURE_HEAD_BYTES).arrayBuffer()
    head = new TextDecoder('latin1').decode(new Uint8Array(buffer))
  } catch {
    return { ok: false, message: 'This file could not be read.' }
  }

  if (!hasPdfSignature(head)) {
    return {
      ok: false,
      message: 'This file is not a valid PDF (no PDF signature), even though its name ends in .pdf.',
    }
  }

  return { ok: true }
}
