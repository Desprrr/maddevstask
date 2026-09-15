export interface Group {
  id: number
  name: string
  created_at: string
  alert_emails: string[]
}

export interface Check {
  id: number
  name: string
  url: string
  group_id: number | null
  interval_seconds: number
  timeout_ms: number
  expected_status_code: number
  expected_body_substring: string | null
  is_paused: boolean
  is_public: boolean
  created_at: string
  updated_at: string
}

export interface CheckResult {
  id: number
  check_id: number
  checked_at: string
  success: boolean
  response_time_ms: number | null
  status_code: number | null
  error: string | null
}

export interface CheckStatus {
  check_id: number
  name: string
  group_id: number | null
  is_paused: boolean
  last_checked_at: string | null
  last_success: boolean | null
  last_response_time_ms: number | null
  is_down: boolean
  current_incident_started_at: string | null
  current_downtime_seconds: number | null
}

export interface Incident {
  id: number
  check_id: number
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
}

export type HistoryRange = 'day' | 'week' | 'month'

export interface HistoryPoint {
  bucket_start: string
  avg_response_time_ms: number | null
  uptime_ratio: number | null
  sample_count: number
}

export interface CheckHistory {
  range: HistoryRange
  points: HistoryPoint[]
  overall_uptime_ratio: number | null
}

export interface MaintenanceWindow {
  id: number
  check_id: number | null
  group_id: number | null
  starts_at: string
  ends_at: string
  note: string | null
}

export interface PublicCheckStatus {
  check_id: number
  name: string
  status: 'up' | 'down'
  last_checked_at: string | null
  current_downtime_seconds: number | null
  uptime_ratio_24h: number | null
}

export interface PublicGroupStatus {
  group_id: number | null
  name: string | null
  status: 'up' | 'down'
  checks: PublicCheckStatus[]
}

export interface PublicStatus {
  groups: PublicGroupStatus[]
}

export interface CheckResultEvent {
  type: 'check.result'
  check_id: number
  group_id: number | null
  success: boolean
  response_time_ms: number | null
  status_code: number | null
  error: string | null
  checked_at: string
}

export interface IncidentWsEvent {
  type: 'incident.opened' | 'incident.closed'
  check_id: number
  group_id: number | null
  incident_id: number
  started_at: string
  ended_at: string | null
}

export interface AdminChangedEvent {
  type: 'admin.changed'
}

export type RealtimeEvent = CheckResultEvent | IncidentWsEvent | AdminChangedEvent
