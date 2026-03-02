import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { getColorVar } from 'lib/colors'
import {
    AppMetricsTimeSeriesResponse,
    AppMetricsTotalsRequest,
    appMetricsLogic,
    loadAppMetricsTotals,
    type AppMetricsTotalsResponse,
} from 'lib/components/AppMetrics/appMetricsLogic'

import { isOptOutEligibleAction } from './hogflows/steps/types'
import { EXIT_NODE_ID, workflowLogic } from './workflowLogic'
import type { workflowMetricsSummaryLogicType } from './workflowMetricsSummaryLogicType'

type WorkflowSummaryMetric = 'started' | 'in_progress' | 'persons_messaged' | 'completed'
type MessageMetric = 'email_sent' | 'email_opened' | 'email_unsubscribed'

export type MessageMetricRow = {
    id: string
    message: string
    sent: number
    opened: number
    unsubscribed: number
}

export const WORKFLOW_SUMMARY_METRICS: Record<
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
        name: 'Emails delivered',
        description: 'Total number of emails delivered by this workflow',
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

const SUMMARY_METRIC_KEYS = Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]

const MESSAGE_METRICS: MessageMetric[] = ['email_sent', 'email_opened', 'email_unsubscribed']

export interface WorkflowMetricsSummaryLogicProps {
    logicKey: string
    id: string
}

export const workflowMetricsSummaryLogic = kea<workflowMetricsSummaryLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'workflowMetricsSummaryLogic']),
    props({} as WorkflowMetricsSummaryLogicProps),
    key(({ logicKey }: WorkflowMetricsSummaryLogicProps) => logicKey),
    connect((props: WorkflowMetricsSummaryLogicProps) => ({
        values: [
            workflowLogic,
            ['workflow'],
            appMetricsLogic({ logicKey: props.logicKey }),
            [
                'appMetricsTrendsLoading',
                'appMetricsTrends',
                'getSingleTrendSeries',
                'params',
                'currentTeam',
                'getDateRangeAbsolute',
            ],
            appMetricsLogic({
                logicKey: `workflow-exit-node-completed-${props.id}`,
                loadOnMount: true,
                loadOnChanges: true,
                forceParams: {
                    appSource: 'hog_flow',
                    appSourceId: props.id,
                    instanceId: EXIT_NODE_ID,
                    metricName: 'succeeded',
                    breakdownBy: 'metric_name' as const,
                },
            }),
            [
                'appMetricsTrendsLoading as exitNodeCompletedLoading',
                'appMetricsTrends as exitNodeCompletedTrends',
                'getSingleTrendSeries as getExitNodeSingleTrendSeries',
            ],
        ],
        actions: [appMetricsLogic({ logicKey: props.logicKey }), ['setParams', 'loadAppMetricsTrendsSuccess']],
    })),
    loaders(({ values }) => ({
        messageTotalsByActionId: [
            {} as Record<string, Partial<Record<MessageMetric, number>>>,
            {
                loadMessageTotals: async (_, breakpoint) => {
                    await breakpoint(10)
                    const dateRange = values.getDateRangeAbsolute()
                    const request: AppMetricsTotalsRequest = {
                        appSource: values.params.appSource,
                        appSourceId: values.params.appSourceId,
                        breakdownBy: ['instance_id', 'metric_name'],
                        metricName: [...MESSAGE_METRICS],
                        dateFrom: dateRange.dateFrom.toISOString(),
                        dateTo: dateRange.dateTo.toISOString(),
                    }

                    const totalsResponse = await loadAppMetricsTotals(request, values.currentTeam?.timezone ?? 'UTC')
                    await breakpoint(10)

                    return mapMessageMetricsToActions(totalsResponse)
                },
            },
        ],
    })),
    selectors(() => ({
        loading: [
            (s) => [s.appMetricsTrendsLoading, s.exitNodeCompletedLoading],
            (appMetricsTrendsLoading: boolean, exitNodeCompletedLoading: boolean) =>
                appMetricsTrendsLoading || exitNodeCompletedLoading,
        ],

        messageActions: [(s) => [s.workflow], (workflow) => workflow.actions.filter(isOptOutEligibleAction)],

        metricNameBySummaryMetric: [
            (s) => [s.appMetricsTrends],
            (appMetricsTrends): Record<WorkflowSummaryMetric, string> =>
                SUMMARY_METRIC_KEYS.reduce(
                    (acc, metricKey) => {
                        const metric = WORKFLOW_SUMMARY_METRICS[metricKey]
                        acc[metricKey] =
                            metric.metricNames.find((name) =>
                                appMetricsTrends?.series.some((series: { name: string }) => series.name === name)
                            ) ?? metric.metricNames[0]
                        return acc
                    },
                    {} as Record<WorkflowSummaryMetric, string>
                ),
        ],

        workflowSummaryTrends: [
            (s) => [
                s.appMetricsTrends,
                s.exitNodeCompletedTrends,
                s.metricNameBySummaryMetric,
                s.getExitNodeSingleTrendSeries,
            ],
            (
                appMetricsTrends,
                exitNodeCompletedTrends,
                metricNameBySummaryMetric,
                getExitNodeSingleTrendSeries
            ): AppMetricsTimeSeriesResponse | null => {
                if (!appMetricsTrends && !exitNodeCompletedTrends) {
                    return null
                }

                const labels = appMetricsTrends?.labels ?? exitNodeCompletedTrends?.labels ?? []
                const completedValues =
                    getExitNodeSingleTrendSeries('succeeded')?.series[0]?.values ??
                    Array.from({ length: labels.length }, () => 0)
                const triggeredValues =
                    appMetricsTrends?.series.find((series: { name: string }) => series.name === 'triggered')?.values ??
                    Array.from({ length: labels.length }, () => 0)

                return {
                    labels,
                    series: SUMMARY_METRIC_KEYS.map((summaryMetric) => {
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
                        const matchedSeries = appMetricsTrends?.series.find(
                            (series: { name: string }) => series.name === selectedMetricName
                        )

                        return {
                            name: WORKFLOW_SUMMARY_METRICS[summaryMetric].name,
                            values: matchedSeries?.values ?? Array.from({ length: labels.length }, () => 0),
                        }
                    }),
                }
            },
        ],

        messageMetricsRows: [
            (s) => [s.messageActions, s.messageTotalsByActionId],
            (messageActions, messageTotalsByActionId): MessageMetricRow[] =>
                messageActions.map((action: { id: string; name: string }) => {
                    const totals = messageTotalsByActionId[action.id] || {}
                    return {
                        id: action.id,
                        message: action.name,
                        sent: totals.email_sent ?? 0,
                        opened: totals.email_opened ?? 0,
                        unsubscribed: totals.email_unsubscribed ?? 0,
                    }
                }),
        ],

        summaryMetricKeys: [() => [], (): WorkflowSummaryMetric[] => SUMMARY_METRIC_KEYS],
    })),

    afterMount(({ actions }) => {
        actions.loadMessageTotals({})
    }),

    listeners(({ actions, values, props }) => ({
        setParams: () => {
            // Sync date/interval params to the exit node logic
            const exitNodeLogic = appMetricsLogic({
                logicKey: `workflow-exit-node-completed-${props.id}`,
            })
            exitNodeLogic.actions.setParams({
                interval: values.params.interval,
                dateFrom: values.params.dateFrom,
                dateTo: values.params.dateTo,
            })
            actions.loadMessageTotals({})
        },
    })),
])

function subtractSeriesValues(minuend: number[] | undefined, subtrahend: number[] | undefined, size: number): number[] {
    return Array.from({ length: size }, (_, index) => Math.max(0, (minuend?.[index] ?? 0) - (subtrahend?.[index] ?? 0)))
}

export function withDisplayName(
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

export function subtractSeries(
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
