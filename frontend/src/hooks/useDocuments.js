import { useCallback, useEffect, useState } from 'react'
import { listDocuments } from '@/api/documents'
import { isAbortError } from '@/api/errors'

/**
 * Document catalogue from GET /api/documents.
 *
 * Keeps the last successful list visible while a refresh is in flight, so an
 * upload can refresh the library without blanking it. Cancels on unmount.
 */
export function useDocuments({ auto = true } = {}) {
  const [state, setState] = useState({
    documents: [],
    count: 0,
    phase: 'loading',
    isRefreshing: false,
    error: null,
  })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!auto) return undefined

    const controller = new AbortController()
    let active = true
    setState((previous) => ({
      ...previous,
      phase: previous.documents.length ? previous.phase : 'loading',
      isRefreshing: true,
      error: null,
    }))

    listDocuments({ signal: controller.signal })
      .then((payload) => {
        if (!active) return
        setState({
          documents: payload.documents,
          count: payload.count,
          phase: 'ready',
          isRefreshing: false,
          error: null,
        })
      })
      .catch((error) => {
        if (!active || isAbortError(error)) return
        setState((previous) => ({
          ...previous,
          phase: 'error',
          isRefreshing: false,
          error,
        }))
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [auto, attempt])

  const refresh = useCallback(() => setAttempt((value) => value + 1), [])

  return { ...state, refresh }
}
