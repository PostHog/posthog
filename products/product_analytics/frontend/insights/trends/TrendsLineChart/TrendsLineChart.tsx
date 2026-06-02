import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { DEFAULT_Y_AXIS_ID, TimeSeriesLineChart } from 'lib/hog-charts'
import type { PointClickData, Series, TimeSeriesLineChartConfig, TooltipConfig, TooltipContext } from 'lib/hog-charts'
import { percentage } from 'lib/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { AnnotationsLayer } from '../shared/AnnotationsLayer'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { handleTrendsChartClick } from '../shared/handleTrendsChartClick'
import { TrendsAlertOverlays } from '../shared/TrendsAlertOverlays'
import { buildTrendsSeriesMeta, resolveGroupTypeLabel, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { buildTrendsLineTimeSeriesConfig, buildTrendsSeries } from './trendsChartTransforms'

interface TrendsLineChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

const handleChartError = makeChartErrorHandler('trends-line-chart')

export function TrendsLineChart({ context, inSharedMode = false }: TrendsLineChartProps): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps, insight } = useValues(insightLogic)

    const {
        indexedResults,
        display,
        interval,
        showPercentStackView,
        supportsPercentStackView,
        yAxisScaleType,
        showMultipleYAxes,
        goalLines,
        getTrendsColor,
        getTrendsHidden,
        currentPeriodResult,
        breakdownFilter,
        insightData,
        trendsFilter,
        formula,
        isStickiness,
        labelGroupType,
        hasPersonsModal,
        querySource,
        incompletenessOffsetFromEnd,
        showMovingAverage,
        movingAverageIntervals,
        showTrendLines,
        showValuesOnSeries,
        showConfidenceIntervals,
        confidenceLevel,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const isPercentStackView = !!showPercentStackView && !!supportsPercentStackView
    const resolvedGroupTypeLabel = context?.groupTypeLabel ?? resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    const labels = currentPeriodResult?.labels ?? []

    const hasData =
        indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result: IndexedTrendResult) => result.count !== 0).length > 0

    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildTrendsSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                display: display ?? undefined,
                showMultipleYAxes: showMultipleYAxes ?? undefined,
                incompletenessOffsetFromEnd,
                isStickiness,
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: buildTrendsSeriesMeta,
            }),
        [
            indexedResults,
            display,
            getTrendsColor,
            getTrendsHidden,
            isStickiness,
            incompletenessOffsetFromEnd,
            showMultipleYAxes,
        ]
    )

    const valueLabelFormatter = useCallback(
        (value: number) => {
            // In percent layout the chart computes each segment's share of its band and passes
            // a 0..1 fraction here, so we render it directly as a percentage.
            if (isPercentStackView) {
                return percentage(value, 1)
            }
            return formatAggregationAxisValue(trendsFilter, value, baseCurrency)
        },
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const chartConfig: TimeSeriesLineChartConfig = useMemo(
        () =>
            buildTrendsLineTimeSeriesConfig({
                results: indexedResults ?? [],
                trendsFilter,
                baseCurrency,
                isPercentStackView,
                isStickiness,
                yAxisScaleType,
                interval,
                timezone,
                allDays: currentPeriodResult?.days ?? [],
                xAxisLabel: trendsFilter?.xAxisLabel,
                yAxisLabel: trendsFilter?.yAxisLabel,
                goalLines,
                incompletenessOffsetFromEnd,
                getHidden: getTrendsHidden,
                showConfidenceIntervals,
                confidenceLevel,
                showMovingAverage,
                movingAverageIntervals,
                showTrendLines,
                valueLabels: showValuesOnSeries ? { formatter: valueLabelFormatter } : false,
                showCrosshair: true,
                tooltip: TOOLTIP_CONFIG,
            }),
        [
            indexedResults,
            trendsFilter,
            baseCurrency,
            isPercentStackView,
            isStickiness,
            yAxisScaleType,
            interval,
            timezone,
            currentPeriodResult?.days,
            trendsFilter?.xAxisLabel,
            trendsFilter?.yAxisLabel,
            goalLines,
            incompletenessOffsetFromEnd,
            getTrendsHidden,
            showConfidenceIntervals,
            confidenceLevel,
            showMovingAverage,
            movingAverageIntervals,
            showTrendLines,
            showValuesOnSeries,
            valueLabelFormatter,
        ]
    )

    const indexByResult = useMemo(() => {
        const m = new Map<IndexedTrendResult, number>()
        ;(indexedResults ?? []).forEach((r, i) => m.set(r, i))
        return m
    }, [indexedResults])

    const getYAxisId = useCallback(
        (r: IndexedTrendResult) => {
            const idx = indexByResult.get(r) ?? 0
            return showMultipleYAxes && idx > 0 ? `y${idx}` : DEFAULT_Y_AXIS_ID
        },
        [indexByResult, showMultipleYAxes]
    )

    const canHandleClick = !!context?.onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo(
        () => ({
            context,
            hasPersonsModal: !!hasPersonsModal,
            interval,
            timezone,
            weekStartDay,
            resolvedDateRange: insightData?.resolved_date_range ?? null,
            querySource,
            indexedResults: indexedResults ?? [],
            openPersonsModal,
        }),
        [
            context,
            hasPersonsModal,
            interval,
            timezone,
            weekStartDay,
            insightData?.resolved_date_range,
            querySource,
            indexedResults,
        ]
    )

    const onPointClick = useCallback(
        (clickData: PointClickData) => {
            handleTrendsChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
        },
        [clickDeps]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps)
                  }
                : undefined
            return (
                <TrendsTooltip
                    context={ctx}
                    timezone={timezone}
                    interval={interval ?? undefined}
                    breakdownFilter={breakdownFilter ?? undefined}
                    dateRange={insightData?.resolved_date_range ?? undefined}
                    trendsFilter={trendsFilter}
                    formula={formula}
                    showPercentView={isStickiness}
                    isPercentStackView={isPercentStackView}
                    baseCurrency={baseCurrency}
                    groupTypeLabel={resolvedGroupTypeLabel}
                    formatCompareLabel={context?.formatCompareLabel}
                    onRowClick={onRowClick}
                />
            )
        },
        [
            timezone,
            interval,
            breakdownFilter,
            insightData?.resolved_date_range,
            trendsFilter,
            formula,
            isStickiness,
            isPercentStackView,
            baseCurrency,
            resolvedGroupTypeLabel,
            context?.formatCompareLabel,
            canHandleClick,
            clickDeps,
        ]
    )

    if (!hasData) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    const showAnnotations = !inSharedMode
    const annotationsDates = currentPeriodResult?.days ?? []

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
        >
            {insight.id ? (
                <TrendsAlertOverlays
                    insightId={insight.id}
                    insightProps={insightProps}
                    indexedResults={indexedResults}
                    getColor={getTrendsColor}
                    getYAxisId={getYAxisId}
                    isHidden={getTrendsHidden}
                />
            ) : null}
            {showAnnotations && <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationsDates} />}
        </TimeSeriesLineChart>
    )
}
