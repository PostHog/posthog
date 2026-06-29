import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'

import { getColorVar } from 'lib/colors'
import {
    AppMetricsTimeSeriesResponse,
    AppMetricsTotalsRequest,
    appMetricsLogic,
    loadAppMetricsTotals,
    type AppMetricsTotalsResponse,
} from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab, LogEntryLevel, PropertyFilterType, PropertyOperator } from '~/types'

import { isEmailAction } from './hogflows/steps/types'
import { workflowLogic } from './workflowLogic'
import type { workflowMetricsSummaryLogicType } from './workflowMetricsSummaryLogicType'

// Each conversion is emitted as a `$workflows_conversion` PostHog event carrying `$workflow_id`, so
// "View converted users" deep-links to the events explorer scoped to this workflow and date range.
const CONVERSION_EVENT = '$workflows_conversion'

// The run-level "succeeded" metric is emitted once per run that finishes successfully, with an
// empty instance_id — for ANY terminal path, including early exits (e.g. exiting on conversion).
// Filtering on it (rather than the exit node's succeeded) makes "Completed" count converted /
// early-exited runs too, and keeps "In progress" from treating those finished runs as still live.
const RUN_LEVEL_INSTANCE_ID = ''

export type WorkflowSummaryMetric = 'started' | 'in_progress' | 'persons_messaged' | 'completed' | 'converted'
export type EmailMetric =
    | 'email_sent'
    | 'email_delivered'
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
    bounced: number
    blocked: number
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
            'Total number of workflow runs that finished — whether they reached the end of the workflow or exited early (for example, by meeting the conversion goal on an exit-on-conversion workflow). This may include runs that began before the selected date range but finished within it.',
        color: getColorVar('success'),
        metricNames: ['succeeded'],
    },
    converted: {
        name: 'Converted',
        description:
            'Total number of conversions recorded for this workflow. A conversion is counted when a person matches the workflow’s conversion goal (property- or event-based), regardless of whether the workflow is set to exit on conversion.',
        color: getColorVar('purple'),
        metricNames: ['conversion'],
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
    email_delivered: {
        name: 'Delivered',
        description:
            "Total number of emails that were successfully delivered to the recipient's inbox. This is confirmed by the recipient's mail server accepting the email.",
        color: getColorVar('success'),
        metricNames: ['email_delivered'],
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

// Email metrics whose SES events also write per-invocation log entries (see the SES webhook
// handler). Clicking the tile drills into the Invocations tab filtered to those log entries.
// The `search` term matches the start of the log message the handler emits (e.g. "Permanent
// bounce to …"), so it surfaces every invocation that logged that failure in the timeframe.
export const EMAIL_METRIC_LOG_FILTERS: Partial<Record<EmailMetric, { search: string; levels: LogEntryLevel[] }>> = {
    email_bounced: { search: 'bounce', levels: ['WARN', 'ERROR'] },
    email_blocked: { search: 'Complaint', levels: ['WARN', 'ERROR'] },
    // email_failed (RenderingFailure + Reject) is intentionally omitted: its two SES events emit
    // differently-worded messages ("Rendering failure …" vs "Message rejected by SES …") with no
    // shared substring, and filtering by ERROR level alone would also catch permanent bounces.
    // A reliable drill-down would need the log writer to emit a stable machine token to match on.
}

// Build the router search params that point the Invocations (logs) tab at the invocations whose
// log entries match the given email metric over the metrics view's current timeframe.
export function buildEmailMetricLogSearchParams(
    metricKey: EmailMetric,
    dateFrom: string,
    dateTo: string
): Record<string, string | string[]> | null {
    const filter = EMAIL_METRIC_LOG_FILTERS[metricKey]
    if (!filter) {
        return null
    }
    return {
        search: filter.search,
        levels: filter.levels,
        date_from: dateFrom,
        date_to: dateTo,
    }
}

const SUMMARY_METRIC_KEYS = (Object.keys(WORKFLOW_SUMMARY_METRICS) as WorkflowSummaryMetric[]).filter(
    (key) => key !== 'in_progress'
)

const EMAIL_METRICS: EmailMetric[] = [
    'email_sent',
    'email_delivered',
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
    appSourceId?: string
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
                logicKey: `workflow-completed-${props.appSourceId ?? props.id}`,
                loadOnMount: true,
                loadOnChanges: true,
                forceParams: {
                    appSource: 'hog_flow',
                    appSourceId: props.appSourceId ?? props.id,
                    instanceId: RUN_LEVEL_INSTANCE_ID,
                    metricName: 'succeeded',
                    breakdownBy: 'metric_name' as const,
                },
            }),
            [
                'appMetricsTrendsLoading as completedLoading',
                'appMetricsTrends as completedTrends',
                'getSingleTrendSeries as getCompletedSingleTrendSeries',
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
        conversionStats: [
            { conversions: 0, started: 0 } as {
                conversions: number
                started: number
            },
            {
                loadConversionStats: async (_, breakpoint) => {
                    await breakpoint(10)
                    const timezone = values.currentTeam?.timezone ?? 'UTC'
                    const dateRange = values.getDateRangeAbsolute()
                    const baseRequest: AppMetricsTotalsRequest = {
                        appSource: values.params.appSource,
                        appSourceId: values.params.appSourceId,
                        breakdownBy: ['metric_name'],
                        dateFrom: dateRange.dateFrom.toISOString(),
                        dateTo: dateRange.dateTo.toISOString(),
                        metricName: ['conversion'],
                    }
                    // The two totals have no data dependency, so fetch them in parallel.
                    const [conversionResponse, startedResponse] = await Promise.all([
                        loadAppMetricsTotals(baseRequest, timezone),
                        loadAppMetricsTotals({ ...baseRequest, metricName: ['triggered'] }, timezone),
                    ])
                    await breakpoint(10)

                    const conversions = Object.values(conversionResponse).reduce((sum, r) => sum + r.total, 0)
                    const started = Object.values(startedResponse).reduce((sum, r) => sum + r.total, 0)
                    return { conversions, started }
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

                    const completedRequest: AppMetricsTotalsRequest = {
                        ...request,
                        instanceId: RUN_LEVEL_INSTANCE_ID,
                        metricName: ['succeeded'],
                    }
                    const completedResponse = await loadAppMetricsTotals(completedRequest, timezone)
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
            (s) => [s.appMetricsTrendsLoading, s.completedLoading],
            (appMetricsTrendsLoading: boolean, completedLoading: boolean) =>
                appMetricsTrendsLoading || completedLoading,
        ],

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

        conversionRate: [
            (s) => [s.conversionStats],
            ({ conversions, started }): number => (started > 0 ? conversions / started : 0),
        ],

        // Only surface the conversion tiles when a goal is actually configured — without one the
        // backend never emits conversion metrics/events, so the tiles would always read empty.
        hasConversionGoal: [
            (s) => [s.workflow],
            (workflow): boolean => {
                const filters = workflow.conversion?.filters
                const hasPropertyGoal = Array.isArray(filters) && filters.length > 0
                const hasEventGoal = (workflow.conversion?.events?.length ?? 0) > 0
                return hasPropertyGoal || hasEventGoal
            },
        ],

        convertedUsersUrl: [
            (s) => [s.getDateRangeAbsolute, (_, p: WorkflowMetricsSummaryLogicProps) => p.id],
            (getDateRangeAbsolute, id): string => {
                const { dateFrom, dateTo } = getDateRangeAbsolute()
                const source: EventsQuery = {
                    kind: NodeKind.EventsQuery,
                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                    orderBy: ['timestamp DESC'],
                    event: CONVERSION_EVENT,
                    after: dateFrom.toISOString(),
                    before: dateTo.toISOString(),
                    properties: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$workflow_id',
                            operator: PropertyOperator.Exact,
                            value: id,
                        },
                    ],
                }
                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    full: true,
                    source,
                    propertiesViaUrl: true,
                    showSavedQueries: true,
                    showPersistentColumnConfigurator: true,
                }
                return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url
            },
        ],
    }),

    // Separate block so these selectors can reference emailActions and metricNameBySummaryMetric via `s`
    selectors({
        workflowSummaryTrends: [
            (s) => [
                s.appMetricsTrends,
                s.completedTrends,
                s.metricNameBySummaryMetric,
                s.getCompletedSingleTrendSeries,
            ],
            (
                appMetricsTrends,
                completedTrends,
                metricNameBySummaryMetric,
                getCompletedSingleTrendSeries
            ): AppMetricsTimeSeriesResponse | null => {
                if (!appMetricsTrends && !completedTrends) {
                    return null
                }

                const labels = appMetricsTrends?.labels ?? completedTrends?.labels ?? []
                const completedValues =
                    getCompletedSingleTrendSeries('succeeded')?.series[0]?.values ??
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
                        // Fallback to calculating delivered as sent - bounced - blocked if email_delivered metric is not available, since we were not always collecting this metric
                        delivered: totals.email_delivered ?? Math.max(0, sent - bounced - blocked),
                        sent: totals.email_sent ?? 0,
                        opened: totals.email_opened ?? 0,
                        linkClicked: totals.email_link_clicked ?? 0,
                        bounced,
                        blocked,
                    }
                }),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadEmailTotals({})
        actions.loadInProgressTotal({})
        actions.loadConversionStats({})
    }),

    listeners(({ actions, values, props }) => ({
        setParams: () => {
            // Sync date/interval params to the completed (run-level succeeded) logic
            const completedLogic = appMetricsLogic({
                logicKey: `workflow-completed-${props.appSourceId ?? props.id}`,
            })
            completedLogic.actions.setParams({
                interval: values.params.interval,
                dateFrom: values.params.dateFrom,
                dateTo: values.params.dateTo,
            })
            actions.loadEmailTotals({})
            actions.loadConversionStats({})
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
