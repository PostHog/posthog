import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import type { ChartLegendConfig, ChartTheme, RadialSlicePayload, Series, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import {
    formatAggregationAxisValue,
    formatAggregationAxisValueWithShareOfTotal,
} from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'
import { datasetToActorsQuery } from 'products/product_analytics/frontend/insights/trends/viz/datasetToActorsQuery'

import { InsightSeriesTooltip } from '../../shared/InsightSeriesTooltip'
import { getSeriesIdentification } from '../../shared/seriesIdentification'
import { buildTrendsPieSeries } from '../TrendsPieChart/trendsPieTransforms'
import { getTrendsSeriesDisplayLabel } from './getTrendsSeriesDisplayLabel'
import { buildTrendsSeriesMeta, type TrendsSeriesMeta } from './trendsSeriesMeta'
import { useInsightsLegendConfig } from './useInsightsLegendConfig'

export interface TrendsPartOfWholeChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
    showPersonsModal?: boolean
}

export interface TrendsPartOfWholeChart {
    theme: ChartTheme
    legendConfig: ChartLegendConfig
    series: Series<TrendsSeriesMeta>[]
    hasResults: boolean
    showAggregation: boolean
    formattedTotal: string
    valueFormatter: (value: number) => string
    renderTooltip: (ctx: TooltipContext<TrendsSeriesMeta>) => JSX.Element
    onSliceClick: ((payload: RadialSlicePayload<TrendsSeriesMeta>) => void) | undefined
}

/** The data, legend, total, tooltip and click handling a trends pie, donut or proportion bar shares.
 *  `floorsNegativeParts` matches the total to a chart that draws a negative part as 0. */
export function useTrendsPartOfWholeChart({
    context,
    inSharedMode,
    showPersonsModal = true,
    floorsNegativeParts = false,
}: TrendsPartOfWholeChartProps & { floorsNegativeParts?: boolean }): TrendsPartOfWholeChart {
    const theme = useChartTheme()

    const { insightProps } = useValues(insightLogic)
    const legendConfig = useInsightsLegendConfig({ insightProps, inSharedMode })
    const { baseCurrency } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { aggregationLabel } = useValues(groupsModel)

    const {
        indexedResults,
        trendsFilter,
        formula,
        pieChartVizOptions,
        hasDataWarehouseSeries,
        querySource,
        breakdownFilter,
        labelGroupType,
        getTrendsColor,
        getTrendsHidden,
        isSingleSeriesDefinition,
    } = useValues(trendsDataLogic(insightProps))

    const seriesIdentification = useMemo(
        () => getSeriesIdentification((indexedResults ?? []).map(buildTrendsSeriesMeta)),
        [indexedResults]
    )

    const resolvedGroupTypeLabel =
        context?.groupTypeLabel ??
        (labelGroupType === 'people'
            ? 'people'
            : labelGroupType === 'none'
              ? ''
              : aggregationLabel(labelGroupType).plural)

    const onDataPointClick = context?.onDataPointClick

    // Share the line/bar label resolver so the legend humanizes event names ($pageview → Pageview)
    // and honors series renames, instead of showing the raw event key.
    const getLabel = useCallback(
        (r: IndexedTrendResult): string =>
            getTrendsSeriesDisplayLabel(r, {
                breakdownFilter,
                cohorts: allCohorts.results,
                formatPropertyValueForDisplay,
                isSingleSeriesDefinition,
                seriesIdentification,
            }),
        [
            breakdownFilter,
            allCohorts.results,
            formatPropertyValueForDisplay,
            isSingleSeriesDefinition,
            seriesIdentification,
        ]
    )

    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildTrendsPieSeries(indexedResults ?? [], {
                getColor: getTrendsColor,
                // Hidden series are listed (dimmed) and excluded via config.legend.hiddenKeys instead
                // of being dropped here, so the legend can restore them.
                getHidden: undefined,
                getLabel,
            }),
        [indexedResults, getTrendsColor, getLabel]
    )

    const visibleResults = useMemo(
        () => ((indexedResults ?? []) as IndexedTrendResult[]).filter((r) => !getTrendsHidden(r)),
        [indexedResults, getTrendsHidden]
    )

    const total = useMemo(
        () =>
            visibleResults.reduce((acc: number, r: IndexedTrendResult) => {
                const value = r.aggregated_value ?? 0
                if (!floorsNegativeParts) {
                    return acc + value
                }
                return acc + (Number.isFinite(value) ? Math.max(0, value) : 0)
            }, 0),
        [visibleResults, floorsNegativeParts]
    )

    const valueFormatter = useCallback(
        (v: number) => formatAggregationAxisValue(trendsFilter, v, baseCurrency),
        [trendsFilter, baseCurrency]
    )

    // ActionsPie disables clicks entirely when the insight has data-warehouse series (see
    // ActionsPie.tsx — `onClick={hasDataWarehouseSeries ? undefined : onClick}`); match that here.
    const canHandleClick = !hasDataWarehouseSeries && (!!onDataPointClick || (showPersonsModal && !formula))

    // Click parity with ActionsPie. The legacy path builds an InsightActorsQuery from the
    // GraphDataset.breakdownValues array; here each slice is already a single result, so we
    // pull its breakdown/compare straight from the IndexedTrendResult.
    const handleSliceClick = useCallback(
        (seriesKey: string, label: string | undefined) => {
            const result = visibleResults.find((r: IndexedTrendResult) => String(r.id) === seriesKey)
            if (!result) {
                return
            }
            if (onDataPointClick) {
                onDataPointClick(
                    {
                        breakdown: result.breakdown_value,
                        compare: result.compare_label || undefined,
                    },
                    // Legacy parity with ActionsPie — passes the first result, not the clicked one.
                    (indexedResults ?? [])[0]
                )
                return
            }
            if (!showPersonsModal || formula || hasDataWarehouseSeries || !querySource) {
                return
            }
            openPersonsModal({
                title: label || '',
                query: datasetToActorsQuery({
                    dataset: {
                        action: result.action,
                        breakdown_value: result.breakdown_value,
                        compare_label: result.compare_label,
                    },
                    query: querySource,
                }),
                additionalSelect: {
                    value_at_data_point: 'event_count',
                    matched_recordings: 'matched_recordings',
                },
                orderBy: ['event_count DESC, actor_id DESC'],
            })
        },
        [
            visibleResults,
            indexedResults,
            onDataPointClick,
            showPersonsModal,
            formula,
            hasDataWarehouseSeries,
            querySource,
        ]
    )

    const onSliceClick = useCallback(
        (payload: RadialSlicePayload<TrendsSeriesMeta>) => handleSliceClick(payload.series.key, payload.series.label),
        [handleSliceClick]
    )

    const renderCount = useCallback(
        (value: number) => formatAggregationAxisValueWithShareOfTotal(trendsFilter, value, total, baseCurrency),
        [trendsFilter, total, baseCurrency]
    )

    const onRowClick = useMemo(
        () => (canHandleClick ? (datum: SeriesDatum) => handleSliceClick(String(datum.id), datum.label) : undefined),
        [canHandleClick, handleSliceClick]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => (
            <InsightSeriesTooltip
                context={ctx}
                breakdownFilter={breakdownFilter ?? undefined}
                trendsFilter={trendsFilter}
                baseCurrency={baseCurrency}
                groupTypeLabel={resolvedGroupTypeLabel}
                formatCompareLabel={context?.formatCompareLabel}
                onRowClick={onRowClick}
                showHeader={false}
                renderCount={renderCount}
            />
        ),
        [
            breakdownFilter,
            trendsFilter,
            baseCurrency,
            resolvedGroupTypeLabel,
            context?.formatCompareLabel,
            onRowClick,
            renderCount,
        ]
    )

    return {
        theme,
        legendConfig,
        series,
        hasResults: !!(indexedResults ?? []).length,
        showAggregation: !pieChartVizOptions?.hideAggregation,
        formattedTotal: formatAggregationAxisValue(trendsFilter, total, baseCurrency),
        valueFormatter,
        renderTooltip,
        onSliceClick: canHandleClick ? onSliceClick : undefined,
    }
}
