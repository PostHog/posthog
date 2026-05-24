import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { TimeSeriesBarChart } from 'lib/hog-charts'
import type { PointClickData, TimeSeriesBarChartConfig, TooltipContext } from 'lib/hog-charts'
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
import { type TrendsChartClickDeps } from '../shared/handleTrendsChartClick'
import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { handleTrendsLifecycleChartClick } from './handleTrendsLifecycleChartClick'
import {
    buildTrendsLifecycleConfig,
    buildTrendsLifecycleSeries,
    shortenLifecycleLabel,
} from './trendsLifecycleChartTransforms'

interface TrendsLifecycleChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const EMPTY_LABELS: string[] = []
const LIFECYCLE_TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }

const buildLifecycleMeta = (r: IndexedTrendResult): TrendsSeriesMeta => ({
    action: r.action,
    breakdown_value: r.breakdown_value,
    compare_label: r.compare_label,
    days: r.days,
    order: r.action?.order ?? r.id,
    filter: r.filter,
})

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'trends-lifecycle-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

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
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)

    const isGrouped = !(lifecycleFilter?.stacked ?? true)

    const hasData =
        !!indexedResults?.[0] &&
        !!indexedResults[0].data &&
        indexedResults.some((r: IndexedTrendResult) => r.count !== 0)

    const { series, labels } = useMemo(() => {
        const lifecycleSeries = buildTrendsLifecycleSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
            buildMeta: buildLifecycleMeta,
        })
        return { series: lifecycleSeries, labels: currentPeriodResult?.labels ?? EMPTY_LABELS }
    }, [indexedResults, currentPeriodResult?.labels])

    const timeSeriesConfig: TimeSeriesBarChartConfig = useMemo(
        () =>
            buildTrendsLifecycleConfig({
                trendsFilter,
                baseCurrency,
                isGrouped,
                yAxisScaleType,
                interval,
                timezone,
                allDays: currentPeriodResult?.days ?? [],
                tooltip: LIFECYCLE_TOOLTIP_CONFIG,
            }),
        [trendsFilter, baseCurrency, isGrouped, yAxisScaleType, interval, timezone, currentPeriodResult?.days]
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
            handleTrendsLifecycleChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
        },
        [clickDeps]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsLifecycleChartClick(seriesKey, datum.dataIndex, clickDeps)
                  }
                : undefined
            const lifecycleCtx: TooltipContext<TrendsSeriesMeta> = {
                ...ctx,
                seriesData: ctx.seriesData.map((entry) => ({
                    ...entry,
                    series: {
                        ...entry.series,
                        label: shortenLifecycleLabel(entry.series.label),
                    },
                })),
            }
            return (
                <TrendsTooltip
                    context={lifecycleCtx}
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
