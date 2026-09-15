<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { api } from '../api/http'
import { connectRealtime } from '../api/ws'
import StatusBadge from '../components/StatusBadge.vue'
import { useNow } from '../composables/useNow'
import type { PublicStatus, RealtimeEvent } from '../types'
import { formatDateTime, formatDuration, formatPercent } from '../utils/format'

const data = ref<PublicStatus | null>(null)
const loading = ref(true)
const now = useNow()
// анкор в epoch-мс для тикающего отображения длительности падения на клиенте
const incidentAnchors = reactive<Record<number, number>>({})

let disconnect: (() => void) | null = null

function applyEvent(event: RealtimeEvent) {
  if (!data.value) return
  if (event.type === 'admin.changed') return // публичный канал такое не шлёт, но типы общие

  for (const group of data.value.groups) {
    const check = group.checks.find((c) => c.check_id === event.check_id)
    if (!check) continue

    if (event.type === 'check.result') {
      check.last_checked_at = event.checked_at
    } else if (event.type === 'incident.opened') {
      check.status = 'down'
      incidentAnchors[event.check_id] = new Date(event.started_at).getTime()
      group.status = 'down'
    } else if (event.type === 'incident.closed') {
      check.status = 'up'
      delete incidentAnchors[event.check_id]
      group.status = group.checks.every((c) => c.status === 'up') ? 'up' : 'down'
    }
  }
}

function liveDowntime(checkId: number, fallback: number | null): number | null {
  const anchor = incidentAnchors[checkId]
  if (anchor === undefined) return fallback
  return (now.value - anchor) / 1000
}

onMounted(async () => {
  data.value = await api.public.status()
  for (const group of data.value.groups) {
    for (const check of group.checks) {
      if (check.status === 'down' && check.current_downtime_seconds !== null) {
        incidentAnchors[check.check_id] = Date.now() - check.current_downtime_seconds * 1000
      }
    }
  }
  loading.value = false
  disconnect = connectRealtime('public', applyEvent)
})

onUnmounted(() => disconnect?.())
</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>Статус сервисов</h1>
    </header>

    <p v-if="loading" class="muted">Загрузка…</p>
    <p v-else-if="!data?.groups.length" class="muted">Публичных проверок пока нет.</p>

    <section v-for="group in data?.groups" :key="group.group_id ?? 'none'" class="card">
      <div class="card-header">
        <h2>{{ group.name ?? 'Без группы' }}</h2>
        <StatusBadge :status="group.status" />
      </div>
      <table>
        <thead>
          <tr>
            <th>Сервис</th>
            <th>Статус</th>
            <th>Аптайм за 24ч</th>
            <th>Проверено</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="check in group.checks" :key="check.check_id">
            <td>{{ check.name }}</td>
            <td>
              <StatusBadge :status="check.status" />
              <span v-if="check.status === 'down'" class="muted">
                &nbsp;{{ formatDuration(liveDowntime(check.check_id, check.current_downtime_seconds)) }}
              </span>
            </td>
            <td>{{ formatPercent(check.uptime_ratio_24h) }}</td>
            <td>{{ formatDateTime(check.last_checked_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.page {
  max-width: 900px;
  margin: 0 auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.page-header h1 {
  font-size: 1.4rem;
  margin: 0;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.card-header h2 {
  margin: 0;
  font-size: 1.05rem;
}
.muted {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
</style>
