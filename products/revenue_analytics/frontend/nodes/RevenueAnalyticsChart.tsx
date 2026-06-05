import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { ChartLegend, TimeSeriesBarChart, TimeSeriesLineChart, legendItemsFromSeries } from '@posthog/quill-charts'
import type {
    GoalLineConfig,
    TimeSeriesBarChartConfig,
    TimeSeriesLineChartConfig,
    TooltipConfig,
    TooltipContext,
    YAxisConfig,
} from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { teamLogic } from 'scenes/teamLogic'

import type { TrendsFilter } from '~/queries/schema/schema-general'
import type { GraphDataset } from '~/types'

import { trendsFilterToYFormatterConfig } from 'products/product_analytics/frontend/insights/trends/shared/trendsAxisFormat'
import type { TrendsSeriesMeta } from 'products/product_analytics/frontend/insights/trends/shared/trendsSeriesMeta'
import { TrendsTooltip } from 'products/product_analytics/frontend/insights/trends/shared/TrendsTooltip'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { buildRevenueAnalyticsSeries, type RevenueAnalyticsChartKind } from './revenueAnalyticsChartTransforms'

export type { RevenueAnalyticsChartKind }

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

export interface RevenueAnalyticsChartLegendProps {
    show: boolean
    position?: 'top' | 'bottom' | 'left' | 'right'
    // chart.js drew the first series at the bottom of a stack while listing it at the top of the
    // legend; reversing keeps the legend reading top-down in the same visual order as the stack.
    reverse?: boolean
}

export interface RevenueAnalyticsChartProps {
    dataAttr: string
    datasets: GraphDataset[]
    labels: string[]
    kind: RevenueAnalyticsChartKind
    trendsFilter?: TrendsFilter | null
    goalLines?: GoalLineConfig[]
    legend?: RevenueAnalyticsChartLegendProps
    // Stacked bars only — stack negative segments (e.g. churn/contraction) below the zero baseline.
    divergingStack?: boolean
    // Dash the final segment to mark the still-incomplete current period (line/area only).
    isInProgress?: boolean
    // Override the per-series color (e.g. MRR breakdown maps status → fixed color). When omitted,
    // the chart falls back to the theme palette by series index, matching the legacy chart.
    getColor?: (dataset: GraphDataset, index: number) => string | undefined
}

export function RevenueAnalyticsChart({
    dataAttr,
    datasets,
    labels,
    kind,
    trendsFilter,
    goalLines,
    legend,
    divergingStack,
    isInProgress = false,
    getColor,
}: RevenueAnalyticsChartProps): JSX.Element {
    const { timezone, baseCurrency } = useValues(teamLogic)
    const { dateFilter } = useValues(revenueAnalyticsLogic)

    const theme = useMemo(() => buildTheme(), [])

    const series = useMemo(
        () => buildRevenueAnalyticsSeries(datasets, { kind, isInProgress, getColor }),
        [datasets, kind, isInProgress, getColor]
    )

    const yAxis = useMemo<YAxisConfig>(
        () => ({ ...trendsFilterToYFormatterConfig(trendsFilter, false, baseCurrency), showGrid: true }),
        [trendsFilter, baseCurrency]
    )

    const legendItems = useMemo(() => {
        const items = legendItemsFromSeries(series, theme)
        return legend?.reverse ? [...items].reverse() : items
    }, [series, theme, legend?.reverse])

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => (
            <TrendsTooltip
                context={ctx}
                timezone={timezone}
                interval={dateFilter.interval}
                trendsFilter={trendsFilter}
                baseCurrency={baseCurrency}
                groupTypeLabel=""
            />
        ),
        [timezone, dateFilter.interval, trendsFilter, baseCurrency]
    )

    const legendPosition = legend?.position ?? 'right'
    const showLegend = !!legend?.show

    if (kind === 'bar') {
        const config: TimeSeriesBarChartConfig = {
            yAxis,
            goalLines,
            barLayout: 'stacked',
            divergingStack,
            tooltip: TOOLTIP_CONFIG,
        }
        return (
            <ChartLegend
                show={showLegend}
                items={legendItems}
                position={legendPosition}
                legendDataAttr={`${dataAttr}-legend`}
            >
                <TimeSeriesBarChart<TrendsSeriesMeta>
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={config}
                    tooltip={renderTooltip}
                    className="BarGraph"
                    dataAttr={dataAttr}
                />
            </ChartLegend>
        )
    }

    const config: TimeSeriesLineChartConfig = {
        yAxis,
        goalLines,
        showCrosshair: true,
        tooltip: TOOLTIP_CONFIG,
    }
    return (
        <ChartLegend
            show={showLegend}
            items={legendItems}
            position={legendPosition}
            legendDataAttr={`${dataAttr}-legend`}
        >
            <TimeSeriesLineChart<TrendsSeriesMeta>
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={renderTooltip}
                className="LineGraph"
                dataAttr={dataAttr}
            />
        </ChartLegend>
    )
}
