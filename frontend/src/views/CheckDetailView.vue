<script setup lang="ts">
import {
  Chart as ChartJS,
  type ChartOptions,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Title,
  Tooltip,
} from 'chart.js'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { Line } from 'vue-chartjs'
import { api } from '../api/http'
import StatusBadge from '../components/StatusBadge.vue'
import { useNow } from '../composables/useNow'
import { useChecksStore } from '../stores/checks'
import type { CheckHistory, HistoryRange, Incident, MaintenanceWindow } from '../types'
import { formatDateTime, formatDuration, formatPercent, incidentEndLabel } from '../utils/format'
import { buildHistorySeries, formatAxisTick, gapShadingPlugin } from '../utils/historyChart'

ChartJS.register(LineElement, PointElement, LinearScale, Tooltip, Legend, Title)

const route = useRoute()
const checkId = computed(() => Number(route.params.id))

const checksStore = useChecksStore()
const now = useNow()

const history = ref<CheckHistory | null>(null)
const incidents = ref<Incident[]>([])
const windows = ref<MaintenanceWindow[]>([])
const range = ref<HistoryRange>('day')
const loadingHistory = ref(false)

const check = computed(() => checksStore.checks.find((c) => c.id === checkId.value))
const status = computed(() => checksStore.statuses[checkId.value])

const statusKind = computed<'up' | 'down' | 'paused'>(() => {
  if (check.value?.is_paused) return 'paused'
  return status.value?.is_down ? 'down' : 'up'
})

const liveDowntime = computed(() => {
  if (!status.value?.current_incident_started_at) return null
  return (now.value - new Date(status.value.current_incident_started_at).getTime()) / 1000
})

async function loadHistory() {
  loadingHistory.value = true
  try {
    history.value = await api.checks.history(checkId.value, range.value)
  } finally {
    loadingHistory.value = false
  }
}

async function loadIncidents() {
  incidents.value = await api.checks.incidents(checkId.value)
}

async function loadWindows() {
  windows.value = await api.maintenanceWindows.listForCheck(checkId.value)
}

watch(range, loadHistory)
// admin.changed или переподключение WS: пока соединения не было, события могли потеряться
watch(
  () => checksStore.syncGeneration,
  () => Promise.all([loadHistory(), loadIncidents(), loadWindows()]),
)
// инцидент открылся или закрылся — обновить журнал
watch(
  () => status.value?.is_down,
  (isDown, wasDown) => {
    if (wasDown !== undefined && isDown !== wasDown) void loadIncidents()
  },
)

onMounted(async () => {
  await checksStore.fetchAll()
  checksStore.startRealtime()
  await Promise.all([loadHistory(), loadIncidents(), loadWindows()])
})
onUnmounted(() => checksStore.stopRealtime())

const series = computed(() => (history.value ? buildHistorySeries(history.value) : null))

const chartData = computed(() => ({
  datasets: [
    {
      label: 'Время ответа (мс)',
      data: series.value?.responseTime ?? [],
      borderColor: '#2563eb',
      backgroundColor: 'rgba(37,99,235,0.15)',
      yAxisID: 'y',
      pointRadius: range.value === 'day' ? 0 : 2,
      tension: 0.2,
    },
    {
      label: 'Доступность (%)',
      data: series.value?.uptimePercent ?? [],
      borderColor: '#dc2626',
      backgroundColor: 'rgba(220,38,38,0.15)',
      yAxisID: 'uptime',
      pointRadius: 0,
      stepped: true,
    },
  ],
}))

const shading = gapShadingPlugin(() => series.value?.gaps ?? [])

const chartOptions = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  parsing: false,
  interaction: { mode: 'nearest', axis: 'x', intersect: false },
  scales: {
    x: {
      type: 'linear',
      min: series.value?.min,
      max: series.value?.max,
      ticks: { maxTicksLimit: 8, callback: (value) => formatAxisTick(range.value, Number(value)) },
    },
    y: { beginAtZero: true, title: { display: true, text: 'мс' } },
    uptime: {
      position: 'right',
      min: 0,
      max: 100,
      grid: { drawOnChartArea: false },
      title: { display: true, text: '%' },
    },
  },
  plugins: {
    tooltip: {
      callbacks: { title: (items) => new Date(items[0]?.parsed.x ?? 0).toLocaleString() },
    },
  },
}))

const gapsTotalSeconds = computed(
  () => (series.value?.gaps ?? []).reduce((sum, g) => sum + (g.end - g.start), 0) / 1000,
)

async function togglePause() {
  if (!check.value) return
  if (check.value.is_paused) await checksStore.resume(check.value.id)
  else await checksStore.pause(check.value.id)
}

const runningNow = ref(false)
async function runNow() {
  runningNow.value = true
  try {
    await checksStore.runNow(checkId.value)
    await loadIncidents()
  } finally {
    runningNow.value = false
  }
}

// --- окна обслуживания ---
const windowForm = reactive({ starts_at: '', ends_at: '', note: '' })

async function createWindow() {
  if (!windowForm.starts_at || !windowForm.ends_at) return
  await api.maintenanceWindows.create({
    check_id: checkId.value,
    starts_at: new Date(windowForm.starts_at).toISOString(),
    ends_at: new Date(windowForm.ends_at).toISOString(),
    note: windowForm.note.trim() || null,
  })
  windowForm.starts_at = ''
  windowForm.ends_at = ''
  windowForm.note = ''
  await loadWindows()
}

async function removeWindow(id: number) {
  await api.maintenanceWindows.remove(id)
  await loadWindows()
}
</script>

<template>
  <div class="page">
    <RouterLink to="/">← К списку проверок</RouterLink>

    <template v-if="check">
      <header class="page-header">
        <div>
          <h1>{{ check.name }}</h1>
          <p class="muted">{{ check.url }}</p>
        </div>
        <div class="actions">
          <StatusBadge :status="statusKind" />
          <span v-if="statusKind === 'down'" class="muted">{{ formatDuration(liveDowntime) }}</span>
        </div>
      </header>

      <section class="card actions-bar">
        <button @click="togglePause">{{ check.is_paused ? 'Возобновить' : 'Поставить на паузу' }}</button>
        <button :disabled="runningNow" @click="runNow">Проверить сейчас</button>
        <span class="muted">
          Интервал: {{ check.interval_seconds }}с · Таймаут: {{ check.timeout_ms }}мс · Ожид. код:
          {{ check.expected_status_code }}
        </span>
      </section>

      <section class="card">
        <div class="card-header">
          <h2>История</h2>
          <div class="range-buttons">
            <button :class="{ primary: range === 'day' }" @click="range = 'day'">Сутки</button>
            <button :class="{ primary: range === 'week' }" @click="range = 'week'">Неделя</button>
            <button :class="{ primary: range === 'month' }" @click="range = 'month'">Месяц</button>
          </div>
        </div>
        <p class="muted">
          Доступность за период: {{ formatPercent(history?.overall_uptime_ratio) }}
          <template v-if="series?.gaps.length">
            · <span class="gap-swatch"></span> мониторинг не работал {{ series.gaps.length }} раз(а), всего
            {{ formatDuration(gapsTotalSeconds) }} — эти интервалы не считаются ни работой, ни падением
          </template>
        </p>
        <div class="chart-wrap">
          <Line
            v-if="history && history.points.length"
            :data="chartData"
            :options="chartOptions"
            :plugins="[shading]"
          />
          <p v-else class="muted">Пока нет данных за этот период.</p>
        </div>
      </section>

      <section class="card">
        <h2>Журнал инцидентов</h2>
        <table v-if="incidents.length">
          <thead>
            <tr>
              <th>Начало</th>
              <th>Конец</th>
              <th>Длительность</th>
              <th>Чем закончился</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="incident in incidents" :key="incident.id">
              <td>{{ formatDateTime(incident.started_at) }}</td>
              <td>{{ incident.ended_at ? formatDateTime(incident.ended_at) : 'сейчас' }}</td>
              <td>{{ incident.duration_seconds !== null ? formatDuration(incident.duration_seconds) : '—' }}</td>
              <td :class="{ muted: incident.end_reason && incident.end_reason !== 'recovered' }">
                {{ incidentEndLabel(incident) }}
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">Инцидентов не было.</p>
      </section>

      <section class="card">
        <h2>Окна обслуживания</h2>
        <table v-if="windows.length">
          <thead>
            <tr>
              <th>Начало</th>
              <th>Конец</th>
              <th>Заметка</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="w in windows" :key="w.id">
              <td>{{ formatDateTime(w.starts_at) }}</td>
              <td>{{ formatDateTime(w.ends_at) }}</td>
              <td>{{ w.note || '—' }}</td>
              <td><button class="danger" @click="removeWindow(w.id)">Удалить</button></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">Окон обслуживания нет.</p>

        <form class="inline-form" @submit.prevent="createWindow">
          <label>Начало <input v-model="windowForm.starts_at" type="datetime-local" required /></label>
          <label>Конец <input v-model="windowForm.ends_at" type="datetime-local" required /></label>
          <input v-model="windowForm.note" placeholder="Заметка (опц.)" style="width: 14rem" />
          <button type="submit" class="primary">Добавить окно</button>
        </form>
      </section>
    </template>
    <p v-else class="muted">Загрузка…</p>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}
.page-header h1 {
  margin: 0.5rem 0 0.2rem;
  font-size: 1.4rem;
}
.actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.actions-bar {
  display: flex;
  gap: 0.6rem;
  align-items: center;
  flex-wrap: wrap;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.range-buttons {
  display: flex;
  gap: 0.4rem;
}
.chart-wrap {
  height: 280px;
}
.gap-swatch {
  display: inline-block;
  width: 0.8rem;
  height: 0.8rem;
  vertical-align: middle;
  background: rgba(148, 163, 184, 0.45);
  border-radius: 2px;
}
.muted {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
.inline-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-top: 0.75rem;
}
.inline-form label {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.85rem;
  color: var(--color-text-muted);
}
</style>
