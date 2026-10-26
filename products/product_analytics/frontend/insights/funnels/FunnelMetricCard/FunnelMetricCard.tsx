import clsx from 'clsx'
import { useValues } from 'kea'

import { useChartTheme } from '@posthog/quill-charts'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricSubtitle,
    MetricValue,
} from '@posthog/quill-components/metric'

import { hexToRGBA } from 'lib/utils/colors'
import { percentage } from 'lib/utils/numbers'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartParams, TrendResult } from '~/types'

import {
    computeMetricSummary,
    computeMetricSummaryChange,
    formatMetricLabel,
    getMetricChangeTooltip,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SUMMARY_LABELS,
    selectCurrentSeries,
    selectPreviousSeriesSummary,
} from 'products/product_analytics/frontend/insights/trends/Metric/Metric.utils'

import { funnelDataLogic } from '../funnelDataLogic'

const makeChangeColor = (hex: string): { background: string; foreground: string } => ({
    background: hexToRGBA(hex, 0.1),
    foreground: hex,
})

export function FunnelMetricCard({ inCardView }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, interval } = useValues(insightVizDataLogic(insightProps))
    const { incompletenessOffsetFromEnd } = useValues(funnelDataLogic(insightProps))
    const theme = useChartTheme()

    const results = insightData?.result as TrendResult[] | undefined
    const resultSeries = selectCurrentSeries(results)

    if (!resultSeries?.data?.length) {
        return <InsightEmptyState sampleDataVariant="number" />
    }

    // Each point is a conversion rate, so a sum has no meaning. The headline is the average rate.
    const summary = 'average'
    const previousSeries = selectPreviousSeriesSummary(results)
    const change = computeMetricSummaryChange(
        summary,
        { total: resultSeries.count, data: resultSeries.data },
        previousSeries
    )
    const dashedFromIndex =
        incompletenessOffsetFromEnd < 0 ? resultSeries.data.length + incompletenessOffsetFromEnd : undefined

    return (
        <div className={clsx('Metric ph-no-capture flex flex-col w-full p-2', inCardView && 'flex-1')}>
            <Metric
                className={clsx('px-0', inCardView && 'flex-1')}
                sparklineFill={inCardView}
                value={computeMetricSummary(summary, resultSeries.count, resultSeries.data)}
                change={change}
                changeTooltip={getMetricChangeTooltip(summary, previousSeries != null, interval)}
                hoverChangeFromPreviousPoint
                positiveColor={makeChangeColor(METRIC_DEFAULT_INCREASE_COLOR)}
                negativeColor={makeChangeColor(METRIC_DEFAULT_DECREASE_COLOR)}
                restingSubtitle={`${METRIC_SUMMARY_LABELS[summary]} conversion rate`}
                data={resultSeries.data}
                labels={resultSeries.days ?? resultSeries.labels}
                formatLabel={formatMetricLabel}
                theme={theme}
                showChange
                formatValue={(value) => percentage(value / 100, 2, true)}
                sparklineDashedFromIndex={dashedFromIndex}
                sparklineHeight={120}
                dataAttr="funnel-metric-value"
            >
                <MetricHeader className="items-center">
                    <MetricValue />
                    <MetricDelta className="h-auto gap-1 px-2.5 py-1 text-sm [&>svg]:size-3!" />
                </MetricHeader>
                <MetricSubtitle className="mt-1" />
                <MetricSparkline className="mt-4 -mx-2 -mb-2" />
            </Metric>
        </div>
    )
}
