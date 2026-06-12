import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { formatAggregationAxisValue } from '@posthog/query-frontend/nodes/InsightViz/aggregationAxisFormat'
import { InsightEmptyState } from '@posthog/query-frontend/nodes/InsightViz/EmptyStates'
import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'
import type { IndexedTrendResult } from '@posthog/query-frontend/nodes/TrendsQuery/types'
import { openPersonsModal } from '@posthog/query-frontend/persons-modal/PersonsModal'
import { InsightVizNode } from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'
import { ChartLegend, TimeSeriesBarChart, legendItemsFromSeries } from '@posthog/quill-charts'
import type { PointClickData, TooltipContext } from '@posthog/quill-charts'
import { buildTheme } from '@posthog/visualizations/charts/utils/theme'
import type { SeriesDatum } from '@posthog/visualizations/InsightTooltip/insightTooltipUtils'

import { getBarColorFromStatus } from 'lib/colors'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { LifecycleToggle } from '~/types'

import { AnnotationsLayer } from '../shared/AnnotationsLayer'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import {
    handleTrendsChartClick,
    LIFECYCLE_PERSONS_MODAL_OPTIONS,
    type TrendsChartClickDeps,
} from '../shared/handleTrendsChartClick'
import { buildTrendsSeriesMeta, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { buildLifecycleChartModel, buildLifecycleValueLabelFormatter } from './trendsLifecycleChartTransforms'

interface TrendsLifecycleChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const EMPTY_LABELS: string[] = []
const LIFECYCLE_TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }

const handleChartError = makeChartErrorHandler('trends-lifecycle-chart')

// Lifecycle rows label themselves by status ("New", "Returning", ...) — not by
// the underlying event/action. The row's ribbon color already identifies the
// series, so we render the label as plain text and skip InsightLabel (which
// would otherwise prefer `action.name` like "$pageview").
const renderLifecycleSeriesLabel = (datum: SeriesDatum): React.ReactNode => datum.label

export function TrendsLifecycleChart({ context, inSharedMode = false }: TrendsLifecycleChartProps): JSX.Element | null {
    const theme = useMemo(() => buildTheme(), [])
    const { insightProps, insight } = useValues(insightLogic)

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
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)

    const isStacked = lifecycleFilter?.stacked ?? true

    const hasData =
        !!indexedResults?.[0] &&
        !!indexedResults[0].data &&
        indexedResults.some((r: IndexedTrendResult) => r.count !== 0)

    const formatValue = useCallback(
        (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
        [trendsFilter, baseCurrency]
    )

    const valueLabelFormatter = useMemo(
        () =>
            buildLifecycleValueLabelFormatter(formatValue, {
                showValues: !!showValuesOnSeries,
                showPercentages: !!showPercentagesOnSeries,
            }),
        [formatValue, showValuesOnSeries, showPercentagesOnSeries]
    )

    const { series, labels, config } = useMemo(
        () =>
            buildLifecycleChartModel<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: (status) => getBarColorFromStatus((status ?? 'new') as LifecycleToggle),
                buildMeta: buildTrendsSeriesMeta,
                labels: currentPeriodResult?.labels ?? EMPTY_LABELS,
                isStacked,
                trendsFilter,
                baseCurrency,
                yAxisScaleType,
                interval,
                timezone,
                allDays: currentPeriodResult?.days ?? [],
                valueLabels: showValuesOnSeries || showPercentagesOnSeries ? { formatter: valueLabelFormatter } : false,
                tooltip: LIFECYCLE_TOOLTIP_CONFIG,
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
        ]
    )

    const legendItems = useMemo(() => legendItemsFromSeries(series, theme), [series, theme])

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

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps, LIFECYCLE_PERSONS_MODAL_OPTIONS)
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
                    baseCurrency={baseCurrency}
                    groupTypeLabel="Users"
                    onRowClick={onRowClick}
                    renderSeriesOverride={renderLifecycleSeriesLabel}
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
            baseCurrency,
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
        <ChartLegend show={!!showLegend} items={legendItems} position="top" legendDataAttr="trend-lifecycle-legend">
            <TimeSeriesBarChart<TrendsSeriesMeta>
                series={series}
                labels={labels}
                config={config}
                theme={theme}
                tooltip={renderTooltip}
                onPointClick={canHandleClick ? onPointClick : undefined}
                className="BarGraph"
                dataAttr="trend-lifecycle-graph"
                onError={handleChartError}
            >
                {showAnnotations && (
                    <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationsDates} />
                )}
            </TimeSeriesBarChart>
        </ChartLegend>
    )
}
