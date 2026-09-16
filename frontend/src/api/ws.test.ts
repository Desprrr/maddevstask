import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeWebSocket } from '../test/fakeWebSocket'
import { connectRealtime } from './ws'

describe('connectRealtime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.reset()
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('calls onOpen on the first connection and on every reconnect', () => {
    const onOpen = vi.fn()
    const disconnect = connectRealtime('admin', () => {}, onOpen)

    FakeWebSocket.latest().open()
    expect(onOpen).toHaveBeenCalledTimes(1)

    // бэкенд перезапустился: пока соединения нет, события теряются
    FakeWebSocket.latest().drop()
    vi.advanceTimersByTime(1000)
    expect(FakeWebSocket.instances).toHaveLength(2)
    FakeWebSocket.latest().open()
    expect(onOpen).toHaveBeenCalledTimes(2)

    disconnect()
  })

  it('backs off up to 15s and resets the delay after a successful open', () => {
    const disconnect = connectRealtime('public', () => {})

    for (const delay of [1000, 2000, 4000, 8000, 15000, 15000]) {
      FakeWebSocket.latest().drop()
      vi.advanceTimersByTime(delay - 1)
      const before = FakeWebSocket.instances.length
      vi.advanceTimersByTime(1)
      expect(FakeWebSocket.instances.length).toBe(before + 1)
    }

    FakeWebSocket.latest().open()
    FakeWebSocket.latest().drop()
    vi.advanceTimersByTime(1000)
    expect(FakeWebSocket.latest().url).toMatch(/\/ws\/public$/)
    expect(FakeWebSocket.instances).toHaveLength(8)

    disconnect()
  })

  it('delivers parsed events, ignores garbage, and does not reconnect after disconnect', () => {
    const onEvent = vi.fn()
    const disconnect = connectRealtime('public', onEvent)
    const socket = FakeWebSocket.latest()

    socket.receive({ type: 'public.changed' })
    socket.onmessage?.({ data: 'not json' })
    expect(onEvent).toHaveBeenCalledExactlyOnceWith({ type: 'public.changed' })

    disconnect()
    vi.advanceTimersByTime(60_000)
    expect(socket.closed).toBe(true)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})
