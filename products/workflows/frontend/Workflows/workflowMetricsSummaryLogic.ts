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
import { dayjs } from 'lib/dayjs'

import { isEmailAction } from './hogflows/steps/types'
import { EXIT_NODE_ID, workflowLogic } from './workflowLogic'
import type { workflowMetricsSummaryLogicType } from './workflowMetricsSummaryLogicType'

export type WorkflowSummaryMetric = 'started' | 'in_progress' | 'persons_messaged' | 'completed'
export type EmailMetric =
    | 'email_sent'
    | 'email_failed'
    | 'email_opened'
    | 'email_link_clicked'
    | 'email_bounced'
    | 'email_blocked'
    | 'email_spam'

export type EmailMetricRow = {
    id: string
    email: string
    delivered: number
    sent: number
    opened: number
    linkClicked: number
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
    in_progress: {
        name: 'In progress',
        description: 'Total number of workflow runs currently in progress',
        color: getColorVar('warning'),
        metricNames: ['in_progress'],
    },
    started: {
        name: 'Started',
        description: 'Total number of workflow runs started',
        color: getColorVar('success'),
        metricNames: ['triggered'],
    },
    persons_messaged: {
        name: 'Emails sent',
        description: 'Total number of emails attempted to be sent by this workflow',
        color: '#00F',
        metricNames: ['email_sent'],
    },
    completed: {
        name: 'Completed',
        description:
            'Total number of workflow runs completed. This may include runs that began before the selected date range but completed within it.',
        color: getColorVar('success'),
        metricNames: ['succeeded'],
    },
}

export const WORKFLOW_EMAIL_METRICS: Record<
    EmailMetric,
    { name: string; description: string; color: string; metricNames: string[] }
> = {
    email_sent: {
        name: 'Sent',
        description: 'Total number of emails sent to recipients',
        color: getColorVar('primary'),
        metricNames: ['email_sent'],
    },
    email_failed: {
        name: 'Failed',
        description:
            'Total number of emails that were not attempted to be sent. This typically indicates the PostHog email service determined the email contained a virus.',
        color: getColorVar('danger'),
        metricNames: ['email_failed'],
    },
    email_opened: {
        name: 'Opened',
        description: 'Total number of emails opened',
        color: getColorVar('blue'),
        metricNames: ['email_opened'],
    },
    email_link_clicked: {
        name: 'Link clicked',
        description: 'Total number of times links in emails were clicked',
        color: getColorVar('indigo'),
        metricNames: ['email_link_clicked'],
    },
    email_bounced: {
        name: 'Bounced',
        description: 'Total number of emails that bounced',
        color: getColorVar('orange'),
        metricNames: ['email_bounced'],
    },
    email_blocked: {
        name: 'Blocked',
        description: 'Total number of emails that were blocked by the recipient server',
        color: getColorVar('red'),
        metricNames: ['email_blocked'],
    },
    email_spam: {
        name: 'Marked as spam',
        description: 'Total number of emails that were marked as spam by recipient server or recipient email client',
        color: getColorVar('danger'),
        metricNames: ['email_spam'],
    },
}

const SUMMARY_METRIC_KEYS = (Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]).filter(
    (key) => key !== 'in_progress'
)

const EMAIL_METRICS: EmailMetric[] = [
    'email_sent',
    'email_opened',
    'email_failed',
    'email_link_clicked',
    'email_bounced',
    'email_blocked',
    'email_spam',
]

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
            appMetricsLogic({
                logicKey: `workflow-early-exit-${props.id}`,
                loadOnMount: true,
                loadOnChanges: true,
                forceParams: {
                    appSource: 'hog_flow',
                    appSourceId: props.id,
                    metricName: 'early_exit',
                    breakdownBy: 'metric_name' as const,
                },
            }),
            [
                'appMetricsTrendsLoading as earlyExitLoading',
                'appMetricsTrends as earlyExitTrends',
                'getSingleTrendSeries as getEarlyExitSingleTrendSeries',
            ],
        ],
        actions: [appMetricsLogic({ logicKey: props.logicKey }), ['setParams', 'loadAppMetricsTrendsSuccess']],
    })),
    loaders(({ values }) => ({
        emailTotalsByActionId: [
            {} as Record<string, Partial<Record<EmailMetric, number>>>,
            {
                loadEmailTotals: async (_, breakpoint) => {
                    await breakpoint(10)
                    const dateRange = values.getDateRangeAbsolute()
                    const request: AppMetricsTotalsRequest = {
                        appSource: values.params.appSource,
                        appSourceId: values.params.appSourceId,
                        breakdownBy: ['instance_id', 'metric_name'],
                        metricName: [...EMAIL_METRICS],
                        dateFrom: dateRange.dateFrom.toISOString(),
                        dateTo: dateRange.dateTo.toISOString(),
                    }

                    const totalsResponse = await loadAppMetricsTotals(request, values.currentTeam?.timezone ?? 'UTC')
                    await breakpoint(10)

                    return mapEmailMetricsToActions(totalsResponse)
                },
            },
        ],
        inProgressTotal: [
            0,
            {
                loadInProgressTotal: async (_, breakpoint) => {
                    await breakpoint(10)
                    const timezone = values.currentTeam?.timezone ?? 'UTC'
                    const dateFrom = dayjs().tz(timezone).subtract(30, 'day').toISOString()
                    const request: AppMetricsTotalsRequest = {
                        appSource: values.params.appSource,
                        appSourceId: values.params.appSourceId,
                        breakdownBy: ['metric_name'],
                        metricName: ['triggered'],
                        dateFrom,
                        dateTo: dayjs().tz(timezone).toISOString(),
                    }
                    const triggeredResponse = await loadAppMetricsTotals(request, timezone)
                    await breakpoint(10)

                    const exitRequest: AppMetricsTotalsRequest = {
                        ...request,
                        instanceId: EXIT_NODE_ID,
                        metricName: ['succeeded'],
                    }
                    const completedResponse = await loadAppMetricsTotals(exitRequest, timezone)
                    await breakpoint(10)

                    const triggered = Object.values(triggeredResponse).reduce((sum, r) => sum + r.total, 0)
                    const completed = Object.values(completedResponse).reduce((sum, r) => sum + r.total, 0)
                    return Math.max(0, triggered - completed)
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.appMetricsTrendsLoading, s.exitNodeCompletedLoading, s.earlyExitLoading],
            (appMetricsTrendsLoading: boolean, exitNodeCompletedLoading: boolean, earlyExitLoading: boolean) =>
                appMetricsTrendsLoading || exitNodeCompletedLoading || earlyExitLoading,
        ],

        hasConversion: [(s) => [s.workflow], (workflow) => !!workflow.conversion],

        emailActions: [(s) => [s.workflow], (workflow) => workflow.actions.filter(isEmailAction)],

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

        summaryMetricKeys: [() => [], (): WorkflowSummaryMetric[] => SUMMARY_METRIC_KEYS],
    }),

    // Separate block so these selectors can reference emailActions and metricNameBySummaryMetric via `s`
    selectors({
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

                return {
                    labels,
                    series: SUMMARY_METRIC_KEYS.map((summaryMetric) => {
                        if (summaryMetric === 'completed') {
                            return {
                                name: WORKFLOW_SUMMARY_METRICS.completed.name,
                                values: completedValues,
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

        conversionRateSeries: [
            (s) => [s.appMetricsTrends, s.earlyExitTrends, s.metricNameBySummaryMetric],
            (appMetricsTrends, earlyExitTrends, metricNameBySummaryMetric): AppMetricsTimeSeriesResponse | null => {
                if (!appMetricsTrends && !earlyExitTrends) {
                    return null
                }

                const labels = appMetricsTrends?.labels ?? earlyExitTrends?.labels ?? []
                const startedMetricName = metricNameBySummaryMetric.started
                const startedValues =
                    appMetricsTrends?.series.find((series: { name: string }) => series.name === startedMetricName)
                        ?.values ?? Array.from({ length: labels.length }, () => 0)
                const earlyExitValues =
                    earlyExitTrends?.series.find((series: { name: string }) => series.name === 'early_exit')?.values ??
                    Array.from({ length: labels.length }, () => 0)

                return {
                    labels,
                    series: [
                        {
                            name: 'Conversion rate',
                            values: startedValues.map((started: number, i: number) =>
                                started > 0 ? Math.round((earlyExitValues[i] / started) * 10000) / 100 : 0
                            ),
                        },
                    ],
                }
            },
        ],

        conversionTotal: [
            (s) => [s.getEarlyExitSingleTrendSeries],
            (getEarlyExitSingleTrendSeries): number => {
                const series = getEarlyExitSingleTrendSeries('early_exit')
                if (!series) {
                    return 0
                }
                return series.series.reduce(
                    (acc: number, curr: { values: number[] }) =>
                        acc + curr.values.reduce((a: number, v: number) => a + v, 0),
                    0
                )
            },
        ],

        startedTotal: [
            (s) => [s.appMetricsTrends, s.metricNameBySummaryMetric],
            (appMetricsTrends, metricNameBySummaryMetric): number => {
                if (!appMetricsTrends) {
                    return 0
                }
                const startedMetricName = metricNameBySummaryMetric.started
                const series = appMetricsTrends.series.find((s: { name: string }) => s.name === startedMetricName)
                if (!series) {
                    return 0
                }
                return series.values.reduce((acc: number, v: number) => acc + v, 0)
            },
        ],

        conversionRate: [
            (s) => [s.conversionTotal, s.startedTotal],
            (conversionTotal: number, startedTotal: number): number =>
                startedTotal > 0 ? Math.round((conversionTotal / startedTotal) * 10000) / 100 : 0,
        ],

        emailMetricsRows: [
            (s) => [s.emailActions, s.emailTotalsByActionId],
            (emailActions, emailTotalsByActionId): EmailMetricRow[] =>
                emailActions.map((action: { id: string; name: string }) => {
                    const totals = emailTotalsByActionId[action.id] || {}
                    const sent = totals.email_sent ?? 0
                    const bounced = totals.email_bounced ?? 0
                    const blocked = totals.email_blocked ?? 0
                    return {
                        id: action.id,
                        email: action.name,
                        delivered: Math.max(0, sent - bounced - blocked),
                        sent,
                        opened: totals.email_opened ?? 0,
                        linkClicked: totals.email_link_clicked ?? 0,
                    }
                }),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadEmailTotals({})
        actions.loadInProgressTotal({})
    }),

    listeners(({ actions, values, props }) => ({
        setParams: () => {
            // Sync date/interval params to the exit node and early exit logics
            const dateIntervalParams = {
                interval: values.params.interval,
                dateFrom: values.params.dateFrom,
                dateTo: values.params.dateTo,
            }
            appMetricsLogic({
                logicKey: `workflow-exit-node-completed-${props.id}`,
            }).actions.setParams(dateIntervalParams)
            appMetricsLogic({
                logicKey: `workflow-early-exit-${props.id}`,
            }).actions.setParams(dateIntervalParams)
            actions.loadEmailTotals({})
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

function mapEmailMetricsToActions(
    totalsResponse: AppMetricsTotalsResponse
): Record<string, Partial<Record<EmailMetric, number>>> {
    const result: Record<string, Partial<Record<EmailMetric, number>>> = {}

    Object.values(totalsResponse).forEach(({ total, breakdowns }) => {
        const [instanceId, metricName] = breakdowns
        if (!instanceId || !isEmailMetric(metricName)) {
            return
        }

        result[instanceId] = result[instanceId] || {}
        result[instanceId][metricName] = total
    })

    return result
}

function isEmailMetric(metricName: string): metricName is EmailMetric {
    return EMAIL_METRICS.includes(metricName as EmailMetric)
}
