import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/http'
import { FakeWebSocket } from '../test/fakeWebSocket'
import type { PublicCheckStatus, PublicStatus } from '../types'
import { usePublicStatusStore } from './publicStatus'

function check(overrides: Partial<PublicCheckStatus> = {}): PublicCheckStatus {
  return {
    check_id: 1,
    name: 'api',
    status: 'up',
    last_checked_at: null,
    current_downtime_seconds: null,
    uptime_ratio_24h: 1,
    ...overrides,
  }
}

function snapshot(...checks: PublicCheckStatus[]): PublicStatus {
  const status = checks.some((c) => c.status === 'down') ? 'down' : 'up'
  return { groups: [{ group_id: 1, name: 'Prod', status, checks }] }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('public status store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    FakeWebSocket.reset()
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('reloads the snapshot on public.changed', async () => {
    const statusApi = vi.spyOn(api.public, 'status').mockResolvedValue(snapshot(check()))
    const store = usePublicStatusStore()
    store.start()
    FakeWebSocket.latest().open()
    await flush()
    expect(store.data!.groups[0]!.checks).toHaveLength(1)

    // в админке вторую проверку сделали публичной
    statusApi.mockResolvedValue(snapshot(check(), check({ check_id: 2, name: 'web' })))
    FakeWebSocket.latest().receive({ type: 'public.changed' })
    await flush()

    expect(store.data!.groups[0]!.checks.map((c) => c.name)).toEqual(['api', 'web'])
    store.stop()
  })

  it('reloads after reconnect so a missed incident.closed does not leave the check down', async () => {
    const statusApi = vi
      .spyOn(api.public, 'status')
      .mockResolvedValue(snapshot(check({ status: 'down', current_downtime_seconds: 120 })))
    const store = usePublicStatusStore()
    store.start()
    FakeWebSocket.latest().open()
    await flush()
    expect(store.data!.groups[0]!.status).toBe('down')

    // бэкенд перезапускался, сайт за это время восстановился, incident.closed потерян
    FakeWebSocket.latest().drop()
    statusApi.mockResolvedValue(snapshot(check()))
    await new Promise((resolve) => setTimeout(resolve, 1050))
    FakeWebSocket.latest().open()
    await flush()

    expect(store.data!.groups[0]!.status).toBe('up')
    expect(store.downtimeSeconds(1, Date.now())).toBeNull()
    store.stop()
  })

  it('a paused check does not hold the group down; incidents update group status', async () => {
    vi.spyOn(api.public, 'status').mockResolvedValue(
      snapshot(check(), check({ check_id: 2, name: 'batch', status: 'paused' })),
    )
    const store = usePublicStatusStore()
    await store.load()
    const group = store.data!.groups[0]!
    expect(group.status).toBe('up')

    store.applyEvent({ type: 'incident.opened', check_id: 1, started_at: '2026-01-01T10:00:00Z', ended_at: null })
    expect(group.status).toBe('down')
    expect(store.downtimeSeconds(1, Date.parse('2026-01-01T10:01:30Z'))).toBe(90)

    store.applyEvent({
      type: 'incident.closed',
      check_id: 1,
      started_at: '2026-01-01T10:00:00Z',
      ended_at: '2026-01-01T10:02:00Z',
    })
    expect(group.status).toBe('up')
    expect(group.checks[1]!.status).toBe('paused')
  })
})
