import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { TimeSeriesBarChart } from '@posthog/quill-charts'
import type { PointClickData, Series, TimeSeriesBarChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { INSIGHT_TOOLTIP_CONFIG_LEGACY } from '../../shared/tooltipConfig'
import { makeChartErrorHandler } from '../../trends/shared/chartErrorHandler'
import { getTrendsSeriesDisplayLabel } from '../../trends/shared/getTrendsSeriesDisplayLabel'
import {
    buildTrendsSeriesMeta,
    resolveGroupTypeLabel,
    type TrendsSeriesMeta,
} from '../../trends/shared/trendsSeriesMeta'
import { TrendsTooltip } from '../../trends/shared/TrendsTooltip'
import { useInsightsLegendConfig } from '../../trends/shared/useInsightsLegendConfig'
import { handleStickinessChartClick } from '../StickinessLineChart/handleStickinessChartClick'
import {
    buildStickinessLabels,
    buildStickinessTooltipTitle,
    stickinessPercentFormatter,
    STICKINESS_TOOLTIP_CONFIG,
} from '../StickinessLineChart/stickinessChartTransforms'
import { buildStickinessBarSeries, buildStickinessBarTimeSeriesConfig } from './stickinessBarChartTransforms'

interface StickinessBarChartProps {
    context?: QueryContext<InsightVizNode>
}

const handleChartError = makeChartErrorHandler('stickiness-bar-chart')

export function StickinessBarChart({ context }: StickinessBarChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const { insightProps } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]
    const tooltipConfig = quillTooltipEnabled ? STICKINESS_TOOLTIP_CONFIG : INSIGHT_TOOLTIP_CONFIG_LEGACY

    const legendConfig = useInsightsLegendConfig({ insightProps })
    const quillLegendEnabled = !!legendConfig

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

    // Inverted polarity vs legacy `isStacked` in `ActionsLineGraph`; matches `TrendsBarChart`.
    const isGrouped = display === ChartDisplayType.ActionsUnstackedBar

    const resolvedGroupTypeLabel = context?.groupTypeLabel ?? resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    const bucketCount = currentPeriodResult?.labels?.length ?? 0
    const labels = useMemo(() => buildStickinessLabels(bucketCount, interval), [bucketCount, interval])

    const hasData = (indexedResults ?? []).some((r: IndexedTrendResult) => r.count !== 0)

    // `TimeSeriesBarChart` has a single y-axis — `showMultipleYAxes` is intentionally not forwarded.
    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildStickinessBarSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                // With the quill legend on, hidden series stay listed (dimmed) and are excluded via
                // config.legend.hiddenKeys instead of being dropped here, so the legend can restore them.
                getHidden: quillLegendEnabled ? undefined : getTrendsHidden,
                getLabel,
                buildMeta: buildTrendsSeriesMeta,
            }),
        [indexedResults, getTrendsColor, getTrendsHidden, getLabel, quillLegendEnabled]
    )

    const chartConfig: TimeSeriesBarChartConfig = useChartConfig(
        () => ({
            ...buildStickinessBarTimeSeriesConfig({
                yAxisScaleType,
                isGrouped,
                valueLabels: showValuesOnSeries ? { formatter: stickinessPercentFormatter } : false,
                tooltip: tooltipConfig,
            }),
            // Interactive legend is a component concern, kept out of the pure transform.
            legend: legendConfig,
        }),
        [yAxisScaleType, isGrouped, showValuesOnSeries, legendConfig, tooltipConfig]
    )

    // Close over the primitives so the click memos don't invalidate when unrelated
    // context fields change. `openPersonsModal` is a stable module import.
    const onDataPointClick = context?.onDataPointClick
    const formatCompareLabel = context?.formatCompareLabel
    const hasClickHandler = !!onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo(
        () => ({
            context: onDataPointClick ? { onDataPointClick } : undefined,
            hasPersonsModal: !!hasPersonsModal,
            interval,
            querySource,
            indexedResults: indexedResults ?? [],
            openPersonsModal,
        }),
        [onDataPointClick, hasPersonsModal, interval, querySource, indexedResults]
    )

    const onPointClick = useCallback(
        (clickData: PointClickData) => {
            handleStickinessChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
        },
        [clickDeps]
    )

    const altTitle = useMemo(() => buildStickinessTooltipTitle(interval), [interval])

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = hasClickHandler
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleStickinessChartClick(seriesKey, datum.dataIndex, clickDeps)
                  }
                : undefined
            const sharedProps = {
                context: ctx,
                timezone,
                interval: interval ?? undefined,
                breakdownFilter: breakdownFilter ?? undefined,
                trendsFilter,
                showPercentView: true as const,
                isPercentStackView: false as const,
                baseCurrency,
                groupTypeLabel: resolvedGroupTypeLabel,
                formatCompareLabel,
                onRowClick,
                altTitle,
            }
            return quillTooltipEnabled ? <InsightSeriesTooltip {...sharedProps} /> : <TrendsTooltip {...sharedProps} />
        },
        [
            timezone,
            interval,
            breakdownFilter,
            trendsFilter,
            formula,
            baseCurrency,
            resolvedGroupTypeLabel,
            formatCompareLabel,
            hasClickHandler,
            clickDeps,
            altTitle,
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

    return (
        <TimeSeriesBarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={chartConfig}
            tooltip={renderTooltip}
            onPointClick={hasClickHandler ? onPointClick : undefined}
            className="BarGraph"
            dataAttr="stickiness-bar-graph"
            onError={handleChartError}
        />
    )
}
