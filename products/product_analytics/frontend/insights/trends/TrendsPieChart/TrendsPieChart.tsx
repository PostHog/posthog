import clsx from 'clsx'
import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, type ErrorInfo } from 'react'

import { PieChart } from '@posthog/quill-charts'
import type { PieChartConfig } from '@posthog/quill-charts'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartDisplayType } from '~/types'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { type TrendsPartOfWholeChartProps, useTrendsPartOfWholeChart } from '../shared/useTrendsPartOfWholeChart'
import { DonutCenterLabel } from './DonutCenterLabel'

const DONUT_INNER_RADIUS_RATIO = 0.6

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'trends-pie-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function TrendsPieChart(props: TrendsPartOfWholeChartProps): JSX.Element | null {
    const { context } = props
    const {
        theme,
        legendConfig,
        series,
        hasResults,
        showAggregation,
        formattedTotal,
        valueFormatter,
        renderTooltip,
        onSliceClick,
    } = useTrendsPartOfWholeChart(props)

    const { insightProps } = useValues(insightLogic)
    const {
        display,
        showValuesOnSeries,
        showLabelOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        pieChartVizOptions,
    } = useValues(trendsDataLogic(insightProps))

    const isPercentStackView = !!showPercentStackView && !!supportsPercentStackView
    const isDonut = display === ChartDisplayType.ActionsDonut

    // Values and percentages are independent on a pie: either one alone puts that number on the
    // slice, and both together read as `352 (18.4%)`, matching the tooltip.
    const showValue = !!showValuesOnSeries
    const showPercent = isPercentStackView

    const pieConfig: PieChartConfig<TrendsSeriesMeta> = useMemo(
        () => ({
            showValueOnSlice: showValue || showPercent,
            sliceValueDisplay: showValue && showPercent ? 'both' : showPercent ? 'percent' : 'value',
            showLabelOnSlice: !!showLabelOnSeries,
            isPercent: isPercentStackView,
            disableHoverOffset: !!pieChartVizOptions?.disableHoverOffset,
            innerRadiusRatio: isDonut ? DONUT_INNER_RADIUS_RATIO : undefined,
            legend: legendConfig,
        }),
        [
            showValue,
            showPercent,
            showLabelOnSeries,
            isPercentStackView,
            pieChartVizOptions?.disableHoverOffset,
            isDonut,
            legendConfig,
        ]
    )

    // An all-hidden pie must keep rendering the legend (dimmed rows) so the hidden slices can be
    // restored — only a truly empty result set gets the empty state.
    if (!hasResults) {
        return (
            <InsightEmptyState
                heading={context?.emptyStateHeading}
                detail={context?.emptyStateDetail}
                sampleDataVariant="pie"
            />
        )
    }

    // A bottom legend (exports/shared images) hugs the bottom of the chart box. If the box fills a
    // tall card the round pie centers in it, stranding the legend far below the pie and up against
    // the total. Bound the box to a square around the pie so the legend sits right under it, and
    // center the whole group. In-app (right legend) the chart keeps filling the column.
    const legendAtBottom = !!legendConfig.show && legendConfig.position === 'bottom'

    // A donut's hollow center is the natural home for the total, so move it there instead of
    // stranding it below the chart.
    const centerLabel = isDonut && showAggregation ? <DonutCenterLabel>{formattedTotal}</DonutCenterLabel> : undefined

    const pie = (
        <PieChart<TrendsSeriesMeta>
            series={series}
            theme={theme}
            config={pieConfig}
            tooltip={renderTooltip}
            onSliceClick={onSliceClick}
            valueFormatter={valueFormatter}
            centerLabel={centerLabel}
            dataAttr="trend-pie-graph"
            onError={handleChartError}
        />
    )

    return (
        // `flex-1 min-h-0` (not `h-full`) so the chart fills the flex column even when the
        // parent only sets `min-height`/`flex` — a percentage height would collapse to 0,
        // leaving `PieChart` with `outerRadius <= 0` and no slices. Mirrors the bar/line charts.
        <div className={clsx('flex flex-col w-full flex-1 min-h-0', legendAtBottom && 'justify-center')}>
            {legendAtBottom ? <div className="flex flex-col w-full min-h-0 max-h-full aspect-square">{pie}</div> : pie}
            {showAggregation && !isDonut && (
                <div
                    className={clsx('text-7xl text-center font-bold m-0', legendAtBottom && 'mt-6')}
                    data-attr="trend-total"
                >
                    {formattedTotal}
                </div>
            )}
        </div>
    )
}
