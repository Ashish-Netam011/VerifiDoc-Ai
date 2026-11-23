
import { useEffect, useRef, useState } from 'react'
import { Search, FileText, AlertCircle, Loader2 } from 'lucide-react'
import {
  Container,
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from '@/components/ui'
import { searchDocuments } from '@/api/search'
import { isAbortError } from '@/api/errors'
import { useDocuments } from '@/hooks/useDocuments'

const formatScore = (value) =>
  typeof value === 'number' ? value.toFixed(4) : '—'

export function SearchPage() {
  const { documents, phase: documentsPhase } = useDocuments()

  const [query, setQuery] = useState('')
  const [documentId, setDocumentId] = useState('')
  const [topK, setTopK] = useState(5)
  const [results, setResults] = useState([])
  const [searchedQuery, setSearchedQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hasSearched, setHasSearched] = useState(false)

  const controllerRef = useRef(null)

  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  async function handleSearch(event) {
    event.preventDefault()

    const trimmedQuery = query.trim()

    if (!trimmedQuery || loading) return

    const controller = new AbortController()
    controllerRef.current = controller

    setLoading(true)
    setError('')
    setResults([])
    setHasSearched(true)
    setSearchedQuery(trimmedQuery)

    try {
      const response = await searchDocuments(
        {
          query: trimmedQuery,
          topK,
          documentId: documentId || null,
        },
        {
          signal: controller.signal,
        },
      )

      if (controller.signal.aborted) return

      setResults(
        Array.isArray(response?.results) ? response.results : [],
      )
    } catch (err) {
      if (!isAbortError(err)) {
        setError(err?.message || 'Search failed. Please try again.')
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
        setLoading(false)
      }
    }
  }

  return (
    <Container className="py-8">
      <div className="mb-6">
        <p className="text-sm font-medium text-blue-600">
          HYBRID RETRIEVAL
        </p>

        <h1 className="mt-1 text-2xl font-bold text-slate-900">
          Search Documents
        </h1>

        <p className="mt-2 text-sm text-slate-600">
          Find relevant passages across your uploaded PDFs using semantic
          and keyword-based retrieval.
        </p>
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Search your evidence</CardTitle>
        </CardHeader>

        <CardContent>
          <form onSubmit={handleSearch} className="space-y-4">
            <label
              htmlFor="search-query"
              className="block text-sm font-medium"
            >
              Search query
            </label>

            <div className="flex flex-col gap-3 sm:flex-row">
              <input
                id="search-query"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="e.g. What is the monthly rent and payment deadline?"
                className="min-w-0 flex-1 rounded-lg border border-slate-300 px-4 py-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                required
              />

              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-3 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}

                {loading ? 'Searching...' : 'Search'}
              </button>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label
                  htmlFor="search-document"
                  className="mb-1 block text-sm font-medium text-slate-700"
                >
                  Search scope
                </label>

                <select
                  id="search-document"
                  value={documentId}
                  onChange={(event) => setDocumentId(event.target.value)}
                  disabled={documentsPhase === 'loading'}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                >
                  <option value="">All documents</option>

                  {documents.map((document) => (
                    <option
                      key={document.document_id}
                      value={document.document_id}
                    >
                      {document.filename}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="search-top-k"
                  className="mb-1 block text-sm font-medium text-slate-700"
                >
                  Maximum results
                </label>

                <select
                  id="search-top-k"
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value))}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                >
                  {[3, 5, 10, 15, 20].map((value) => (
                    <option key={value} value={value}>
                      {value} results
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>

      {error && (
        <div
          role="alert"
          className="mb-5 flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      {loading && (
        <div
          role="status"
          className="flex items-center justify-center gap-3 py-12 text-sm text-slate-500"
        >
          <Loader2 className="h-5 w-5 animate-spin" />
          Retrieving relevant passages...
        </div>
      )}

      {!loading && hasSearched && !error && (
        <section aria-live="polite">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold text-slate-900">
              Search results
            </h2>

            <span className="text-sm text-slate-500">
              {results.length} passage
              {results.length === 1 ? '' : 's'} found
            </span>
          </div>

          {results.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center">
                <Search className="mx-auto mb-3 h-8 w-8 text-slate-400" />

                <p className="font-medium text-slate-800">
                  No matching passages found
                </p>

                <p className="mt-1 text-sm text-slate-500">
                  Try different keywords or search across all documents.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {results.map((result, index) => (
                <Card key={result.chunk_id}>
                  <CardContent className="py-5">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <FileText className="h-4 w-4 shrink-0 text-blue-600" />

                        <span className="truncate text-sm font-semibold text-slate-900">
                          {result.filename}
                        </span>
                      </div>

                      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                        Result {index + 1}
                      </span>
                    </div>

                    <p className="mb-3 text-xs text-slate-500">
                      Page {result.page_number}
                    </p>

                    <p className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">
                      {result.text}
                    </p>

                    <div className="mt-4 flex flex-wrap gap-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
                      <span>
                        Semantic: {formatScore(result.semantic_score)}
                      </span>

                      <span>
                        BM25: {formatScore(result.bm25_score)}
                      </span>

                      <span>
                        RRF: {formatScore(result.rrf_score)}
                      </span>
                    </div>

                    <p className="mt-2 break-all text-xs text-slate-400">
                      Chunk ID: {result.chunk_id}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          <p className="mt-4 text-xs text-slate-400">
            Query: "{searchedQuery}". Retrieval scores indicate ranking
            signals, not answer confidence or factual verification.
          </p>
        </section>
      )}

      {!hasSearched && (
        <div className="py-12 text-center">
          <Search className="mx-auto mb-3 h-10 w-10 text-slate-300" />

          <p className="font-medium text-slate-700">
            Search across your document collection
          </p>

          <p className="mt-1 text-sm text-slate-500">
            Enter a question or keywords to retrieve relevant passages.
          </p>
        </div>
      )}
    </Container>
  )
}
