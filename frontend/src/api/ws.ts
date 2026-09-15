import type { RealtimeEvent } from '../types'

/** Открывает WS-соединение с автопереподключением (экспоненциальный backoff,
 * потолок 15с) и возвращает функцию отключения. */
export function connectRealtime(
  channel: 'admin' | 'public',
  onEvent: (event: RealtimeEvent) => void,
): () => void {
  let socket: WebSocket | null = null
  let closedByCaller = false
  let retryDelay = 1000
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${protocol}://${location.host}/ws/${channel}`)

    socket.onmessage = (event) => {
      try {
        onEvent(JSON.parse(event.data) as RealtimeEvent)
      } catch {
        // не-JSON/незнакомое сообщение — игнорируем
      }
    }

    socket.onopen = () => {
      retryDelay = 1000
    }

    socket.onclose = () => {
      if (closedByCaller) return
      retryTimer = setTimeout(connect, retryDelay)
      retryDelay = Math.min(retryDelay * 2, 15000)
    }
  }

  connect()

  return () => {
    closedByCaller = true
    if (retryTimer) clearTimeout(retryTimer)
    socket?.close()
  }
}
