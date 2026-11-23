import { useEffect } from 'react'
import { AlertCircle, CheckCircle2, X } from 'lucide-react'

/**
 * Single transient notification. Kept in a persistent aria-live region so the
 * message is announced even though the content appears later.
 */
export function Toast({ toast, onDismiss, duration = 6000 }) {
  useEffect(() => {
    if (!toast) return undefined
    const timer = setTimeout(onDismiss, duration)
    return () => clearTimeout(timer)
  }, [toast, onDismiss, duration])

  const isError = toast?.kind === 'error'
  const Icon = isError ? AlertCircle : CheckCircle2

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-4 sm:justify-end sm:px-6"
      aria-live="polite"
      role="status"
    >
      {toast ? (
        <div
          className={`pointer-events-auto flex max-w-sm items-start gap-3 rounded-xl border bg-white px-4 py-3 shadow-lg ${
            isError ? 'border-rose-200' : 'border-emerald-200'
          }`}
        >
          <Icon
            className={`mt-0.5 h-4 w-4 shrink-0 ${isError ? 'text-rose-600' : 'text-emerald-600'}`}
            aria-hidden="true"
          />
          <div className="min-w-0 text-sm text-slate-800">{toast.message}</div>
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
            aria-label="Dismiss notification"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      ) : null}
    </div>
  )
}
