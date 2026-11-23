import { useState, useCallback } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui'

export function QuestionInput({
  onSubmit,
  onClose,
  isAsking = false,
  disabled = false,
}) {
  const [text, setText] = useState('')

  const handleSubmit = useCallback(async (event) => {
    event?.preventDefault()

    const question = text.trim()

    if (!question || isAsking || disabled) return

    const result = await onSubmit(question)

    // Preserve the question if the request fails.
    if (result) {
      setText('')
    }
  }, [text, isAsking, disabled, onSubmit])

  const handleKeyDown = useCallback((event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSubmit(event)
    }
  }, [handleSubmit])

  return (
    <Card>
      <CardHeader className="flex flex-col gap-2">
        <CardTitle>Ask a question</CardTitle>
      </CardHeader>

      <CardContent>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isAsking || disabled}
          placeholder="Enter your question about the documents…"
          aria-disabled={isAsking || disabled}
          aria-label="Question input"
          rows={3}
          className="w-full border rounded-lg border-slate-200 px-3 py-2 resize-y text-slate-800 focus:outline-none focus:border-emerald-300 focus:shadow-sm"
        />
      </CardContent>

      <CardContent className="flex justify-end gap-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isAsking || disabled || !text.trim()}
          className="inline-flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-slate-400"
        >
          {isAsking ? 'Sending…' : 'Submit'}
        </button>

        <button
          type="button"
          onClick={() => {
            setText('')
            onClose?.()
          }}
          disabled={isAsking}
          className="rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-slate-400"
        >
          Cancel
        </button>
      </CardContent>
    </Card>
  )
}

export default QuestionInput