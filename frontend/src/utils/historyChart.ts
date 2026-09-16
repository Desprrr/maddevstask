import type { Plugin } from 'chart.js'
import type { CheckHistory, HistoryRange } from '../types'

export interface XY {
  x: number
  y: number | null
}

export interface TimeSpan {
  start: number
  end: number
}

export interface HistorySeries {
  responseTime: XY[]
  uptimePercent: XY[]
  gaps: TimeSpan[]
  min: number
  max: number
}

const BUCKET_MS: Record<HistoryRange, number> = {
  day: 0, // сырые точки
  week: 3_600_000,
  month: 86_400_000,
}

/** Точки для графика по оси времени.
 *
 * Разрыв (мониторинг не работал) рвёт линию: между соседними точками вставляется
 * `y: null`. Разрывы короче бакета линию не рвут — при часовых бакетах двухминутный
 * рестарт иначе разрезал бы час, в котором данные есть. Их всё равно видно
 * по затенению (`gapShadingPlugin`). */
export function buildHistorySeries(history: CheckHistory): HistorySeries {
  const gaps = history.gaps.map((g) => ({ start: Date.parse(g.start), end: Date.parse(g.end) }))
  const breaks = gaps
    .filter((g) => g.end - g.start >= BUCKET_MS[history.range])
    .map((g) => g.start + (g.end - g.start) / 2)

  const responseTime: XY[] = []
  const uptimePercent: XY[] = []
  let nextBreak = 0
  for (const point of history.points) {
    const x = Date.parse(point.bucket_start)
    while (nextBreak < breaks.length && breaks[nextBreak]! < x) {
      responseTime.push({ x: breaks[nextBreak]!, y: null })
      uptimePercent.push({ x: breaks[nextBreak]!, y: null })
      nextBreak += 1
    }
    responseTime.push({ x, y: point.avg_response_time_ms })
    uptimePercent.push({ x, y: point.uptime_ratio === null ? null : point.uptime_ratio * 100 })
  }

  return {
    responseTime,
    uptimePercent,
    gaps,
    min: Date.parse(history.range_start),
    max: Date.parse(history.range_end),
  }
}

export function formatAxisTick(range: HistoryRange, ms: number): string {
  const date = new Date(ms)
  const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const day = date.toLocaleDateString([], { day: '2-digit', month: '2-digit' })
  if (range === 'day') return time
  if (range === 'week') return `${day} ${time}`
  return day
}

/** Затеняет интервалы, когда мониторинг не работал. Минимум 2px ширины, чтобы
 * короткий рестарт на месячном графике не пропадал совсем. */
export function gapShadingPlugin(getGaps: () => TimeSpan[], color = 'rgba(148, 163, 184, 0.28)'): Plugin<'line'> {
  return {
    id: 'monitoringGaps',
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea } = chart
      const x = chart.scales.x
      if (!x) return
      ctx.save()
      ctx.fillStyle = color
      for (const gap of getGaps()) {
        const left = Math.max(x.getPixelForValue(gap.start), chartArea.left)
        const right = Math.min(x.getPixelForValue(gap.end), chartArea.right)
        if (right < chartArea.left || left > chartArea.right) continue
        const width = Math.max(right - left, 2)
        ctx.fillRect(left, chartArea.top, width, chartArea.bottom - chartArea.top)
      }
      ctx.restore()
    },
  }
}
