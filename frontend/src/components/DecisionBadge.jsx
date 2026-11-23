const decisionConfig = {
  answer: {
    label: 'ANSWER',
    classes: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
  partial_answer: {
    label: 'PARTIAL ANSWER',
    classes: 'bg-amber-100 text-amber-800 border-amber-200',
  },
  abstain: {
    label: 'ABSTAINED',
    classes: 'bg-slate-100 text-slate-800 border-slate-200',
  },
}

export function DecisionBadge({
  decision,
  reason,
  missing_information = [],
}) {
  const config = decisionConfig[decision] || {
    label: 'UNKNOWN',
    classes: 'bg-slate-100 text-slate-700 border-slate-200',
  }

  const explanation =
    reason ||
    missing_information[0] ||
    null

  return (
    <div className="space-y-2">
      <span
        className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${config.classes}`}
        role="status"
      >
        {config.label}
      </span>

      {explanation && (
        <p className="text-sm text-slate-500">
          {explanation}
        </p>
      )}
    </div>
  )
}

export default DecisionBadge