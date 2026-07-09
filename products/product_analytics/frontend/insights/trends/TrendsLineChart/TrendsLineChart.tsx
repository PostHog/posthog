import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { DEFAULT_Y_AXIS_ID, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { PointClickData, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme, useChartConfig, useDateRangeZoom } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ciRanges } from 'lib/statistics'
import { percentage } from 'lib/utils/numbers'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { INSIGHT_TOOLTIP_CONFIG, INSIGHT_TOOLTIP_CONFIG_LEGACY } from '../../shared/tooltipConfig'
import { AnnotationsLayer } from '../shared/AnnotationsLayer'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { getTrendsSeriesDisplayLabel } from '../shared/getTrendsSeriesDisplayLabel'
import { handleTrendsChartClick } from '../shared/handleTrendsChartClick'
import { TrendsAlertOverlays } from '../shared/TrendsAlertOverlays'
import { buildTrendsSeriesMeta, resolveGroupTypeLabel, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip as TrendsTooltipLegacy } from '../shared/TrendsTooltip'
import { useInsightsLegendConfig } from '../shared/useInsightsLegendConfig'
import { buildTrendsLineTimeSeriesConfig, buildTrendsSeries } from './trendsChartTransforms'

interface TrendsLineChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const handleChartError = makeChartErrorHandler('trends-line-chart')

export function TrendsLineChart({ context, inSharedMode = false }: TrendsLineChartProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]
    const TOOLTIP_CONFIG = quillTooltipEnabled ? INSIGHT_TOOLTIP_CONFIG : INSIGHT_TOOLTIP_CONFIG_LEGACY
    const theme = useChartTheme()
    const { insightProps, insight } = useValues(insightLogic)

    const legendConfig = useInsightsLegendConfig({ insightProps, inSharedMode })
    const quillLegendEnabled = !!legendConfig

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

    const labels = currentPeriodResult?.labels ?? []

    const hasData =
        indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result: IndexedTrendResult) => result.count !== 0).length > 0

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

    const onDateRangeZoom = useDateRangeZoom(currentPeriodResult?.days, context?.onDateRangeZoom)

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps)
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
            }
            return quillTooltipEnabled ? (
                <InsightSeriesTooltip {...tooltipProps} />
            ) : (
                <TrendsTooltipLegacy {...tooltipProps} />
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
            quillTooltipEnabled,
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
                // With the quill legend on, hidden series are listed (dimmed) and excluded via
                // config.legend.hiddenKeys instead of being dropped here, so the legend can restore them.
                getHidden: quillLegendEnabled ? undefined : getTrendsHidden,
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
            getTrendsHidden,
            getLabel,
            quillLegendEnabled,
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
                allDays: currentPeriodResult?.days ?? [],
                xAxisLabel: trendsFilter?.xAxisLabel,
                yAxisLabel: trendsFilter?.yAxisLabel,
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
                showCrosshair: true,
                tooltip: TOOLTIP_CONFIG,
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
            currentPeriodResult?.days,
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
            TOOLTIP_CONFIG,
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
            onPointClick={canHandleClick ? onPointClick : undefined}
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
