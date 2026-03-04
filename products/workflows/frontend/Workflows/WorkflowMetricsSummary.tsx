import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonLabel, LemonTable, LemonTableColumns, SpinnerOverlay } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { humanFriendlyNumber } from 'lib/utils'

import {
    WORKFLOW_SUMMARY_METRICS,
    type EmailMetricRow,
    withDisplayName,
    workflowMetricsSummaryLogic,
    type WorkflowMetricsSummaryLogicProps,
} from './workflowMetricsSummaryLogic'

interface WorkflowMetricsSummaryProps extends WorkflowMetricsSummaryLogicProps {
    onSelectAction?: (actionId: string) => void
}

export function WorkflowMetricsSummary({ onSelectAction, ...props }: WorkflowMetricsSummaryProps): JSX.Element {
    const {
        loading,
        summaryMetricKeys,
        metricNameBySummaryMetric,
        getSingleTrendSeries,
        getExitNodeSingleTrendSeries,
        inProgressTotal,
        inProgressTotalLoading,
        workflowSummaryTrends,
        emailMetricsRows,
        emailTotalsByActionIdLoading,
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
        [onSelectAction]
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
                    const metric = WORKFLOW_SUMMARY_METRICS[summaryMetric]
                    const metricName = metricNameBySummaryMetric[summaryMetric]
                    const timeSeries =
                        summaryMetric === 'completed'
                            ? withDisplayName(getExitNodeSingleTrendSeries('succeeded'), metric.name)
                            : withDisplayName(getSingleTrendSeries(metricName), metric.name)

                    const previousPeriodTimeSeries =
                        summaryMetric === 'completed'
                            ? withDisplayName(getExitNodeSingleTrendSeries('succeeded', true), metric.name)
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
                        />
                    )
                })}
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
