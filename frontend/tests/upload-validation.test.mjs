/**
 * Client-side upload validation tests (Node's built-in runner, no packages).
 * These cover the hint layer only; the backend remains authoritative.
 */

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  MAX_UPLOAD_BYTES,
  validatePdfFile,
} from '../src/lib/uploadValidation.js'

const encoder = new TextEncoder()

function pdfFile(name = 'lease.pdf', padding = 64) {
  return new File(
    [encoder.encode('%PDF-1.7\n'), new Uint8Array(padding)],
    name,
    { type: 'application/pdf' },
  )
}

test('accepts a PDF with a valid signature', async () => {
  assert.deepEqual(await validatePdfFile(pdfFile()), { ok: true })
})

test('rejects a non-PDF extension even when the MIME type claims PDF', async () => {
  const result = await validatePdfFile(pdfFile('notes.txt'))
  assert.equal(result.ok, false)
  assert.match(result.message, /Only PDF files are accepted/)
})

test('rejects a .pdf file without a PDF signature', async () => {
  const file = new File([encoder.encode('just some text')], 'fake.pdf', {
    type: 'application/pdf',
  })
  const result = await validatePdfFile(file)
  assert.equal(result.ok, false)
  assert.match(result.message, /not a valid PDF/)
})

test('rejects an empty file', async () => {
  const file = new File([], 'empty.pdf', { type: 'application/pdf' })
  const result = await validatePdfFile(file)
  assert.equal(result.ok, false)
  assert.match(result.message, /empty/)
})

test('rejects a file over the size limit and names the limit', async () => {
  const result = await validatePdfFile(pdfFile('big.pdf'), { maxBytes: 10 })
  assert.equal(result.ok, false)
  assert.match(result.message, /accepts up to 10 B/)
})

test('accepts a file exactly at the size limit', async () => {
  const file = pdfFile('exact.pdf', 0)
  assert.equal(file.size, 9)
  assert.deepEqual(await validatePdfFile(file, { maxBytes: 9 }), { ok: true })
})

test('the default limit mirrors the backend default of 25 MB', () => {
  assert.equal(MAX_UPLOAD_BYTES, 25 * 1024 * 1024)
})
