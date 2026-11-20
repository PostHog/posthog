import { useValues } from 'kea'
import { useMemo } from 'react'

import { Card, CardContent, Dot, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    formatReportMetricParts,
    formatReportMetricValue,
    reportMetricChartType,
    reportMetricGoalUnit,
    reportMetricInterval,
    ReportMetricSeriesPoints,
} from '../../../utils/reportMetrics'
import { monitoringChartMarkers, monitoringChartPoints, monitoringOutcome } from '../../../utils/reportMonitoringChart'
import { ReportObservationChart } from '../ReportObservationChart'

const SUB_DAY_INTERVALS = new Set(['second', 'minute', 'hour'])

/**
 * The metric the fix should move, charted across the release, beside the result the report expects.
 * The figure under the target is read from the chart, not a verdict: the follow-up checks give that.
 */
export function ReportOutcomeCard({
    metric,
    points,
    monitoringStartedAt,
}: {
    metric: ReportMetricApi
    points: ReportMetricSeriesPoints
    monitoringStartedAt: string
}): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const interval = reportMetricInterval(metric)
    // The chart compares its inputs by identity, so they are built once per data change, not per render.
    const chart = useMemo(() => {
        const now = Date.now()
        const chartPoints = monitoringChartPoints(points, now, timezone)
        return {
            points: chartPoints,
            markers: monitoringChartMarkers(
                points.labels,
                { referencePeriodMinutes: 0, startedAt: monitoringStartedAt },
                now,
                timezone
            ),
            observed: monitoringOutcome({
                metric,
                points: chartPoints,
                startedAt: monitoringStartedAt,
                interval,
                now,
                timezone,
            }),
        }
    }, [metric, points, monitoringStartedAt, interval, timezone])
    const goal = formatReportMetricParts(metric, metric.goal_value)
    const observed = chart.observed
    const observedValue = observed ? (formatReportMetricValue(metric, observed.value) ?? String(observed.value)) : null
    const observedFrom = observed
        ? dayjs(observed.from).format(SUB_DAY_INTERVALS.has(interval) ? 'MMM D, HH:mm' : 'MMM D')
        : null

    return (
        <Card size="sm" data-attr="inbox-report-outcome-card">
            <CardContent className="grid grid-cols-1 gap-4 @2xl:grid-cols-[minmax(0,1fr)_13rem]">
                <ReportObservationChart
                    metric={metric}
                    points={chart.points}
                    type={reportMetricChartType(metric)}
                    interval={interval}
                    markers={chart.markers}
                />
                <div className="flex flex-col gap-1.5 border-border @2xl:border-s @2xl:ps-4">
                    <Text size="xs" variant="muted" weight="medium" render={<h3 className="m-0" />}>
                        Expected impact
                    </Text>
                    {goal && (
                        <div className="flex flex-wrap items-baseline gap-x-2">
                            <span className="text-2xl font-semibold tabular-nums text-success-foreground">
                                {goal.value}
                            </span>
                            <Text size="sm" variant="muted" render={<span />}>
                                {reportMetricGoalUnit(metric, goal.unit)}
                            </Text>
                        </div>
                    )}
                    <Text size="sm" weight="medium" render={<p className="m-0" />}>
                        {metric.title}
                    </Text>
                    {observed && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />} className="flex gap-1.5">
                            <Dot
                                variant={observed.value === 0 ? 'success' : 'warning'}
                                aria-hidden
                                className="mt-1 self-start"
                            />
                            <span>
                                {observed.aggregation === 'total'
                                    ? `${observedValue} since ${observedFrom}, the first full ${interval} after the fix merged`
                                    : `${observedValue} per ${interval} on average since ${observedFrom}, the first full ${interval} after the fix merged`}
                            </span>
                        </Text>
                    )}
                </div>
            </CardContent>
        </Card>
    )
}
