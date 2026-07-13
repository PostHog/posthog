import { useValues } from 'kea'
import { useMemo } from 'react'

import { SlopeChart, createXAxisTickCallback } from '@posthog/quill-charts'
import type { Series, SlopeChartConfig, SlopeSeriesMeta } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { makeChartErrorHandler } from '../shared/chartErrorHandler'

interface TrendsSlopeChartProps {
    context?: QueryContext<InsightVizNode>
}

const handleChartError = makeChartErrorHandler('trends-slope-chart')

export function TrendsSlopeChart({ context }: TrendsSlopeChartProps): JSX.Element | null {
    const theme = useChartTheme()
    const { insightProps } = useValues(insightLogic)

    const { indexedResults, currentPeriodResult, getTrendsColor, getTrendsHidden, trendsFilter, interval, showLegend } =
        useValues(trendsDataLogic(insightProps))
    const { timezone } = useValues(insightVizDataLogic(insightProps))
    const { baseCurrency } = useValues(teamLogic)

    // The backend returns each series as its two points (first and last interval bucket) with two
    // matching labels, so we just map to quill series: resolve the theme colour, drop legend-hidden
    // series, and forward the backend's `incomplete_end` flag (which dashes the connector). A
    // single-bucket range comes back as one point and is dropped — there's no slope to draw.
    const labels = currentPeriodResult?.labels ?? []
    const series = useMemo<Series<SlopeSeriesMeta>[]>(() => {
        return (indexedResults ?? [])
            .filter((result: IndexedTrendResult) => !getTrendsHidden(result) && (result.data?.length ?? 0) >= 2)
            .map((result: IndexedTrendResult) => ({
                key: String(result.id),
                label: result.label ?? '',
                color: getTrendsColor(result),
                data: result.data,
                meta: result.incomplete_end ? { incompleteEnd: true } : undefined,
            }))
    }, [indexedResults, getTrendsColor, getTrendsHidden])

    const config = useMemo<SlopeChartConfig>(
        () => ({
            valueFormatter: (value: number) => formatAggregationAxisValue(trendsFilter, value, baseCurrency),
            // The chart's own legend carries the series name + first-to-last change, gated on the
            // insight's "Show legend" toggle, so there's only ever one legend and no in-chart names.
            showSeriesLabels: false,
            legend: { show: !!showLegend },
            xTickFormatter: createXAxisTickCallback({
                interval: interval ?? 'day',
                allDays: currentPeriodResult?.days ?? [],
                timezone,
            }),
        }),
        [trendsFilter, baseCurrency, showLegend, interval, currentPeriodResult, timezone]
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
