import { useValues } from 'kea'
import { useMemo } from 'react'

import { SlopeChart } from '@posthog/quill-charts'
import type { SlopeChartConfig } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { makeChartErrorHandler } from '../shared/chartErrorHandler'
import { buildSlopeSeries, slopeLabels } from './slopeChartTransforms'

interface TrendsSlopeChartProps {
    context?: QueryContext<InsightVizNode>
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
        incompletenessOffsetFromEnd,
    } = useValues(trendsDataLogic(insightProps))
    const { baseCurrency } = useValues(teamLogic)

    // The backend returns exactly two points per series (the first and last interval bucket);
    // buildSlopeSeries maps them to quill series, honoring legend show/hide and dashing the
    // connector when the last bucket is the current incomplete period.
    const labels = useMemo(() => slopeLabels(currentPeriodResult?.labels ?? []), [currentPeriodResult?.labels])
    const series = useMemo(
        () =>
            buildSlopeSeries(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                incompletenessOffsetFromEnd,
            }),
        [indexedResults, getTrendsColor, getTrendsHidden, incompletenessOffsetFromEnd]
    )

    const config = useMemo<SlopeChartConfig>(
        () => ({
            valueFormatter: (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
            // The legend already names each series, so keep the in-chart name labels off to reduce clutter
            // — the legend still shows the formatted change per series.
            showSeriesLabels: false,
            legend: { show: series.length > 1, position: 'bottom' },
            deltaFormatter: (delta: number) =>
                `${delta >= 0 ? '+' : ''}${formatAggregationAxisValue(trendsFilter, delta, baseCurrency)}`,
        }),
        [trendsFilter, baseCurrency, series.length]
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
            className="SlopeGraph"
            dataAttr="trends-slope-graph"
            onError={handleChartError}
        />
    )
}
