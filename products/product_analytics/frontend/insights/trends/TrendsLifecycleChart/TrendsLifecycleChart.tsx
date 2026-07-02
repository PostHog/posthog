import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { TimeSeriesBarChart } from '@posthog/quill-charts'
import type { ChartLegendConfig, PointClickData, TooltipContext } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getBarColorFromStatus } from 'lib/colors'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { AnnotationsLayer } from '../shared/AnnotationsLayer'
import { buildBaseLegendConfig } from '../shared/buildBaseLegendConfig'
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
const LIFECYCLE_TOOLTIP_CONFIG = { placement: 'cursor' as const }
const LIFECYCLE_TOOLTIP_CONFIG_LEGACY = { pinnable: true, placement: 'top' as const }

const handleChartError = makeChartErrorHandler('trends-lifecycle-chart')

// Lifecycle rows label themselves by status ("New", "Returning", ...) — not by
// the underlying event/action. The row's ribbon color already identifies the
// series, so we render the label as plain text and skip InsightLabel (which
// would otherwise prefer `action.name` like "$pageview").
const renderLifecycleSeriesLabel = (datum: SeriesDatum): React.ReactNode => datum.label

export function TrendsLifecycleChart({ context, inSharedMode = false }: TrendsLifecycleChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]
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
    const legendConfig = useMemo<ChartLegendConfig>(
        () => buildBaseLegendConfig({ show: !!showLegend, legendPosition, canEditInsight, inSharedMode }),
        [showLegend, legendPosition, canEditInsight, inSharedMode]
    )

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

    const {
        series,
        labels,
        config: baseConfig,
    } = useMemo(
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
                tooltip: quillTooltipEnabled ? LIFECYCLE_TOOLTIP_CONFIG : LIFECYCLE_TOOLTIP_CONFIG_LEGACY,
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
            quillTooltipEnabled,
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
            }
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps, LIFECYCLE_PERSONS_MODAL_OPTIONS)
                  }
                : undefined
            return quillTooltipEnabled ? (
                <InsightSeriesTooltip {...sharedProps} sortedByValue={false} hideZeroRows onRowClick={onRowClick} />
            ) : (
                <TrendsTooltip {...sharedProps} onRowClick={onRowClick} />
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
            quillTooltipEnabled,
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
            config={config}
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
