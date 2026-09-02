import { useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useMemo } from 'react'

import { DEFAULT_Y_AXIS_ID, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { PointClickData, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme, useChartConfig, useDateRangeZoom } from 'lib/charts/hooks'
import { AnnotationsLayer } from 'lib/components/AnnotationsOverlay/AnnotationsLayer'
import { dayjs } from 'lib/dayjs'
import { ciRanges } from 'lib/statistics'
import { percentage } from 'lib/utils/numbers'
import { isMultiSeriesFormula } from 'lib/utils/strings'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, type IntervalType } from '~/types'

import { chartStyleCurve } from '../../shared/chartStyleAdapter'
import { hasTrendsChartData } from '../../shared/hasTrendsChartData'
import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { INSIGHT_TOOLTIP_CONFIG } from '../../shared/tooltipConfig'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { getTrendsSeriesDisplayLabel } from '../shared/getTrendsSeriesDisplayLabel'
import { handleTrendsChartClick } from '../shared/handleTrendsChartClick'
import { TrendsAlertOverlays } from '../shared/TrendsAlertOverlays'
import { buildTrendsSeriesMeta, resolveGroupTypeLabel, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { useInsightsLegendConfig } from '../shared/useInsightsLegendConfig'
import { buildTrendsLineTimeSeriesConfig, buildTrendsSeries } from './trendsChartTransforms'

interface TrendsLineChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
    embedded?: boolean
}

const handleChartError = makeChartErrorHandler('trends-line-chart')

// A completed comparison ("previous") period can span more buckets than the still-in-progress
// current period — e.g. a full "yesterday" against "today" so far at hour granularity. The x-axis
// is keyed off the current period's days, so the extra previous-period points would fall outside
// the domain and get clipped. Extend the domain forward by the interval so the previous series
// spans the full width; the current series keeps its shorter, dashed tail.
export function extendLabelsToLongestSeries(
    labels: string[],
    interval: IntervalType | null | undefined,
    results: IndexedTrendResult[]
): string[] {
    const maxLength = results.reduce((max, r) => Math.max(max, r.data?.length ?? 0), 0)
    if (!labels.length || labels.length >= maxLength) {
        return labels
    }
    const hasTime = labels[0].includes(' ')
    const format = hasTime ? 'YYYY-MM-DD HH:mm:ss' : 'YYYY-MM-DD'
    const extended = [...labels]
    let cursor = dayjs(labels[labels.length - 1])
    while (extended.length < maxLength) {
        cursor = cursor.add(1, (interval ?? 'day') as dayjs.ManipulateType)
        extended.push(cursor.format(format))
    }
    return extended
}

export function TrendsLineChart({
    context,
    inSharedMode = false,
    embedded = false,
}: TrendsLineChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const { insightProps, insight } = useValues(insightLogic)

    const legendConfig = useInsightsLegendConfig({ insightProps, inSharedMode })

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
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const getLabel = useCallback(
        (r: IndexedTrendResult): string =>
            getTrendsSeriesDisplayLabel(r, {
                breakdownFilter,
                cohorts: allCohorts?.results,
                formatPropertyValueForDisplay,
            }),
        [breakdownFilter, allCohorts?.results, formatPropertyValueForDisplay]
    )

    const isPercentStackView = !!showPercentStackView && !!supportsPercentStackView
    const resolvedGroupTypeLabel = context?.groupTypeLabel ?? resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    // The chart keys x positions off these strings, so they must be unique per point. The
    // backend's display labels are not: week and hour labels omit the year, so a multi-year
    // range repeats them and every repeated point snaps back to the first occurrence's x,
    // drawing the line backwards. Pass the ISO days instead; the interval-aware tick and
    // tooltip formatters already render display text from them. Stickiness x values are
    // interval counts rather than dates, so it keeps its (already unique) labels.
    const days = currentPeriodResult?.days
    const useDayLabels = !isStickiness && !!days?.length
    const labels = useDayLabels
        ? extendLabelsToLongestSeries(days as string[], interval, indexedResults ?? [])
        : (currentPeriodResult?.labels ?? [])
    // Keep the tick formatter's day context in step with the (possibly extended) domain.
    const allDays = useDayLabels ? labels : (currentPeriodResult?.days ?? [])

    const hasData = hasTrendsChartData(indexedResults)

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
    // The persons modal is intentionally unavailable for multi-series formulas (there's no
    // single series of actors behind a computed ratio). On dashboard/card tiles a click
    // instead opens the underlying insight, since there's nowhere else for the click to go.
    const isFormulaDrillDownDisabled = !canHandleClick && isMultiSeriesFormula(formula)
    const canNavigateToInsight = embedded && !inSharedMode && isFormulaDrillDownDisabled && !!insight.short_id
    const canHandlePointInteraction = canHandleClick || canNavigateToInsight

    const navigateToInsight = useCallback(() => {
        if (!insight.short_id) {
            return
        }
        router.actions.push(urls.insightView(insight.short_id, insightProps.dashboardId))
    }, [insight.short_id, insightProps.dashboardId])

    // The default footer offers persons, which isn't where this click goes.
    const viewInsightFooter = canNavigateToInsight ? 'Click to view the insight' : undefined

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
            if (canHandleClick) {
                handleTrendsChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
            } else if (canNavigateToInsight) {
                navigateToInsight()
            }
        },
        [canHandleClick, canNavigateToInsight, clickDeps, navigateToInsight]
    )

    const onDateRangeZoom = useDateRangeZoom(currentPeriodResult?.days, context?.onDateRangeZoom)

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandlePointInteraction
                ? (datum: SeriesDatum) => {
                      if (canHandleClick) {
                          const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                          handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps)
                      } else {
                          navigateToInsight()
                      }
                  }
                : undefined
            const tooltipProps = {
                context: ctx,
                timezone,
                interval: interval ?? undefined,
                breakdownFilter: breakdownFilter ?? undefined,
                dateRange: insightData?.resolved_date_range ?? undefined,
                trendsFilter,
                formula,
                showPercentView: isStickiness,
                isPercentStackView,
                baseCurrency,
                groupTypeLabel: resolvedGroupTypeLabel,
                formatCompareLabel: context?.formatCompareLabel,
                onRowClick,
                footerOverride: viewInsightFooter,
            }
            return <InsightSeriesTooltip {...tooltipProps} />
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
            canHandlePointInteraction,
            canHandleClick,
            navigateToInsight,
            viewInsightFooter,
            clickDeps,
        ]
    )

    const series = useMemo(
        () =>
            buildTrendsSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                isArea: display === ChartDisplayType.ActionsAreaGraph,
                showMultipleYAxes: showMultipleYAxes ?? undefined,
                incompletenessOffsetFromEnd,
                isStickiness,
                getColor: getTrendsColor,
                // Hidden series are listed (dimmed) and excluded via config.legend.hiddenKeys instead
                // of being dropped here, so the legend can restore them.
                getHidden: undefined,
                getLabel,
                buildMeta: buildTrendsSeriesMeta,
            }),
        [
            indexedResults,
            display,
            showMultipleYAxes,
            incompletenessOffsetFromEnd,
            isStickiness,
            getTrendsColor,
            getLabel,
        ]
    )

    const config = useChartConfig(
        () =>
            buildTrendsLineTimeSeriesConfig<IndexedTrendResult>({
                results: indexedResults ?? [],
                trendsFilter,
                baseCurrency,
                isPercentStackView,
                isStickiness,
                yAxisScaleType,
                interval,
                timezone,
                allDays,
                xAxisLabel: trendsFilter?.xAxisLabel,
                yAxisLabel: trendsFilter?.yAxisLabel,
                yAxisStartAtZero: trendsFilter?.yAxisStartAtZero,
                yAxisMin: trendsFilter?.yAxisMin,
                yAxisMax: trendsFilter?.yAxisMax,
                goalLines,
                incompletenessOffsetFromEnd,
                getHidden: getTrendsHidden,
                getLabel,
                showConfidenceIntervals: showConfidenceIntervals ?? undefined,
                confidenceLevel: confidenceLevel ?? undefined,
                ciRanges,
                showMovingAverage: showMovingAverage ?? undefined,
                movingAverageIntervals: movingAverageIntervals ?? undefined,
                showTrendLines: showTrendLines ?? undefined,
                valueLabels: showValuesOnSeries && valueLabelFormatter ? { formatter: valueLabelFormatter } : false,
                curve: chartStyleCurve(trendsFilter?.chartStyle),
                showCrosshair: true,
                tooltip: INSIGHT_TOOLTIP_CONFIG,
                legend: legendConfig,
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
            allDays,
            goalLines,
            incompletenessOffsetFromEnd,
            getTrendsHidden,
            getLabel,
            showConfidenceIntervals,
            confidenceLevel,
            showMovingAverage,
            movingAverageIntervals,
            showTrendLines,
            showValuesOnSeries,
            valueLabelFormatter,
            legendConfig,
        ]
    )

    if (!hasData) {
        return (
            <InsightEmptyState
                heading={context?.emptyStateHeading}
                detail={context?.emptyStateDetail}
                sampleDataVariant="line"
            />
        )
    }

    const showAnnotations = !inSharedMode && trendsFilter?.showAnnotations !== false
    const annotationsDates = currentPeriodResult?.days ?? []

    return (
        <TimeSeriesLineChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={config}
            tooltip={renderTooltip}
            onPointClick={canHandlePointInteraction ? onPointClick : undefined}
            onDateRangeZoom={onDateRangeZoom}
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
