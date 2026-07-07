import type {
    GoalLineConfig,
    Series,
    TimeSeriesBarChartConfig,
    TimeSeriesLineChartConfig,
    TooltipConfig,
    TrendLineConfig,
    YAxisConfig,
} from '@posthog/quill-charts'

import { schemaGoalLinesToConfigs } from 'products/product_analytics/frontend/insights/trends/shared/goalLinesAdapter'
import type { GoalLineLike } from 'products/product_analytics/frontend/insights/trends/shared/trendsChartDisplayOptions'

// Dependency-neutral shape both the kea `RetentionTrendPayload` and lighter fixtures (e.g. the MCP
// UI app) satisfy. Declared structurally rather than imported from `scenes/retention/types` so this
// module stays free of `~/`/`scenes/` deps and compiles in the MCP Vite bundle, which only resolves
// `products/*` and `@posthog/*`. The real `RetentionTrendPayload` is assignable to this (asserted in
// retentionChartTransforms.test.ts), so web callers pass it unchanged.
export interface RetentionResultLike {
    count: number
    data: number[]
    days?: string[]
    labels?: string[]
    index?: number
    breakdown_value?: string | number | null
}

// `retentionGraphLogic.trendSeries` spreads `cohortRetention` onto each entry, so the
// runtime shape includes a cohort `label` field that the declared type doesn't list.
export type RetentionTrendSeriesEntry = RetentionResultLike & { label?: string }

export interface RetentionSeriesMeta {
    /** Original row index from the unfiltered results — drives modal opens in non-interval view. */
    rowIndex: number
    /** Same as rowIndex; read by InsightSeriesTooltip (meta.order ?? idx), where the narrowed
     *  grouped-bar row list makes the positional idx fallback point at the wrong cohort. */
    order: number
    breakdown_value?: string | number | null
    days?: string[]
    cohortLabel?: string
    cohortCount: number
}

export interface BuildRetentionSeriesOpts {
    /** Negative — index from the end where the in-progress tail begins. Omit to skip. */
    incompletenessOffsetFromEnd?: number
    /** True when an interval is selected (x-axis is cohorts, not interval offsets).
     *  In this layout the partial-stroke "in-progress" segment doesn't apply per-series. */
    isIntervalView: boolean
}

export function buildRetentionSeries(
    seriesPayloads: RetentionTrendSeriesEntry[],
    opts: BuildRetentionSeriesOpts
): Series<RetentionSeriesMeta>[] {
    const { incompletenessOffsetFromEnd, isIntervalView } = opts
    return seriesPayloads.map((s, i) => {
        const rowIndex = s.index ?? i
        const dataLength = s.data.length
        const isInProgress =
            !isIntervalView && incompletenessOffsetFromEnd !== undefined && incompletenessOffsetFromEnd < 0
        const dashedFromIndex = isInProgress ? dataLength + (incompletenessOffsetFromEnd as number) : undefined

        const breakdown = s.breakdown_value != null && s.breakdown_value !== '' ? String(s.breakdown_value) : null
        // `label` is the cohort date in normal view; absent in interval view (use breakdown instead).
        const label = breakdown ?? s.label ?? `Cohort ${rowIndex}`

        return {
            key: `retention-${rowIndex}`,
            label,
            data: s.data,
            meta: {
                rowIndex,
                order: rowIndex,
                breakdown_value: s.breakdown_value,
                days: s.days,
                cohortLabel: s.label,
                cohortCount: s.count,
            },
            stroke: dashedFromIndex !== undefined ? { partial: { fromIndex: dashedFromIndex } } : undefined,
        }
    })
}

export interface BuildRetentionChartConfigOpts {
    isPercentage: boolean
    goalLines?: GoalLineLike[] | null
    showTrendLines?: boolean
    series: Series<RetentionSeriesMeta>[]
    tooltip?: TooltipConfig
}

function buildTrendLines(
    series: Series<RetentionSeriesMeta>[],
    enabled: boolean | undefined
): TrendLineConfig[] | undefined {
    if (!enabled || series.length === 0) {
        return undefined
    }
    return series.map((s) => ({ seriesKey: s.key, kind: 'linear' }))
}

function buildGoalLines(goalLines: GoalLineLike[] | null | undefined): GoalLineConfig[] | undefined {
    return schemaGoalLinesToConfigs(goalLines)
}

export function buildRetentionLineChartConfig(opts: BuildRetentionChartConfigOpts): TimeSeriesLineChartConfig {
    return {
        yAxis: {
            format: opts.isPercentage ? 'percentage' : 'numeric',
            scale: 'linear',
            showGrid: true,
        },
        goalLines: buildGoalLines(opts.goalLines),
        trendLines: buildTrendLines(opts.series, opts.showTrendLines),
        tooltip: opts.tooltip,
    }
}

export function buildRetentionBarChartConfig(
    opts: BuildRetentionChartConfigOpts
): TimeSeriesBarChartConfig & { yAxis?: YAxisConfig } {
    return {
        yAxis: {
            format: opts.isPercentage ? 'percentage' : 'numeric',
            scale: 'linear',
            showGrid: true,
        },
        // Bars side-by-side so the retention trend per cohort stays distinguishable.
        barLayout: 'grouped',
        goalLines: buildGoalLines(opts.goalLines),
        tooltip: opts.tooltip,
    }
}

// --- Cohort shaping ----------------------------------------------------------------------------
// Turns a raw retention query result into chart entries. Lives here (not in the MCP host) so the
// cohort math is unit-tested. Structural/neutral so it stays MCP-bundle-safe.

/** Structural cohort shape the MCP `RetentionResultItem` satisfies. */
export interface RetentionCohortLike {
    date?: string | null
    breakdown_value?: string | number | null
    values: { count: number; aggregation_value?: number | null }[]
}

function formatCohortStartDate(date: string | null | undefined, period: string): string | null {
    if (!date) {
        return null
    }
    const d = new Date(date)
    if (Number.isNaN(d.getTime())) {
        return null
    }
    if (period === 'Hour') {
        return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric' })
    }
    if (period === 'Month') {
        return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    }
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatRetentionCohortLabel(cohort: RetentionCohortLike, cohortNumber: number, period: string): string {
    const startDate = formatCohortStartDate(cohort.date, period)
    const breakdown =
        cohort.breakdown_value !== undefined && cohort.breakdown_value !== null && cohort.breakdown_value !== ''
            ? String(cohort.breakdown_value)
            : null
    const base = `Cohort ${cohortNumber}`
    if (breakdown) {
        return startDate ? `${base} (${breakdown}, ${startDate})` : `${base} (${breakdown})`
    }
    return startDate ? `${base} (${startDate})` : base
}

/** Mirrors retentionLogic: `count` aggregation → percentage of the reference cohort size
 *  (`total` = interval 0, `previous` = preceding interval); other aggregations surface
 *  `aggregation_value` directly. */
export function computeRetentionSeriesValue(
    values: RetentionCohortLike['values'],
    intervalIndex: number,
    aggregationType: string,
    reference: string
): number {
    const current = values[intervalIndex]
    if (!current) {
        return 0
    }
    if (aggregationType !== 'count') {
        return current.aggregation_value ?? 0
    }
    if (reference === 'previous') {
        if (intervalIndex === 0) {
            // referenceCount at interval 0 is the cohort's own size, so an empty cohort is 0%, not
            // 100% — mirrors retentionLogic's `referenceCount > 0 ? ... : 0`.
            return current.count > 0 ? 100 : 0
        }
        const prev = values[intervalIndex - 1]
        if (!prev || prev.count === 0) {
            return 0
        }
        return (current.count / prev.count) * 100
    }
    const baseline = values[0]?.count ?? 0
    if (baseline === 0) {
        return 0
    }
    return (current.count / baseline) * 100
}

/** Sorts cohorts chronologically; cohorts with a missing/invalid date keep their order at the end. */
export function sortRetentionCohorts<C extends RetentionCohortLike>(cohorts: C[]): C[] {
    return [...cohorts].sort((a, b) => {
        const ta = a.date ? new Date(a.date).getTime() : Number.POSITIVE_INFINITY
        const tb = b.date ? new Date(b.date).getTime() : Number.POSITIVE_INFINITY
        const aMissing = Number.isNaN(ta) || !Number.isFinite(ta)
        const bMissing = Number.isNaN(tb) || !Number.isFinite(tb)
        if (aMissing && bMissing) {
            return 0
        }
        if (aMissing) {
            return 1
        }
        if (bMissing) {
            return -1
        }
        return ta - tb
    })
}

// Known retention aggregations (`RetentionAggregationType`): 'count' (unique users, shown as a
// percentage), 'sum', and 'avg'. Any future/unknown aggregation falls back to 'Avg' rather than
// throwing — keep this in sync if the backend adds an aggregation type.
const RETENTION_Y_AXIS_LABELS: Record<string, string> = {
    count: 'Retention %',
    sum: 'Sum',
    avg: 'Avg',
}

function retentionYAxisLabel(aggregationType: string): string {
    return RETENTION_Y_AXIS_LABELS[aggregationType] ?? 'Avg'
}

export interface BuildRetentionChartModelOpts {
    aggregationType: string
    reference: string
    period: string
    showTrendLines?: boolean
    getColor: (index: number) => string
    tooltip?: TooltipConfig
    /** Cohorts beyond this are dropped so each line keeps a distinct palette color.
     *  Omit for no cap (web behavior) — colors wrap once they exceed the palette. */
    maxCohorts?: number
}

export interface RetentionChartModel {
    series: Series<RetentionSeriesMeta>[]
    labels: string[]
    lineConfig: TimeSeriesLineChartConfig
    barConfig: TimeSeriesBarChartConfig & { yAxis?: YAxisConfig }
    /** Cohort count before the `maxCohorts` cap — lets the host show a truncation notice. */
    totalCohorts: number
}

/** Assembles the full retention chart model (sort → cap → per-interval values → series → line/bar
 *  configs) so the MCP visualizer stays presentational and the cohort math is tested here. */
export function buildRetentionChartModel<C extends RetentionCohortLike>(
    cohorts: C[],
    opts: BuildRetentionChartModelOpts
): RetentionChartModel {
    const sorted = sortRetentionCohorts(cohorts)
    const limited = opts.maxCohorts != null ? sorted.slice(0, opts.maxCohorts) : sorted
    const numIntervals = limited.reduce((max, c) => Math.max(max, c.values.length), 0)
    const labels = Array.from({ length: numIntervals }, (_, i) => `${opts.period} ${i}`)

    const entries: RetentionTrendSeriesEntry[] = limited.map((cohort, idx) => ({
        count: cohort.values[0]?.count ?? 0,
        data: Array.from({ length: numIntervals }, (_, i) =>
            computeRetentionSeriesValue(cohort.values, i, opts.aggregationType, opts.reference)
        ),
        labels,
        index: idx,
        label: formatRetentionCohortLabel(cohort, idx + 1, opts.period),
    }))

    const series = buildRetentionSeries(entries, { isIntervalView: false }).map((s, i) => ({
        ...s,
        color: opts.getColor(i),
    }))

    const isPercentage = opts.aggregationType === 'count'
    const yAxisLabel = retentionYAxisLabel(opts.aggregationType)
    const lineBase = buildRetentionLineChartConfig({
        isPercentage,
        showTrendLines: opts.showTrendLines,
        series,
        tooltip: opts.tooltip,
    })
    const barBase = buildRetentionBarChartConfig({ isPercentage, series, tooltip: opts.tooltip })

    return {
        series,
        labels,
        lineConfig: { ...lineBase, yAxis: { ...lineBase.yAxis, label: yAxisLabel } },
        barConfig: { ...barBase, yAxis: { ...barBase.yAxis, label: yAxisLabel } },
        totalCohorts: sorted.length,
    }
}
