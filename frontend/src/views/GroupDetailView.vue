<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import MaintenanceWindows from '../components/MaintenanceWindows.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useNow } from '../composables/useNow'
import { useChecksStore } from '../stores/checks'
import { useGroupsStore } from '../stores/groups'
import type { Check } from '../types'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const groupId = computed(() => Number(route.params.id))

const checksStore = useChecksStore()
const groupsStore = useGroupsStore()
const now = useNow(30_000)

const group = computed(() => groupsStore.groups.find((g) => g.id === groupId.value))
const checks = computed(() => checksStore.checks.filter((c) => c.group_id === groupId.value))

function statusKind(check: Check): 'up' | 'down' | 'paused' {
  if (check.is_paused) return 'paused'
  return checksStore.statuses[check.id]?.is_down ? 'down' : 'up'
}

onMounted(async () => {
  await Promise.all([groupsStore.fetchAll(), checksStore.fetchAll()])
  checksStore.startRealtime()
})
onUnmounted(() => checksStore.stopRealtime())
</script>

<template>
  <div class="page">
    <RouterLink to="/">← К списку проверок</RouterLink>

    <template v-if="group">
      <header>
        <h1>{{ group.name }}</h1>
        <p class="muted">Оповещения: {{ group.alert_emails.join(', ') || 'адресов нет' }}</p>
      </header>

      <section class="card">
        <h2>Проверки группы</h2>
        <div v-if="checks.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Статус</th>
                <th>Проверено</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="check in checks" :key="check.id">
                <td><RouterLink :to="`/checks/${check.id}`">{{ check.name }}</RouterLink></td>
                <td><StatusBadge :status="statusKind(check)" /></td>
                <td>{{ formatDateTime(checksStore.statuses[check.id]?.last_checked_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted">В группе пока нет проверок.</p>
      </section>

      <section class="card">
        <h2>Окна обслуживания группы</h2>
        <p class="muted">Действуют на все проверки группы, в том числе добавленные позже.</p>
        <MaintenanceWindows :group-id="groupId" :reload-key="checksStore.syncGeneration" :now="now" />
      </section>
    </template>
    <p v-else-if="groupsStore.loading" class="muted">Загрузка…</p>
    <p v-else class="muted">Группа не найдена.</p>
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
h1 {
  margin: 0.5rem 0 0.2rem;
  font-size: 1.4rem;
}
.muted {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
.table-wrap {
  overflow-x: auto;
}
</style>
