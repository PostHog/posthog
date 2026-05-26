import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import {
    BarChart,
    buildYTickFormatter,
    DEFAULT_Y_AXIS_ID,
    ReferenceLines,
    TimeSeriesBarChart,
    ValueLabels,
} from 'lib/hog-charts'
import type { BarChartConfig, PointClickData, TimeSeriesBarChartConfig, TooltipContext } from 'lib/hog-charts'
import { percentage } from 'lib/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
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
import { ChartDisplayType } from '~/types'

import { AnnotationsLayer } from '../shared/AnnotationsLayer'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { goalLinesToReferenceLines } from '../shared/goalLinesAdapter'
import { handleTrendsChartClick, type TrendsChartClickDeps } from '../shared/handleTrendsChartClick'
import { TrendsAlertOverlays } from '../shared/TrendsAlertOverlays'
import { trendsFilterToYFormatterConfig } from '../shared/trendsAxisFormat'
import { buildTrendsSeriesMeta, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { handleTrendsBarAggregatedChartClick } from './handleTrendsBarAggregatedChartClick'
import {
    buildTrendsBarAggregatedSeries,
    buildTrendsBarTimeSeries,
    buildTrendsBarTimeSeriesConfig,
} from './trendsBarChartTransforms'

interface TrendsBarChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const EMPTY_LABELS: string[] = []
const TIME_SERIES_TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }
const AGGREGATED_TOOLTIP_CONFIG = { pinnable: false }

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

export function TrendsBarChart({ context, inSharedMode = false }: TrendsBarChartProps): JSX.Element | null {
    const theme = useMemo(() => buildTheme(), [])
    const { insightProps, insight } = useValues(insightLogic)

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
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const isAggregated = display === ChartDisplayType.ActionsBarValue
    const isGrouped = display === ChartDisplayType.ActionsUnstackedBar
    const isPercentStackView = !isAggregated && !!showPercentStackView && !!supportsPercentStackView

    const resolvedGroupTypeLabel = resolveGroupTypeLabel(labelGroupType, aggregationLabel, context?.groupTypeLabel)

    const hasData =
        !!indexedResults?.[0] &&
        (isAggregated
            ? indexedResults.some(
                  (r: IndexedTrendResult) => Number.isFinite(r.aggregated_value) && r.aggregated_value !== 0
              )
            : !!indexedResults[0].data && indexedResults.some((r: IndexedTrendResult) => r.count !== 0))

    const { series, labels } = useMemo(() => {
        if (isAggregated) {
            return buildTrendsBarAggregatedSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: buildTrendsSeriesMeta,
            })
        }
        const timeSeries = buildTrendsBarTimeSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
            getColor: getTrendsColor,
            getHidden: getTrendsHidden,
            buildMeta: buildTrendsSeriesMeta,
        })
        return { series: timeSeries, labels: currentPeriodResult?.labels ?? EMPTY_LABELS }
    }, [isAggregated, indexedResults, getTrendsColor, getTrendsHidden, currentPeriodResult?.labels])

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

    const timeSeriesConfig: TimeSeriesBarChartConfig = useMemo(
        () =>
            buildTrendsBarTimeSeriesConfig({
                trendsFilter,
                baseCurrency,
                isPercentStackView,
                isGrouped,
                yAxisScaleType,
                interval,
                timezone,
                allDays: currentPeriodResult?.days ?? [],
                goalLines,
                valueLabels: showValuesOnSeries ? { formatter: valueLabelFormatter } : false,
                tooltip: TIME_SERIES_TOOLTIP_CONFIG,
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
            goalLines,
            showValuesOnSeries,
            valueLabelFormatter,
        ]
    )

    const aggregatedYTickFormatter = useMemo(
        () => buildYTickFormatter(trendsFilterToYFormatterConfig(trendsFilter, isPercentStackView, baseCurrency)),
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const aggregatedConfig: BarChartConfig = useMemo(
        () => ({
            showGrid: true,
            tooltip: AGGREGATED_TOOLTIP_CONFIG,
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            axisOrientation: 'horizontal',
            barLayout: 'stacked',
            yTickFormatter: aggregatedYTickFormatter,
        }),
        [yAxisScaleType, aggregatedYTickFormatter]
    )

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

    // Bar charts don't yet expose multi-axis configuration, so all series live on the
    // primary axis — alert anomaly markers always read the default scale.
    const getYAxisId = useCallback(() => DEFAULT_Y_AXIS_ID, [])

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

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            // Sparse-stacked: drop sibling series with data=0 at this band so the tooltip shows one row.
            const tooltipCtx: TooltipContext<TrendsSeriesMeta> = isAggregated
                ? {
                      ...ctx,
                      seriesData: ctx.seriesData.filter((entry) => {
                          const raw = entry.series.data[ctx.dataIndex]
                          return typeof raw === 'number' && raw !== 0
                      }),
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
            return (
                <TrendsTooltip
                    context={tooltipCtx}
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
                    showHeader={isAggregated ? false : undefined}
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
            isAggregated,
        ]
    )

    if (!hasData) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
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
    const showAnnotations = !inSharedMode
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
