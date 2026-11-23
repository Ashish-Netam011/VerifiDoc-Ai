import { useCallback, useEffect, useRef, useState } from 'react'
import { uploadDocument } from '@/api/documents'
import { isAbortError } from '@/api/errors'
import { validatePdfFile } from '@/lib/uploadValidation'

/**
 * Multiple independent uploads with real XMLHttpRequest progress.
 *
 * - Every file gets its own item and its own state
 *   (`queued` | `uploading` | `success` | `error` | `rejected`).
 * - Client validation failures become `rejected` items with the message; they
 *   never reach the backend.
 * - Files are sent one at a time. This keeps the local embedding model and
 *   upload bandwidth predictable; each item's outcome and progress are still
 *   independent.
 * - A successful item is only marked `success` after the backend answers with
 *   document metadata.
 * - An identical file already queued or uploading is rejected as a duplicate.
 */

let uploadCounter = 0
function nextUploadId() {
  uploadCounter += 1
  return `upload-${Date.now()}-${uploadCounter}`
}

export function useUploadQueue({ onUploaded } = {}) {
  const [items, setItems] = useState([])
  const itemsRef = useRef([])
  const activeIdRef = useRef(null)
  const controllerRef = useRef(null)
  const onUploadedRef = useRef(onUploaded)

  useEffect(() => {
    onUploadedRef.current = onUploaded
  }, [onUploaded])

  useEffect(() => {
    itemsRef.current = items
  }, [items])

  const patch = useCallback((id, changes) => {
    setItems((previous) =>
      previous.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    )
  }, [])

  const addFiles = useCallback(async (fileList) => {
    const files = Array.from(fileList ?? [])
    if (files.length === 0) return

    const prepared = []
    for (const file of files) {
      const base = {
        id: nextUploadId(),
        file,
        name: file.name,
        size: file.size,
        progress: null,
        message: null,
        document: null,
      }

      const duplicate = [...itemsRef.current, ...prepared].some(
        (item) =>
          (item.status === 'queued' || item.status === 'uploading') &&
          item.name === file.name &&
          item.size === file.size,
      )
      if (duplicate) {
        prepared.push({
          ...base,
          status: 'rejected',
          message: 'This file is already uploading.',
        })
        continue
      }

      const verdict = await validatePdfFile(file)
      prepared.push(
        verdict.ok
          ? { ...base, status: 'queued' }
          : { ...base, status: 'rejected', message: verdict.message },
      )
    }

    itemsRef.current = [...itemsRef.current, ...prepared]
    setItems((previous) => [...previous, ...prepared])
  }, [])

  // Send the next queued file once nothing else is in flight.
  useEffect(() => {
    if (activeIdRef.current) return
    const next = items.find((item) => item.status === 'queued')
    if (!next) return

    const controller = new AbortController()
    activeIdRef.current = next.id
    controllerRef.current = controller
    patch(next.id, { status: 'uploading', progress: null, message: null })

    uploadDocument(next.file, {
      signal: controller.signal,
      onProgress: ({ ratio }) => patch(next.id, { progress: ratio }),
    })
      .then((document) => {
        patch(next.id, {
          status: 'success',
          progress: 1,
          document,
          message: null,
        })
        onUploadedRef.current?.(document)
      })
      .catch((error) => {
        if (isAbortError(error)) return
        patch(next.id, {
          status: 'error',
          progress: null,
          message: error?.message ?? 'The upload failed.',
          error,
        })
      })
      .finally(() => {
        activeIdRef.current = null
        controllerRef.current = null
      })
  }, [items, patch])

  useEffect(
    () => () => {
      controllerRef.current?.abort()
    },
    [],
  )

  const retry = useCallback(
    (id) => {
      setItems((previous) =>
        previous.map((item) =>
          item.id === id && (item.status === 'error' || item.status === 'rejected')
            ? {
                ...item,
                status: 'queued',
                progress: null,
                message: null,
                error: null,
              }
            : item,
        ),
      )
    },
    [],
  )

  const dismiss = useCallback((id) => {
    setItems((previous) =>
      previous.filter(
        (item) => !(item.id === id && item.status !== 'uploading'),
      ),
    )
  }, [])

  const clearFinished = useCallback(() => {
    setItems((previous) => previous.filter((item) => item.status === 'uploading'))
  }, [])

  const isUploading = items.some(
    (item) => item.status === 'uploading' || item.status === 'queued',
  )

  return {
    items,
    addFiles,
    retry,
    dismiss,
    clearFinished,
    isUploading,
    activeCount: items.filter((item) => item.status === 'uploading').length,
  }
}
