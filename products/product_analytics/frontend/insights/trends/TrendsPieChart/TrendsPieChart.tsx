import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import {
    formatAggregationAxisValue,
    formatAggregationAxisValueWithShareOfTotal,
} from '@posthog/query-frontend/nodes/InsightViz/aggregationAxisFormat'
import { InsightEmptyState } from '@posthog/query-frontend/nodes/InsightViz/EmptyStates'
import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'
import type { IndexedTrendResult } from '@posthog/query-frontend/nodes/TrendsQuery/types'
import { datasetToActorsQuery } from '@posthog/query-frontend/nodes/TrendsQuery/viz/datasetToActorsQuery'
import { openPersonsModal } from '@posthog/query-frontend/persons-modal/PersonsModal'
import { InsightVizNode } from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'
import { PieChart } from '@posthog/quill-charts'
import type { PieChartConfig, RadialSlicePayload, Series, TooltipContext } from '@posthog/quill-charts'
import { buildTheme } from '@posthog/visualizations/charts/utils/theme'
import type { SeriesDatum } from '@posthog/visualizations/InsightTooltip/insightTooltipUtils'

import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { TrendsTooltip } from '../shared/TrendsTooltip'
import { buildTrendsPieSeries } from './trendsPieTransforms'

interface TrendsPieChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
    showPersonsModal?: boolean
}

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'trends-pie-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function TrendsPieChart({
    context,
    inSharedMode = false,
    showPersonsModal = true,
}: TrendsPieChartProps): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    // isDarkModeOn invalidates the memo so buildTheme() re-reads CSS vars on dark-mode toggle.
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const { insightProps } = useValues(insightLogic)
    const { baseCurrency } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { aggregationLabel } = useValues(groupsModel)

    const {
        indexedResults,
        trendsFilter,
        formula,
        showValuesOnSeries,
        showLabelOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        pieChartVizOptions,
        hasDataWarehouseSeries,
        querySource,
        breakdownFilter,
        labelGroupType,
        getTrendsColor,
        getTrendsHidden,
    } = useValues(trendsDataLogic(insightProps))

    const isPercentStackView = !!showPercentStackView && !!supportsPercentStackView

    const resolvedGroupTypeLabel =
        context?.groupTypeLabel ??
        (labelGroupType === 'people'
            ? 'people'
            : labelGroupType === 'none'
              ? ''
              : aggregationLabel(labelGroupType).plural)

    const onDataPointClick = context?.onDataPointClick
    const showAggregation = !pieChartVizOptions?.hideAggregation

    const getLabel = useCallback(
        (r: IndexedTrendResult): string =>
            breakdownFilter
                ? formatBreakdownLabel(
                      r.breakdown_value,
                      breakdownFilter,
                      allCohorts.results,
                      formatPropertyValueForDisplay
                  )
                : (r.label ?? ''),
        [breakdownFilter, allCohorts.results, formatPropertyValueForDisplay]
    )

    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildTrendsPieSeries(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                getLabel,
            }),
        [indexedResults, getTrendsColor, getTrendsHidden, getLabel]
    )

    const visibleResults = useMemo(
        () => ((indexedResults ?? []) as IndexedTrendResult[]).filter((r) => !getTrendsHidden(r)),
        [indexedResults, getTrendsHidden]
    )

    const total = useMemo(
        () => visibleResults.reduce((acc: number, r: IndexedTrendResult) => acc + (r.aggregated_value ?? 0), 0),
        [visibleResults]
    )

    const valueFormatter = useCallback(
        (v: number) => formatAggregationAxisValue(trendsFilter, v, baseCurrency),
        [trendsFilter, baseCurrency]
    )

    const pieConfig: PieChartConfig<TrendsSeriesMeta> = useMemo(
        () => ({
            showValueOnSlice: !!showValuesOnSeries,
            showLabelOnSlice: !!showLabelOnSeries,
            isPercent: isPercentStackView,
            disableHoverOffset: !!pieChartVizOptions?.disableHoverOffset,
        }),
        [showValuesOnSeries, showLabelOnSeries, isPercentStackView, pieChartVizOptions?.disableHoverOffset]
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
            <TrendsTooltip
                context={ctx}
                breakdownFilter={breakdownFilter ?? undefined}
                trendsFilter={trendsFilter}
                formula={formula}
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
            formula,
            baseCurrency,
            resolvedGroupTypeLabel,
            context?.formatCompareLabel,
            onRowClick,
            renderCount,
        ]
    )

    if (!visibleResults.length) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    return (
        <div className={`flex flex-col w-full h-full ${inSharedMode ? 'ActionsPie--shared' : 'ActionsPie'}`}>
            <PieChart<TrendsSeriesMeta>
                series={series}
                theme={theme}
                config={pieConfig}
                tooltip={renderTooltip}
                onSliceClick={canHandleClick ? onSliceClick : undefined}
                valueFormatter={valueFormatter}
                dataAttr="trend-pie-graph"
                onError={handleChartError}
            />
            {showAggregation && (
                <div className="text-7xl text-center font-bold m-0">
                    {formatAggregationAxisValue(trendsFilter, total, baseCurrency)}
                </div>
            )}
        </div>
    )
}
