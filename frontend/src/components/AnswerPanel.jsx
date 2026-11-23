import { Card, CardHeader, CardContent } from '@/components/ui'
import { DecisionBadge } from './DecisionBadge'
import { ClaimList } from './ClaimList'
import { EvidenceGapReport } from './EvidenceGapReport'

export function AnswerPanel({ response }) {
  if (!response) return null

  const {
    decision,
    answer,
    claims = [],
    missing_information = [],
    conflicts = [],
    evidence_gap_report,
  } = response

  const hasConflicts = conflicts.length > 0

  return (
    <Card className="w-full">
      <CardHeader>
        <DecisionBadge
          decision={decision}
          reason={evidence_gap_report?.reason}
          missing_information={missing_information}
          conflicts={conflicts}
        />
      </CardHeader>

      <CardContent className="space-y-4">
        {decision === 'answer' && (
          <p className="whitespace-pre-wrap text-slate-800">
            {answer}
          </p>
        )}

        {decision === 'partial_answer' && (
          <div>
            <p className="whitespace-pre-wrap text-slate-800">
              {answer}
            </p>

            <p className="mt-2 text-sm text-amber-700">
              Some requested information could not be verified.
              Review the evidence gap report below.
            </p>
          </div>
        )}

        {decision === 'abstain' && (
          <p className="text-sm text-slate-600">
            {evidence_gap_report?.reason ||
              missing_information[0] ||
              'There is insufficient evidence to answer this question.'}
          </p>
        )}

        {hasConflicts && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-3">
            <h3 className="mb-2 text-sm font-semibold text-rose-800">
              Evidence conflicts
            </h3>

            {conflicts.map((conflict, index) => (
              <div key={`${conflict.chunk_id || 'conflict'}-${index}`} className="mb-2 text-sm text-rose-700">
                <p>{conflict.claim_text}</p>
                <p className="mt-1 text-xs text-rose-600">
                  {conflict.filename} · Page {conflict.page_number}
                </p>
              </div>
            ))}
          </div>
        )}

        {claims.length > 0 && (
          <ClaimList claims={claims} />
        )}

        {evidence_gap_report && (
          <EvidenceGapReport
            evidence_gap_report={evidence_gap_report}
          />
        )}
      </CardContent>
    </Card>
  )
}

export default AnswerPanel