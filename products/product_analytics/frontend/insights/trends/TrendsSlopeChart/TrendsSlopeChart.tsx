import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { SlopeChart } from '@posthog/quill-charts'
import type { PointClickData, SlopeChartConfig } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { handleTrendsChartClick } from '../shared/handleTrendsChartClick'
import { buildSlopeSeries, slopeLabels } from './slopeChartTransforms'

interface TrendsSlopeChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const handleChartError = makeChartErrorHandler('trends-slope-chart')

export function TrendsSlopeChart({ context }: TrendsSlopeChartProps): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps } = useValues(insightLogic)

    const {
        indexedResults,
        currentPeriodResult,
        getTrendsColor,
        getTrendsHidden,
        trendsFilter,
        interval,
        insightData,
        querySource,
        hasPersonsModal,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)

    const labels = useMemo(() => slopeLabels(currentPeriodResult?.labels ?? []), [currentPeriodResult?.labels])
    const series = useMemo(
        () => buildSlopeSeries(indexedResults ?? [], { getColor: getTrendsColor, getHidden: getTrendsHidden }),
        [indexedResults, getTrendsColor, getTrendsHidden]
    )

    const config = useMemo<SlopeChartConfig>(
        () => ({
            valueFormatter: (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
            // The legend already names each series, so keep the in-chart name labels off to reduce clutter
            // — but still show the formatted change per series in the legend.
            showSeriesLabels: false,
            legend: { show: series.length > 1, position: 'bottom' },
            deltaFormatter: (delta: number) =>
                `${delta >= 0 ? '+' : ''}${formatAggregationAxisValue(trendsFilter, delta, baseCurrency)}`,
        }),
        [trendsFilter, baseCurrency, series.length]
    )

    const canHandleClick = !!context?.onDataPointClick || !!hasPersonsModal
    const clickDeps = useMemo(
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
        (clickData: PointClickData) => {
            // The slope only has two columns; map them back to the first/last index of the full series.
            const dataset = (indexedResults ?? []).find(
                (r: IndexedTrendResult) => String(r.id) === clickData.series.key
            )
            const realIndex = clickData.dataIndex <= 0 ? 0 : Math.max(0, (dataset?.data?.length ?? 0) - 1)
            handleTrendsChartClick(clickData.series.key, realIndex, clickDeps)
        },
        [indexedResults, clickDeps]
    )

    if (series.length === 0) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    return (
        <SlopeChart
            series={series}
            labels={labels}
            theme={theme}
            config={config}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="SlopeGraph"
            dataAttr="trends-slope-graph"
            onError={handleChartError}
        />
    )
}
