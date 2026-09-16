/** Управляемая подмена WebSocket: тест сам решает, когда соединение открылось,
 * закрылось или пришло сообщение. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = []

  url: string
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  static latest(): FakeWebSocket {
    const socket = FakeWebSocket.instances.at(-1)
    if (!socket) throw new Error('no WebSocket was opened')
    return socket
  }

  static reset() {
    FakeWebSocket.instances = []
  }

  open() {
    this.onopen?.()
  }

  receive(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  /** Обрыв со стороны сервера (рестарт бэкенда, сеть). */
  drop() {
    this.onclose?.()
  }

  close() {
    this.closed = true
    this.onclose?.()
  }
}
