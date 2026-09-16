import type { AdminRealtimeEvent, PublicRealtimeEvent } from '../types'

interface EventsByChannel {
  admin: AdminRealtimeEvent
  public: PublicRealtimeEvent
}

/** Открывает WS-соединение с автопереподключением (экспоненциальный backoff,
 * потолок 15с) и возвращает функцию отключения.
 *
 * `onOpen` вызывается при КАЖДОМ открытии, включая переподключения. Пока соединения
 * не было (рестарт бэкенда, обрыв сети), события терялись — например,
 * `incident.closed`, и статус залипал в "упал". Сервер не хранит пропущенные
 * события, поэтому единственный надёжный способ — перезапросить снимок через REST. */
export function connectRealtime<C extends keyof EventsByChannel>(
  channel: C,
  onEvent: (event: EventsByChannel[C]) => void,
  onOpen?: () => void,
): () => void {
  let socket: WebSocket | null = null
  let closedByCaller = false
  let retryDelay = 1000
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${protocol}://${location.host}/ws/${channel}`)

    socket.onmessage = (event) => {
      let parsed: EventsByChannel[C]
      try {
        parsed = JSON.parse(event.data) as EventsByChannel[C]
      } catch {
        return // не-JSON сообщение — игнорируем
      }
      onEvent(parsed)
    }

    socket.onopen = () => {
      retryDelay = 1000
      onOpen?.()
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
