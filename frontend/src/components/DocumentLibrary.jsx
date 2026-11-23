import {
  AlertCircle,
  ChevronRight,
  FileText,
  Inbox,
  RefreshCw,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui'
import {
  formatBytes,
  formatDateTime,
  pluralize,
  shortId,
} from '@/lib/format'

const STATUS_STYLES = {
  processed: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  failed: 'border-rose-200 bg-rose-50 text-rose-700',
}

function StatusPill({ status }) {
  if (!status) return null
  const style =
    STATUS_STYLES[status] ?? 'border-slate-200 bg-slate-50 text-slate-600'
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${style}`}
    >
      {status}
    </span>
  )
}

function DocumentCard({ document, isSelected, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(document.document_id)}
      aria-pressed={isSelected}
      className={`w-full rounded-xl border p-4 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
        isSelected
          ? 'border-slate-900 bg-white shadow-sm ring-1 ring-slate-900'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm'
      }`}
    >
      <div className="flex items-start gap-3">
        <span className="rounded-lg bg-slate-100 p-2" aria-hidden="true">
          <FileText className="h-4 w-4 text-slate-600" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900" title={document.filename}>
            {document.filename}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            {formatDateTime(document.uploaded_at)}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-600">
            <span>{pluralize(document.page_count, 'page')}</span>
            <span>{pluralize(document.chunk_count, 'chunk')}</span>
            <span>{formatBytes(document.file_size_bytes)}</span>
          </div>
          <div className="mt-2 flex items-center justify-between gap-2">
            <code
              className="truncate font-mono text-[11px] text-slate-400"
              title={document.document_id}
            >
              {shortId(document.document_id)}
            </code>
            <StatusPill status={document.status} />
          </div>
        </div>
        <ChevronRight
          className="mt-1 h-4 w-4 shrink-0 text-slate-400"
          aria-hidden="true"
        />
      </div>
    </button>
  )
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start gap-3">
        <div className="h-8 w-8 rounded-lg bg-slate-100" />
        <div className="flex-1 space-y-2">
          <div className="h-3.5 w-2/3 rounded bg-slate-100" />
          <div className="h-3 w-1/3 rounded bg-slate-100" />
          <div className="h-3 w-1/2 rounded bg-slate-100" />
        </div>
      </div>
    </div>
  )
}

/**
 * Document catalogue from GET /api/documents. Only fields the backend returns
 * are displayed; there is no delete action because the backend has no delete
 * endpoint.
 */
export function DocumentLibrary({ library, selectedId, onSelect }) {
  const {
    documents,
    count,
    phase,
    isRefreshing,
    error,
    refresh,
  } = library
  const hasDocuments = documents.length > 0

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <CardTitle>Library</CardTitle>
          {phase === 'ready' ? (
            <span className="text-xs text-slate-500">
              {pluralize(count, 'document')}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={isRefreshing}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${isRefreshing ? 'animate-spin' : ''}`}
            aria-hidden="true"
          />
          {isRefreshing ? 'Refreshing' : 'Refresh'}
        </button>
      </CardHeader>
      <CardContent>
        {phase === 'loading' && !hasDocuments ? (
          <div className="grid gap-3" aria-busy="true" aria-label="Loading documents">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : phase === 'error' && !hasDocuments ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-5">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" aria-hidden="true" />
              <div>
                <p className="text-sm font-medium text-rose-900">
                  The document list could not be loaded.
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
        ) : !hasDocuments ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 px-6 py-10 text-center">
            <Inbox className="h-6 w-6 text-slate-400" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium text-slate-800">No documents yet</p>
            <p className="mt-1 max-w-sm text-xs text-slate-500">
              Upload a PDF above. It will appear here once the backend has
              extracted, chunked and indexed it.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {phase === 'error' ? (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                <span>
                  Refresh failed: {error?.message ?? 'unknown error.'} Showing the
                  last loaded list.
                </span>
                <button
                  type="button"
                  onClick={refresh}
                  className="shrink-0 rounded-md border border-amber-300 bg-white px-2 py-1 font-medium text-amber-800 hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                >
                  Retry
                </button>
              </div>
            ) : null}
            <div className="grid gap-3">
              {documents.map((document) => (
                <DocumentCard
                  key={document.document_id}
                  document={document}
                  isSelected={document.document_id === selectedId}
                  onSelect={onSelect}
                />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
