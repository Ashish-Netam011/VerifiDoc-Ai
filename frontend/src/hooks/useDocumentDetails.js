import { useCallback, useEffect, useState } from 'react'
import {
  getDocument,
  getDocumentChunks,
  getDocumentTables,
} from '@/api/documents'
import { isAbortError } from '@/api/errors'

/**
 * Metadata and extracted chunks for one document. Both endpoints are required
 * by Phase 4.2, so they are requested together and the panel only becomes
 * ready when both succeed.
 */
export function useDocumentDetails(documentId) {
  const [state, setState] = useState({
    phase: 'idle',
    document: null,
    chunkResponse: null,
    tableResponse: null,
    error: null,
  })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!documentId) {
      setState({
        phase: 'idle',
        document: null,
        chunkResponse: null,
        tableResponse: null,
        error: null,
      })
      return undefined
    }

    const controller = new AbortController()
    let active = true
    setState({
      phase: 'loading',
      document: null,
      chunkResponse: null,
      tableResponse: null,
      error: null,
    })

    Promise.all([
      getDocument(documentId, { signal: controller.signal }),
      getDocumentChunks(documentId, { signal: controller.signal }),
      getDocumentTables(documentId, { signal: controller.signal }),
    ])
      .then(([document, chunkResponse, tableResponse]) => {
        if (!active) return
        setState({
          phase: 'ready',
          document,
          chunkResponse,
          tableResponse,
          error: null,
        })
      })
      .catch((error) => {
        if (!active || isAbortError(error)) return
        setState({
          phase: 'error',
          document: null,
          chunkResponse: null,
          tableResponse: null,
          error,
        })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [documentId, attempt])

  const refresh = useCallback(() => setAttempt((value) => value + 1), [])

  return { ...state, refresh }
}
