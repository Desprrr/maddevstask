import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type CheckCreatePayload, type CheckUpdatePayload } from '../api/http'
import { connectRealtime } from '../api/ws'
import type { AdminRealtimeEvent, Check, CheckStatus } from '../types'
import { useGroupsStore } from './groups'

export const useChecksStore = defineStore('checks', () => {
  const checks = ref<Check[]>([])
  const statuses = ref<Record<number, CheckStatus>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)
  /** Растёт при каждом admin.changed и каждом (пере)подключении WS. Страницы со своими
   * данными (журнал инцидентов, окна обслуживания, история) следят за ним и перезапрашивают. */
  const syncGeneration = ref(0)

  let disconnectRealtime: (() => void) | null = null
  let realtimeRefs = 0

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      const [checkList, statusList] = await Promise.all([api.checks.list(), api.checks.status()])
      checks.value = checkList
      statuses.value = Object.fromEntries(statusList.map((s) => [s.check_id, s]))
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function refreshStatuses() {
    statuses.value = Object.fromEntries((await api.checks.status()).map((s) => [s.check_id, s]))
  }

  async function create(payload: CheckCreatePayload) {
    const created = await api.checks.create(payload)
    checks.value.push(created)
    await refreshStatuses()
    return created
  }

  async function update(id: number, payload: CheckUpdatePayload) {
    const updated = await api.checks.update(id, payload)
    const idx = checks.value.findIndex((c) => c.id === id)
    if (idx !== -1) checks.value[idx] = updated
    return updated
  }

  async function remove(id: number) {
    await api.checks.remove(id)
    checks.value = checks.value.filter((c) => c.id !== id)
    delete statuses.value[id]
  }

  async function pause(id: number) {
    const updated = await api.checks.pause(id)
    const idx = checks.value.findIndex((c) => c.id === id)
    if (idx !== -1) checks.value[idx] = updated
    return updated
  }

  async function resume(id: number) {
    const updated = await api.checks.resume(id)
    const idx = checks.value.findIndex((c) => c.id === id)
    if (idx !== -1) checks.value[idx] = updated
    return updated
  }

  async function runNow(id: number) {
    const result = await api.checks.runNow(id)
    await refreshStatuses()
    return result
  }

  /** Перезапросить снимок целиком. Структурные изменения (создание/удаление/пауза чека
   * или группы, окна обслуживания) не несут детальный payload — проще и надёжнее
   * перезапросить списки, чем воспроизводить каждую мутацию. То же после переподключения:
   * события, пришедшие пока WS не было, потеряны. */
  function resync() {
    syncGeneration.value += 1
    void fetchAll()
    void useGroupsStore().fetchAll()
  }

  function applyRealtimeEvent(event: AdminRealtimeEvent) {
    if (event.type === 'admin.changed') {
      resync()
      return
    }

    const existing = statuses.value[event.check_id]
    if (event.type === 'check.result') {
      statuses.value[event.check_id] = {
        check_id: event.check_id,
        name: existing?.name ?? checks.value.find((c) => c.id === event.check_id)?.name ?? '',
        group_id: event.group_id,
        is_paused: existing?.is_paused ?? false,
        last_checked_at: event.checked_at,
        last_success: event.success,
        last_response_time_ms: event.response_time_ms,
        is_down: existing?.is_down ?? false,
        current_incident_started_at: existing?.current_incident_started_at ?? null,
        current_downtime_seconds: existing?.current_downtime_seconds ?? null,
      }
    } else if (event.type === 'incident.opened') {
      if (existing) {
        existing.is_down = true
        existing.current_incident_started_at = event.started_at
      }
    } else if (event.type === 'incident.closed') {
      if (existing) {
        existing.is_down = false
        existing.current_incident_started_at = null
        existing.current_downtime_seconds = null
      }
    }
  }

  /** Несколько компонентов на странице могут одновременно хотеть live-обновления
   * — держим одно WS-соединение и счётчик подписчиков, а не по одному на компонент. */
  function startRealtime() {
    realtimeRefs += 1
    if (!disconnectRealtime) {
      disconnectRealtime = connectRealtime('admin', applyRealtimeEvent, resync)
    }
  }

  function stopRealtime() {
    realtimeRefs = Math.max(0, realtimeRefs - 1)
    if (realtimeRefs === 0 && disconnectRealtime) {
      disconnectRealtime()
      disconnectRealtime = null
    }
  }

  return {
    checks,
    statuses,
    loading,
    error,
    syncGeneration,
    fetchAll,
    refreshStatuses,
    create,
    update,
    remove,
    pause,
    resume,
    runNow,
    applyRealtimeEvent,
    startRealtime,
    stopRealtime,
  }
})
