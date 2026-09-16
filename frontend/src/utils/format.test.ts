import { describe, expect, it } from 'vitest'
import { incidentEndLabel } from './format'

describe('incidentEndLabel', () => {
  it('tells a real recovery apart from an incident cut by monitor downtime or pause', () => {
    const ended = '2026-01-01T10:05:00Z'
    expect(incidentEndLabel({ ended_at: null, end_reason: null })).toBe('идёт сейчас')
    expect(incidentEndLabel({ ended_at: ended, end_reason: 'recovered' })).toBe('сайт восстановился')
    expect(incidentEndLabel({ ended_at: ended, end_reason: 'monitoring_gap' })).toMatch(/мониторинг прерывался/)
    expect(incidentEndLabel({ ended_at: ended, end_reason: 'paused' })).toMatch(/пауз/)
  })
})
