import { describe, expect, it } from 'vitest'
import type { CheckHistory, HistoryPoint } from '../types'
import { buildHistorySeries } from './historyChart'

const t = (iso: string) => Date.parse(iso)

function point(bucket_start: string, avg: number | null, uptime: number | null = 1): HistoryPoint {
  return { bucket_start, avg_response_time_ms: avg, uptime_ratio: uptime, sample_count: 1 }
}

function history(overrides: Partial<CheckHistory>): CheckHistory {
  return {
    range: 'day',
    range_start: '2026-01-01T00:00:00Z',
    range_end: '2026-01-02T00:00:00Z',
    points: [],
    gaps: [],
    overall_uptime_ratio: null,
    ...overrides,
  }
}

describe('buildHistorySeries', () => {
  it('breaks the line where monitoring was down instead of joining the neighbours', () => {
    const series = buildHistorySeries(
      history({
        points: [point('2026-01-01T10:00:00Z', 20), point('2026-01-01T10:00:30Z', 30), point('2026-01-01T14:00:00Z', 25)],
        gaps: [{ start: '2026-01-01T10:00:30Z', end: '2026-01-01T14:00:00Z' }],
      }),
    )

    expect(series.responseTime).toEqual([
      { x: t('2026-01-01T10:00:00Z'), y: 20 },
      { x: t('2026-01-01T10:00:30Z'), y: 30 },
      { x: t('2026-01-01T12:00:15Z'), y: null },
      { x: t('2026-01-01T14:00:00Z'), y: 25 },
    ])
    expect(series.gaps).toEqual([{ start: t('2026-01-01T10:00:30Z'), end: t('2026-01-01T14:00:00Z') }])
  })

  it('x-axis spans the whole requested period, so a gap up to now is visible', () => {
    const series = buildHistorySeries(
      history({
        points: [point('2026-01-01T10:00:00Z', 20)],
        gaps: [{ start: '2026-01-01T10:00:00Z', end: '2026-01-02T00:00:00Z' }],
      }),
    )

    expect(series.min).toBe(t('2026-01-01T00:00:00Z'))
    expect(series.max).toBe(t('2026-01-02T00:00:00Z'))
  })

  it('in hourly buckets a gap shorter than an hour is shaded but does not cut the line', () => {
    const series = buildHistorySeries(
      history({
        range: 'week',
        points: [point('2026-01-01T10:00:00Z', 20), point('2026-01-01T11:00:00Z', 22), point('2026-01-01T15:00:00Z', 21)],
        gaps: [
          { start: '2026-01-01T10:20:00Z', end: '2026-01-01T10:23:00Z' },
          { start: '2026-01-01T11:40:00Z', end: '2026-01-01T15:05:00Z' },
        ],
      }),
    )

    expect(series.responseTime.map((p) => p.y)).toEqual([20, 22, null, 21])
    expect(series.gaps).toHaveLength(2)
  })

  it('uptime is plotted in percent and a failed probe is not mistaken for a gap', () => {
    const series = buildHistorySeries(
      history({ points: [point('2026-01-01T10:00:00Z', 20, 1), point('2026-01-01T10:00:30Z', null, 0)] }),
    )

    expect(series.uptimePercent.map((p) => p.y)).toEqual([100, 0])
    expect(series.gaps).toEqual([])
  })
})
