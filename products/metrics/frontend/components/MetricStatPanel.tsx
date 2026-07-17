import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import { MetricCard, useChartTheme } from '@posthog/quill-charts'

import {
    computeMetricSummary,
    computeMetricSummaryChange,
    getMetricChangeTooltip,
    type MetricSummary,
    METRIC_SUMMARY_LABELS,
} from 'lib/components/Metric/metricSummary'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { MetricAggregation, MetricsAnomalyBadge } from './metricsViewerLogic'

export interface MetricStatPanelProps {
    /** Headline title — the metric name. */
    title: string
    /** How the series is summarized into one value. */
    summary: MetricSummary
    /** The bucket aggregation, shown in the subtitle for context. */
    aggregation: MetricAggregation
    /** Grand total across buckets (basis for the 'total' summary). */
    total: number
    /** Per-bucket values the summary and sparkline are computed from. */
    values: number[]
    /** Pre-formatted bucket labels for the sparkline hover. */
    labels: string[]
    /** "vs baseline" anomaly badge, or null when the metric is flat / not characterized. */
    anomaly: MetricsAnomalyBadge | null
}

/** A Grafana-style "stat" panel: one headline value + change pill + sparkline, with an optional anomaly badge. */
export function MetricStatPanel({
    title,
    summary,
    aggregation,
    total,
    values,
    labels,
    anomaly,
}: MetricStatPanelProps): JSX.Element {
    const theme = useChartTheme()
    return (
        <div className="flex flex-col h-full">
            {anomaly && (
                <div className="flex justify-end">
                    <Tooltip
                        title={`Baseline ${humanFriendlyNumber(anomaly.baselineMean)} → recent ${humanFriendlyNumber(
                            anomaly.anomalyMean
                        )}${anomaly.onsetTime ? `, onset ${dayjs(anomaly.onsetTime).format('D MMM HH:mm')}` : ''}`}
                    >
                        <LemonTag type="warning">
                            {anomaly.direction === 'up' ? '▲' : '▼'} {anomaly.percent}% vs baseline
                        </LemonTag>
                    </Tooltip>
                </div>
            )}
            <MetricCard
                className="flex-1"
                title={title}
                restingSubtitle={`${METRIC_SUMMARY_LABELS[summary]} · ${aggregation}`}
                value={computeMetricSummary(summary, total, values)}
                change={computeMetricSummaryChange(summary, { total, data: values }, undefined)}
                changeTooltip={getMetricChangeTooltip(summary, false, null)}
                changeSize="md"
                changeInline
                hoverChangeFromPreviousPoint
                data={values}
                labels={labels}
                theme={theme}
                sparklineFill
                sparklineHeight={140}
                formatValue={(value) => humanFriendlyNumber(value)}
                dataAttr="metrics-stat-value"
            />
        </div>
    )
}
