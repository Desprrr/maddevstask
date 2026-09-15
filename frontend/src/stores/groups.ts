import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type GroupCreatePayload, type GroupUpdatePayload } from '../api/http'
import type { Group } from '../types'

export const useGroupsStore = defineStore('groups', () => {
  const groups = ref<Group[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      groups.value = await api.groups.list()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function create(payload: GroupCreatePayload) {
    const created = await api.groups.create(payload)
    groups.value.push(created)
    return created
  }

  async function update(id: number, payload: GroupUpdatePayload) {
    const updated = await api.groups.update(id, payload)
    const idx = groups.value.findIndex((g) => g.id === id)
    if (idx !== -1) groups.value[idx] = updated
    return updated
  }

  async function remove(id: number) {
    await api.groups.remove(id)
    groups.value = groups.value.filter((g) => g.id !== id)
  }

  return { groups, loading, error, fetchAll, create, update, remove }
})
