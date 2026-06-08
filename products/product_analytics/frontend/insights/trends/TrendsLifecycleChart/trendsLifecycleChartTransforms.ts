import type { Series, TimeInterval, TimeSeriesBarChartConfig } from '@posthog/quill-charts'

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
}

export function buildTrendsLifecycleConfig(opts: BuildTrendsLifecycleConfigOpts): TimeSeriesBarChartConfig {
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
    }
}

/** Lifecycle series labels arrive as "Pageview - new", "Pageview - returning", etc.
 *  Returns just the capitalized status ("New", "Returning"). */
export function shortenLifecycleLabel(label: string | null | undefined): string {
    const parts = label?.split(' - ')
    const tail = parts?.[parts.length - 1] ?? label ?? 'None'
    // Inlined rather than imported from `lib/utils` so this module stays MCP-bundle-safe.
    return tail.charAt(0).toUpperCase() + tail.slice(1)
}
