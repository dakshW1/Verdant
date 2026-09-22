import { describe, expect, it } from 'vitest'
import { formatClockTime, formatDuration, formatQualityPercent } from './format'

describe('formatQualityPercent', () => {
  it('scales a [0,1] score to a whole-number percent (Bug 2 regression)', () => {
    expect(formatQualityPercent(0.85)).toBe('85%')
    expect(formatQualityPercent(0.5)).toBe('50%')
    expect(formatQualityPercent(1)).toBe('100%')
    expect(formatQualityPercent(0)).toBe('0%')
  })

  it('rounds to the nearest whole percent', () => {
    expect(formatQualityPercent(0.704)).toBe('70%')
    expect(formatQualityPercent(0.706)).toBe('71%')
  })

  it('clamps out-of-range values instead of producing >100% or negative percents', () => {
    expect(formatQualityPercent(1.5)).toBe('100%')
    expect(formatQualityPercent(-0.2)).toBe('0%')
  })

  it('distinguishes "unknown" from a real zero score, unlike the old `?? 0` pattern', () => {
    expect(formatQualityPercent(null)).toBe('—')
    expect(formatQualityPercent(undefined)).toBe('—')
    expect(formatQualityPercent(Number.NaN)).toBe('—')
    // A real, measured zero is NOT the same as "we don't know" and must render differently.
    expect(formatQualityPercent(0)).not.toBe(formatQualityPercent(null))
  })
})

describe('formatDuration', () => {
  it('formats sub-minute durations in seconds', () => {
    expect(formatDuration(45)).toBe('45s')
  })

  it('formats minute-scale durations', () => {
    expect(formatDuration(125)).toBe('2m 5s')
    expect(formatDuration(120)).toBe('2m')
  })

  it('formats hour-scale durations', () => {
    expect(formatDuration(3960)).toBe('1h 6m')
    expect(formatDuration(3600)).toBe('1h')
  })

  it('handles invalid input without throwing', () => {
    expect(formatDuration(-5)).toBe('—')
    expect(formatDuration(Number.NaN)).toBe('—')
  })
})

describe('formatClockTime', () => {
  it('offsets from a fixed plan start and renders a clock time string', () => {
    const start = new Date('2026-01-01T00:00:00')
    const result = formatClockTime(3600, start) // +1 hour
    expect(result).toMatch(/^\d{1,2}:\d{2}/)
  })
})
