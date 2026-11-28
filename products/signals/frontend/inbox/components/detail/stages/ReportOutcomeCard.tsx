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
    ReportMetricSeriesPoints,
    reportMetricUnitWord,
} from '../../../utils/reportMetrics'
import { monitoringChartMarkers, monitoringChartPoints } from '../../../utils/reportMonitoringChart'
import { ReportObservationChart } from '../ReportObservationChart'

/** The total of the buckets that start after the fix shipped, and the first of them. Null when none has started. */
function sinceTheFix(
    points: ReportMetricSeriesPoints,
    monitoringStartedAt: string
): { total: number; from: string } | null {
    const firstAfter = points.labels.findIndex((label) => dayjs(label).isAfter(monitoringStartedAt))
    if (firstAfter === -1) {
        return null
    }
    const total = points.values.slice(firstAfter).reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0)
    return { total, from: points.labels[firstAfter] }
}

/**
 * The metric the fix should move, charted across the release, beside the result the report expects.
 * The figure under the target is a count from the chart, not a verdict: the follow-up checks give that.
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
    // The chart compares its inputs by identity, so they are built once per data change, not per render.
    const chart = useMemo(() => {
        const now = Date.now()
        return {
            points: monitoringChartPoints(points, now, timezone),
            markers: monitoringChartMarkers(
                points.labels,
                { referencePeriodMinutes: 0, startedAt: monitoringStartedAt },
                now,
                timezone
            ),
        }
    }, [points, monitoringStartedAt, timezone])
    const goal = formatReportMetricParts(metric, metric.goal_value)
    const unitWord = reportMetricUnitWord(metric)
    const observed = sinceTheFix(points, monitoringStartedAt)

    return (
        <Card size="sm" data-attr="inbox-report-outcome-card">
            <CardContent className="grid grid-cols-1 gap-4 @2xl:grid-cols-[minmax(0,1fr)_13rem]">
                <ReportObservationChart
                    metric={metric}
                    points={chart.points}
                    type={reportMetricChartType(metric)}
                    interval="day"
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
                                {metric.goal_grain === 'per_interval'
                                    ? `${goal.unit ?? unitWord} per day`
                                    : (goal.unit ?? unitWord)}
                            </Text>
                        </div>
                    )}
                    <Text size="sm" weight="medium" render={<p className="m-0" />}>
                        {metric.title}
                    </Text>
                    {observed && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />} className="flex gap-1.5">
                            <Dot
                                variant={observed.total === 0 ? 'success' : 'warning'}
                                aria-hidden
                                className="mt-1 self-start"
                            />
                            <span>
                                {`${formatReportMetricValue(metric, observed.total) ?? observed.total} since ${dayjs(observed.from).format('MMM D')}, the first full day after the fix merged`}
                            </span>
                        </Text>
                    )}
                </div>
            </CardContent>
        </Card>
    )
}
