import { DEFAULT_TIMEOUTS, request } from './client.js'

export function getAmendments({ asOfDate = '', signal } = {}) {
  const query = asOfDate
    ? `?as_of_date=${encodeURIComponent(asOfDate)}`
    : ''
  return request(`/api/amendments${query}`, {
    signal,
    timeoutMs: DEFAULT_TIMEOUTS.documents,
  })
}
