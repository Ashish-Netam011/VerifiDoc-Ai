import { useRef, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  RefreshCw,
  UploadCloud,
  X,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui'
import { formatBytes, pluralize } from '@/lib/format'
import { MAX_UPLOAD_LABEL } from '@/lib/uploadValidation'

const STATUS_LABEL = {
  queued: 'Queued',
  uploading: 'Uploading',
  success: 'Uploaded',
  error: 'Failed',
  rejected: 'Not uploaded',
}

function StatusIcon({ status }) {
  if (status === 'uploading' || status === 'queued') {
    return <Loader2 className="h-4 w-4 animate-spin text-slate-500" aria-hidden="true" />
  }
  if (status === 'success') {
    return <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" />
  }
  return <AlertCircle className="h-4 w-4 text-rose-600" aria-hidden="true" />
}

function UploadRow({ item, onRetry, onDismiss }) {
  const percent = item.progress == null ? 0 : Math.round(item.progress * 100)
  const canDismiss = item.status !== 'uploading' && item.status !== 'queued'
  // Only retry failures that could succeed on a second attempt. A file the
  // client rejected (wrong type, empty, duplicate) would be rejected again, so
  // retrying it would only waste a backend request.
  const canRetry = item.status === 'error'
  const document = item.document

  return (
    <li className="rounded-lg border border-slate-200 px-3 py-3">
      <div className="flex items-start gap-3">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <p className="truncate text-sm font-medium text-slate-900" title={item.name}>
              {item.name}
            </p>
            <span className="shrink-0 text-xs text-slate-500">
              {formatBytes(item.size)}
            </span>
          </div>

          {item.status === 'uploading' ? (
            <div className="mt-2">
              <div
                className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100"
                role="progressbar"
                aria-label={`Upload progress for ${item.name}`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
              >
                <div
                  className="h-full rounded-full bg-slate-900 transition-[width] duration-200"
                  style={{ width: `${percent}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {item.progress == null
                  ? 'Sending to the backend…'
                  : `${percent}% uploaded · the server is indexing the PDF`}
              </p>
            </div>
          ) : (
            <div className="mt-1.5 flex items-center gap-2 text-xs">
              <StatusIcon status={item.status} />
              <span
                className={
                  item.status === 'success'
                    ? 'text-emerald-700'
                    : item.status === 'error' || item.status === 'rejected'
                      ? 'text-rose-700'
                      : 'text-slate-600'
                }
              >
                {STATUS_LABEL[item.status] ?? item.status}
              </span>
              {item.status === 'success' && document ? (
                <span className="text-slate-500">
                  · {pluralize(document.page_count, 'page')} ·{' '}
                  {pluralize(document.chunk_count, 'chunk')}
                </span>
              ) : null}
            </div>
          )}

          {item.message ? (
            <p className="mt-2 text-xs text-rose-700">{item.message}</p>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {canRetry ? (
            <button
              type="button"
              onClick={() => onRetry(item.id)}
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
            >
              <RefreshCw className="h-3 w-3" aria-hidden="true" />
              Retry
            </button>
          ) : null}
          {canDismiss ? (
            <button
              type="button"
              onClick={() => onDismiss(item.id)}
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
              aria-label={`Dismiss ${item.name}`}
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </div>
    </li>
  )
}

/**
 * Drag-and-drop + file picker. Client checks are hints; the backend decides
 * whether an upload is valid, and an item only shows "Uploaded" after it
 * returns document metadata.
 */
export function UploadPanel({ uploads }) {
  const inputRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)
  const { items, addFiles, retry, dismiss, clearFinished, isUploading } = uploads

  const openPicker = () => inputRef.current?.click()

  const handleInput = (event) => {
    // Copy first: resetting value clears the live FileList, and the same file
    // must stay selectable again afterwards.
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (files.length) addFiles(files)
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setIsDragging(false)
    if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files)
  }

  const finishedCount = items.filter(
    (item) => item.status !== 'uploading' && item.status !== 'queued',
  ).length

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>Upload documents</CardTitle>
        <span className="text-xs text-slate-500">
          PDF only · up to {MAX_UPLOAD_LABEL} each
        </span>
      </CardHeader>
      <CardContent className="space-y-4">
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          className="sr-only"
          onChange={handleInput}
          tabIndex={-1}
          aria-hidden="true"
        />

        <button
          type="button"
          onClick={openPicker}
          onDragEnter={(event) => {
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragOver={(event) => {
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={`flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
            isDragging
              ? 'border-slate-900 bg-slate-50'
              : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
          } focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400`}
        >
          <UploadCloud className="h-6 w-6 text-slate-400" aria-hidden="true" />
          <span className="text-sm font-medium text-slate-900">
            Drop PDFs here, or browse
          </span>
          <span className="text-xs text-slate-500">
            You can select several files at once. Each file uploads independently.
          </span>
        </button>

        {items.length > 0 ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                This session
              </p>
              {finishedCount > 0 ? (
                <button
                  type="button"
                  onClick={clearFinished}
                  className="text-xs font-medium text-slate-500 hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
                >
                  Clear finished
                </button>
              ) : null}
            </div>
            <ul className="space-y-2">
              {items.map((item) => (
                <UploadRow
                  key={item.id}
                  item={item}
                  onRetry={retry}
                  onDismiss={dismiss}
                />
              ))}
            </ul>
            <p className="text-xs text-slate-500" aria-live="polite">
              {isUploading
                ? 'An upload is in progress. Files are sent one at a time.'
                : 'No upload in progress.'}
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
