/**
 * Shared formatting helpers, pulled out of page components so the scaling
 * math (a frequent source of "0.85 rendered as 0.85%" bugs) can be unit
 * tested directly instead of only eyeballed in the browser.
 */

/**
 * Format a [0,1] quality/verifier score as a whole-number percentage string,
 * e.g. 0.85 -> "85%". Returns a distinct placeholder for missing scores
 * instead of silently treating "unknown" the same as "measured zero".
 */
export function formatQualityPercent(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return '—'
  }
  const clamped = Math.max(0, Math.min(1, score))
  return `${Math.round(clamped * 100)}%`
}

/** Seconds -> compact human duration, e.g. 45 -> "45s", 125 -> "2m 5s", 4000 -> "1h 6m". */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.round(seconds % 60)
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

/** Unix-seconds-from-plan-start offset -> "HH:MM" clock time given a plan start Date. */
export function formatClockTime(offsetSeconds: number, planStart: Date = new Date()): string {
  const t = new Date(planStart.getTime() + offsetSeconds * 1000)
  return t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
