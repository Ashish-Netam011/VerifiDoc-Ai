import { useCallback, useState } from 'react'
import { Container } from '@/components/ui'
import { UploadPanel } from '@/components/UploadPanel'
import { DocumentLibrary } from '@/components/DocumentLibrary'
import { DocumentDetails } from '@/components/DocumentDetails'
import { Toast } from '@/components/Toast'
import { useDocuments } from '@/hooks/useDocuments'
import { useUploadQueue } from '@/hooks/useUploadQueue'
import { pluralize } from '@/lib/format'

/**
 * Document workspace: upload, catalogue and details.
 *
 * A document is only treated as uploaded after /api/documents/upload returns
 * metadata; only then is the library refreshed and the new document selected.
 */
export function Library() {
  const library = useDocuments()
  const [selectedId, setSelectedId] = useState(null)
  const [toast, setToast] = useState(null)
  const dismissToast = useCallback(() => setToast(null), [])

  const uploads = useUploadQueue({
    onUploaded: (document) => {
      library.refresh()
      setSelectedId(document.document_id)
      setToast({
        kind: 'success',
        message: `${document.filename} was uploaded and indexed.`,
      })
    },
  })

  return (
    <Container className="py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Documents
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Upload PDFs and inspect exactly what the backend extracted from them.
          </p>
        </div>
        {library.phase === 'ready' ? (
          <p className="text-xs text-slate-500">
            {pluralize(library.count, 'document')} indexed
          </p>
        ) : null}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <div className="space-y-6">
          <UploadPanel uploads={uploads} />
          <DocumentLibrary
            library={library}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
        <div>
          <DocumentDetails
            documentId={selectedId}
            onClose={selectedId ? () => setSelectedId(null) : undefined}
          />
        </div>
      </div>

      <Toast toast={toast} onDismiss={dismissToast} />
    </Container>
  )
}
