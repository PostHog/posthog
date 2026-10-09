import { calendarDaysBetween, formatClock, formatMonthDay, weekdayName } from '@/lib/dates'
import { asRecord } from '@/lib/records'

import type { Metric, MetricBar } from '../types'
import { groupThousands } from './text'

export const MAX_BARS = 14

/** A bar is hot when it is further than this share of the series' spread from the baseline. */
const DEPARTURE_SHARE = 0.15

/** A tail this long back at the baseline means the problem ended, so the tail is cold. */
const RECOVERY_RUN = 2

export interface MetricInput {
    title: string
    role: string
    value: number | null
    series: number[] | null
    value_format: string
    unit: string | null
    caption: string | null
    query?: unknown
}

export function downsample(series: readonly number[], max: number = MAX_BARS): number[] {
    const values = series.filter((value) => Number.isFinite(value))
    if (values.length <= max) {
        return values
    }
    const buckets: number[] = []
    for (let bucket = 0; bucket < max; bucket++) {
        const start = Math.floor((bucket * values.length) / max)
        const end = Math.floor(((bucket + 1) * values.length) / max)
        const slice = values.slice(start, end)
        buckets.push(slice.reduce((sum, value) => sum + value, 0) / slice.length)
    }
    return buckets
}

function median(values: readonly number[]): number {
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 === 1 ? (sorted[middle] ?? 0) : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2
}

export function hotBars(values: readonly number[]): boolean[] {
    const hot = values.map(() => false)
    if (values.length < 2) {
        return hot
    }
    const baseline = median(values.slice(0, Math.max(1, Math.floor(values.length / 4))))
    const spread = Math.max(...values) - Math.min(...values)
    if (!(spread > 0)) {
        return hot
    }
    const departs = (value: number): boolean => Math.abs(value - baseline) > spread * DEPARTURE_SHARE
    const first = values.findIndex(departs)
    if (first === -1) {
        return hot
    }
    let end = values.length
    let run = 0
    for (let index = values.length - 1; index > first && !departs(values[index] ?? baseline); index--) {
        run++
    }
    if (run >= RECOVERY_RUN) {
        end = values.length - run
    }
    return hot.map((_, index) => index >= first && index < end)
}

export function metricBars(series: readonly number[]): MetricBar[] {
    const values = downsample(series)
    const hot = hotBars(values)
    return values.map((value, index) => ({ value, hot: hot[index] ?? false }))
}

const CURRENCY_SYMBOLS: Record<string, string> = { USD: '$', EUR: '€', GBP: '£' }

function compactAmount(value: number): string {
    const size = Math.abs(value)
    if (size >= 1_000_000) {
        return `${groupThousands(value / 1_000_000, 1)}M`
    }
    if (size >= 10_000) {
        return `${groupThousands(value / 1_000, 0)}k`
    }
    return groupThousands(value, 2)
}

export function formatMetricValue(value: number, format: string, unit: string | null): string {
    switch (format) {
        case 'percentage':
            return `${groupThousands(value, 1)}%`
        case 'percentage_scaled':
            return `${groupThousands(value * 100, 1)}%`
        case 'duration': {
            const seconds = unit === 'ms' ? value / 1000 : value
            if (unit === 'ms' && value < 1000) {
                return `${groupThousands(value)} ms`
            }
            return seconds >= 60 ? `${groupThousands(seconds / 60, 1)} min` : `${groupThousands(seconds, 1)}s`
        }
        case 'currency': {
            const code = (unit ?? '').toUpperCase()
            const symbol = CURRENCY_SYMBOLS[code]
            return symbol ? `${symbol}${compactAmount(value)}` : `${compactAmount(value)}${code ? ` ${code}` : ''}`
        }
        default: {
            const number = groupThousands(value, Number.isInteger(value) ? 0 : 1)
            return unit ? `${number} ${unit}` : number
        }
    }
}

const RELATIVE_DATE = /^-(\d+)([hdwmy])$/
const UNIT_MS: Record<string, number> = {
    h: 3_600_000,
    d: 86_400_000,
    w: 7 * 86_400_000,
    m: 30 * 86_400_000,
    y: 365 * 86_400_000,
}
const INTERVAL_MS: Record<string, number> = {
    hour: UNIT_MS.h ?? 0,
    day: UNIT_MS.d ?? 0,
    week: UNIT_MS.w ?? 0,
    month: UNIT_MS.m ?? 0,
}

export function metricWindowStart(query: unknown, points: number, now: Date): Date | null {
    const node = asRecord(query)
    const source = asRecord(node?.source) ?? node
    const dateFrom = asRecord(source?.dateRange)?.date_from
    const relative = typeof dateFrom === 'string' ? RELATIVE_DATE.exec(dateFrom) : null
    if (relative?.[1] && relative[2]) {
        return new Date(now.getTime() - Number(relative[1]) * (UNIT_MS[relative[2]] ?? 0))
    }
    const interval = typeof source?.interval === 'string' ? INTERVAL_MS[source.interval] : undefined
    if (interval && points > 1) {
        return new Date(now.getTime() - (points - 1) * interval)
    }
    return null
}

export function metricRange(start: Date | null, now: Date): string {
    if (!start) {
        return ''
    }
    const days = calendarDaysBetween(start, now)
    const label = days <= 0 ? formatClock(start) : days < 7 ? weekdayName(start) : formatMonthDay(start)
    return `${label} → now`
}

export function metricView(metrics: readonly MetricInput[], now: Date): Metric | undefined {
    const primary = metrics.find((metric) => metric.role === 'primary' && (metric.series?.length ?? 0) > 0)
    if (!primary?.series) {
        return undefined
    }
    const bars = metricBars(primary.series)
    if (bars.length === 0) {
        return undefined
    }
    return {
        label: primary.title.toUpperCase(),
        range: metricRange(metricWindowStart(primary.query, primary.series.length, now), now),
        max: Math.max(...bars.map((bar) => bar.value)),
        bars,
    }
}

export function primaryMetric<T extends MetricInput>(metrics: readonly T[]): T | undefined {
    return metrics.find((metric) => metric.role === 'primary' && metric.value !== null)
}
