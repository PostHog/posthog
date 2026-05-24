import type { Series, TimeSeriesBarChartConfig } from 'lib/hog-charts'
import { getBarColorFromStatus } from 'lib/colors'

import type { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'
import type { IntervalType, LifecycleToggle } from '~/types'

import { buildTrendsYAxisConfig } from '../shared/trendsAxisFormat'

// Shape both IndexedTrendResult (kea) and lighter fixtures satisfy.
export interface TrendsLifecycleResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    status?: string
    days?: string[]
    action?: { order?: number } | null
}

const LIFECYCLE_STATUSES: readonly LifecycleToggle[] = ['new', 'resurrecting', 'returning', 'dormant']

function lifecycleStatusOrder(status: string | undefined): number {
    const i = LIFECYCLE_STATUSES.indexOf(status as LifecycleToggle)
    return i === -1 ? LIFECYCLE_STATUSES.length : i
}

// `dormant` is the only lifecycle status whose values are emitted as negatives,
// so a diverging stack lays it below the zero baseline. The non-dormant series
// are pinned to their fixed lifecycle colors regardless of the data-color theme.
function lifecycleColor(status: string | undefined): string {
    if (status && (LIFECYCLE_STATUSES as readonly string[]).includes(status)) {
        return getBarColorFromStatus(status as LifecycleToggle)
    }
    return getBarColorFromStatus('new')
}

export interface BuildTrendsLifecycleSeriesOpts<R extends TrendsLifecycleResultLike, M = unknown> {
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

export function buildTrendsLifecycleSeries<R extends TrendsLifecycleResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsLifecycleSeriesOpts<R, M> = {}
): Series<M>[] {
    // Stable lifecycle order: new → resurrecting → returning → dormant.
    // d3.stack emits layers in series order, so dormant ends up at the bottom of the
    // diverging stack (its data is negative) and renders below the zero baseline.
    const ordered = results
        .map((r, index) => ({ r, originalIndex: index }))
        .sort((a, b) => lifecycleStatusOrder(a.r.status) - lifecycleStatusOrder(b.r.status))

    return ordered.map(({ r, originalIndex }) => {
        const excluded = opts.getHidden ? opts.getHidden(r, originalIndex) : false
        const meta = opts.buildMeta ? opts.buildMeta(r, originalIndex) : undefined
        return {
            key: String(r.id ?? originalIndex),
            label: r.label ?? '',
            data: r.data,
            color: lifecycleColor(r.status),
            meta,
            visibility: excluded ? { excluded: true } : undefined,
        }
    })
}

export interface BuildTrendsLifecycleConfigOpts {
    trendsFilter?: TrendsFilter | null
    baseCurrency?: CurrencyCode
    isGrouped: boolean
    yAxisScaleType?: string | null
    interval?: IntervalType | null
    timezone?: string
    allDays?: string[]
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
        barLayout: opts.isGrouped ? 'grouped' : 'stacked',
        // Only meaningful in stacked layout — dormant stacks below 0.
        divergingStack: !opts.isGrouped,
        tooltip: opts.tooltip,
    }
}

/** Lifecycle series labels arrive as "Pageview - new", "Pageview - returning", etc.
 *  The legend and tooltip show only the status. */
export function shortenLifecycleLabel(label: string | undefined): string {
    const parts = label?.split(' - ')
    const tail = parts?.[parts.length - 1] ?? label ?? 'None'
    return tail.charAt(0).toUpperCase() + tail.slice(1)
}
