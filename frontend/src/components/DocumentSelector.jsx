import { useCallback, useState } from 'react'
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from '@/components/ui'
import { useDocuments } from '@/hooks/useDocuments'

export function DocumentSelector({ onSelect, placeholder = 'Search documents…' }) {
  const {
    documents,
    phase,
    isRefreshing,
    error,
    refresh,
  } = useDocuments()

  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState(null)

  const filtered = documents.filter((document) =>
    document.filename?.toLowerCase().includes(query.toLowerCase())
  )

  const handleSelect = useCallback((id) => {
    setSelectedId(id)
    onSelect?.(id)
  }, [onSelect])

  return (
    <Card>
      <CardHeader className="flex flex-col gap-2">
        <CardTitle>Document scope</CardTitle>
        <p className="text-xs text-slate-500">
          Choose a PDF or search across all uploaded documents.
        </p>
      </CardHeader>

      <CardContent>
        <input
  type="text"
  placeholder={placeholder}
  value={query}
  onChange={(event) => setQuery(event.target.value)}
  disabled={isRefreshing}
  aria-label="Search documents"
  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:border-emerald-300 focus:outline-none disabled:opacity-50"
/>

        <button
          type="button"
          onClick={() => handleSelect(null)}
          className={`mt-3 w-full rounded-md border p-2 text-left text-sm ${
            selectedId === null
              ? 'border-emerald-400 bg-emerald-50'
              : 'border-slate-200'
          }`}
        >
          All documents
        </button>

        {phase === 'loading' && (
          <p className="mt-3 text-sm text-slate-500">Loading documents…</p>
        )}

        {phase === 'error' && (
          <div className="mt-3 text-sm text-rose-600">
            <p>{error?.message || 'Could not load documents.'}</p>
            <button
              type="button"
              onClick={refresh}
              className="mt-1 underline"
            >
              Try again
            </button>
          </div>
        )}

        {phase === 'ready' && documents.length === 0 && (
          <p className="mt-3 text-sm text-slate-500">
            No documents uploaded yet.
          </p>
        )}

        {filtered.length > 0 && (
          <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">
            {filtered.map((document) => (
              <button
                key={document.document_id}
                type="button"
                onClick={() => handleSelect(document.document_id)}
                className={`flex w-full flex-col rounded-md border p-3 text-left text-sm ${
                  selectedId === document.document_id
                    ? 'border-emerald-400 bg-emerald-50'
                    : 'border-slate-200 hover:border-slate-400'
                }`}
              >
                <span className="font-medium text-slate-800">
                  {document.filename}
                </span>
                <span className="mt-1 text-xs text-slate-500">
                  {document.page_count} pages · {document.chunk_count} chunks
                </span>
              </button>
            ))}
          </div>
        )}

        {phase === 'ready' && query && filtered.length === 0 && (
          <p className="mt-3 text-sm text-slate-500">
            No matching documents found.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export default DocumentSelector