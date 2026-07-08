import type {
    Series,
    TimeInterval,
    TimeSeriesBarChartConfig,
    ValueLabelFormatter,
    YAxisConfig,
} from '@posthog/quill-charts'

import { buildTrendsYAxisConfig } from '../shared/trendsAxisFormat'
import type { YFormatterFields } from '../shared/trendsChartDisplayOptions'

// Canonical lifecycle status enumeration: new → resurrecting → returning → dormant. Declared here
// (rather than imported from trendsSeriesMeta, which pulls in `~/` types) so this module stays free
// of `~/`/`lib/` deps and compiles in the MCP Vite bundle, which only resolves `products/*` and
// `@posthog/*`. The lifecycle chart renders series in the reverse order (dormant first) to match the
// legacy chart (`trendsDataLogic.ts:197`).
const LIFECYCLE_STATUS_ORDER: readonly string[] = ['new', 'resurrecting', 'returning', 'dormant']

// Shape both IndexedTrendResult (kea) and lighter fixtures (e.g. the MCP UI app) satisfy.
export interface TrendsLifecycleResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    status?: string
    days?: string[]
    action?: { order?: number } | null
}

function lifecycleStatusOrder(status: string | undefined): number {
    const i = LIFECYCLE_STATUS_ORDER.indexOf(status ?? '')
    return i === -1 ? LIFECYCLE_STATUS_ORDER.length : i
}

export interface LifecycleValueLabelOptions {
    showValues: boolean
    showPercentages: boolean
}

// Positives only — dormant is the lone negative series, so it's excluded from the active total.
function activeBandTotal(bandValues: number[] | undefined): number {
    return (bandValues ?? []).reduce((sum, v) => (v > 0 ? sum + v : sum), 0)
}

// Dormant orgs lapsed from the *previous* period's active pool, so their share divides by that
// period's total rather than the current one.
export function buildLifecycleValueLabelFormatter(
    formatValue: (value: number) => string,
    { showValues, showPercentages }: LifecycleValueLabelOptions
): ValueLabelFormatter {
    return (value, _seriesIndex, _dataIndex, context) => {
        const valueText = showValues ? formatValue(value) : ''
        if (!showPercentages || context.isPercent) {
            return valueText
        }
        const isDormant = context.rawValue < 0
        const denominator = isDormant
            ? activeBandTotal(context.previousBandValues)
            : activeBandTotal(context.bandValues)
        if (denominator === 0) {
            // Dormant in the first period has no previous band to divide by — show its value rather than blank.
            return isDormant ? formatValue(value) : valueText
        }
        const pct = Math.round((Math.abs(context.rawValue) / denominator) * 100)
        return showValues ? `${valueText} (${pct}%)` : `${pct}%`
    }
}

/** Drops rows whose lifecycle status is toggled off — mirrors the main app's legend toggles, which
 *  the MCP host honors from the query (the web chart toggles interactively instead). With no toggle
 *  set every row passes; once a toggle is active, a row without a status is dropped. */
export function filterToggledLifecycleResults<R extends { status?: string }>(
    results: R[],
    toggledLifecycles: readonly string[] | undefined
): R[] {
    if (!toggledLifecycles) {
        return results
    }
    return results.filter((r) => !!r.status && toggledLifecycles.includes(r.status))
}

export interface BuildTrendsLifecycleSeriesOpts<R extends TrendsLifecycleResultLike, M = unknown> {
    // Injected so the transform stays free of `lib/colors` (the MCP bundle can't resolve it). Web
    // passes `getBarColorFromStatus`, which throws on unknown statuses — surfacing bad data rather
    // than silently miscoloring it. `dormant` is the only status emitted as negatives, so a diverging
    // stack lays it below the zero baseline regardless of color.
    getColor: (status: string | undefined) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

export function buildTrendsLifecycleSeries<R extends TrendsLifecycleResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsLifecycleSeriesOpts<R, M>
): Series<M>[] {
    // Stable lifecycle order: dormant → returning → resurrecting → new — matches the
    // legacy lifecycle chart (`trendsDataLogic.ts:197`) so the legend reads top-down the
    // same way. Dormant's data is negative, so the diverging stack still renders it below
    // the zero baseline regardless of its position in the series array.
    const ordered = results
        .map((r, index) => ({ r, originalIndex: index }))
        .sort((a, b) => lifecycleStatusOrder(b.r.status) - lifecycleStatusOrder(a.r.status))

    return ordered.map(({ r, originalIndex }) => {
        const excluded = opts.getHidden ? opts.getHidden(r, originalIndex) : false
        const meta = opts.buildMeta ? opts.buildMeta(r, originalIndex) : undefined
        return {
            key: String(r.id ?? originalIndex),
            // Labels arrive as "Pageview - new" / "Pageview - returning"; the row's color
            // already identifies the underlying event, so we keep just the status —
            // shortened here so both legend and tooltip pick up the clean form.
            label: shortenLifecycleLabel(r.label),
            data: r.data,
            color: opts.getColor(r.status),
            meta,
            visibility: excluded ? { excluded: true } : undefined,
        }
    })
}

export interface BuildTrendsLifecycleConfigOpts {
    trendsFilter?: YFormatterFields | null
    baseCurrency?: string
    isStacked: boolean
    yAxisScaleType?: string | null
    interval?: TimeInterval | null
    timezone?: string
    allDays?: string[]
    valueLabels?: TimeSeriesBarChartConfig['valueLabels']
    tooltip?: TimeSeriesBarChartConfig['tooltip']
    legend?: TimeSeriesBarChartConfig['legend']
}

export function buildTrendsLifecycleConfig(
    opts: BuildTrendsLifecycleConfigOpts
): TimeSeriesBarChartConfig & { yAxis?: YAxisConfig } {
    const yAxis = buildTrendsYAxisConfig(opts.trendsFilter, false, opts.baseCurrency, {
        yAxisScaleType: opts.yAxisScaleType,
        showGrid: true,
    })
    return {
        xAxis: {
            timezone: opts.timezone,
            interval: opts.interval ?? 'day',
            allDays: opts.allDays ?? [],
        },
        yAxis,
        valueLabels: opts.valueLabels,
        barLayout: opts.isStacked ? 'stacked' : 'grouped',
        // Only meaningful in stacked layout — dormant stacks below 0.
        divergingStack: opts.isStacked,
        tooltip: opts.tooltip,
        legend: opts.legend,
    }
}

export interface BuildLifecycleChartModelOpts<
    R extends TrendsLifecycleResultLike,
    M = unknown,
> extends BuildTrendsLifecycleConfigOpts {
    /** Final x-axis labels (already formatted by the host — kea dates vs the MCP `formatDate`). */
    labels: string[]
    getColor: (status: string | undefined) => string
    /** Client-side legend toggle state. Omit on hosts that toggle interactively (the web chart). */
    toggledLifecycles?: readonly string[]
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

/** The complete input a host hands to quill's `TimeSeriesBarChart` for a lifecycle chart. */
export interface LifecycleChartModel<M = unknown> {
    series: Series<M>[]
    labels: string[]
    config: TimeSeriesBarChartConfig
}

/** Assembles the full lifecycle chart model (filter → series → config) so both the web container and
 *  the MCP visualizer share one tested path; each injects only host-specific bits (color, labels,
 *  tooltip, meta, interactivity flags). */
export function buildLifecycleChartModel<R extends TrendsLifecycleResultLike, M = unknown>(
    results: R[],
    opts: BuildLifecycleChartModelOpts<R, M>
): LifecycleChartModel<M> {
    const visible = filterToggledLifecycleResults(results, opts.toggledLifecycles)
    const series = buildTrendsLifecycleSeries<R, M>(visible, {
        getColor: opts.getColor,
        getHidden: opts.getHidden,
        buildMeta: opts.buildMeta,
    })
    const config = buildTrendsLifecycleConfig(opts)
    return { series, labels: opts.labels, config }
}

/** Lifecycle series labels arrive as "Pageview - new", "Pageview - returning", etc.
 *  Returns just the capitalized status ("New", "Returning"). */
export function shortenLifecycleLabel(label: string | null | undefined): string {
    const parts = label?.split(' - ')
    const tail = parts?.[parts.length - 1] ?? label ?? 'None'
    // Inlined rather than imported from `lib/utils` so this module stays MCP-bundle-safe.
    return tail.charAt(0).toUpperCase() + tail.slice(1)
}
