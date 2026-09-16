<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { onMounted, onUnmounted } from 'vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useNow } from '../composables/useNow'
import { usePublicStatusStore } from '../stores/publicStatus'
import { formatDateTime, formatDuration, formatPercent } from '../utils/format'

const store = usePublicStatusStore()
const { data, loading } = storeToRefs(store)
const now = useNow()

onMounted(() => {
  void store.load()
  store.start()
})
onUnmounted(() => store.stop())
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
      <div class="table-wrap">
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
                  &nbsp;{{ formatDuration(store.downtimeSeconds(check.check_id, now)) }}
                </span>
              </td>
              <td>{{ formatPercent(check.uptime_ratio_24h) }}</td>
              <td>{{ formatDateTime(check.last_checked_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
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
.table-wrap {
  overflow-x: auto;
}
</style>
