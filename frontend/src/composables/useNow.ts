import { onMounted, onUnmounted, ref } from 'vue'

/** Тикающие "текущие часы" для реактивного отображения длительности
 * (например, текущего падения) без ожидания следующего WS-события. */
export function useNow(intervalMs = 1000) {
  const now = ref(Date.now())
  let timer: ReturnType<typeof setInterval> | undefined

  onMounted(() => {
    timer = setInterval(() => {
      now.value = Date.now()
    }, intervalMs)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return now
}
