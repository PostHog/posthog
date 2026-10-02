import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { ReportMetricApi, SignalReportCheckProgressApi } from 'products/signals/frontend/generated/api.schemas'

import { formatReportMetricValue } from '../../utils/reportMetrics'

export function ReportCheckProgress({
    progress,
    loading,
    metric,
}: {
    progress: SignalReportCheckProgressApi | undefined
    loading: boolean
    metric: ReportMetricApi
}): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)
    const points = progress?.points
    const series = useMemo<Series[]>(
        () =>
            points?.length
                ? [
                      {
                          key: 'observed',
                          label: metric.title,
                          data: points.map((point) => point.value),
                          points: { radius: 2 },
                      },
                      {
                          key: 'target',
                          label: progress?.target_type === 'proportional' ? 'Target pace' : 'Target',
                          data: points.map((point) => point.target ?? NaN),
                          stroke: { pattern: [5, 5] },
                      },
                      ...(progress?.target_upper != null
                          ? [
                                {
                                    key: 'target-upper',
                                    label: 'Upper target',
                                    data: points.map((point) => point.target_upper ?? NaN),
                                    stroke: { pattern: [5, 5] },
                                },
                            ]
                          : []),
                  ]
                : [],
        [points, metric.title, progress?.target_type, progress?.target_upper]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            showGrid: true,
            legend: { show: true, interactive: false },
            xAxis: {
                timezone,
                interval:
                    points && points.length > 1 && dayjs(points[1].at).diff(dayjs(points[0].at), 'hour') <= 1
                        ? 'hour'
                        : 'day',
            },
            yAxis: {
                tickFormatter: (value: number) =>
                    formatReportMetricValue(
                        metric.value_format === 'count' ? { ...metric, value_format: 'number' } : metric,
                        value
                    ) ?? String(value),
            },
            tooltip: {
                pinnable: false,
                valueFormatter: (value: number) =>
                    formatReportMetricValue(
                        metric.value_format === 'count' ? { ...metric, value_format: 'number' } : metric,
                        value
                    ) ?? String(value),
            },
        }),
        [metric, timezone, points]
    )
    if (loading && !progress) {
        return <LemonSkeleton className="h-36 w-full" />
    }
    if (!progress) {
        return <p className="m-0 text-secondary text-sm">Couldn't load progress. Refresh the report to try again.</p>
    }
    const labels = {
        on_track: 'Looks on track',
        off_track: 'Not looking good',
        insufficient_data: 'Not enough data',
        unavailable: 'Unavailable',
        error: "Couldn't measure",
    }
    const format = (value: number): string =>
        formatReportMetricValue(
            metric.value_format === 'count' && !Number.isInteger(value)
                ? { ...metric, value_format: 'number' }
                : metric,
            value
        ) ?? String(value)

    return (
        <div className="flex min-w-0 flex-col gap-2" data-attr="report-check-progress">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag
                    type={
                        progress.status === 'on_track'
                            ? 'success'
                            : progress.status === 'off_track'
                              ? 'danger'
                              : 'default'
                    }
                >
                    {labels[progress.status]}
                </LemonTag>
                <span className="text-secondary text-xs">Provisional</span>
            </div>
            {points?.length ? (
                <div className="flex h-44 w-full min-w-0 flex-col">
                    <TimeSeriesLineChart
                        series={series}
                        labels={points.map((point) => point.at)}
                        theme={theme}
                        config={config}
                    />
                </div>
            ) : progress.value != null ? (
                <p className="m-0 text-secondary text-sm">Chart unavailable. The assessment uses the measured total.</p>
            ) : null}
            {progress.value != null && (
                <div className="flex flex-wrap justify-between gap-2 text-sm">
                    <span>Since monitoring began: {format(progress.value)}</span>
                    {progress.target != null && (
                        <span>
                            Target{progress.target_type === 'proportional' ? ' so far' : ''}: {format(progress.target)}
                            {progress.target_upper != null ? ` to ${format(progress.target_upper)}` : ''}
                        </span>
                    )}
                </div>
            )}
            <p className="m-0 text-secondary text-sm">{progress.explanation}</p>
            {progress.sample_size != null && progress.sample_size > 0 && (
                <p className="m-0 text-secondary text-xs">
                    Based on {progress.sample_size.toLocaleString()} qualifying observations.
                </p>
            )}
            {progress.started_at && progress.ended_at && (
                <p className="m-0 text-secondary text-xs">
                    {dayjs(progress.started_at).tz(timezone).format('MMM D, HH:mm')} to{' '}
                    {dayjs(progress.ended_at).tz(timezone).format('MMM D, HH:mm')}
                </p>
            )}
        </div>
    )
}
