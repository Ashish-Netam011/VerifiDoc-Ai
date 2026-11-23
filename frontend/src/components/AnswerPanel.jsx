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
    faithfulness,
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

        {faithfulness && (
          <section className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-900">
                Sentence-level faithfulness
              </h3>
              <p className="text-lg font-semibold text-slate-900">
                {faithfulness.percentage == null
                  ? 'Not scored'
                  : `${faithfulness.percentage}%`}
              </p>
            </div>
            <p className="mt-1 text-xs text-slate-600">
              {faithfulness.supported_sentence_count ?? 0} supported ·{' '}
              {faithfulness.unsupported_sentence_count ?? 0} unsupported ·{' '}
              {faithfulness.total_sentence_count ?? 0} total sentences
              {decision === 'abstain' ? ' · abstention is not scored as 100%' : ''}
            </p>
            {faithfulness.metric_note ? (
              <p className="mt-2 text-xs text-slate-500">{faithfulness.metric_note}</p>
            ) : null}
            {faithfulness.sentences?.length ? (
              <ol className="mt-3 space-y-3">
                {faithfulness.sentences.map((item) => (
                  <li
                    key={item.sentence_index}
                    className="rounded-md border border-slate-200 bg-white p-3"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`mt-0.5 rounded px-2 py-0.5 text-[10px] font-semibold ${
                        item.supported
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-amber-100 text-amber-900'
                      }`}>
                        {item.supported ? 'Supported' : 'Unsupported'}
                      </span>
                      <p className="whitespace-pre-wrap text-sm text-slate-800">
                        {item.sentence}
                      </p>
                    </div>
                    {item.evidence?.length ? (
                      <ul className="mt-2 space-y-2 pl-2">
                        {item.evidence.map((source, index) => (
                          <li
                            key={`${source.chunk_id}-${index}`}
                            className="border-l-2 border-emerald-300 pl-3"
                          >
                            <blockquote className="text-xs text-slate-600">
                              “{source.quotation}”
                            </blockquote>
                            <p className="mt-1 text-[10px] text-slate-500">
                              {source.filename} · Page {source.page_number}
                            </p>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : null}
          </section>
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