import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { PieChart } from 'lib/hog-charts'
import type { PieChartConfig, RadialSlicePayload, Series, TooltipContext } from 'lib/hog-charts'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import type { TrendsSeriesMeta } from '../shared/trendsSeriesMeta'
import { PieTooltip } from './PieTooltip'
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
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const { insightProps } = useValues(insightLogic)
    const { baseCurrency } = useValues(teamLogic)
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const {
        indexedResults,
        trendsFilter,
        formula,
        showValuesOnSeries,
        showLabelOnSeries,
        pieChartVizOptions,
        hasDataWarehouseSeries,
        querySource,
        breakdownFilter,
        getTrendsColor,
        getTrendsHidden,
    } = useValues(trendsDataLogic(insightProps))

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
            disableHoverOffset: !!pieChartVizOptions?.disableHoverOffset,
        }),
        [showValuesOnSeries, showLabelOnSeries, pieChartVizOptions?.disableHoverOffset]
    )

    const canHandleClick = !!onDataPointClick || (showPersonsModal && !formula && !hasDataWarehouseSeries)

    // Click parity with ActionsPie. The legacy path builds an InsightActorsQuery from the
    // GraphDataset.breakdownValues array; here each slice is already a single result, so we
    // pull its breakdown/compare straight from the IndexedTrendResult.
    const onSliceClick = useCallback(
        (payload: RadialSlicePayload<TrendsSeriesMeta>) => {
            const result = visibleResults.find((r: IndexedTrendResult) => String(r.id) === payload.series.key)
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
                title: payload.series.label || '',
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

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => <PieTooltip ctx={ctx} valueFormatter={valueFormatter} />,
        [valueFormatter]
    )

    const centerLabel = useMemo(() => {
        if (!showAggregation) {
            return null
        }
        return (
            <div className="text-center font-bold text-3xl leading-tight">
                {formatAggregationAxisValue(trendsFilter, total, baseCurrency)}
            </div>
        )
    }, [showAggregation, total, trendsFilter, baseCurrency])

    if (!visibleResults.length) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    return (
        <PieChart<TrendsSeriesMeta>
            series={series}
            theme={theme}
            config={pieConfig}
            tooltip={renderTooltip}
            onSliceClick={canHandleClick ? onSliceClick : undefined}
            valueFormatter={valueFormatter}
            centerLabel={centerLabel}
            className={inSharedMode ? 'ActionsPie--shared' : 'ActionsPie'}
            dataAttr="trend-pie-graph"
            onError={handleChartError}
        />
    )
}
