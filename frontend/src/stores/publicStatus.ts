import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { api } from '../api/http'
import { connectRealtime } from '../api/ws'
import type { PublicGroupStatus, PublicRealtimeEvent, PublicStatus } from '../types'

/** Группа "упала", если упала хотя бы одна её проверка; пауза группу не роняет. */
export function groupStatusOf(group: PublicGroupStatus): 'up' | 'down' {
  return group.checks.some((c) => c.status === 'down') ? 'down' : 'up'
}

export const usePublicStatusStore = defineStore('publicStatus', () => {
  const data = ref<PublicStatus | null>(null)
  const loading = ref(true)
  // момент начала текущего падения (epoch-мс) — длительность тикает на клиенте
  const incidentAnchors = reactive<Record<number, number>>({})

  let disconnect: (() => void) | null = null

  async function load() {
    const snapshot = await api.public.status()
    for (const key of Object.keys(incidentAnchors)) delete incidentAnchors[Number(key)]
    const fetchedAt = Date.now()
    for (const group of snapshot.groups) {
      for (const check of group.checks) {
        if (check.status === 'down' && check.current_downtime_seconds !== null) {
          incidentAnchors[check.check_id] = fetchedAt - check.current_downtime_seconds * 1000
        }
      }
    }
    data.value = snapshot
    loading.value = false
  }

  function applyEvent(event: PublicRealtimeEvent) {
    if (event.type === 'public.changed') {
      // проверку сделали публичной/приватной, удалили, поставили на паузу, переименовали группу
      void load()
      return
    }
    if (!data.value) return

    for (const group of data.value.groups) {
      const check = group.checks.find((c) => c.check_id === event.check_id)
      if (!check) continue

      if (event.type === 'check.result') {
        check.last_checked_at = event.checked_at
      } else if (event.type === 'incident.opened') {
        check.status = 'down'
        incidentAnchors[event.check_id] = new Date(event.started_at).getTime()
      } else if (event.type === 'incident.closed') {
        // закрытие из-за паузы приходит вместе с public.changed — снимок поставит "paused"
        if (check.status === 'down') check.status = 'up'
        check.current_downtime_seconds = null
        delete incidentAnchors[event.check_id]
      }
      group.status = groupStatusOf(group)
    }
  }

  function downtimeSeconds(checkId: number, now: number): number | null {
    const anchor = incidentAnchors[checkId]
    return anchor === undefined ? null : (now - anchor) / 1000
  }

  function start() {
    if (disconnect) return
    // load и при первом открытии, и после переподключения: события за время обрыва потеряны
    disconnect = connectRealtime('public', applyEvent, () => void load())
  }

  function stop() {
    disconnect?.()
    disconnect = null
  }

  return { data, loading, load, applyEvent, downtimeSeconds, start, stop }
})
