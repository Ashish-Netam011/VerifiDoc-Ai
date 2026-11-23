import { useCallback, useState } from 'react'

import { Container } from '@/components/ui'
import { HealthBadge } from '@/components/HealthBadge'
import { DocumentSelector } from '@/components/DocumentSelector'
import { QuestionInput } from '@/components/QuestionInput'
import { AnswerPanel } from '@/components/AnswerPanel'
import { useAsk } from '@/hooks/useAsk'

export function AskPage() {
  const {
    lastAsk,
    isAsking,
    error,
    ask,
  } = useAsk()

  const [selectedDocId, setSelectedDocId] = useState(null)

  const handleSubmit = useCallback(
    async (question) => {
      return await ask({
        question,
        documentId: selectedDocId,
      })
    },
    [ask, selectedDocId]
  )

  return (
    <Container>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            ProofLens AI
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Ask questions. Inspect evidence. Trust only what is proved.
          </p>
        </div>

        <HealthBadge />
      </div>

      <div className="mx-auto max-w-3xl space-y-5">
        <DocumentSelector
          onSelect={setSelectedDocId}
        />

        <QuestionInput
          onSubmit={handleSubmit}
          onClose={() => setSelectedDocId(null)}
          isAsking={isAsking}
        />

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"
          >
            {error}
          </div>
        )}

        {lastAsk && (
          <div className="answer-content">
            <AnswerPanel response={lastAsk} />
          </div>
        )}
      </div>
    </Container>
  )
}

export default AskPage