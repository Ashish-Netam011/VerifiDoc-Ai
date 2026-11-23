import { useCallback, useEffect, useRef, useState } from 'react'
import { askQuestion } from '@/api/ask'
import { isAbortError } from '@/api/errors'
import { useDocuments } from '@/hooks/useDocuments'

function mapDecision(decision) {
  switch (decision) {
    case 'answer':
      return 'answered'
    case 'partial_answer':
      return 'partial'
    case 'abstain':
      return 'abstained'
    default:
      return 'idle'
  }
}

function getErrorMessage(error) {
  if (typeof error === 'string') return error
  return error?.message || 'The request failed. Please try again.'
}

export function useAsk({ auto = true } = {}) {
  const [state, setState] = useState({
    status: 'idle',
    lastAsk: null,
    isAsking: false,
    error: null,
  })

  const controllerRef = useRef(null)

  // Load the document catalogue when the Q&A workspace mounts.
  const {
    documents,
    phase,
    isRefreshing,
    error: documentsError,
    refresh,
  } = useDocuments({ auto })

  const ask = useCallback(async ({
    question,
    topK = 5,
    documentId,
  } = {}) => {
    const normalizedQuestion =
      typeof question === 'string' ? question.trim() : ''

    if (!normalizedQuestion) {
      setState((previous) => ({
        ...previous,
        error: 'Please enter a question.',
      }))
      return null
    }

    // Cancel any previous request before starting another.
    controllerRef.current?.abort()

    const controller = new AbortController()
    controllerRef.current = controller

    setState({
      status: 'asking',
      lastAsk: null,
      isAsking: true,
      error: null,
    })

    try {
      const payload = await askQuestion(
        {
          question: normalizedQuestion,
          topK,
          documentId,
        },
        {
          signal: controller.signal,
        }
      )

      // Ignore results from requests that are no longer active.
      if (controllerRef.current !== controller) return null

      const decision = mapDecision(payload.decision)

      const response = {
        question: normalizedQuestion,
        decision: payload.decision,
        verification_status: payload.verification_status,
        answer: payload.answer,
        claims: payload.claims ?? [],
        limitations: payload.limitations ?? [],
        retrieval: payload.retrieval,
        model: payload.model,
        missing_information: payload.missing_information ?? [],
        conflicts: payload.conflicts ?? [],
        evidence_gap_report: payload.evidence_gap_report ?? null,
        faithfulness: payload.faithfulness ?? null,
        retrievedAt: Date.now(),
      }

      setState({
        status: decision,
        lastAsk: response,
        isAsking: false,
        error: null,
      })

      return response
    } catch (error) {
      if (controllerRef.current !== controller) return null

      if (isAbortError(error)) {
        setState({
          status: 'idle',
          lastAsk: null,
          isAsking: false,
          error: null,
        })
        return null
      }

      setState({
        status: 'failed',
        lastAsk: null,
        isAsking: false,
        error: getErrorMessage(error),
      })

      return null
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
    }
  }, [])

  const cancel = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null

    setState((previous) => ({
      ...previous,
      status: 'idle',
      isAsking: false,
    }))
  }, [])

  // Abort an active request when the component unmounts.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
      controllerRef.current = null
    }
  }, [])

  return {
    status: state.status,
    isAsking: state.isAsking,
    error: state.error,
    lastAsk: state.lastAsk,

    documents,
    phase,
    isRefreshing,
    documentsError,
    refresh,

    ask,
    cancel,
    mapDecision,
  }
}

export default useAsk