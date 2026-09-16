import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/http'
import type { MaintenanceWindow } from '../types'
import MaintenanceWindows from './MaintenanceWindows.vue'

function win(overrides: Partial<MaintenanceWindow> = {}): MaintenanceWindow {
  return {
    id: 1,
    check_id: null,
    group_id: 5,
    starts_at: '2026-01-01T10:00:00Z',
    ends_at: '2026-01-01T12:00:00Z',
    note: 'релиз',
    ...overrides,
  }
}

describe('MaintenanceWindows', () => {
  afterEach(() => vi.restoreAllMocks())

  it('creates a window for the whole group', async () => {
    vi.spyOn(api.maintenanceWindows, 'listForGroup').mockResolvedValueOnce([]).mockResolvedValue([win()])
    const create = vi.spyOn(api.maintenanceWindows, 'create').mockResolvedValue(win())
    const wrapper = mount(MaintenanceWindows, { props: { groupId: 5 } })
    await flushPromises()
    expect(wrapper.text()).toContain('Окон обслуживания нет')

    await wrapper.find('input[name="starts_at"]').setValue('2026-01-01T10:00')
    await wrapper.find('input[name="ends_at"]').setValue('2026-01-01T12:00')
    await wrapper.find('input[name="note"]').setValue(' релиз ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(create).toHaveBeenCalledExactlyOnceWith({
      check_id: null,
      group_id: 5,
      starts_at: new Date('2026-01-01T10:00').toISOString(),
      ends_at: new Date('2026-01-01T12:00').toISOString(),
      note: 'релиз',
    })
    expect(wrapper.text()).toContain('релиз')
  })

  it('rejects a window that ends before it starts without calling the API', async () => {
    vi.spyOn(api.maintenanceWindows, 'listForCheck').mockResolvedValue([])
    const create = vi.spyOn(api.maintenanceWindows, 'create')
    const wrapper = mount(MaintenanceWindows, { props: { checkId: 3 } })
    await flushPromises()

    await wrapper.find('input[name="starts_at"]').setValue('2026-01-01T12:00')
    await wrapper.find('input[name="ends_at"]').setValue('2026-01-01T10:00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(create).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('позже начала')
  })

  it('readonly mode lists windows without editing controls and reloads on reloadKey change', async () => {
    const list = vi.spyOn(api.maintenanceWindows, 'listForGroup').mockResolvedValue([win()])
    const wrapper = mount(MaintenanceWindows, {
      props: { groupId: 5, readonly: true, reloadKey: 0, now: Date.parse('2026-01-01T11:00:00Z') },
    })
    await flushPromises()

    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).toContain('идёт сейчас')

    await wrapper.setProps({ reloadKey: 1 })
    await flushPromises()
    expect(list).toHaveBeenCalledTimes(2)
  })
})
