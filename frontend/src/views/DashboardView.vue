<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import StatusBadge from '../components/StatusBadge.vue'
import { useNow } from '../composables/useNow'
import { useChecksStore } from '../stores/checks'
import { useGroupsStore } from '../stores/groups'
import type { Check } from '../types'
import { formatDateTime, formatDuration, formatMs } from '../utils/format'

const checksStore = useChecksStore()
const groupsStore = useGroupsStore()
const now = useNow()

onMounted(async () => {
  await Promise.all([groupsStore.fetchAll(), checksStore.fetchAll()])
  checksStore.startRealtime()
})
onUnmounted(() => checksStore.stopRealtime())

// --- группы ---
const newGroupName = ref('')
const newGroupEmails = ref('')

function splitEmails(value: string): string[] {
  return value
    .split(',')
    .map((e) => e.trim())
    .filter(Boolean)
}

async function createGroup() {
  if (!newGroupName.value.trim()) return
  await groupsStore.create({ name: newGroupName.value.trim(), alert_emails: splitEmails(newGroupEmails.value) })
  newGroupName.value = ''
  newGroupEmails.value = ''
}

async function deleteGroup(id: number) {
  if (!confirm('Удалить группу? Чеки внутри останутся, но станут без группы.')) return
  await groupsStore.remove(id)
  await checksStore.fetchAll()
}

const editingGroupId = ref<number | null>(null)
const editingEmails = ref('')

function startEditEmails(groupId: number, currentEmails: string[]) {
  editingGroupId.value = groupId
  editingEmails.value = currentEmails.join(', ')
}

async function saveEmails() {
  if (editingGroupId.value === null) return
  await groupsStore.update(editingGroupId.value, { alert_emails: splitEmails(editingEmails.value) })
  editingGroupId.value = null
}

// --- чеки ---
const checkForm = reactive({
  name: '',
  url: '',
  group_id: '' as number | '',
  interval_seconds: 60,
  timeout_ms: 5000,
  expected_status_code: 200,
  expected_body_substring: '',
  is_public: false,
})

async function createCheck() {
  if (!checkForm.name.trim() || !checkForm.url.trim()) return
  await checksStore.create({
    name: checkForm.name.trim(),
    url: checkForm.url.trim(),
    group_id: checkForm.group_id === '' ? null : Number(checkForm.group_id),
    interval_seconds: checkForm.interval_seconds,
    timeout_ms: checkForm.timeout_ms,
    expected_status_code: checkForm.expected_status_code,
    expected_body_substring: checkForm.expected_body_substring.trim() || null,
    is_public: checkForm.is_public,
  })
  checkForm.name = ''
  checkForm.url = ''
  checkForm.group_id = ''
  checkForm.interval_seconds = 60
  checkForm.timeout_ms = 5000
  checkForm.expected_status_code = 200
  checkForm.expected_body_substring = ''
  checkForm.is_public = false
}

async function togglePause(check: Check) {
  if (check.is_paused) await checksStore.resume(check.id)
  else await checksStore.pause(check.id)
}

async function removeCheck(id: number) {
  if (!confirm('Удалить проверку?')) return
  await checksStore.remove(id)
}

const runningNow = ref<Set<number>>(new Set())
async function runNow(id: number) {
  runningNow.value.add(id)
  try {
    await checksStore.runNow(id)
  } finally {
    runningNow.value.delete(id)
  }
}

// --- группировка для отображения ---
interface Section {
  groupId: number | null
  name: string
  emails: string[]
  checks: Check[]
}

const sections = computed<Section[]>(() => {
  const byGroup = new Map<number | null, Check[]>()
  for (const check of checksStore.checks) {
    const key = check.group_id
    if (!byGroup.has(key)) byGroup.set(key, [])
    byGroup.get(key)!.push(check)
  }

  const result: Section[] = groupsStore.groups.map((g) => ({
    groupId: g.id,
    name: g.name,
    emails: g.alert_emails,
    checks: byGroup.get(g.id) ?? [],
  }))

  const ungrouped = byGroup.get(null) ?? []
  if (ungrouped.length > 0) {
    result.push({ groupId: null, name: 'Без группы', emails: [], checks: ungrouped })
  }
  return result
})

function statusKind(check: Check): 'up' | 'down' | 'paused' {
  if (check.is_paused) return 'paused'
  const status = checksStore.statuses[check.id]
  return status?.is_down ? 'down' : 'up'
}

/** Общий статус группы: "down", если упал хотя бы один её чек (пауза не
 * считается падением) — то же правило, что и на публичной странице. */
function groupStatus(checks: Check[]): 'up' | 'down' {
  return checks.some((c) => statusKind(c) === 'down') ? 'down' : 'up'
}

function liveDowntime(check: Check): number | null {
  const status = checksStore.statuses[check.id]
  if (!status?.current_incident_started_at) return null
  return (now.value - new Date(status.current_incident_started_at).getTime()) / 1000
}
</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>Монитор доступности сайтов</h1>
      <RouterLink to="/status" target="_blank">Публичная страница статуса →</RouterLink>
    </header>

    <section class="card">
      <h2>Группы</h2>
      <table v-if="groupsStore.groups.length">
        <thead>
          <tr>
            <th>Название</th>
            <th>Адреса оповещений</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="g in groupsStore.groups" :key="g.id">
            <td><RouterLink :to="`/groups/${g.id}`">{{ g.name }}</RouterLink></td>
            <td>
              <template v-if="editingGroupId === g.id">
                <input v-model="editingEmails" placeholder="a@x.com, b@y.com" style="width: 16rem" />
                <button @click="saveEmails">Сохранить</button>
              </template>
              <template v-else>
                {{ g.alert_emails.join(', ') || '—' }}
                <button @click="startEditEmails(g.id, g.alert_emails)">Изменить</button>
              </template>
            </td>
            <td><button class="danger" @click="deleteGroup(g.id)">Удалить</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">Групп пока нет.</p>

      <form class="inline-form" @submit.prevent="createGroup">
        <input v-model="newGroupName" placeholder="Название группы" required />
        <input v-model="newGroupEmails" placeholder="Адреса оповещений через запятую" style="width: 18rem" />
        <button type="submit" class="primary">Добавить группу</button>
      </form>
    </section>

    <section class="card">
      <h2>Добавить проверку</h2>
      <form class="check-form" @submit.prevent="createCheck">
        <input v-model="checkForm.name" placeholder="Название" required />
        <input v-model="checkForm.url" placeholder="https://example.com" required style="width: 20rem" />
        <select v-model="checkForm.group_id">
          <option value="">Без группы</option>
          <option v-for="g in groupsStore.groups" :key="g.id" :value="g.id">{{ g.name }}</option>
        </select>
        <label>Интервал (сек) <input v-model.number="checkForm.interval_seconds" type="number" min="30" max="3600" style="width: 5rem" /></label>
        <label>Таймаут (мс) <input v-model.number="checkForm.timeout_ms" type="number" min="1" style="width: 5rem" /></label>
        <label>Ожид. код <input v-model.number="checkForm.expected_status_code" type="number" style="width: 4rem" /></label>
        <input v-model="checkForm.expected_body_substring" placeholder="Ожидаемая строка в теле (опц.)" style="width: 14rem" />
        <label><input v-model="checkForm.is_public" type="checkbox" /> Публично</label>
        <button type="submit" class="primary">Добавить</button>
      </form>
    </section>

    <p v-if="checksStore.error" class="error">{{ checksStore.error }}</p>

    <section v-for="section in sections" :key="section.groupId ?? 'none'" class="card">
      <div class="card-header">
        <h2>
          <RouterLink v-if="section.groupId !== null" :to="`/groups/${section.groupId}`">{{ section.name }}</RouterLink>
          <template v-else>{{ section.name }}</template>
        </h2>
        <StatusBadge v-if="section.checks.length" :status="groupStatus(section.checks)" />
      </div>
      <div v-if="section.checks.length" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Название</th>
            <th>URL</th>
            <th>Статус</th>
            <th>Ответ</th>
            <th>Проверено</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="check in section.checks" :key="check.id">
            <td><RouterLink :to="`/checks/${check.id}`">{{ check.name }}</RouterLink></td>
            <td class="muted">{{ check.url }}</td>
            <td>
              <StatusBadge :status="statusKind(check)" />
              <span v-if="statusKind(check) === 'down'" class="muted">
                &nbsp;{{ formatDuration(liveDowntime(check)) }}
              </span>
            </td>
            <td>{{ formatMs(checksStore.statuses[check.id]?.last_response_time_ms) }}</td>
            <td>{{ formatDateTime(checksStore.statuses[check.id]?.last_checked_at) }}</td>
            <td class="actions">
              <button @click="togglePause(check)">{{ check.is_paused ? 'Возобновить' : 'Пауза' }}</button>
              <button :disabled="runningNow.has(check.id)" @click="runNow(check.id)">Проверить сейчас</button>
              <button class="danger" @click="removeCheck(check.id)">Удалить</button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <p v-else class="muted">В этой группе пока нет проверок.</p>
    </section>
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
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}
.page-header h1 {
  font-size: 1.4rem;
  margin: 0;
}
.card h2 {
  margin: 0 0 0.75rem;
  font-size: 1.05rem;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-header h2 {
  margin: 0;
}
.inline-form,
.check-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-top: 0.75rem;
}
.check-form label {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.85rem;
  color: var(--color-text-muted);
}
.muted {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
.actions {
  display: flex;
  gap: 0.4rem;
}
.error {
  color: var(--color-down);
}
.table-wrap {
  overflow-x: auto;
}
</style>
