import { Card, CardHeader, CardContent } from '@/components/ui'

const VERDICT_STYLES = {
  supported: 'bg-emerald-100 text-emerald-800',
  contradicted: 'bg-rose-100 text-rose-800',
  insufficient: 'bg-amber-100 text-amber-800',
  invalid_citation: 'bg-slate-100 text-slate-800',
}

const VERDICT_LABELS = {
  supported: 'Supported',
  contradicted: 'Contradicted',
  insufficient: 'Insufficient',
  invalid_citation: 'Invalid citation',
}

export function ClaimList({ claims, onDetails }) {
  if (!claims || claims.length === 0) {
    return (
      <CardContent>
        <p className="text-slate-500">No claims available.</p>
      </CardContent>
    )
  }

  return (
    <CardContent className="space-y-3">
      {claims.map((claim, index) => (
        <ClaimCard
          key={claim.sources?.[0]?.chunk_id || index}
          claim={claim}
          onDetails={onDetails}
        />
      ))}
    </CardContent>
  )
}

function ClaimCard({ claim, onDetails }) {
  const { text, sources = [], verification } = claim

  const verdict = verification?.status
  const verdictLabel = VERDICT_LABELS[verdict] || 'Unverified'

  return (
    <Card className="border border-slate-200 transition-colors hover:border-emerald-300">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-900 whitespace-pre-wrap">
            {text}
          </p>

          {sources.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              {sources.map((source) => source.filename).filter(Boolean).join(', ')}
              {' · '}
              Page {sources.map((source) => source.page_number).filter(Boolean).join(', ')}
            </p>
          )}
        </div>

        <VerificationChip
          status={verdict}
          label={verdictLabel}
        />
      </CardHeader>

      <CardContent className="space-y-3 p-3 pt-0">
        {sources.map((source, index) => (
          <div
            key={source.chunk_id || index}
            className="rounded-md bg-slate-50 p-3"
          >
            {source.quotation && (
              <blockquote className="whitespace-pre-wrap text-xs text-slate-600">
                "{source.quotation}"
              </blockquote>
            )}

            <p className="mt-2 text-xs text-slate-500">
              {source.filename || 'Unknown document'}
              {source.page_number
                ? ` · Page ${source.page_number}`
                : ''}
            </p>
          </div>
        ))}

        {sources.length > 0 && onDetails && (
          <button
            type="button"
            onClick={() => onDetails(claim)}
            className="rounded-md px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
            aria-label={`View evidence for claim: ${text}`}
          >
            View evidence ({sources.length})
          </button>
        )}

        {sources.length === 0 && (
          <p className="text-xs text-slate-500">
            No source evidence attached to this claim.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function VerificationChip({ status, label }) {
  const classes =
    VERDICT_STYLES[status] || 'bg-slate-200 text-slate-600'

  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-1 text-xs font-medium ${classes}`}
      aria-label={`Verification status: ${label}`}
    >
      {label}
    </span>
  )
}

export default ClaimList