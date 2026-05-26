import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { TimeSeriesBarChart } from 'lib/hog-charts'
import type { PointClickData, Series, TimeSeriesBarChartConfig, TooltipConfig, TooltipContext } from 'lib/hog-charts'
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
import { ChartDisplayType } from '~/types'

import { resolveGroupTypeLabel, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { handleStickinessChartClick } from '../StickinessLineChart/handleStickinessChartClick'
import { buildStickinessLabels, stickinessPercentFormatter } from '../StickinessLineChart/stickinessChartTransforms'
import { buildStickinessBarSeries, buildStickinessBarTimeSeriesConfig } from './stickinessBarChartTransforms'

interface StickinessBarChartProps {
    context?: QueryContext<InsightVizNode>
}

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'stickiness-bar-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

/** Stickiness `date` is an interval-count integer (1, 2, …), not a date.
 *  Render "stickiness on {interval} {day}" so InsightTooltip doesn't try to
 *  format it as a calendar date (which would land on 1970-01-01). */
function buildStickinessAltTitle(interval: string | null | undefined): (seriesData: SeriesDatum[]) => string {
    return (seriesData) => {
        const day = seriesData[0]?.date_label ?? ''
        return `stickiness on ${interval || 'day'} ${day}`
    }
}

export function StickinessBarChart({ context }: StickinessBarChartProps): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
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

    const isGrouped = display === ChartDisplayType.ActionsUnstackedBar

    const resolvedGroupTypeLabel = context?.groupTypeLabel ?? resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    const bucketCount = currentPeriodResult?.labels?.length ?? 0
    const labels = useMemo(() => buildStickinessLabels(bucketCount, interval), [bucketCount, interval])

    const hasData =
        indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result: IndexedTrendResult) => result.count !== 0).length > 0

    // No `showMultipleYAxes` passthrough — `TimeSeriesBarChart` only declares a single
    // y-axis today. All series land on `DEFAULT_Y_AXIS_ID` until multi-axis support arrives.
    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildStickinessBarSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: (rr) => ({
                    action: rr.action,
                    breakdown_value: rr.breakdown_value,
                    compare_label: rr.compare_label,
                    days: rr.days,
                    order: rr.action?.order ?? rr.id,
                    filter: rr.filter,
                }),
            }),
        [indexedResults, getTrendsColor, getTrendsHidden]
    )

    const chartConfig: TimeSeriesBarChartConfig = useMemo(
        () =>
            buildStickinessBarTimeSeriesConfig({
                yAxisScaleType,
                isGrouped,
                valueLabels: showValuesOnSeries ? { formatter: stickinessPercentFormatter } : false,
                tooltip: TOOLTIP_CONFIG,
            }),
        [yAxisScaleType, isGrouped, showValuesOnSeries]
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

    const altTitle = useMemo(() => buildStickinessAltTitle(interval), [interval])

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
        <TimeSeriesBarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={chartConfig}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="BarGraph"
            dataAttr="trend-bar-graph"
            onError={handleChartError}
        />
    )
}
