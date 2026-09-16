import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/http'
import { FakeWebSocket } from '../test/fakeWebSocket'
import type { CheckStatus } from '../types'
import { useChecksStore } from './checks'

function status(overrides: Partial<CheckStatus> = {}): CheckStatus {
  return {
    check_id: 1,
    name: 'api',
    group_id: null,
    is_paused: false,
    last_checked_at: null,
    last_success: false,
    last_response_time_ms: null,
    is_down: true,
    current_incident_started_at: '2026-01-01T10:00:00Z',
    current_downtime_seconds: 60,
    ...overrides,
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('checks store realtime', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    FakeWebSocket.reset()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.spyOn(api.checks, 'list').mockResolvedValue([])
    vi.spyOn(api.groups, 'list').mockResolvedValue([])
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('refetches after a reconnect, so an incident.closed missed during a restart does not stick', async () => {
    const statusApi = vi.spyOn(api.checks, 'status').mockResolvedValue([status()])
    const store = useChecksStore()
    await store.fetchAll()
    store.startRealtime()
    FakeWebSocket.latest().open()
    await flush()
    expect(store.statuses[1]!.is_down).toBe(true)

    // бэкенд перезапускался; за это время сайт восстановился, а incident.closed ушёл в пустоту
    FakeWebSocket.latest().drop()
    statusApi.mockResolvedValue([status({ is_down: false, current_incident_started_at: null, last_success: true })])
    await new Promise((resolve) => setTimeout(resolve, 1050))
    const generation = store.syncGeneration
    FakeWebSocket.latest().open()
    await flush()

    expect(store.statuses[1]!.is_down).toBe(false)
    expect(store.syncGeneration).toBe(generation + 1)
    store.stopRealtime()
  })

  it('admin.changed refetches checks and groups', async () => {
    vi.spyOn(api.checks, 'status').mockResolvedValue([])
    const store = useChecksStore()
    store.startRealtime()

    FakeWebSocket.latest().receive({ type: 'admin.changed' })
    await flush()

    expect(api.checks.list).toHaveBeenCalledTimes(1)
    expect(api.groups.list).toHaveBeenCalledTimes(1)
    store.stopRealtime()
  })
})
