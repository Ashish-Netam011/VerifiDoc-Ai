import { useState } from 'react'
import { AlertCircle, Loader2, RotateCw } from 'lucide-react'
import { getAmendments } from '@/api/amendments'
import { isAbortError } from '@/api/errors'
import { Card, CardContent, CardHeader, CardTitle, Container } from '@/components/ui'

const RESOLUTION_LABELS = {
  resolved: 'Resolved for this date',
  no_amendment: 'No applicable amendment found',
  ambiguous_effective_date: 'Unresolved: effective date is missing or ambiguous',
  ambiguous_amendment: 'Unresolved: multiple amendments have the same effective date',
  circular_relationship: 'Unresolved: circular amendment relationship',
}

export function Amendments() {
  const [asOfDate, setAsOfDate] = useState('')
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function load(event) {
    event?.preventDefault()
    setLoading(true)
    setError('')
    try {
      const response = await getAmendments({ asOfDate })
      setReport(response)
    } catch (requestError) {
      if (!isAbortError(requestError)) {
        setError(requestError?.message || 'Amendment records could not be loaded.')
      }
    } finally {
      setLoading(false)
    }
  }

  const filenames = new Map()
  for (const amendment of report?.amendments ?? []) {
    filenames.set(amendment.amending_document_id, amendment.amending_filename)
    if (amendment.target_document_id) {
      filenames.set(amendment.target_document_id, amendment.target_reference)
    }
  }

  return (
    <Container className="py-8">
      <div className="mb-6">
        <p className="text-sm font-medium text-indigo-700">DOCUMENT VERSION HISTORY</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">Amendment tracking</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">
          Only explicit amendment statements are linked. The newest upload is
          never assumed to be legally applicable; unresolved links and dates are
          shown instead of selecting a version.
        </p>
      </div>

      <Card className="mb-6">
        <CardHeader><CardTitle>Resolve applicable versions</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={load} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label htmlFor="amendment-as-of" className="mb-1 block text-sm font-medium text-slate-700">
                As-of date (optional)
              </label>
              <input
                id="amendment-as-of"
                type="date"
                value={asOfDate}
                onChange={(event) => setAsOfDate(event.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm sm:max-w-xs"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}
              {loading ? 'Inspecting...' : 'Inspect amendments'}
            </button>
          </form>
        </CardContent>
      </Card>

      {error ? (
        <div role="alert" className="mb-5 flex gap-2 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      ) : null}

      {report ? (
        <div className="space-y-6" aria-live="polite">
          {report.chain_issues?.length ? (
            <section
              role="status"
              className="rounded-lg border border-amber-200 bg-amber-50 p-4"
            >
              <h2 className="text-sm font-semibold text-amber-900">
                Unresolved links and incomplete chains
              </h2>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-900">
                {report.chain_issues.map((issue, index) => (
                  <li key={`${issue.amending_document_id}-${index}`}>
                    {issue.amending_filename}: {issue.status.replaceAll('_', ' ')}
                    {issue.target_reference ? ` · target “${issue.target_reference}”` : ''}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {report.as_of_date ? (
            <section>
              <h2 className="mb-3 text-lg font-semibold text-slate-900">
                Resolution as of {report.as_of_date}
              </h2>
              {report.resolutions.length ? (
                <div className="grid gap-3 md:grid-cols-2">
                  {report.resolutions.map((resolution) => (
                    <Card key={resolution.document_id}>
                      <CardContent className="space-y-2">
                        <p className="text-sm font-semibold text-slate-900">
                          {resolution.document_filename ||
                            filenames.get(resolution.document_id) ||
                            resolution.document_id}
                        </p>
                        <p className="text-sm text-slate-700">
                          {RESOLUTION_LABELS[resolution.status] || resolution.status}
                        </p>
                        {resolution.applicable_document_id ? (
                          <p className="text-xs text-indigo-800">
                            Applicable version:{' '}
                            {resolution.applicable_filename ||
                              filenames.get(resolution.applicable_document_id) ||
                              resolution.applicable_document_id}
                          </p>
                        ) : null}
                        <p className="break-all text-xs text-slate-500">
                          Chain: {(resolution.chain_filenames ?? resolution.chain)
                            .map(
                              (name, index) =>
                                name ||
                                filenames.get(resolution.chain[index]) ||
                                resolution.chain[index],
                            )
                            .join(' → ')}
                        </p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-600">No amendment chain could be resolved for this date.</p>
              )}
            </section>
          ) : null}

          <section>
            <h2 className="mb-3 text-lg font-semibold text-slate-900">Explicit amendment records</h2>
            {report.amendments.length ? (
              <div className="space-y-3">
                {report.amendments.map((amendment, index) => (
                  <Card key={`${amendment.amending_document_id}-${amendment.source.chunk_id}-${index}`}>
                    <CardHeader className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <CardTitle>{amendment.amending_filename}</CardTitle>
                        <p className="mt-1 text-xs text-slate-600">
                          Amends: {amendment.target_reference || 'Target not identified'}
                          {amendment.affected_clause
                            ? ` · Clause ${amendment.affected_clause}`
                            : amendment.affected_subject
                              ? ` · Subject: ${amendment.affected_subject}`
                              : ''}
                        </p>
                      </div>
                      <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900">
                        {amendment.status.replaceAll('_', ' ')}
                      </span>
                    </CardHeader>
                    <CardContent>
                      <dl className="grid gap-2 text-xs sm:grid-cols-2">
                        <div><dt className="text-slate-500">Effective date</dt><dd className="text-slate-800">{amendment.effective_date || 'Not established'}</dd></div>
                        <div><dt className="text-slate-500">Amendment date</dt><dd className="text-slate-800">{amendment.amendment_date || 'Not stated'}</dd></div>
                        <div><dt className="text-slate-500">Source page</dt><dd className="text-slate-800">{amendment.source.page_number || 'Unknown'}</dd></div>
                        <div><dt className="text-slate-500">Source chunk</dt><dd className="break-all text-slate-800">{amendment.source.chunk_id || 'Missing'}</dd></div>
                      </dl>
                      <blockquote className="mt-3 border-l-2 border-indigo-300 pl-3 text-sm leading-6 text-slate-700">
                        “{amendment.source.quotation}”
                      </blockquote>
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : (
              <Card><CardContent className="text-sm text-slate-600">
                No explicit amendment statement was detected. This does not prove that no amendment exists.
              </CardContent></Card>
            )}
          </section>
        </div>
      ) : null}
    </Container>
  )
}
