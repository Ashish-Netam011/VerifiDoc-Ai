import { useHealth } from '@/hooks/useHealth'

const BADGE_STYLES = {
  loading: { dot: 'bg-slate-300', text: 'text-slate-500', label: 'Checking backend…' },
  healthy: { dot: 'bg-emerald-500', text: 'text-emerald-700', label: 'Backend and model ready' },
  degraded: { dot: 'bg-amber-500', text: 'text-amber-700', label: 'Backend up, model unavailable' },
  offline: { dot: 'bg-rose-500', text: 'text-rose-700', label: 'Backend unreachable' },
}

function describe({ status, health, error, backendAvailable, ollamaAvailable, modelPresent }) {
  if (status === 'healthy') {
    return health?.model ? `Ready · ${health.model}` : 'Ready'
  }
  if (status === 'degraded') {
    if (!backendAvailable && !health) {
      return error?.message ?? 'Backend reported a problem'
    }
    if (!ollamaAvailable) return 'Ollama is not reachable'
    if (!modelPresent) return health?.model ? `Model missing · ${health.model}` : 'Model missing'
    return health?.detail || 'Backend degraded'
  }
  if (status === 'offline') return 'Backend unreachable'
  return null
}

/** Compact live status for GET /api/health. */
export function HealthBadge({ className = '' }) {
  const health = useHealth()
  const style = BADGE_STYLES[health.status] ?? BADGE_STYLES.loading
  const detail = describe(health)

  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <span
        className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium"
        role="status"
        aria-live="polite"
        title={detail ?? undefined}
      >
        <span className={`h-2 w-2 rounded-full ${style.dot}`} aria-hidden="true" />
        <span className={style.text}>{style.label}</span>
      </span>
      {detail ? (
        <span className="hidden text-xs text-slate-500 sm:inline">{detail}</span>
      ) : null}
      <button
        type="button"
        onClick={health.refresh}
        className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
      >
        Recheck
      </button>
    </div>
  )
}
