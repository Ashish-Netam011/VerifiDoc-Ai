/**
 * GET /api/health
 *
 * Response schema (backend/app/routers/health.py):
 *   { status: "ok" | "degraded",
 *     backend: { status: "ok", version, uptime_s },
 *     llm: { available, model, model_present, detail } }
 *
 * A 200 does not mean the LLM is usable: `status` is "degraded" whenever the
 * model is missing, and `llm.available` is already combined with model
 * presence by the backend. The view model below reports each signal
 * separately instead of trusting the HTTP status.
 */

import { DEFAULT_TIMEOUTS, request } from './client.js'
import { ApiError } from './errors.js'

export function parseHealth(payload) {
  if (!payload || typeof payload !== 'object' || !payload.backend || !payload.llm) {
    throw new ApiError({
      kind: 'parse',
      message: 'The health response could not be read.',
      url: '/api/health',
    })
  }

  const backend = payload.backend
  const llm = payload.llm
  const ollamaAvailable = llm.available === true
  const modelPresent = llm.model_present === true
  const model = typeof llm.model === 'string' ? llm.model : ''
  const llmUsable = ollamaAvailable && modelPresent

  return {
    /** The backend's own verdict, never inferred from HTTP 200. */
    serviceStatus: payload.status === 'ok' ? 'ok' : 'degraded',
    backendAvailable: backend.status === 'ok',
    backendVersion: typeof backend.version === 'string' ? backend.version : '',
    uptimeSeconds: typeof backend.uptime_s === 'number' ? backend.uptime_s : null,
    ollamaAvailable,
    modelPresent,
    model,
    /** "ready" | "ollama_unavailable" | "model_missing" */
    modelState: llmUsable
      ? 'ready'
      : !ollamaAvailable && !modelPresent
        ? 'ollama_unavailable'
        : 'model_missing',
    llmUsable,
    detail: typeof llm.detail === 'string' ? llm.detail : '',
  }
}

export async function getHealth({ signal, timeoutMs = DEFAULT_TIMEOUTS.health } = {}) {
  const payload = await request('/api/health', { timeoutMs, signal })
  return parseHealth(payload)
}
