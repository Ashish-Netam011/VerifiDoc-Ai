import { useCallback, useEffect, useState } from 'react'
import { getHealth } from '@/api/health'
import { isAbortError } from '@/api/errors'

/**
 * Backend + LLM availability from GET /api/health.
 *
 * `status` is derived from the payload, not the HTTP status:
 *   loading  - first probe in flight
 *   healthy  - backend ok AND llm usable (available && model_present)
 *   degraded - backend answered but the LLM is not usable, or health failed
 *   offline  - the backend could not be reached (network/timeout)
 *
 * The hook aborts its request on unmount and exposes `refresh()` for a manual
 * retry.
 */
export function useHealth({ auto = true } = {}) {
  const [state, setState] = useState({
    phase: 'loading',
    health: null,
    error: null,
    checkedAt: null,
  })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!auto) return undefined

    const controller = new AbortController()
    let active = true
    setState((previous) => ({ ...previous, phase: 'loading', error: null }))

    getHealth({ signal: controller.signal })
      .then((health) => {
        if (!active) return
        setState({ phase: 'ready', health, error: null, checkedAt: Date.now() })
      })
      .catch((error) => {
        if (!active || isAbortError(error)) return
        setState({ phase: 'error', health: null, error, checkedAt: Date.now() })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [auto, attempt])

  const refresh = useCallback(() => setAttempt((value) => value + 1), [])

  const { phase, health, error, checkedAt } = state
  let status = 'loading'
  if (phase === 'error') {
    status = error?.isNetwork || error?.isTimeout ? 'offline' : 'degraded'
  } else if (phase === 'ready' && health) {
    status = health.serviceStatus === 'ok' && health.llmUsable ? 'healthy' : 'degraded'
  }

  return {
    status,
    phase,
    health,
    error,
    checkedAt,
    backendAvailable: health?.backendAvailable ?? false,
    providerAvailable: health?.providerAvailable ?? false,
    modelPresent: health?.modelPresent ?? false,
    serviceStatus: health?.serviceStatus ?? null,
    llmUsable: health?.llmUsable ?? false,
    refresh,
  }
}
