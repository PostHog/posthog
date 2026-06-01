import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { TimeSeriesBarChart } from 'lib/hog-charts'
import type { PointClickData, TimeSeriesBarChartConfig, TooltipContext } from 'lib/hog-charts'
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

import { AnnotationsLayer } from '../shared/AnnotationsLayer'
import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import {
    handleTrendsChartClick,
    LIFECYCLE_PERSONS_MODAL_OPTIONS,
    type TrendsChartClickDeps,
} from '../shared/handleTrendsChartClick'
import { buildTrendsSeriesMeta, type TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { buildTrendsLifecycleConfig, buildTrendsLifecycleSeries } from './trendsLifecycleChartTransforms'

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
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)

    const isStacked = lifecycleFilter?.stacked ?? true

    const hasData =
        !!indexedResults?.[0] &&
        !!indexedResults[0].data &&
        indexedResults.some((r: IndexedTrendResult) => r.count !== 0)

    const { series, labels } = useMemo(() => {
        const lifecycleSeries = buildTrendsLifecycleSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
            buildMeta: buildTrendsSeriesMeta,
        })
        return { series: lifecycleSeries, labels: currentPeriodResult?.labels ?? EMPTY_LABELS }
    }, [indexedResults, currentPeriodResult?.labels])

    const valueLabelFormatter = useCallback(
        (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
        [trendsFilter, baseCurrency]
    )

    const timeSeriesConfig: TimeSeriesBarChartConfig = useMemo(
        () =>
            buildTrendsLifecycleConfig({
                trendsFilter,
                baseCurrency,
                isStacked,
                yAxisScaleType,
                interval,
                timezone,
                allDays: currentPeriodResult?.days ?? [],
                valueLabels: showValuesOnSeries ? { formatter: valueLabelFormatter } : false,
                tooltip: LIFECYCLE_TOOLTIP_CONFIG,
            }),
        [
            trendsFilter,
            baseCurrency,
            isStacked,
            yAxisScaleType,
            interval,
            timezone,
            currentPeriodResult?.days,
            showValuesOnSeries,
            valueLabelFormatter,
        ]
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
        <TimeSeriesBarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            config={timeSeriesConfig}
            theme={theme}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="BarGraph"
            dataAttr="trend-lifecycle-graph"
            onError={handleChartError}
        >
            {showAnnotations && <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationsDates} />}
        </TimeSeriesBarChart>
    )
}
