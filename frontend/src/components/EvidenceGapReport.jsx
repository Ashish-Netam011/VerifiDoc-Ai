import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui'

const statusClasses = {
  supported: 'bg-emerald-100 text-emerald-800',
  contradicted: 'bg-rose-100 text-rose-800',
  unverified: 'bg-amber-100 text-amber-800',
  missing: 'bg-slate-100 text-slate-600',
  invalid_citation: 'bg-slate-100 text-slate-600',
  condition_not_preserved: 'bg-slate-100 text-slate-600',
}

export function EvidenceGapReport({ evidence_gap_report }) {
  if (!evidence_gap_report) return null

  const {
    status,
    reason,
    missing_information = [],
    conflicts = [],
    supporting_evidence = [],
    coverage,
    signals,
  } = evidence_gap_report

  const title = {
    answer: 'Evidence report',
    partial_answer: 'Evidence gaps',
    abstain: 'Why VerifiDoc abstained',
  }[status] || 'Evidence report'

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {reason && (
          <p className="text-sm text-slate-500">{reason}</p>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {missing_information.length > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              Missing information
            </h3>

            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
              {missing_information.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </section>
        )}

        {conflicts.length > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-rose-700">
              Conflicting evidence
            </h3>

            <div className="space-y-2">
              {conflicts.map((conflict, index) => (
                <div
                  key={`${conflict.chunk_id || 'conflict'}-${index}`}
                  className="rounded-lg border border-rose-200 bg-rose-50 p-3"
                >
                  <p className="text-sm font-medium text-rose-800">
                    {conflict.kind === 'claim_contradiction'
                      ? 'Contradiction'
                      : 'Conflicting amounts'}
                  </p>

                  <p className="mt-1 text-sm text-rose-700">
                    {conflict.claim_text}
                  </p>

                  <p className="mt-2 text-xs text-rose-600">
                    {conflict.filename} · Page {conflict.page_number}
                  </p>

                  {conflict.detail && (
                    <p className="mt-1 text-xs text-rose-600">
                      {conflict.detail}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {supporting_evidence.length > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              Supporting evidence
            </h3>

            <div className="space-y-2">
              {supporting_evidence.map((evidence, index) => (
                <div
                  key={`${evidence.chunk_id}-${index}`}
                  className="rounded-lg border border-slate-200 p-3"
                >
                  <p className="text-sm text-slate-700">
                    {evidence.description}
                  </p>

                  <p className="mt-1 text-xs text-slate-500">
                    {evidence.filename} · Page {evidence.page_number}
                  </p>

                  {evidence.claim_text && (
                    <p className="mt-2 text-xs text-slate-600">
                      Claim: {evidence.claim_text}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {coverage?.components?.length > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              Evidence coverage
            </h3>

            <div className="space-y-3">
              {coverage.components.map((component, index) => (
                <div key={index}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-slate-700">
                      {component.label}
                    </span>

                    <span
                      className={`rounded-full px-2 py-1 text-xs font-medium ${
                        statusClasses[component.status] ||
                        'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {component.status}
                    </span>
                  </div>

                  {component.matched_phrase && (
                    <p className="mt-1 text-xs text-slate-500">
                      Matched: {component.matched_phrase}
                    </p>
                  )}

                  {component.evidence_chunk_ids?.length > 0 && (
                    <p className="mt-1 break-all text-xs text-slate-400">
                      Evidence IDs: {component.evidence_chunk_ids.join(', ')}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {coverage?.status === 'uncertain' && (
          <p className="text-sm text-slate-500">
            VerifiDoc could not reliably identify all requested facts.
          </p>
        )}

        {signals && (
          <details className="rounded-lg border border-slate-200 p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-600">
              Technical diagnostics
            </summary>

            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs text-slate-500">
              {JSON.stringify(signals, null, 2)}
            </pre>
          </details>
        )}
      </CardContent>
    </Card>
  )
}

export default EvidenceGapReport