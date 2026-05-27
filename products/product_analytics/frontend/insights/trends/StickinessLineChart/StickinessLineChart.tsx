import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { TimeSeriesLineChart } from 'lib/hog-charts'
import type { PointClickData, Series, TimeSeriesLineChartConfig, TooltipContext } from 'lib/hog-charts'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { buildTrendsSeriesMeta, resolveGroupTypeLabel, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { handleStickinessChartClick } from './handleStickinessChartClick'
import {
    buildStickinessLabels,
    buildStickinessLineTimeSeriesConfig,
    buildStickinessSeries,
    buildStickinessTooltipTitle,
    stickinessPercentFormatter,
    STICKINESS_TOOLTIP_CONFIG,
} from './stickinessChartTransforms'

interface StickinessLineChartProps {
    context?: QueryContext<InsightVizNode>
}

const handleChartError = makeChartErrorHandler('stickiness-line-chart')

export function StickinessLineChart({ context }: StickinessLineChartProps): JSX.Element | null {
    const theme = useMemo(() => buildTheme(), [])
    const { insightProps } = useValues(insightLogic)

    const {
        indexedResults,
        display,
        interval,
        yAxisScaleType,
        showMultipleYAxes,
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

    const resolvedGroupTypeLabel = context?.groupTypeLabel ?? resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    const bucketCount = currentPeriodResult?.labels?.length ?? 0
    const labels = useMemo(() => buildStickinessLabels(bucketCount, interval), [bucketCount, interval])

    const hasData =
        indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result: IndexedTrendResult) => result.count !== 0).length > 0

    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildStickinessSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                showMultipleYAxes: showMultipleYAxes ?? undefined,
                display: display ?? undefined,
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: buildTrendsSeriesMeta,
            }),
        [indexedResults, display, getTrendsColor, getTrendsHidden, showMultipleYAxes]
    )

    const chartConfig: TimeSeriesLineChartConfig = useMemo(
        () =>
            buildStickinessLineTimeSeriesConfig({
                yAxisScaleType,
                valueLabels: showValuesOnSeries ? { formatter: stickinessPercentFormatter } : false,
                showCrosshair: true,
                tooltip: STICKINESS_TOOLTIP_CONFIG,
            }),
        [yAxisScaleType, showValuesOnSeries]
    )

    const canHandleClick = !!context?.onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo(
        () => ({
            context,
            hasPersonsModal: !!hasPersonsModal,
            interval,
            querySource,
            indexedResults: indexedResults ?? [],
            openPersonsModal,
        }),
        [context, hasPersonsModal, interval, querySource, indexedResults]
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
            const onRowClick = canHandleClick
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
                    formatCompareLabel={context?.formatCompareLabel}
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
            context?.formatCompareLabel,
            canHandleClick,
            clickDeps,
            altTitle,
        ]
    )

    if (!hasData) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    return (
        <TimeSeriesLineChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={chartConfig}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="LineGraph"
            dataAttr="trend-line-graph"
            onError={handleChartError}
        />
    )
}
