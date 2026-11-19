import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import type { ReportMonitoringSummaryApi } from 'products/signals/frontend/generated/api.schemas'

import type { MonitoringEvidence } from '../../utils/monitoringTimeline'
import { formatReportMetricValue, reportMetricChartType } from '../../utils/reportMetrics'
import { monitoringChartMarkers } from '../../utils/reportMonitoringChart'
import { monitoringSummaryTimeline } from '../../utils/reportMonitoringSummary'
import { CHART_TIMELINE_HEIGHT, ReportChartMonitoringTimeline } from '../detail/ReportChartMonitoringTimeline'
import { OBSERVATION_CHART_HEIGHT_CLASS, ReportObservationChart } from '../detail/ReportObservationChart'

export function MonitoringEvidenceChart({
    summary,
    evidence,
    now,
}: {
    summary: ReportMonitoringSummaryApi
    evidence: MonitoringEvidence
    now: number
}): JSX.Element | null {
    const { timezone } = useValues(teamLogic)
    const { metric, interval, trend } = evidence
    const lead = summary.lead_check
    if (!lead || !metric.series_buckets) {
        return null
    }
    const labels = metric.series_buckets
    const type = reportMetricChartType(metric)
    const targetText =
        trend.target != null
            ? formatReportMetricValue(
                  { ...metric, value_format: metric.value_format === 'count' ? 'number' : metric.value_format },
                  trend.target
              )
            : null
    const sign = lead.comparison.operator === 'gte' ? '≥' : '≤'
    // A linear target scales with time, so its line is a per-bucket rate; a fixed one holds for every bucket.
    const perBucket = lead.monitoring.threshold_scaling === 'linear' ? `/${interval}` : ''

    return (
        <div className={OBSERVATION_CHART_HEIGHT_CLASS}>
            <ReportObservationChart
                metric={metric}
                points={{ labels, values: trend.values }}
                type={type}
                interval={interval}
                markers={monitoringChartMarkers(
                    labels,
                    {
                        referencePeriodMinutes: lead.monitoring.reference_period_minutes,
                        thresholdScaling: lead.monitoring.threshold_scaling,
                        startedAt: summary.started_at,
                    },
                    now,
                    timezone
                )}
                goalLines={
                    trend.target != null && targetText
                        ? [
                              {
                                  value: trend.target,
                                  label: `Target: ${sign}${targetText}${perBucket}`,
                                  labelPosition: 'end',
                              },
                          ]
                        : undefined
                }
                footer={{
                    node: (
                        <ReportChartMonitoringTimeline
                            timeline={monitoringSummaryTimeline(summary, now)}
                            type={type}
                            interval={interval}
                        />
                    ),
                    height: CHART_TIMELINE_HEIGHT,
                }}
            />
        </div>
    )
}
