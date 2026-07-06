import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonLabel, LemonTable, LemonTableColumns, Link, SpinnerOverlay } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    type EmailMetric,
    WORKFLOW_SUMMARY_METRICS,
    type EmailMetricRow,
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
        conversionRate,
        conversionStats,
        conversionStatsLoading,
        convertedUsersUrl,
        hasConversionGoal,
    } = useValues(workflowMetricsSummaryLogic(props))

    const emailMetricsColumns: LemonTableColumns<EmailMetricRow> = useMemo(
        () => [
            {
                title: 'Email',
                dataIndex: 'email',
                key: 'email',
                render: (_, row) =>
                    onSelectAction ? (
                        <span className="cursor-pointer text-link" onClick={() => onSelectAction(row.id)}>
                            {row.email}
                        </span>
                    ) : (
                        row.email
                    ),
            },
            {
                title: 'Sent',
                dataIndex: 'sent',
                key: 'sent',
                align: 'right',
                render: (_, row) => row.sent.toLocaleString(),
            },
            {
                title: 'Delivered',
                dataIndex: 'delivered',
                key: 'delivered',
                align: 'right',
                render: (_, row) => row.delivered.toLocaleString(),
            },
            {
                title: 'Bounced',
                dataIndex: 'bounced',
                key: 'bounced',
                align: 'right',
                render: (_, row) =>
                    onMetricClick && row.bounced > 0 ? (
                        <span className="cursor-pointer text-link" onClick={() => onMetricClick('email_bounced')}>
                            {row.bounced.toLocaleString()}
                        </span>
                    ) : (
                        row.bounced.toLocaleString()
                    ),
            },
            {
                title: 'Blocked',
                dataIndex: 'blocked',
                key: 'blocked',
                align: 'right',
                render: (_, row) =>
                    onMetricClick && row.blocked > 0 ? (
                        <span className="cursor-pointer text-link" onClick={() => onMetricClick('email_blocked')}>
                            {row.blocked.toLocaleString()}
                        </span>
                    ) : (
                        row.blocked.toLocaleString()
                    ),
            },
            {
                title: 'Opened',
                dataIndex: 'opened',
                key: 'opened',
                align: 'right',
                render: (_, row) => row.opened.toLocaleString(),
            },
            {
                title: 'Clicked',
                dataIndex: 'linkClicked',
                key: 'linkClicked',
                align: 'right',
                render: (_, row) => row.linkClicked.toLocaleString(),
            },
        ],
        [onSelectAction, onMetricClick]
    )

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
                    const timeSeries =
                        summaryMetric === 'completed'
                            ? withDisplayName(getCompletedSingleTrendSeries('succeeded'), metric.name)
                            : withDisplayName(getSingleTrendSeries(metricName), metric.name)

                    const previousPeriodTimeSeries =
                        summaryMetric === 'completed'
                            ? withDisplayName(getCompletedSingleTrendSeries('succeeded', true), metric.name)
                            : withDisplayName(getSingleTrendSeries(metricName, true), metric.name)

                    return (
                        <AppMetricSummary
                            key={summaryMetric}
                            name={metric.name}
                            description={metric.description}
                            loading={loading}
                            timeSeries={timeSeries}
                            previousPeriodTimeSeries={previousPeriodTimeSeries}
                            color={metric.color}
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

            <LemonTable
                columns={emailMetricsColumns}
                dataSource={emailMetricsRows}
                loading={emailTotalsByActionIdLoading}
                rowKey="id"
                size="small"
                emptyState="No email actions in this workflow"
            />

            <AppMetricsTrends appMetricsTrends={workflowSummaryTrends} loading={loading} />
        </>
    )
}
