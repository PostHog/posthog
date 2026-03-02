import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

import {
    WORKFLOW_SUMMARY_METRICS,
    type MessageMetricRow,
    subtractSeries,
    withDisplayName,
    workflowMetricsSummaryLogic,
    type WorkflowMetricsSummaryLogicProps,
} from './workflowMetricsSummaryLogic'

export function WorkflowMetricsSummary(props: WorkflowMetricsSummaryLogicProps): JSX.Element {
    const {
        loading,
        summaryMetricKeys,
        metricNameBySummaryMetric,
        getSingleTrendSeries,
        getExitNodeSingleTrendSeries,
        workflowSummaryTrends,
        messageMetricsRows,
        messageTotalsByActionIdLoading,
    } = useValues(workflowMetricsSummaryLogic(props))

    const messageMetricsColumns: LemonTableColumns<MessageMetricRow> = useMemo(
        () => [
            {
                title: 'Message',
                dataIndex: 'message',
                key: 'message',
            },
            {
                title: 'Sent',
                dataIndex: 'sent',
                key: 'sent',
                align: 'right',
                render: (_, row) => row.sent.toLocaleString(),
            },
            {
                title: 'Opened',
                dataIndex: 'opened',
                key: 'opened',
                align: 'right',
                render: (_, row) => row.opened.toLocaleString(),
            },
            {
                title: 'Unsubscribed',
                dataIndex: 'unsubscribed',
                key: 'unsubscribed',
                align: 'right',
                render: (_, row) => row.unsubscribed.toLocaleString(),
            },
        ],
        []
    )

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {summaryMetricKeys.map((summaryMetric) => {
                    const metric = WORKFLOW_SUMMARY_METRICS[summaryMetric]
                    const metricName = metricNameBySummaryMetric[summaryMetric]
                    const timeSeries =
                        summaryMetric === 'completed'
                            ? withDisplayName(getExitNodeSingleTrendSeries('succeeded'), metric.name)
                            : summaryMetric === 'in_progress'
                              ? subtractSeries(
                                    getSingleTrendSeries('triggered'),
                                    getExitNodeSingleTrendSeries('succeeded'),
                                    metric.name
                                )
                              : withDisplayName(getSingleTrendSeries(metricName), metric.name)

                    const previousPeriodTimeSeries =
                        summaryMetric === 'completed'
                            ? withDisplayName(getExitNodeSingleTrendSeries('succeeded', true), metric.name)
                            : summaryMetric === 'in_progress'
                              ? subtractSeries(
                                    getSingleTrendSeries('triggered', true),
                                    getExitNodeSingleTrendSeries('succeeded', true),
                                    metric.name
                                )
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
                columns={messageMetricsColumns}
                dataSource={messageMetricsRows}
                loading={messageTotalsByActionIdLoading}
                rowKey="id"
                size="small"
                emptyState="No message actions in this workflow"
            />

            <AppMetricsTrends appMetricsTrends={workflowSummaryTrends} loading={loading} />
        </>
    )
}
