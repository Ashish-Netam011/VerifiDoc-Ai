/** Small display formatters. They never invent data: unknown values render as "—". */

export function formatBytes(bytes) {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`

  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  const rounded = value < 10 ? value.toFixed(1) : Math.round(value)
  return `${rounded} ${units[index]}`
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function pluralize(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`
}

/** Compact identifier for dense cards; the full ID is shown in the details panel. */
export function shortId(id) {
  if (typeof id !== 'string' || id.length < 12) return id || '—'
  return `${id.slice(0, 8)}…${id.slice(-4)}`
}
