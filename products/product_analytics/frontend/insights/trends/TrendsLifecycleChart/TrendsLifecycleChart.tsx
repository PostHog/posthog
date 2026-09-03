import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { TimeSeriesBarChart } from '@posthog/quill-charts'
import type { ChartLegendConfig, PointClickData, TooltipContext } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme, useDateRangeZoom } from 'lib/charts/hooks'
import { getBarColorFromStatus } from 'lib/colors'
import { AnnotationsLayer } from 'lib/components/AnnotationsOverlay/AnnotationsLayer'
import { useChartLegendSeriesMenu } from 'lib/components/ChartLegendSeriesMenu/useChartLegendSeriesMenu'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import type { LifecycleToggle } from '~/types'

import { hasTrendsChartData } from '../../shared/hasTrendsChartData'
import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { buildBaseLegendConfig } from '../shared/buildBaseLegendConfig'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import {
    handleTrendsChartClick,
    LIFECYCLE_PERSONS_MODAL_OPTIONS,
    type TrendsChartClickDeps,
} from '../shared/handleTrendsChartClick'
import { buildTrendsSeriesMeta, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { buildLifecycleChartModel, buildLifecycleValueLabelFormatter } from './trendsLifecycleChartTransforms'

interface TrendsLifecycleChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const EMPTY_LABELS: string[] = []
const LIFECYCLE_TOOLTIP_CONFIG = { placement: 'cursor' as const }

const handleChartError = makeChartErrorHandler('trends-lifecycle-chart')

// Lifecycle rows label themselves by status ("New", "Returning", ...) — not by
// the underlying event/action. The row's ribbon color already identifies the
// series, so we render the label as plain text and skip InsightLabel (which
// would otherwise prefer `action.name` like "$pageview").
const renderLifecycleSeriesLabel = (datum: SeriesDatum): React.ReactNode => datum.label

export function TrendsLifecycleChart({ context, inSharedMode = false }: TrendsLifecycleChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const { insightProps, insight, canEditInsight } = useValues(insightLogic)

    const {
        indexedResults,
        interval,
        yAxisScaleType,
        currentPeriodResult,
        breakdownFilter,
        insightData,
        trendsFilter,
        lifecycleFilter,
        formula,
        hasPersonsModal,
        querySource,
        showValuesOnSeries,
        showPercentagesOnSeries,
        showLegend,
        legendPosition,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)

    // Lifecycle statuses all share the same resultCustomizationKey (same action.order), so
    // useInsightsLegendConfig can't distinguish them — build the config inline and let the
    // chart manage toggle state internally.
    const legendRenderItem = useChartLegendSeriesMenu({ surface: 'lifecycle', seriesCount: indexedResults.length })
    const legendConfig = useMemo<ChartLegendConfig>(
        () =>
            buildBaseLegendConfig({
                show: !!showLegend,
                legendPosition,
                canEditInsight,
                inSharedMode,
                renderItem: legendRenderItem,
            }),
        [showLegend, legendPosition, canEditInsight, inSharedMode, legendRenderItem]
    )

    const isStacked = lifecycleFilter?.stacked ?? true

    const hasData = hasTrendsChartData(indexedResults)

    const formatValue = useCallback(
        (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
        [trendsFilter, baseCurrency]
    )

    // Dormant counts are emitted negative so they stack below the zero baseline, but the tooltip
    // shows the magnitude — the "Dormant" label already carries the direction.
    const renderTooltipCount = useCallback((value: number) => formatValue(Math.abs(value)), [formatValue])

    const valueLabelFormatter = useMemo(
        () =>
            buildLifecycleValueLabelFormatter(formatValue, {
                showValues: !!showValuesOnSeries,
                showPercentages: !!showPercentagesOnSeries,
            }),
        [formatValue, showValuesOnSeries, showPercentagesOnSeries]
    )

    const {
        series,
        labels,
        config: baseConfig,
    } = useMemo(
        () =>
            buildLifecycleChartModel<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: (status) => getBarColorFromStatus((status ?? 'new') as LifecycleToggle),
                buildMeta: buildTrendsSeriesMeta,
                // Bands are keyed by these strings, so they must be unique per point. Display
                // labels are not (week and hour labels omit the year, so multi-year ranges
                // repeat them); use the ISO days, which ticks and tooltips format from.
                labels: currentPeriodResult?.days?.length
                    ? currentPeriodResult.days
                    : (currentPeriodResult?.labels ?? EMPTY_LABELS),
                isStacked,
                trendsFilter,
                baseCurrency,
                yAxisScaleType,
                interval,
                timezone,
                allDays: currentPeriodResult?.days ?? [],
                valueLabels: showValuesOnSeries || showPercentagesOnSeries ? { formatter: valueLabelFormatter } : false,
                tooltip: LIFECYCLE_TOOLTIP_CONFIG,
                legend: legendConfig,
            }),
        [
            indexedResults,
            currentPeriodResult?.labels,
            currentPeriodResult?.days,
            isStacked,
            trendsFilter,
            baseCurrency,
            yAxisScaleType,
            interval,
            timezone,
            showValuesOnSeries,
            showPercentagesOnSeries,
            valueLabelFormatter,
            legendConfig,
        ]
    )
    const config = useChartConfig(() => baseConfig, [baseConfig])

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

    const onPointClick = useCallback(
        (clickData: PointClickData<TrendsSeriesMeta>) => {
            handleTrendsChartClick(
                clickData.series.key,
                clickData.dataIndex,
                clickDeps,
                LIFECYCLE_PERSONS_MODAL_OPTIONS
            )
        },
        [clickDeps]
    )

    const onDateRangeZoom = useDateRangeZoom(currentPeriodResult?.days, context?.onDateRangeZoom)

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const sharedProps = {
                context: ctx,
                timezone,
                interval: interval ?? undefined,
                breakdownFilter: breakdownFilter ?? undefined,
                dateRange: insightData?.resolved_date_range ?? undefined,
                trendsFilter,
                formula,
                baseCurrency,
                groupTypeLabel: 'Users' as const,
                renderSeriesOverride: renderLifecycleSeriesLabel,
                renderCount: renderTooltipCount,
            }
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps, LIFECYCLE_PERSONS_MODAL_OPTIONS)
                  }
                : undefined
            return <InsightSeriesTooltip {...sharedProps} sortedByValue={false} hideZeroRows onRowClick={onRowClick} />
        },
        [
            timezone,
            interval,
            breakdownFilter,
            insightData?.resolved_date_range,
            trendsFilter,
            formula,
            baseCurrency,
            renderTooltipCount,
            canHandleClick,
            clickDeps,
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

    const showAnnotations = !inSharedMode
    const annotationsDates = currentPeriodResult?.days ?? []

    return (
        <TimeSeriesBarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            config={config}
            theme={theme}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            onDateRangeZoom={onDateRangeZoom}
            className="BarGraph"
            dataAttr="trend-lifecycle-graph"
            onError={handleChartError}
        >
            {showAnnotations && <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationsDates} />}
        </TimeSeriesBarChart>
    )
}
