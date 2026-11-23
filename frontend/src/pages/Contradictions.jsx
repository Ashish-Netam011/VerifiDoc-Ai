import { useRef, useState } from 'react'
import { AlertCircle, Loader2, Search } from 'lucide-react'
import { analyzeConflicts } from '@/api/conflicts'
import { isAbortError } from '@/api/errors'
import { Card, CardContent, CardHeader, CardTitle, Container } from '@/components/ui'

const STATUS_STYLE = {
  confirmed_conflict: 'bg-rose-100 text-rose-800',
  consistent: 'bg-emerald-100 text-emerald-800',
  unresolved: 'bg-amber-100 text-amber-800',
}

function FactSource({ fact, side }) {
  return (
    <article className="min-w-0 rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {side}
      </p>
      <h3 className="mt-1 break-words text-sm font-semibold text-slate-900">
        {fact.filename || 'Unknown document'}
      </h3>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-slate-500">Value</dt>
        <dd className="font-medium text-slate-800">
          {fact.value} {fact.unit || ''}
        </dd>
        <dt className="text-slate-500">Page</dt>
        <dd className="text-slate-800">{fact.page_number || 'Unknown'}</dd>
        <dt className="text-slate-500">Conditions</dt>
        <dd className="text-slate-800">{fact.conditions || 'Not stated'}</dd>
        <dt className="text-slate-500">Relevant date</dt>
        <dd className="text-slate-800">{fact.relevant_date || 'Not stated'}</dd>
      </dl>
      <blockquote className="mt-3 border-l-2 border-slate-300 pl-3 text-sm leading-6 text-slate-700">
        “{fact.quotation}”
      </blockquote>
      <p className="mt-2 break-all text-[10px] text-slate-400">
        {fact.document_id} · {fact.chunk_id}
      </p>
    </article>
  )
}

export function Contradictions() {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const controller = useRef(null)

  async function submit(event) {
    event.preventDefault()
    if (!query.trim() || loading) return
    controller.current?.abort()
    const active = new AbortController()
    controller.current = active
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const response = await analyzeConflicts(
        { query: query.trim(), topK: 20 },
        { signal: active.signal },
      )
      if (!active.signal.aborted) setResult(response)
    } catch (requestError) {
      if (!isAbortError(requestError)) {
        setError(requestError?.message || 'Fact comparison failed.')
      }
    } finally {
      if (controller.current === active) {
        controller.current = null
        setLoading(false)
      }
    }
  }

  return (
    <Container className="py-8">
      <div className="mb-6">
        <p className="text-sm font-medium text-rose-700">CROSS-DOCUMENT REVIEW</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">
          Contradiction analysis
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">
          Compare explicit numeric and date facts in retrieved passages. Different
          conditions or relevant periods remain unresolved rather than being
          presented as a confirmed conflict.
        </p>
      </div>

      <Card className="mb-6">
        <CardHeader><CardTitle>Find facts to compare</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row">
            <label className="sr-only" htmlFor="conflict-query">Comparison topic</label>
            <input
              id="conflict-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-slate-300 px-4 py-3 text-sm"
              placeholder="e.g. rent amount and payment conditions"
              required
            />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-3 text-sm font-medium text-white disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {loading ? 'Comparing...' : 'Compare facts'}
            </button>
          </form>
        </CardContent>
      </Card>

      {error ? (
        <div role="alert" className="mb-5 flex gap-2 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      ) : null}

      {result ? (
        <section aria-live="polite" className="space-y-4">
          <p className="text-sm text-slate-600">
            {result.comparisons.length} comparison(s) · {result.facts.length} extracted candidate fact(s).
            Candidate extraction is heuristic; verify quotations in the source documents.
          </p>
          {result.comparisons.length ? result.comparisons.map((comparison, index) => (
            <Card key={`${comparison.left.chunk_id}-${comparison.right.chunk_id}-${index}`}>
              <CardHeader className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>{comparison.subject} · {comparison.attribute}</CardTitle>
                  <p className="mt-1 text-xs text-slate-600">{comparison.reason}</p>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  STATUS_STYLE[comparison.status] || STATUS_STYLE.unresolved
                }`}>
                  {comparison.status.replaceAll('_', ' ')}
                </span>
              </CardHeader>
              <CardContent className="grid gap-3 md:grid-cols-2">
                <FactSource fact={comparison.left} side="Source A" />
                <FactSource fact={comparison.right} side="Source B" />
              </CardContent>
            </Card>
          )) : (
            <Card><CardContent className="py-8 text-sm text-slate-600">
              No comparable fact pairs were identified for this retrieval. This does not establish that the documents contain no contradictions.
            </CardContent></Card>
          )}
        </section>
      ) : null}
    </Container>
  )
}
