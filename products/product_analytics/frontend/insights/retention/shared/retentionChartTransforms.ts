import type {
    GoalLineConfig,
    Series,
    TimeSeriesBarChartConfig,
    TimeSeriesLineChartConfig,
    TooltipConfig,
    TrendLineConfig,
} from 'lib/hog-charts'
import type { RetentionTrendPayload } from 'scenes/retention/types'

import type { GoalLine as SchemaGoalLine } from '~/queries/schema/schema-general'

import { schemaGoalLinesToConfigs } from 'products/product_analytics/frontend/insights/trends/shared/goalLinesAdapter'

// `retentionGraphLogic.trendSeries` spreads `cohortRetention` onto each entry, so the
// runtime shape includes a cohort `label` field that the declared type doesn't list.
export type RetentionTrendSeriesEntry = RetentionTrendPayload & { label?: string }

export interface RetentionSeriesMeta {
    /** Original row index from the unfiltered results — drives modal opens in non-interval view. */
    rowIndex: number
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
    goalLines?: SchemaGoalLine[] | null
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

function buildGoalLines(goalLines: SchemaGoalLine[] | null | undefined): GoalLineConfig[] | undefined {
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

export function buildRetentionBarChartConfig(opts: BuildRetentionChartConfigOpts): TimeSeriesBarChartConfig {
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
