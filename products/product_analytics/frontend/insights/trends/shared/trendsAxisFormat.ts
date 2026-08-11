import type { YAxisConfig, YFormatterConfig } from '@posthog/quill-charts'

import type { YFormatterFields } from './trendsChartDisplayOptions'

export function trendsFilterToYFormatterConfig(
    trendsFilter: YFormatterFields | null | undefined,
    isPercentStackView: boolean,
    baseCurrency?: string
): YFormatterConfig {
    if (isPercentStackView) {
        // BarChart's percent layout puts the value scale on 0..1, so use the 0..1 formatter.
        return { format: 'percentage_scaled' }
    }
    return {
        format: trendsFilter?.aggregationAxisFormat ?? 'numeric',
        prefix: trendsFilter?.aggregationAxisPrefix,
        suffix: trendsFilter?.aggregationAxisPostfix,
        decimalPlaces: trendsFilter?.decimalPlaces,
        minDecimalPlaces: trendsFilter?.minDecimalPlaces,
        currency: baseCurrency,
    }
}

export interface TrendsYAxisRangeOpts {
    isPercentStackView: boolean
    yAxisScaleType?: string | null
    startAtZero?: boolean | null
    min?: number | null
    max?: number | null
}

/**
 * The y-axis range a chart should actually apply, once the states that pin the domain have vetoed
 * it: a percent stack fixes the axis to 0..1, and a log axis has no zero baseline to drop.
 *
 * The values stay in the filter when vetoed, so switching the display back restores them. This is
 * the only place that rule lives — the UI greys the controls out to explain it, but a chart built
 * from a stored query, the API, or MCP never passes through the UI.
 */
export function resolveTrendsYAxisRange(opts: TrendsYAxisRangeOpts): {
    startAtZero?: boolean
    min?: number
    max?: number
} {
    if (opts.isPercentStackView || opts.yAxisScaleType === 'log10') {
        return {}
    }
    const bound = (value: number | null | undefined): number | undefined =>
        typeof value === 'number' && isFinite(value) ? value : undefined
    return {
        startAtZero: opts.startAtZero === false ? false : undefined,
        min: bound(opts.min),
        max: bound(opts.max),
    }
}

export function buildTrendsYAxisConfig(
    trendsFilter: YFormatterFields | null | undefined,
    isPercentStackView: boolean,
    baseCurrency: string | undefined,
    extras: {
        yAxisScaleType?: string | null
        showGrid?: boolean
        startAtZero?: boolean | null
        min?: number | null
        max?: number | null
    } = {}
): YAxisConfig {
    return {
        ...trendsFilterToYFormatterConfig(trendsFilter, isPercentStackView, baseCurrency),
        scale: extras.yAxisScaleType === 'log10' ? 'log' : 'linear',
        showGrid: extras.showGrid,
        ...resolveTrendsYAxisRange({ ...extras, isPercentStackView }),
    }
}
