import type {
  Check,
  CheckHistory,
  CheckResult,
  CheckStatus,
  Group,
  HistoryRange,
  Incident,
  MaintenanceWindow,
  PublicStatus,
} from '../types'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  body: string

  constructor(status: number, body: string) {
    super(`API error ${status}: ${body}`)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
  })
  if (!response.ok) {
    const body = await response.text()
    throw new ApiError(response.status, body)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export interface GroupCreatePayload {
  name: string
  alert_emails?: string[]
}

export interface GroupUpdatePayload {
  name?: string
  alert_emails?: string[]
}

export interface CheckCreatePayload {
  name: string
  url: string
  group_id?: number | null
  interval_seconds?: number
  timeout_ms?: number
  expected_status_code?: number
  expected_body_substring?: string | null
  is_public?: boolean
}

export type CheckUpdatePayload = Partial<CheckCreatePayload>

export interface MaintenanceWindowCreatePayload {
  check_id?: number | null
  group_id?: number | null
  starts_at: string
  ends_at: string
  note?: string | null
}

export const api = {
  groups: {
    list: () => request<Group[]>('/groups'),
    create: (data: GroupCreatePayload) =>
      request<Group>('/groups', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: GroupUpdatePayload) =>
      request<Group>(`/groups/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    remove: (id: number) => request<void>(`/groups/${id}`, { method: 'DELETE' }),
  },
  checks: {
    list: (groupId?: number) =>
      request<Check[]>(`/checks${groupId !== undefined ? `?group_id=${groupId}` : ''}`),
    status: () => request<CheckStatus[]>('/checks/status'),
    get: (id: number) => request<Check>(`/checks/${id}`),
    create: (data: CheckCreatePayload) =>
      request<Check>('/checks', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: CheckUpdatePayload) =>
      request<Check>(`/checks/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    remove: (id: number) => request<void>(`/checks/${id}`, { method: 'DELETE' }),
    pause: (id: number) => request<Check>(`/checks/${id}/pause`, { method: 'POST' }),
    resume: (id: number) => request<Check>(`/checks/${id}/resume`, { method: 'POST' }),
    runNow: (id: number) => request<CheckResult>(`/checks/${id}/run-now`, { method: 'POST' }),
    history: (id: number, range: HistoryRange) =>
      request<CheckHistory>(`/checks/${id}/history?range=${range}`),
    incidents: (id: number) => request<Incident[]>(`/checks/${id}/incidents`),
  },
  maintenanceWindows: {
    listForCheck: (checkId: number) =>
      request<MaintenanceWindow[]>(`/maintenance-windows?check_id=${checkId}`),
    listForGroup: (groupId: number) =>
      request<MaintenanceWindow[]>(`/maintenance-windows?group_id=${groupId}`),
    create: (data: MaintenanceWindowCreatePayload) =>
      request<MaintenanceWindow>('/maintenance-windows', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    remove: (id: number) => request<void>(`/maintenance-windows/${id}`, { method: 'DELETE' }),
  },
  public: {
    status: () => request<PublicStatus>('/public/status'),
  },
}
