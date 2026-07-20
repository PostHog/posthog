import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { IconArrowRight, IconLetter, IconNotification } from '@posthog/icons'
import { LemonLabel, LemonTable, LemonTableColumns, LemonTag, Link, SpinnerOverlay } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { type AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    type EmailMetric,
    type EmailMetricRow,
    METRIC_COLORS,
    type PushMetricRow,
    WORKFLOW_SUMMARY_METRICS,
    withDisplayName,
    workflowMetricsSummaryLogic,
    type WorkflowMetricsSummaryLogicProps,
} from './workflowMetricsSummaryLogic'

interface WorkflowMetricsSummaryProps extends WorkflowMetricsSummaryLogicProps {
    onSelectAction?: (actionId: string) => void
    /** Drill a per-email metric into its filtered logs (only bounced/blocked have a log filter). */
    onMetricClick?: (metricKey: EmailMetric) => void
}

export function WorkflowMetricsSummary({
    onSelectAction,
    onMetricClick,
    ...props
}: WorkflowMetricsSummaryProps): JSX.Element {
    const {
        loading,
        summaryMetricKeys,
        metricNameBySummaryMetric,
        getSingleTrendSeries,
        getCompletedSingleTrendSeries,
        inProgressTotal,
        inProgressTotalLoading,
        workflowSummaryTrends,
        emailMetricsRows,
        emailTotalsByActionIdLoading,
        pushMetricsRows,
        pushTotalsByActionIdLoading,
        conversionRate,
        conversionStats,
        conversionStatsLoading,
        convertedUsersUrl,
        hasConversionGoal,
        messagingChannels,
        sentSummaryLabel,
    } = useValues(workflowMetricsSummaryLogic(props))

    // Email and push don't share a funnel, so each channel gets its own table with the columns that
    // actually apply — email keeps the delivery→open→click funnel, push surfaces skipped/failed as
    // first-class columns. A workflow with a single channel just shows that one table.
    const viewMetricsColumn = useCallback(
        (id: string): JSX.Element => (
            <Link onClick={() => onSelectAction?.(id)} className="whitespace-nowrap inline-flex items-center gap-1">
                View metrics <IconArrowRight />
            </Link>
        ),
        [onSelectAction]
    )

    const emailColumns: LemonTableColumns<EmailMetricRow> = useMemo(() => {
        return [
            {
                title: 'Step',
                key: 'step',
                render: (_, row) => <span className="font-medium">{row.email}</span>,
            },
            { title: 'Sent', key: 'sent', align: 'right', render: (_, row) => row.sent.toLocaleString() },
            {
                title: 'Delivered',
                key: 'delivered',
                align: 'right',
                render: (_, row) => row.delivered.toLocaleString(),
            },
            { title: 'Opened', key: 'opened', align: 'right', render: (_, row) => row.opened.toLocaleString() },
            { title: 'Clicked', key: 'clicked', align: 'right', render: (_, row) => row.linkClicked.toLocaleString() },
            {
                title: 'Issues',
                key: 'issues',
                render: (_, row) => {
                    const issues = [
                        {
                            label: 'bounced',
                            value: row.bounced,
                            type: 'danger' as const,
                            metric: 'email_bounced' as EmailMetric,
                        },
                        {
                            label: 'blocked',
                            value: row.blocked,
                            type: 'danger' as const,
                            metric: 'email_blocked' as EmailMetric,
                        },
                        {
                            label: 'bounce prevented',
                            value: row.bouncePrevented,
                            type: 'warning' as const,
                            metric: 'email_bounce_prevented' as EmailMetric,
                        },
                    ].filter((issue) => issue.value > 0)
                    if (issues.length === 0) {
                        return <span className="text-muted">—</span>
                    }
                    return (
                        <div className="flex flex-wrap gap-1">
                            {issues.map((issue) => (
                                <LemonTag
                                    key={issue.label}
                                    type={issue.type}
                                    onClick={onMetricClick ? () => onMetricClick(issue.metric) : undefined}
                                    forceClickable={!!onMetricClick}
                                >
                                    {issue.value.toLocaleString()} {issue.label}
                                </LemonTag>
                            ))}
                        </div>
                    )
                },
            },
            ...(onSelectAction
                ? [
                      {
                          title: '',
                          key: 'view',
                          align: 'right' as const,
                          render: (_: unknown, row: EmailMetricRow) => viewMetricsColumn(row.id),
                      },
                  ]
                : []),
        ]
    }, [onSelectAction, onMetricClick, viewMetricsColumn])

    const pushColumns: LemonTableColumns<PushMetricRow> = useMemo(() => {
        return [
            {
                title: 'Step',
                key: 'step',
                render: (_, row) => <span className="font-medium">{row.push}</span>,
            },
            { title: 'Sent', key: 'sent', align: 'right', render: (_, row) => row.sent.toLocaleString() },
            { title: 'Skipped', key: 'skipped', align: 'right', render: (_, row) => row.skipped.toLocaleString() },
            { title: 'Failed', key: 'failed', align: 'right', render: (_, row) => row.failed.toLocaleString() },
            ...(onSelectAction
                ? [
                      {
                          title: '',
                          key: 'view',
                          align: 'right' as const,
                          render: (_: unknown, row: PushMetricRow) => viewMetricsColumn(row.id),
                      },
                  ]
                : []),
        ]
    }, [onSelectAction, viewMetricsColumn])

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                <div className="flex flex-1 flex-col relative border rounded p-3 bg-surface-primary min-w-[16rem]">
                    <div className="flex flex-col h-full">
                        <LemonLabel info={WORKFLOW_SUMMARY_METRICS.in_progress.description}>
                            {WORKFLOW_SUMMARY_METRICS.in_progress.name}
                        </LemonLabel>
                        <div className="flex flex-1 items-center justify-center">
                            {inProgressTotalLoading ? (
                                <SpinnerOverlay />
                            ) : inProgressTotal === 0 ? (
                                <LemonLabel className="text-muted text-md mb-2">No workflows in progress</LemonLabel>
                            ) : (
                                <div className="text-6xl text-muted-foreground mb-2">
                                    {humanFriendlyNumber(inProgressTotal)}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
                {summaryMetricKeys.map((summaryMetric) => {
                    if (summaryMetric === 'converted' && !hasConversionGoal) {
                        return null
                    }
                    const metric = WORKFLOW_SUMMARY_METRICS[summaryMetric]
                    const metricName = metricNameBySummaryMetric[summaryMetric]

                    // The "sent" tile is channel-aware: email-only and push-only get their own label,
                    // and a flow that sends both sums the two channels into one "Messages" total.
                    const isSent = summaryMetric === 'persons_messaged'
                    const { hasEmail, hasPush } = messagingChannels
                    const name = isSent ? sentSummaryLabel : metric.name
                    const description =
                        isSent && hasEmail && hasPush
                            ? 'Total number of messages (emails and push notifications) attempted to be sent by this workflow'
                            : isSent && hasPush
                              ? 'Total number of push notifications attempted to be sent by this workflow'
                              : metric.description
                    const sentSeries = (previous?: boolean): AppMetricsTimeSeriesResponse | null => {
                        if (hasEmail && hasPush) {
                            // Split the combined "Messages" tile into Emails + Push lines. The headline
                            // number stays their sum (AppMetricSummary totals across series); the sparkline
                            // and its tooltip break the total down by channel.
                            const emailSeries = getSingleTrendSeries('email_sent', previous)
                            const pushSeries = getSingleTrendSeries('push_sent', previous)
                            const labels = emailSeries?.labels ?? pushSeries?.labels ?? []
                            return {
                                labels,
                                series: [
                                    { name: 'Emails', values: emailSeries?.series[0]?.values ?? [] },
                                    { name: 'Push notifications', values: pushSeries?.series[0]?.values ?? [] },
                                ],
                            }
                        }
                        return withDisplayName(
                            getSingleTrendSeries(hasPush ? 'push_sent' : 'email_sent', previous),
                            name
                        )
                    }

                    const timeSeries = isSent
                        ? sentSeries()
                        : summaryMetric === 'completed'
                          ? withDisplayName(getCompletedSingleTrendSeries('succeeded'), name)
                          : withDisplayName(getSingleTrendSeries(metricName), name)

                    const previousPeriodTimeSeries = isSent
                        ? sentSeries(true)
                        : summaryMetric === 'completed'
                          ? withDisplayName(getCompletedSingleTrendSeries('succeeded', true), name)
                          : withDisplayName(getSingleTrendSeries(metricName, true), name)

                    return (
                        <AppMetricSummary
                            key={summaryMetric}
                            name={name}
                            description={description}
                            loading={loading}
                            timeSeries={timeSeries}
                            previousPeriodTimeSeries={previousPeriodTimeSeries}
                            color={METRIC_COLORS[name] ?? metric.color}
                            seriesColors={METRIC_COLORS}
                            colorIfZero={getColorVar('muted')}
                            footer={
                                summaryMetric === 'converted' &&
                                !conversionStatsLoading &&
                                conversionStats.conversions > 0 ? (
                                    <Link to={convertedUsersUrl}>View converted users</Link>
                                ) : null
                            }
                        />
                    )
                })}
                {hasConversionGoal && (
                    <div className="flex flex-1 flex-col relative border rounded p-3 bg-surface-primary min-w-[16rem]">
                        <div className="flex flex-col h-full">
                            <LemonLabel info="Share of started workflow runs that recorded a conversion (Converted ÷ Started) over the selected date range.">
                                Conversion rate
                            </LemonLabel>
                            <div className="flex flex-1 items-center justify-center">
                                {conversionStatsLoading ? (
                                    <SpinnerOverlay />
                                ) : conversionStats.started === 0 ? (
                                    <LemonLabel className="text-muted text-md mb-2">No workflows started</LemonLabel>
                                ) : (
                                    <div className="text-6xl text-muted-foreground mb-2">
                                        {`${(Math.min(conversionRate, 1) * 100).toFixed(1)}%`}
                                    </div>
                                )}
                            </div>
                            {!conversionStatsLoading && conversionStats.conversions > 0 && (
                                <Link to={convertedUsersUrl} className="text-xs text-center">
                                    View converted users
                                </Link>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* A table per channel, since email and push report different metrics. */}
            {emailMetricsRows.length > 0 ? (
                <div className="flex flex-col gap-1">
                    <LemonLabel className="flex items-center gap-1.5">
                        <span className="flex text-lg text-secondary">
                            <IconLetter />
                        </span>
                        Email steps
                    </LemonLabel>
                    <LemonTable
                        columns={emailColumns}
                        dataSource={emailMetricsRows}
                        loading={emailTotalsByActionIdLoading}
                        rowKey="id"
                        size="small"
                    />
                </div>
            ) : null}
            {pushMetricsRows.length > 0 ? (
                <div className="flex flex-col gap-1">
                    <LemonLabel className="flex items-center gap-1.5">
                        <span className="flex text-lg text-secondary">
                            <IconNotification />
                        </span>
                        Push steps
                    </LemonLabel>
                    <LemonTable
                        columns={pushColumns}
                        dataSource={pushMetricsRows}
                        loading={pushTotalsByActionIdLoading}
                        rowKey="id"
                        size="small"
                    />
                </div>
            ) : null}

            <AppMetricsTrends appMetricsTrends={workflowSummaryTrends} loading={loading} seriesColors={METRIC_COLORS} />
        </>
    )
}
