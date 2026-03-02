import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import {
    AppMetricsTimeSeriesResponse,
    AppMetricsTotalsRequest,
    appMetricsLogic,
    loadAppMetricsTotals,
    type AppMetricsTotalsResponse,
} from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

import { isOptOutEligibleAction } from './hogflows/steps/types'
import { EXIT_NODE_ID, workflowLogic } from './workflowLogic'

type WorkflowSummaryMetric = 'started' | 'in_progress' | 'persons_messaged' | 'completed'
type MessageMetric = 'email_sent' | 'email_opened' | 'email_unsubscribed'

type MessageMetricRow = {
    id: string
    message: string
    sent: number
    opened: number
    unsubscribed: number
}

const WORKFLOW_SUMMARY_METRICS: Record<
    WorkflowSummaryMetric,
    {
        name: string
        description: string
        color: string
        metricNames: string[]
    }
> = {
    started: {
        name: 'Started',
        description: 'Total number of workflow runs started',
        color: getColorVar('success'),
        metricNames: ['triggered'],
    },
    in_progress: {
        name: 'In progress',
        description: 'Total number of workflow runs currently in progress',
        color: getColorVar('warning'),
        metricNames: ['in_progress'],
    },
    persons_messaged: {
        name: 'Messages delivered',
        description: 'Total number of messages delivered by this workflow',
        color: getColorVar('primary'),
        metricNames: ['email_sent'],
    },
    completed: {
        name: 'Completed',
        description: 'Total number of workflow runs completed',
        color: getColorVar('success'),
        metricNames: ['succeeded'],
    },
}

const MESSAGE_METRICS: MessageMetric[] = ['email_sent', 'email_opened', 'email_unsubscribed']

export function WorkflowMetricsSummary({ logic }: { logic: ReturnType<typeof appMetricsLogic> }): JSX.Element {
    const { workflow } = useValues(workflowLogic)
    const {
        appMetricsTrendsLoading,
        getSingleTrendSeries,
        appMetricsTrends,
        params,
        currentTeam,
        getDateRangeAbsolute,
    } = useValues(logic)

    const exitNodeCompletedLogic = appMetricsLogic({
        logicKey: `workflow-exit-node-completed-${params.appSourceId}`,
        loadOnMount: true,
        loadOnChanges: true,
        forceParams: {
            appSource: params.appSource,
            appSourceId: params.appSourceId,
            instanceId: EXIT_NODE_ID,
            metricName: 'succeeded',
            breakdownBy: 'metric_name',
            interval: params.interval,
            dateFrom: params.dateFrom,
            dateTo: params.dateTo,
        },
    })

    const {
        appMetricsTrendsLoading: exitNodeCompletedLoading,
        appMetricsTrends: exitNodeCompletedTrends,
        getSingleTrendSeries: getExitNodeSingleTrendSeries,
    } = useValues(exitNodeCompletedLogic)

    const [messageTotalsByActionId, setMessageTotalsByActionId] = useState<
        Record<string, Partial<Record<MessageMetric, number>>>
    >({})
    const [messageTotalsLoading, setMessageTotalsLoading] = useState(false)

    const messageActions = useMemo(() => workflow.actions.filter(isOptOutEligibleAction), [workflow.actions])

    const metricNameBySummaryMetric = useMemo(() => {
        return (Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]).reduce(
            (acc, key) => {
                const metric = WORKFLOW_SUMMARY_METRICS[key]
                const selectedMetricName =
                    metric.metricNames.find((metricName) =>
                        appMetricsTrends?.series.some((series) => series.name === metricName)
                    ) ?? metric.metricNames[0]
                acc[key] = selectedMetricName
                return acc
            },
            {} as Record<WorkflowSummaryMetric, string>
        )
    }, [appMetricsTrends])

    const workflowSummaryTrends = useMemo((): AppMetricsTimeSeriesResponse | null => {
        if (!appMetricsTrends && !exitNodeCompletedTrends) {
            return null
        }

        const labels = appMetricsTrends?.labels ?? exitNodeCompletedTrends?.labels ?? []
        const completedValues =
            getExitNodeSingleTrendSeries('succeeded')?.series[0]?.values ??
            Array.from({ length: labels.length }, () => 0)
        const triggeredValues =
            appMetricsTrends?.series.find((series) => series.name === 'triggered')?.values ??
            Array.from({ length: labels.length }, () => 0)

        return {
            labels,
            series: (Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]).map((summaryMetric) => {
                if (summaryMetric === 'completed') {
                    return {
                        name: WORKFLOW_SUMMARY_METRICS.completed.name,
                        values: completedValues,
                    }
                }

                if (summaryMetric === 'in_progress') {
                    return {
                        name: WORKFLOW_SUMMARY_METRICS.in_progress.name,
                        values: subtractSeriesValues(triggeredValues, completedValues, labels.length),
                    }
                }

                const selectedMetricName = metricNameBySummaryMetric[summaryMetric]
                const matchedSeries = appMetricsTrends?.series.find((series) => series.name === selectedMetricName)

                return {
                    name: WORKFLOW_SUMMARY_METRICS[summaryMetric].name,
                    values: matchedSeries?.values ?? Array.from({ length: labels.length }, () => 0),
                }
            }),
        }
    }, [appMetricsTrends, exitNodeCompletedTrends, metricNameBySummaryMetric, getExitNodeSingleTrendSeries])

    const messageMetricsRows = useMemo<MessageMetricRow[]>(() => {
        return messageActions.map((action) => {
            const totals = messageTotalsByActionId[action.id] || {}
            return {
                id: action.id,
                message: action.name,
                sent: totals.email_sent ?? 0,
                opened: totals.email_opened ?? 0,
                unsubscribed: totals.email_unsubscribed ?? 0,
            }
        })
    }, [messageActions, messageTotalsByActionId])

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

    useEffect(() => {
        let cancelled = false

        const loadMessageTotals = async (): Promise<void> => {
            setMessageTotalsLoading(true)
            try {
                const dateRange = getDateRangeAbsolute()
                const request: AppMetricsTotalsRequest = {
                    appSource: params.appSource,
                    appSourceId: params.appSourceId,
                    breakdownBy: ['metric_name'],
                    metricName: [...MESSAGE_METRICS],
                    dateFrom: dateRange.dateFrom.toISOString(),
                    dateTo: dateRange.dateTo.toISOString(),
                }

                const totalsResponse = await loadAppMetricsTotals(request, currentTeam?.timezone ?? 'UTC')
                if (cancelled) {
                    return
                }

                const nextTotalsByActionId = mapMessageMetricsToActions(totalsResponse)
                setMessageTotalsByActionId(nextTotalsByActionId)
            } finally {
                if (!cancelled) {
                    setMessageTotalsLoading(false)
                }
            }
        }

        void loadMessageTotals()

        return () => {
            cancelled = true
        }
    }, [
        params.appSource,
        params.appSourceId,
        params.dateFrom,
        params.dateTo,
        params.interval,
        currentTeam?.timezone,
        getDateRangeAbsolute,
    ])

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {(Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]).map((summaryMetric) => {
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
                            loading={appMetricsTrendsLoading || exitNodeCompletedLoading}
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
                loading={messageTotalsLoading}
                rowKey="id"
                size="small"
                emptyState="No message actions in this workflow"
            />

            <AppMetricsTrends
                appMetricsTrends={workflowSummaryTrends}
                loading={appMetricsTrendsLoading || exitNodeCompletedLoading}
            />
        </>
    )
}

function withDisplayName(
    series: AppMetricsTimeSeriesResponse | null,
    displayName: string
): AppMetricsTimeSeriesResponse | null {
    if (!series) {
        return null
    }

    return {
        labels: series.labels,
        series: series.series.map((item) => ({
            ...item,
            name: displayName,
        })),
    }
}

function subtractSeries(
    minuendSeries: AppMetricsTimeSeriesResponse | null,
    subtrahendSeries: AppMetricsTimeSeriesResponse | null,
    displayName: string
): AppMetricsTimeSeriesResponse | null {
    if (!minuendSeries && !subtrahendSeries) {
        return null
    }

    const labels = minuendSeries?.labels ?? subtrahendSeries?.labels ?? []

    return {
        labels,
        series: [
            {
                name: displayName,
                values: subtractSeriesValues(
                    minuendSeries?.series[0]?.values,
                    subtrahendSeries?.series[0]?.values,
                    labels.length
                ),
            },
        ],
    }
}

function subtractSeriesValues(minuend: number[] | undefined, subtrahend: number[] | undefined, size: number): number[] {
    return Array.from({ length: size }, (_, index) => Math.max(0, (minuend?.[index] ?? 0) - (subtrahend?.[index] ?? 0)))
}

function mapMessageMetricsToActions(
    totalsResponse: AppMetricsTotalsResponse
): Record<string, Partial<Record<MessageMetric, number>>> {
    const result: Record<string, Partial<Record<MessageMetric, number>>> = {}

    Object.values(totalsResponse).forEach(({ total, breakdowns }) => {
        const [instanceId, metricName] = breakdowns
        if (!instanceId || !isMessageMetric(metricName)) {
            return
        }

        result[instanceId] = result[instanceId] || {}
        result[instanceId][metricName] = total
    })

    return result
}

function isMessageMetric(metricName: string): metricName is MessageMetric {
    return MESSAGE_METRICS.includes(metricName as MessageMetric)
}
