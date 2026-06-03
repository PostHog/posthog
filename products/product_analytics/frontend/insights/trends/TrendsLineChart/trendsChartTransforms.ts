import { normalizeAxisLabel } from '@posthog/quill-charts'
import type { TimeSeriesLineChartConfig, TooltipConfig } from '@posthog/quill-charts'

import type { CurrencyCode, GoalLine as SchemaGoalLine, TrendsFilter } from '~/queries/schema/schema-general'
import type { IntervalType } from '~/types'

import { schemaGoalLinesToConfigs } from '../shared/goalLinesAdapter'
import { buildTrendsYAxisConfig } from '../shared/trendsAxisFormat'
import { buildDerivedConfigs, type TrendsResultLike } from './trendsSeriesTransforms'

// The framework-agnostic series/derived-config transforms live in `trendsSeriesTransforms`
// (dependency-clean so the MCP UI app can bundle them); re-exported here so existing callers
// keep their import path.
export * from './trendsSeriesTransforms'

export interface BuildTrendsLineTimeSeriesConfigOpts<R extends TrendsResultLike> {
    results: readonly R[]
    trendsFilter?: TrendsFilter | null
    baseCurrency?: CurrencyCode
    isPercentStackView: boolean
    isStickiness?: boolean
    yAxisScaleType?: string | null
    interval?: IntervalType | null
    timezone?: string
    allDays?: string[]
    xAxisLabel?: string | null
    yAxisLabel?: string | null
    goalLines?: SchemaGoalLine[] | null
    incompletenessOffsetFromEnd?: number
    getHidden?: (r: R) => boolean

    showConfidenceIntervals?: boolean
    confidenceLevel?: number
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showTrendLines?: boolean

    valueLabels?: TimeSeriesLineChartConfig['valueLabels']

    showCrosshair?: boolean
    tooltip?: TooltipConfig
}

export function buildTrendsLineTimeSeriesConfig<R extends TrendsResultLike>(
    opts: BuildTrendsLineTimeSeriesConfigOpts<R>
): TimeSeriesLineChartConfig {
    const yAxis = buildTrendsYAxisConfig(opts.trendsFilter, opts.isPercentStackView, opts.baseCurrency, {
        yAxisScaleType: opts.yAxisScaleType,
        showGrid: true,
    })
    const goalLineConfigs = schemaGoalLinesToConfigs(opts.goalLines)
    const derivedConfigs = buildDerivedConfigs(opts.results, {
        showConfidenceIntervals: opts.showConfidenceIntervals,
        confidenceLevel: opts.confidenceLevel,
        showMovingAverage: opts.showMovingAverage,
        movingAverageIntervals: opts.movingAverageIntervals,
        showTrendLines: opts.showTrendLines,
        isStickiness: opts.isStickiness,
        incompletenessOffsetFromEnd: opts.incompletenessOffsetFromEnd,
        getHidden: opts.getHidden,
    })
    return {
        xAxis: {
            label: normalizeAxisLabel(opts.xAxisLabel),
            timezone: opts.timezone,
            interval: opts.interval ?? 'day',
            allDays: opts.allDays ?? [],
        },
        yAxis: {
            ...yAxis,
            label: normalizeAxisLabel(opts.yAxisLabel),
        },
        valueLabels: opts.valueLabels,
        goalLines: goalLineConfigs,
        ...derivedConfigs,
        percentStackView: opts.isPercentStackView,
        showCrosshair: opts.showCrosshair,
        tooltip: opts.tooltip,
    }
}
