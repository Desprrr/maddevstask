<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api/http'
import type { MaintenanceWindow } from '../types'
import { formatDateTime } from '../utils/format'

/** Окна обслуживания одной проверки или целой группы. Окно группы действует на все её
 * проверки. В окне оповещения не отправляются: если падение закончилось внутри окна,
 * писем не будет вовсе, если продолжается после — уйдёт DOWN. */
const props = defineProps<{
  checkId?: number
  groupId?: number
  readonly?: boolean
  /** Смена значения — перезапросить список (admin.changed, переподключение WS). */
  reloadKey?: number
  /** Текущее время (мс) — чтобы подсветить идущее окно. */
  now?: number
}>()

const windows = ref<MaintenanceWindow[]>([])
const error = ref<string | null>(null)
const form = reactive({ starts_at: '', ends_at: '', note: '' })

async function load() {
  if (props.groupId !== undefined) windows.value = await api.maintenanceWindows.listForGroup(props.groupId)
  else if (props.checkId !== undefined) windows.value = await api.maintenanceWindows.listForCheck(props.checkId)
}

watch(() => [props.checkId, props.groupId, props.reloadKey], load, { immediate: true })

function isActive(w: MaintenanceWindow): boolean {
  const now = props.now ?? Date.now()
  return Date.parse(w.starts_at) <= now && now <= Date.parse(w.ends_at)
}

const sorted = computed(() => [...windows.value].sort((a, b) => a.starts_at.localeCompare(b.starts_at)))

async function create() {
  error.value = null
  const startsAt = new Date(form.starts_at)
  const endsAt = new Date(form.ends_at)
  if (Number.isNaN(startsAt.getTime()) || Number.isNaN(endsAt.getTime())) {
    error.value = 'Укажите начало и конец окна.'
    return
  }
  if (endsAt <= startsAt) {
    error.value = 'Конец окна должен быть позже начала.'
    return
  }
  try {
    await api.maintenanceWindows.create({
      check_id: props.groupId === undefined ? (props.checkId ?? null) : null,
      group_id: props.groupId ?? null,
      starts_at: startsAt.toISOString(),
      ends_at: endsAt.toISOString(),
      note: form.note.trim() || null,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    return
  }
  form.starts_at = ''
  form.ends_at = ''
  form.note = ''
  await load()
}

async function remove(id: number) {
  await api.maintenanceWindows.remove(id)
  await load()
}
</script>

<template>
  <div>
    <div v-if="sorted.length" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Начало</th>
            <th>Конец</th>
            <th>Заметка</th>
            <th v-if="!readonly"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in sorted" :key="w.id" :class="{ active: isActive(w) }">
            <td>{{ formatDateTime(w.starts_at) }}</td>
            <td>
              {{ formatDateTime(w.ends_at) }}
              <span v-if="isActive(w)" class="active-label">идёт сейчас</span>
            </td>
            <td>{{ w.note || '—' }}</td>
            <td v-if="!readonly"><button class="danger" @click="remove(w.id)">Удалить</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="muted">Окон обслуживания нет.</p>

    <form v-if="!readonly" class="inline-form" @submit.prevent="create">
      <label>Начало <input v-model="form.starts_at" type="datetime-local" name="starts_at" /></label>
      <label>Конец <input v-model="form.ends_at" type="datetime-local" name="ends_at" /></label>
      <input v-model="form.note" name="note" placeholder="Заметка (опц.)" style="width: 14rem" />
      <button type="submit" class="primary">Добавить окно</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<style scoped>
.muted {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}
.error {
  color: var(--color-down);
  font-size: 0.85rem;
}
.table-wrap {
  overflow-x: auto;
}
.active-label {
  margin-left: 0.4rem;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
tr.active td {
  font-weight: 600;
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
