import { parseBucketStart } from '@/lib/dates'
import { formatMetricValue } from '@/model/adapters/metric'
import type { MetricInterval } from '@/model/types'
import type { InsightSeriesView, InsightSnapshot, NumberDelta, ResolvedRange } from '@/model/views'
import { formatAxisDate } from '@/ui/chart/chartMath'
import { seriesColor } from '@/ui/chart/palette'
import type { ChartPoint, ChartSeries } from '@/ui/chart/types'

import { formatRangeSpan } from './rangePresets'

/** How a tile or a screen shows an insight: a big number, a chart, or a card that opens it on the web. */
export type InsightDisplay = 'number' | 'chart' | 'web'

export function insightDisplay(snapshot: InsightSnapshot): InsightDisplay {
    if (snapshot.kindLabel === 'Big number' && snapshot.capabilities.number) {
        return 'number'
    }
    if (snapshot.capabilities.chart && snapshot.chartKind && snapshot.allSeries.some((s) => s.points.length > 0)) {
        return 'chart'
    }
    return 'web'
}

export function snapshotFormatter(snapshot: Pick<InsightSnapshot, 'format'>): (value: number) => string {
    const { valueFormat, unit } = snapshot.format
    return (value) => formatMetricValue(value, valueFormat, unit)
}

function seriesLabel(series: InsightSeriesView): string {
    const breakdown = series.breakdownValue
    if (breakdown === null || breakdown === '' || series.label.includes(String(breakdown))) {
        return series.label
    }
    return `${series.label} · ${breakdown}`
}

function chartPoints(series: InsightSeriesView, length: number): ChartPoint[] {
    return Array.from({ length }, (_, index) => {
        const point = series.points[index]
        return point ? { at: parseBucketStart(point.at), value: point.value } : { at: Number.NaN, value: Number.NaN }
    })
}

/**
 * The chart's series: every current series in the web's palette order, and each previous-period series paired with
 * its current one. Every series gets the length of the first current series, which the chart requires.
 */
export function snapshotChartSeries(snapshot: InsightSnapshot): ChartSeries[] {
    const current = snapshot.allSeries.filter((series) => series.compare !== 'previous')
    const previous = snapshot.allSeries.filter((series) => series.compare === 'previous')
    const length = current[0]?.points.length ?? 0
    if (length === 0) {
        return []
    }
    const inProgress = snapshot.inProgressFrom
    const incompleteFrom = inProgress ? current[0]?.points.findIndex((point) => point.at === inProgress) : -1
    const result: ChartSeries[] = current.map((series, index) => ({
        key: series.key,
        label: seriesLabel(series),
        color: seriesColor(index),
        points: chartPoints(series, length),
        ...(incompleteFrom !== undefined && incompleteFrom >= 0 ? { incompleteFrom } : {}),
    }))
    for (const series of previous) {
        const partner = current.find(
            (candidate) =>
                candidate.seriesIndex === series.seriesIndex && candidate.breakdownValue === series.breakdownValue
        )
        if (!partner) {
            continue
        }
        result.push({
            key: series.key,
            label: current.length === 1 ? 'Previous period' : `${seriesLabel(partner)}, previous period`,
            color: seriesColor(current.indexOf(partner)),
            points: chartPoints(series, length),
            compareOf: partner.key,
        })
    }
    return result
}

/** The series behind a chart key, for the actors query at a point. */
export function seriesForKey(snapshot: InsightSnapshot, key: string): InsightSeriesView | undefined {
    return snapshot.allSeries.find((series) => series.key === key)
}

const INTERVAL_LABELS: Record<MetricInterval, string> = {
    hour: 'Hourly',
    day: 'Daily',
    week: 'Weekly',
    month: 'Monthly',
}

export function intervalLabel(interval: MetricInterval): string {
    return INTERVAL_LABELS[interval]
}

/** The resolved window as the web writes it, without times unless the buckets are hours. */
export function resolvedRangeText(range: ResolvedRange | null, interval: MetricInterval): string | null {
    if (!range) {
        return null
    }
    if (interval === 'hour') {
        return formatRangeSpan(range.from, range.to)
    }
    return formatRangeSpan(range.from.slice(0, 10), range.to.slice(0, 10))
}

/** The previous period's window, from the dates of a compare series. */
export function previousRangeText(snapshot: InsightSnapshot): string | null {
    const previous = snapshot.allSeries.find((series) => series.compare === 'previous')
    const first = previous?.points[0]?.at
    const last = previous?.points[previous.points.length - 1]?.at
    if (!first || !last) {
        return null
    }
    return snapshot.interval === 'hour'
        ? formatRangeSpan(first, last)
        : formatRangeSpan(first.slice(0, 10), last.slice(0, 10))
}

const MINUS = '−'

function signed(value: number, text: string): string {
    if (value > 0) {
        return `+${text}`
    }
    return value < 0 ? `${MINUS}${text}` : text
}

/** "+12.4%", "−0.6 pts", or the change in the value's own format when the previous value is 0. */
export function deltaText(delta: NumberDelta, formatValue: (value: number) => string): string {
    if (delta.change === 0) {
        return 'No change'
    }
    if (delta.unit === 'points') {
        return signed(delta.change, `${Math.abs(delta.change).toFixed(1)} pts`)
    }
    if (delta.percent === null) {
        return signed(delta.change, formatValue(Math.abs(delta.change)))
    }
    return signed(delta.percent, `${Math.abs(delta.percent).toFixed(1)}%`)
}

/** What the delta compares with: "vs previous period" or "vs Oct 12". */
export function deltaBasisText(delta: NumberDelta, interval: MetricInterval): string {
    if (delta.basis === 'compare' || !delta.previousAt) {
        return 'vs previous period'
    }
    return `vs ${formatAxisDate(parseBucketStart(delta.previousAt), interval)}`
}

/** The caption under a big number: "Compared with Oct 12" or "Compared with the previous period". */
export function deltaComparedText(delta: NumberDelta, interval: MetricInterval): string {
    if (delta.basis === 'compare' || !delta.previousAt) {
        return 'Compared with the previous period'
    }
    return `Compared with ${formatAxisDate(parseBucketStart(delta.previousAt), interval)}`
}

/** The bucket a big number is for, such as "Oct 13", or null for a window total. */
export function valueAtText(snapshot: Pick<InsightSnapshot, 'valueAt' | 'interval'>): string | null {
    return snapshot.valueAt ? formatAxisDate(parseBucketStart(snapshot.valueAt), snapshot.interval) : null
}
