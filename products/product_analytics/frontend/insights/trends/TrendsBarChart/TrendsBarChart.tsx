import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import {
    BarChart,
    buildYTickFormatter,
    DEFAULT_Y_AXIS_ID,
    MAX_CATEGORY_LABEL_WIDTH,
    ReferenceLines,
    TimeSeriesBarChart,
    ValueLabels,
} from '@posthog/quill-charts'
import type { BarChartConfig, PointClickData, TimeSeriesBarChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme, useChartConfig } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { getStackBreakdownValues } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { INSIGHT_TOOLTIP_CONFIG, INSIGHT_TOOLTIP_CONFIG_LEGACY } from '../../shared/tooltipConfig'
import { AnnotationsLayer } from '../shared/AnnotationsLayer'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { getTrendsSeriesDisplayLabel } from '../shared/getTrendsSeriesDisplayLabel'
import { goalLinesToReferenceLines } from '../shared/goalLinesAdapter'
import { handleTrendsChartClick, type TrendsChartClickDeps } from '../shared/handleTrendsChartClick'
import { TrendsAlertOverlays } from '../shared/TrendsAlertOverlays'
import { trendsFilterToYFormatterConfig } from '../shared/trendsAxisFormat'
import { buildTrendsSeriesMeta, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { useInsightsLegendConfig } from '../shared/useInsightsLegendConfig'
import { useTrendsDateRangeZoom } from '../shared/useTrendsDateRangeZoom'
import { getAggregatedDisplayLabel as getAggregatedDisplayLabelFn } from './getAggregatedDisplayLabel'
import { handleTrendsBarAggregatedChartClick } from './handleTrendsBarAggregatedChartClick'
import {
    buildTrendsBarAggregatedSeries,
    buildTrendsBarTimeSeries,
    buildTrendsBarTimeSeriesConfig,
} from './trendsBarChartTransforms'

interface TrendsBarChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
    /** True when rendered as a fixed-height dashboard/card tile, false on the full insight page. */
    embedded?: boolean
}

const EMPTY_LABELS: string[] = []
const AGGREGATED_TOOLTIP_CONFIG = { pinnable: false, placement: 'cursor' as const }

type AggregationLabelFn = (groupTypeIndex: number | null | undefined) => { plural: string }

const resolveGroupTypeLabel = (
    labelGroupType: 'people' | 'none' | number,
    aggregationLabel: AggregationLabelFn,
    contextOverride: string | undefined
): string => {
    if (contextOverride != null) {
        return contextOverride
    }
    if (labelGroupType === 'people') {
        return 'people'
    }
    if (labelGroupType === 'none') {
        return ''
    }
    return aggregationLabel(labelGroupType).plural
}

const handleChartError = makeChartErrorHandler('trends-bar-chart')

export function TrendsBarChart({
    context,
    inSharedMode = false,
    embedded = false,
}: TrendsBarChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]
    const TIME_SERIES_TOOLTIP_CONFIG = quillTooltipEnabled ? INSIGHT_TOOLTIP_CONFIG : INSIGHT_TOOLTIP_CONFIG_LEGACY
    const { insightProps, insight } = useValues(insightLogic)

    // Time-series bars (vertical) render the in-chart legend; the aggregated bar-value layout has
    // no legend (each bar is a breakdown row, not a series).
    const legendConfig = useInsightsLegendConfig({ insightProps, inSharedMode })

    const {
        indexedResults,
        display,
        interval,
        showPercentStackView,
        supportsPercentStackView,
        yAxisScaleType,
        currentPeriodResult,
        breakdownFilter,
        insightData,
        trendsFilter,
        formula,
        isStickiness,
        labelGroupType,
        hasPersonsModal,
        querySource,
        getTrendsColor,
        getTrendsHidden,
        goalLines,
        showValuesOnSeries,
        showMultipleYAxes,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const isAggregated = display === ChartDisplayType.ActionsBarValue
    const isGrouped = display === ChartDisplayType.ActionsUnstackedBar
    const quillLegendEnabled = !isAggregated && !!legendConfig
    const isPercentStackView = !isAggregated && !!showPercentStackView && !!supportsPercentStackView
    // Per-series y-axes are only meaningful for grouped (unstacked) bars — stacked layouts share
    // one axis. Mirrors the legacy ActionsLineGraph, which assigns y0/y1/… per dataset.
    const applyMultipleYAxes = !!showMultipleYAxes && isGrouped

    const resolvedGroupTypeLabel = resolveGroupTypeLabel(labelGroupType, aggregationLabel, context?.groupTypeLabel)

    const hasData =
        !!indexedResults?.[0] &&
        (isAggregated
            ? indexedResults.some(
                  (r: IndexedTrendResult) => Number.isFinite(r.aggregated_value) && r.aggregated_value !== 0
              )
            : !!indexedResults[0].data && indexedResults.some((r: IndexedTrendResult) => r.count !== 0))

    const stackBreakdowns = !!querySource && !!getStackBreakdownValues(querySource)

    const getAggregatedDisplayLabel = useCallback(
        (r: IndexedTrendResult): string =>
            getAggregatedDisplayLabelFn(r, {
                stackBreakdowns,
                breakdownFilter,
                cohorts: allCohorts?.results,
                formatPropertyValueForDisplay,
            }),
        [stackBreakdowns, breakdownFilter, allCohorts?.results, formatPropertyValueForDisplay]
    )

    const getLabel = useCallback(
        (r: IndexedTrendResult): string =>
            getTrendsSeriesDisplayLabel(r, {
                breakdownFilter,
                cohorts: allCohorts?.results,
                formatPropertyValueForDisplay,
            }),
        [breakdownFilter, allCohorts?.results, formatPropertyValueForDisplay]
    )

    const { series, labels, displayLabels } = useMemo(() => {
        if (isAggregated) {
            return buildTrendsBarAggregatedSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: buildTrendsSeriesMeta,
                stackBreakdowns,
                getDisplayLabel: getAggregatedDisplayLabel,
            })
        }
        const timeSeries = buildTrendsBarTimeSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
            getColor: getTrendsColor,
            // With the quill legend on, hidden series stay listed (dimmed) and are excluded via
            // config.legend.hiddenKeys instead of being dropped here, so the legend can restore them.
            getHidden: quillLegendEnabled ? undefined : getTrendsHidden,
            getLabel,
            buildMeta: buildTrendsSeriesMeta,
            showMultipleYAxes: applyMultipleYAxes,
        })
        return {
            series: timeSeries,
            labels: currentPeriodResult?.labels ?? EMPTY_LABELS,
            displayLabels: undefined,
        }
    }, [
        isAggregated,
        indexedResults,
        getTrendsColor,
        getTrendsHidden,
        currentPeriodResult?.labels,
        stackBreakdowns,
        getAggregatedDisplayLabel,
        getLabel,
        applyMultipleYAxes,
        quillLegendEnabled,
    ])

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

    const timeSeriesConfig: TimeSeriesBarChartConfig = useChartConfig(
        () => ({
            ...buildTrendsBarTimeSeriesConfig({
                trendsFilter,
                baseCurrency,
                isPercentStackView,
                isGrouped,
                yAxisScaleType,
                interval,
                timezone,
                allDays: currentPeriodResult?.days ?? [],
                xAxisLabel: trendsFilter?.xAxisLabel,
                yAxisLabel: trendsFilter?.yAxisLabel,
                goalLines,
                valueLabels: showValuesOnSeries ? { formatter: valueLabelFormatter } : false,
                tooltip: TIME_SERIES_TOOLTIP_CONFIG,
            }),
            // Interactive legend (toggle callbacks, context menu) is a component concern, kept out
            // of the pure transform so the builder stays free of React state.
            legend: legendConfig,
        }),
        [
            trendsFilter,
            baseCurrency,
            isPercentStackView,
            isGrouped,
            yAxisScaleType,
            interval,
            timezone,
            currentPeriodResult?.days,
            trendsFilter?.xAxisLabel,
            trendsFilter?.yAxisLabel,
            goalLines,
            showValuesOnSeries,
            valueLabelFormatter,
            legendConfig,
            TIME_SERIES_TOOLTIP_CONFIG,
        ]
    )

    const aggregatedYTickFormatter = useMemo(
        () => buildYTickFormatter(trendsFilterToYFormatterConfig(trendsFilter, isPercentStackView, baseCurrency)),
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const aggregatedConfig: BarChartConfig = useChartConfig(() => {
        // Band keys are synthetic per-series; render the human label via the categorical-axis
        // formatter and skip repeats so band-shared breakdown rows don't double-paint.
        let xTickFormatter: BarChartConfig['xTickFormatter']
        if (displayLabels && labels) {
            const firstIndexOf = new Map<string, number>()
            labels.forEach((l, i) => {
                if (!firstIndexOf.has(l)) {
                    firstIndexOf.set(l, i)
                }
            })
            xTickFormatter = (label: string, i: number) =>
                firstIndexOf.get(label) === i ? (displayLabels[i] ?? null) : null
        }
        return {
            showGrid: true,
            tooltip: AGGREGATED_TOOLTIP_CONFIG,
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            axisOrientation: 'horizontal',
            barLayout: 'stacked',
            yTickFormatter: aggregatedYTickFormatter,
            xTickFormatter,
            xAxisLabel: trendsFilter?.xAxisLabel,
            yAxisLabel: trendsFilter?.yAxisLabel,
            // Breakdown values become category (y-axis) labels here; truncate long ones (e.g. URLs)
            // so they don't grow the margin and push the plot off screen. Full value shows on hover.
            maxCategoryLabelWidth: MAX_CATEGORY_LABEL_WIDTH,
            // Dashboard/card tiles are a fixed height, so cap the rows to those that fit. The full
            // insight page is `embedded: false` — even when opened from a dashboard (dashboardId in
            // the URL) — so it keeps the grow-to-fit-all behavior and renders every breakdown row.
            // divergingStack keeps negative values (e.g. a `A*(-1)` formula) below the zero baseline
            // instead of clamping them to 0.
            bars: { fitToHeight: embedded, divergingStack: true },
        }
    }, [
        yAxisScaleType,
        aggregatedYTickFormatter,
        trendsFilter?.xAxisLabel,
        trendsFilter?.yAxisLabel,
        displayLabels,
        labels,
        embedded,
    ])

    const canHandleClick = !!context?.onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo<TrendsChartClickDeps>(
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

    const aggregatedReferenceLines = useMemo(
        () => (isAggregated ? goalLinesToReferenceLines(goalLines, series, 'horizontal') : []),
        [isAggregated, goalLines, series]
    )

    const indexByResult = useMemo(() => {
        const m = new Map<IndexedTrendResult, number>()
        ;(indexedResults ?? []).forEach((r: IndexedTrendResult, i: number) => m.set(r, i))
        return m
    }, [indexedResults])

    // Anomaly markers must read the same axis their series is scaled against.
    const getYAxisId = useCallback(
        (r: IndexedTrendResult) => {
            const idx = indexByResult.get(r) ?? 0
            return applyMultipleYAxes && idx > 0 ? `y${idx}` : DEFAULT_Y_AXIS_ID
        },
        [indexByResult, applyMultipleYAxes]
    )

    const onPointClick = useCallback(
        (clickData: PointClickData) => {
            if (isAggregated) {
                handleTrendsBarAggregatedChartClick(clickData.dataIndex, clickDeps)
            } else {
                handleTrendsChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
            }
        },
        [isAggregated, clickDeps]
    )

    // Time-series layouts only — the aggregated bar-value layout has categorical labels, not dates.
    const onDateRangeZoom = useTrendsDateRangeZoom(context, currentPeriodResult?.days)

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            // BarTooltip already put the cursor-visible segment at seriesData[0] — keep just that.
            const tooltipCtx: TooltipContext<TrendsSeriesMeta> = isAggregated
                ? {
                      ...ctx,
                      seriesData: ctx.seriesData.slice(0, 1),
                  }
                : ctx
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      if (isAggregated) {
                          handleTrendsBarAggregatedChartClick(datum.dataIndex, clickDeps)
                      } else {
                          const seriesKey = tooltipCtx.seriesData[datum.datasetIndex].series.key
                          handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps)
                      }
                  }
                : undefined
            const sharedProps = {
                context: tooltipCtx,
                timezone,
                interval: interval ?? undefined,
                breakdownFilter: breakdownFilter ?? undefined,
                dateRange: insightData?.resolved_date_range ?? undefined,
                trendsFilter,
                showPercentView: isStickiness,
                isPercentStackView,
                baseCurrency,
                groupTypeLabel: resolvedGroupTypeLabel,
                formatCompareLabel: context?.formatCompareLabel,
                onRowClick,
                showHeader: isAggregated ? (false as const) : undefined,
                sortedByValue: false,
            }
            return quillTooltipEnabled ? (
                <InsightSeriesTooltip {...sharedProps} />
            ) : (
                <TrendsTooltip {...sharedProps} formula={formula} />
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
            isAggregated,
            quillTooltipEnabled,
        ]
    )

    if (!hasData) {
        return (
            <InsightEmptyState
                heading={context?.emptyStateHeading}
                detail={context?.emptyStateDetail}
                sampleDataVariant="bar"
            />
        )
    }

    if (isAggregated) {
        return (
            <BarChart<TrendsSeriesMeta>
                series={series}
                labels={labels}
                config={aggregatedConfig}
                theme={theme}
                tooltip={renderTooltip}
                onPointClick={canHandleClick ? onPointClick : undefined}
                className="BarGraph"
                dataAttr="trend-bar-value-graph"
                onError={handleChartError}
            >
                <ReferenceLines lines={aggregatedReferenceLines} />
                {insight.id && (
                    <TrendsAlertOverlays
                        insightId={insight.id}
                        insightProps={insightProps}
                        indexedResults={indexedResults}
                        getColor={getTrendsColor}
                        getYAxisId={getYAxisId}
                        isHidden={getTrendsHidden}
                        axisOrientation="horizontal"
                    />
                )}
                {showValuesOnSeries && <ValueLabels valueFormatter={valueLabelFormatter} />}
            </BarChart>
        )
    }

    // Annotations are date-anchored, so they only make sense for the time-series bar
    // layouts (vertical bars). The horizontal aggregated layout has categorical labels.
    const showAnnotations = !inSharedMode && trendsFilter?.showAnnotations !== false
    const annotationsDates = currentPeriodResult?.days ?? []
    // In compare-against-previous grouped layouts each band holds two bars (previous, current).
    // Anchor each period's annotations on its matching bar so they line up with what they describe.
    const currentSeriesKey = isGrouped ? series.find((s) => s.meta?.compare_label === 'current')?.key : undefined
    const previousSeriesKey = isGrouped ? series.find((s) => s.meta?.compare_label === 'previous')?.key : undefined
    const previousPeriodResult = isGrouped
        ? indexedResults?.find((r: IndexedTrendResult) => r.compare_label === 'previous')
        : undefined
    const annotationsPreviousDates = previousPeriodResult?.days

    return (
        <TimeSeriesBarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            config={timeSeriesConfig}
            theme={theme}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            onDateRangeZoom={onDateRangeZoom}
            className="BarGraph"
            dataAttr="trend-bar-graph"
            onError={handleChartError}
        >
            {insight.id && (
                <TrendsAlertOverlays
                    insightId={insight.id}
                    insightProps={insightProps}
                    indexedResults={indexedResults}
                    getColor={getTrendsColor}
                    getYAxisId={getYAxisId}
                    isHidden={getTrendsHidden}
                />
            )}
            {showAnnotations && (
                <AnnotationsLayer
                    insightNumericId={insight.id || 'new'}
                    dates={annotationsDates}
                    seriesKey={currentSeriesKey}
                    previousDates={annotationsPreviousDates}
                    previousSeriesKey={previousSeriesKey}
                />
            )}
        </TimeSeriesBarChart>
    )
}
