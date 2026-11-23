import { useMemo } from 'react'
import { AlertCircle, FileText, RefreshCw, X } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui'
import { useDocumentDetails } from '@/hooks/useDocumentDetails'
import { formatBytes, formatDateTime, pluralize } from '@/lib/format'

function MetaItem({ label, value, mono = false }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd
        className={`mt-0.5 text-sm text-slate-800 ${mono ? 'break-all font-mono text-xs' : ''}`}
      >
        {value}
      </dd>
    </div>
  )
}

function groupChunksByPage(chunkResponse) {
  const pages = new Map()
  for (const chunk of chunkResponse?.chunks ?? []) {
    const list = pages.get(chunk.page_number) ?? []
    list.push(chunk)
    pages.set(chunk.page_number, list)
  }
  return [...pages.entries()].sort((a, b) => a[0] - b[0])
}

function tableBodyRows(table) {
  const rows = table.rows ?? []
  const firstRow = rows[0]
  const includesHeader =
    table.headers?.length > 0 &&
    firstRow?.length === table.headers.length &&
    table.headers.every(
      (header, index) => (firstRow[index] ?? '').trim() === header.trim(),
    )
  return includesHeader ? rows.slice(1) : rows
}

/**
 * Metadata plus the extracted text the backend actually stores, grouped by
 * page. There is no page image or page-text endpoint, so chunks are the only
 * document view rendered here.
 */
export function DocumentDetails({ documentId, onClose }) {
  const { phase, document, chunkResponse, tableResponse, error, refresh } =
    useDocumentDetails(documentId)
  const pages = useMemo(() => groupChunksByPage(chunkResponse), [chunkResponse])

  return (
    <Card className="xl:sticky xl:top-20">
      <CardHeader className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle className="truncate">
            {document?.filename ?? 'Document details'}
          </CardTitle>
          <p className="mt-0.5 text-xs text-slate-500">
            Metadata and extracted text
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {documentId ? (
            <button
              type="button"
              onClick={refresh}
              disabled={phase === 'loading'}
              className="rounded-md border border-slate-200 p-1.5 text-slate-500 hover:bg-slate-50 disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
              aria-label="Reload document details"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${phase === 'loading' ? 'animate-spin' : ''}`}
                aria-hidden="true"
              />
            </button>
          ) : null}
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
              aria-label="Close document details"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </CardHeader>

      <CardContent>
        {!documentId ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 px-6 py-10 text-center">
            <FileText className="h-6 w-6 text-slate-400" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium text-slate-800">
              No document selected
            </p>
            <p className="mt-1 max-w-xs text-xs text-slate-500">
              Select a document in the library to inspect its metadata and the
              text the backend extracted from it.
            </p>
          </div>
        ) : phase === 'loading' ? (
          <div className="animate-pulse space-y-3" aria-busy="true" aria-label="Loading document details">
            <div className="grid grid-cols-2 gap-3">
              <div className="h-10 rounded bg-slate-100" />
              <div className="h-10 rounded bg-slate-100" />
              <div className="h-10 rounded bg-slate-100" />
              <div className="h-10 rounded bg-slate-100" />
            </div>
            <div className="h-24 rounded bg-slate-100" />
            <div className="h-24 rounded bg-slate-100" />
          </div>
        ) : phase === 'error' ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-5">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" aria-hidden="true" />
              <div>
                <p className="text-sm font-medium text-rose-900">
                  This document could not be loaded.
                </p>
                <p className="mt-1 text-sm text-rose-800">
                  {error?.message ?? 'The backend did not respond.'}
                </p>
                <button
                  type="button"
                  onClick={refresh}
                  className="mt-3 rounded-md border border-rose-300 bg-white px-2.5 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
                >
                  Retry
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-3">
              <MetaItem label="Pages" value={document?.page_count ?? '—'} />
              <MetaItem label="Chunks" value={document?.chunk_count ?? '—'} />
              <MetaItem label="Size" value={formatBytes(document?.file_size_bytes)} />
              <MetaItem
                label="Uploaded"
                value={formatDateTime(document?.uploaded_at)}
              />
              <MetaItem label="Status" value={document?.status ?? '—'} />
              <MetaItem label="Pages extracted" value={chunkResponse?.page_count ?? '—'} />
              <div className="col-span-2">
                <MetaItem
                  label="Document ID"
                  value={document?.document_id ?? '—'}
                  mono
                />
              </div>
              <div className="col-span-2">
                <MetaItem label="Stored file" value={document?.file_path ?? '—'} mono />
              </div>
            </dl>

            <div className="border-t border-slate-100 pt-4">
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-slate-900">
                  Detected tables
                </h3>
                {(tableResponse?.tables ?? []).length === 0 ? (
                  <p className="mt-2 text-xs text-slate-500">
                    No tables were detected in this document.
                  </p>
                ) : (
                  <div className="mt-3 space-y-3">
                    {tableResponse.tables.map((table) => (
                      <section
                        key={table.table_id}
                        className="overflow-hidden rounded-lg border border-slate-200"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-50 px-3 py-2">
                          <p className="text-xs font-semibold text-slate-800">
                            {table.table_id} · Page {table.page_number}
                          </p>
                          <span className={`text-xs font-medium ${
                            table.status === 'extracted'
                              ? 'text-emerald-700'
                              : 'text-amber-700'
                          }`}>
                            {table.status === 'extracted'
                              ? 'Extracted'
                              : 'Review required'}
                          </span>
                        </div>
                        {table.review_reason ? (
                          <p className="px-3 pt-2 text-xs text-amber-800">
                            {table.review_reason}
                          </p>
                        ) : null}
                        <div className="overflow-x-auto p-3">
                          <table className="min-w-full border-collapse text-left text-xs">
                            {table.headers?.length ? (
                              <thead>
                                <tr>
                                  {table.headers.map((header, index) => (
                                    <th
                                      key={`${table.table_id}-h${index}`}
                                      className="border border-slate-200 bg-slate-50 px-2 py-1.5 font-semibold text-slate-700"
                                    >
                                      {header || '—'}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                            ) : null}
                            <tbody>
                              {tableBodyRows(table).map((row, rowIndex) => (
                                <tr key={`${table.table_id}-r${rowIndex}`}>
                                  {row.map((cell, cellIndex) => (
                                    <td
                                      key={`${table.table_id}-${rowIndex}-${cellIndex}`}
                                      className="border border-slate-200 px-2 py-1.5 text-slate-700"
                                    >
                                      {cell ?? '—'}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </section>
                    ))}
                  </div>
                )}
              </div>

              <div className="border-t border-slate-100 pt-4">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-slate-900">
                  Extracted text
                </h3>
                <span className="text-xs text-slate-500">
                  {pluralize(pages.length, 'page')} ·{' '}
                  {pluralize(chunkResponse?.chunks?.length ?? 0, 'chunk')}
                </span>
              </div>

              {pages.length === 0 ? (
                <p className="mt-3 text-xs text-slate-500">
                  The backend returned no chunks for this document.
                </p>
              ) : (
                <div className="mt-3 space-y-4">
                  {pages.map(([pageNumber, chunks]) => (
                    <section key={pageNumber}>
                      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Page {pageNumber} · {pluralize(chunks.length, 'chunk')}
                      </h4>
                      <ol className="mt-2 space-y-2">
                        {chunks.map((chunk) => (
                          <li
                            key={chunk.chunk_id}
                            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
                          >
                            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-800">
                              {chunk.text}
                            </p>
                            <code
                              className="mt-2 block truncate font-mono text-[10px] text-slate-400"
                              title={chunk.chunk_id}
                            >
                              {chunk.chunk_id} · offsets {chunk.start_offset}–
                              {chunk.end_offset}
                            </code>
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                </div>
              )}
            </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
