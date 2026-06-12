import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { InsightEmptyState } from '@posthog/query-frontend/nodes/InsightViz/EmptyStates'
import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'
import type { IndexedTrendResult } from '@posthog/query-frontend/nodes/TrendsQuery/types'
import { openPersonsModal } from '@posthog/query-frontend/persons-modal/PersonsModal'
import { InsightVizNode } from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'
import { TimeSeriesBarChart } from '@posthog/quill-charts'
import type { PointClickData, Series, TimeSeriesBarChartConfig, TooltipContext } from '@posthog/quill-charts'
import { buildTheme } from '@posthog/visualizations/charts/utils/theme'
import type { SeriesDatum } from '@posthog/visualizations/InsightTooltip/insightTooltipUtils'

import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { ChartDisplayType } from '~/types'

import { makeChartErrorHandler } from '../../trends/shared/chartErrorHandler'
import {
    buildTrendsSeriesMeta,
    resolveGroupTypeLabel,
    type TrendsSeriesMeta,
} from '../../trends/shared/trendsSeriesMeta'
import { TrendsTooltip } from '../../trends/shared/TrendsTooltip'
import { handleStickinessChartClick } from '../StickinessLineChart/handleStickinessChartClick'
import {
    buildStickinessLabels,
    buildStickinessTooltipTitle,
    stickinessPercentFormatter,
    STICKINESS_TOOLTIP_CONFIG,
} from '../StickinessLineChart/stickinessChartTransforms'
import { buildStickinessBarSeries, buildStickinessBarTimeSeriesConfig } from './stickinessBarChartTransforms'

interface StickinessBarChartProps {
    context?: QueryContext<InsightVizNode>
}

const handleChartError = makeChartErrorHandler('stickiness-bar-chart')

export function StickinessBarChart({ context }: StickinessBarChartProps): JSX.Element | null {
    const theme = useMemo(() => buildTheme(), [])
    const { insightProps } = useValues(insightLogic)

    const {
        indexedResults,
        display,
        interval,
        yAxisScaleType,
        getTrendsColor,
        getTrendsHidden,
        currentPeriodResult,
        breakdownFilter,
        trendsFilter,
        formula,
        labelGroupType,
        hasPersonsModal,
        querySource,
        showValuesOnSeries,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, baseCurrency } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    // Inverted polarity vs legacy `isStacked` in `ActionsLineGraph`; matches `TrendsBarChart`.
    const isGrouped = display === ChartDisplayType.ActionsUnstackedBar

    const resolvedGroupTypeLabel = context?.groupTypeLabel ?? resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    const bucketCount = currentPeriodResult?.labels?.length ?? 0
    const labels = useMemo(() => buildStickinessLabels(bucketCount, interval), [bucketCount, interval])

    const hasData = (indexedResults ?? []).some((r: IndexedTrendResult) => r.count !== 0)

    // `TimeSeriesBarChart` has a single y-axis — `showMultipleYAxes` is intentionally not forwarded.
    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildStickinessBarSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: buildTrendsSeriesMeta,
            }),
        [indexedResults, getTrendsColor, getTrendsHidden]
    )

    const chartConfig: TimeSeriesBarChartConfig = useMemo(
        () =>
            buildStickinessBarTimeSeriesConfig({
                yAxisScaleType,
                isGrouped,
                valueLabels: showValuesOnSeries ? { formatter: stickinessPercentFormatter } : false,
                tooltip: STICKINESS_TOOLTIP_CONFIG,
            }),
        [yAxisScaleType, isGrouped, showValuesOnSeries]
    )

    // Close over the primitives so the click memos don't invalidate when unrelated
    // context fields change. `openPersonsModal` is a stable module import.
    const onDataPointClick = context?.onDataPointClick
    const formatCompareLabel = context?.formatCompareLabel
    const hasClickHandler = !!onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo(
        () => ({
            context: onDataPointClick ? { onDataPointClick } : undefined,
            hasPersonsModal: !!hasPersonsModal,
            interval,
            querySource,
            indexedResults: indexedResults ?? [],
            openPersonsModal,
        }),
        [onDataPointClick, hasPersonsModal, interval, querySource, indexedResults]
    )

    const onPointClick = useCallback(
        (clickData: PointClickData) => {
            handleStickinessChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
        },
        [clickDeps]
    )

    const altTitle = useMemo(() => buildStickinessTooltipTitle(interval), [interval])

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = hasClickHandler
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleStickinessChartClick(seriesKey, datum.dataIndex, clickDeps)
                  }
                : undefined
            return (
                <TrendsTooltip
                    context={ctx}
                    timezone={timezone}
                    interval={interval ?? undefined}
                    breakdownFilter={breakdownFilter ?? undefined}
                    trendsFilter={trendsFilter}
                    formula={formula}
                    showPercentView={true}
                    isPercentStackView={false}
                    baseCurrency={baseCurrency}
                    groupTypeLabel={resolvedGroupTypeLabel}
                    formatCompareLabel={formatCompareLabel}
                    onRowClick={onRowClick}
                    altTitle={altTitle}
                />
            )
        },
        [
            timezone,
            interval,
            breakdownFilter,
            trendsFilter,
            formula,
            baseCurrency,
            resolvedGroupTypeLabel,
            formatCompareLabel,
            hasClickHandler,
            clickDeps,
            altTitle,
        ]
    )

    if (!hasData) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    return (
        <TimeSeriesBarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={chartConfig}
            tooltip={renderTooltip}
            onPointClick={hasClickHandler ? onPointClick : undefined}
            className="BarGraph"
            dataAttr="stickiness-bar-graph"
            onError={handleChartError}
        />
    )
}
