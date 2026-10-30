import { parseBucketStart } from '@/lib/dates'
import { breakdownLabel, isRankingQuery } from '@/model/adapters/breakdown'
import { isDrawableFunnel } from '@/model/adapters/funnel'
import { formatInsightValue } from '@/model/adapters/insightFormatting'
import { capabilitiesOf, kindLabelOf, queryKindOf } from '@/model/adapters/insightSnapshot'
import { asTrendsInsight, timeSeriesChartKind } from '@/model/adapters/metric'
import { isDrawableRetention } from '@/model/adapters/retention'
import { sqlQueryDisplay, sqlResultDisplay } from '@/model/adapters/sqlVisualization'
import type { MetricInterval } from '@/model/types'
import type { InsightSeriesView, InsightSnapshot, NumberDelta, ResolvedRange } from '@/model/views'
import { formatAxisDate } from '@/ui/chart/chartMath'
import { seriesColor } from '@/ui/chart/palette'
import type { ChartPoint, ChartSeries } from '@/ui/chart/types'

import { hasGoodValue } from './freshness'
import { formatRangeSpan, rangeLabel } from './rangePresets'

/**
 * How a tile or a screen shows an insight: a big number, a line or bar chart, funnel steps, a retention grid, ranked
 * bars, the rows of a SQL result, or a card that opens it on the web.
 */
export type InsightDisplay = 'number' | 'chart' | 'funnel' | 'retention' | 'bars' | 'table' | 'web'

/**
 * The display of a saved query, before any result: a tile keeps one display while it loads, and a dashboard pass
 * knows which tiles the phone cannot draw. A SQL insight on Auto is a table until its result says more.
 */
export function queryDisplay(query: unknown): InsightDisplay {
    if (kindLabelOf(query) === 'Big number' && capabilitiesOf(query).number) {
        return 'number'
    }
    if (queryKindOf(query) === 'HogQLQuery') {
        return sqlQueryDisplay(query)
    }
    if (isDrawableFunnel(query)) {
        return 'funnel'
    }
    if (isDrawableRetention(query)) {
        return 'retention'
    }
    if (isRankingQuery(query)) {
        return 'bars'
    }
    if (timeSeriesChartKind(asTrendsInsight(query))) {
        return 'chart'
    }
    return 'web'
}

export function insightDisplay(snapshot: InsightSnapshot): InsightDisplay {
    // The result settles a SQL display: Auto resolves on its columns, and a chart needs a date x axis.
    if (snapshot.sqlTable) {
        return sqlResultDisplay(snapshot.query, snapshot.sqlTable)
    }
    const display = queryDisplay(snapshot.query)
    // The adapters return null for a result they cannot draw, such as retention rows with breakdown values. That is
    // a kind for the web, not an empty range.
    const rejected = (display === 'funnel' && !snapshot.funnel) || (display === 'retention' && !snapshot.retention)
    return rejected && hasGoodValue(snapshot) ? 'web' : display
}

/**
 * `pending`: no result yet, such as a tile that the dashboard's cache-only read found without a cache. `empty`: a
 * result with nothing to draw for the range. The web card needs no result, so it is always `ready`.
 */
export type InsightRenderState = 'pending' | 'empty' | 'ready'

export function insightRenderState(snapshot: InsightSnapshot): InsightRenderState {
    const display = insightDisplay(snapshot)
    if (display === 'web') {
        return 'ready'
    }
    if (!hasGoodValue(snapshot)) {
        return 'pending'
    }
    const empty = {
        number: snapshot.value === null,
        chart: !snapshot.allSeries.some((series) => series.points.length > 0),
        funnel: !snapshot.funnel?.steps.length,
        retention: !snapshot.retention?.cohorts.length,
        bars: !snapshot.ranking?.rows.length,
        table: !snapshot.sqlTable?.rows.length,
    }[display]
    return empty ? 'empty' : 'ready'
}

/** The line in a chart's place when its result has nothing to draw. A SQL result names its rows. */
export function noDataText(snapshot: Pick<InsightSnapshot, 'resolvedRange' | 'sqlTable'>): string {
    const noun = snapshot.sqlTable ? 'rows' : 'data'
    return snapshot.resolvedRange ? `No ${noun} for this range` : `No ${noun}`
}

export function snapshotFormatter(snapshot: Pick<InsightSnapshot, 'format'>): (value: number) => string {
    return (value) => formatInsightValue(value, snapshot.format)
}

function seriesLabel(series: InsightSeriesView): string {
    const breakdown = breakdownLabel(series.breakdownValue)
    if (breakdown === null || breakdown === '' || series.label.includes(breakdown)) {
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
 * its current one. Every series gets the length of the first current series, which the chart requires. `palette` is the
 * theme's `chartPalette`.
 */
export function snapshotChartSeries(snapshot: InsightSnapshot, palette: readonly string[]): ChartSeries[] {
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
        color: seriesColor(index, palette),
        points: chartPoints(series, length),
        ...(incompleteFrom !== undefined && incompleteFrom >= 0 ? { incompleteFrom } : {}),
    }))
    for (const series of previous) {
        const partner = current.find(
            (candidate) =>
                candidate.seriesIndex === series.seriesIndex &&
                JSON.stringify(candidate.breakdownValue) === JSON.stringify(series.breakdownValue)
        )
        if (!partner) {
            continue
        }
        result.push({
            key: series.key,
            label: current.length === 1 ? 'Previous period' : `${seriesLabel(partner)}, previous period`,
            color: seriesColor(current.indexOf(partner), palette),
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

export function pinRangeLabel(snapshot: InsightSnapshot): string | null {
    return snapshot.usesOwnRange
        ? (resolvedRangeText(snapshot.resolvedRange, snapshot.interval) ?? 'Uses its own range')
        : rangeLabel(null, snapshot.savedRange)
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
