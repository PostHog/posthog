import { useValues } from 'kea'
import { useMemo } from 'react'

import { SlopeChart } from '@posthog/quill-charts'
import type { Series, SlopeChartConfig, SlopeSeriesMeta } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { makeChartErrorHandler } from '../shared/chartErrorHandler'

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

    // The backend returns each series as its two points (first and last interval bucket) with two
    // matching labels, so we just map to quill series: resolve the theme colour, drop legend-hidden
    // series, and flag the incomplete end (which dashes the connector). A single-bucket range comes
    // back as one point and is dropped — there's no slope to draw.
    const labels = currentPeriodResult?.labels ?? []
    const series = useMemo<Series<SlopeSeriesMeta>[]>(() => {
        const lastBucketInProgress = incompletenessOffsetFromEnd !== undefined && incompletenessOffsetFromEnd < 0
        return (indexedResults ?? [])
            .filter((result: IndexedTrendResult) => !getTrendsHidden(result) && (result.data?.length ?? 0) >= 2)
            .map((result: IndexedTrendResult) => ({
                key: String(result.id),
                label: result.label ?? '',
                color: getTrendsColor(result),
                data: result.data,
                meta: lastBucketInProgress ? { incompleteEnd: true } : undefined,
            }))
    }, [indexedResults, getTrendsColor, getTrendsHidden, incompletenessOffsetFromEnd])

    const config = useMemo<SlopeChartConfig>(
        () => ({
            valueFormatter: (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
            // The series name + change live in the insight's shared legend (SlopeGraphLegend, gated on
            // the "Show legend" toggle), so the chart draws neither its own legend nor in-chart names.
            showSeriesLabels: false,
            legend: { show: false },
        }),
        [trendsFilter, baseCurrency]
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
