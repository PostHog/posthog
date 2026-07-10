import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { PointClickData, Series, TimeSeriesLineChartConfig, TooltipContext } from '@posthog/quill-charts'

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

import { chartStyleCurve } from '../../shared/chartStyleAdapter'
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
import { handleStickinessChartClick } from './handleStickinessChartClick'
import {
    buildStickinessLabels,
    buildStickinessLineTimeSeriesConfig,
    buildStickinessSeries,
    buildStickinessTooltipTitle,
    stickinessPercentFormatter,
    STICKINESS_TOOLTIP_CONFIG,
} from './stickinessChartTransforms'

interface StickinessLineChartProps {
    context?: QueryContext<InsightVizNode>
}

const handleChartError = makeChartErrorHandler('stickiness-line-chart')

export function StickinessLineChart({ context }: StickinessLineChartProps): JSX.Element | null {
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
        showMultipleYAxes,
        getTrendsColor,
        getTrendsHidden,
        currentPeriodResult,
        breakdownFilter,
        trendsFilter,
        stickinessFilter,
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

    const resolvedGroupTypeLabel = context?.groupTypeLabel ?? resolveGroupTypeLabel(labelGroupType, aggregationLabel)

    const getLabel = useCallback(
        (r: IndexedTrendResult): string =>
            getTrendsSeriesDisplayLabel(r, {
                breakdownFilter,
                cohorts: allCohorts?.results,
                formatPropertyValueForDisplay,
            }),
        [breakdownFilter, allCohorts?.results, formatPropertyValueForDisplay]
    )

    const bucketCount = currentPeriodResult?.labels?.length ?? 0
    const labels = useMemo(() => buildStickinessLabels(bucketCount, interval), [bucketCount, interval])

    const hasData =
        indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result: IndexedTrendResult) => result.count !== 0).length > 0

    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildStickinessSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                showMultipleYAxes: showMultipleYAxes ?? undefined,
                display: display ?? undefined,
                getColor: getTrendsColor,
                // With the quill legend on, hidden series stay listed (dimmed) and are excluded via
                // config.legend.hiddenKeys instead of being dropped here, so the legend can restore them.
                getHidden: quillLegendEnabled ? undefined : getTrendsHidden,
                getLabel,
                buildMeta: buildTrendsSeriesMeta,
            }),
        [indexedResults, display, getTrendsColor, getTrendsHidden, getLabel, showMultipleYAxes, quillLegendEnabled]
    )

    const chartConfig: TimeSeriesLineChartConfig = useChartConfig(
        () => ({
            ...buildStickinessLineTimeSeriesConfig({
                yAxisScaleType,
                valueLabels: showValuesOnSeries ? { formatter: stickinessPercentFormatter } : false,
                showCrosshair: true,
                tooltip: tooltipConfig,
            }),
            curve: chartStyleCurve(stickinessFilter?.chartStyle),
            // Interactive legend is a component concern, kept out of the pure transform.
            legend: legendConfig,
        }),
        [yAxisScaleType, showValuesOnSeries, legendConfig, tooltipConfig, stickinessFilter?.chartStyle]
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

    const altTitle = useMemo(() => buildStickinessTooltipTitle(interval), [interval])

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
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
                formatCompareLabel: context?.formatCompareLabel,
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
            context?.formatCompareLabel,
            canHandleClick,
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
                sampleDataVariant="line"
            />
        )
    }

    return (
        <TimeSeriesLineChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={chartConfig}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="LineGraph"
            dataAttr="trend-line-graph"
            onError={handleChartError}
        />
    )
}
