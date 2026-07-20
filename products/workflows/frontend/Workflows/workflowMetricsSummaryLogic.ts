import { MakeLogicType, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
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
import { buildHogInvocationsSearchParams } from 'scenes/hog-functions/invocations/hogInvocationsLogic'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab, LogEntryLevel, PropertyFilterType, PropertyOperator } from '~/types'

import type { AppMetricsCommonParams } from '../../../../frontend/src/lib/components/AppMetrics/appMetricsLogic'
import type { Dayjs } from '../../../../frontend/src/lib/dayjs'
import type { TeamPublicType, TeamType } from '../../../../frontend/src/types'
import { isEmailAction, isPushAction } from './hogflows/steps/types'
import type { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

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
    | 'email_bounce_prevented'
    | 'email_blocked'
    | 'email_spam'

export type PushMetric = 'push_sent' | 'push_skipped' | 'push_failed'

export type PushMetricRow = {
    id: string
    push: string
    sent: number
    skipped: number
    failed: number
}

export type EmailMetricRow = {
    id: string
    email: string
    delivered: number
    sent: number
    opened: number
    linkClicked: number
    bounced: number
    bouncePrevented: number
    blocked: number
}

// Single source of truth for metric colors across the workflow metric views. Keyed by the metric's
// display name so the same label reads the same color everywhere — in the summary tiles and in the
// trends chart below them. Pass this to `AppMetricsTrends` as `seriesColors` and to `AppMetricSummary`
// so tiles and charts never drift apart.
//
// Only `success`/`blue`/`purple`/`warning`/`danger` exist as themed color vars; the rest (`orange`,
// `indigo`, `red`, `primary`) resolve to white in dark mode. The whole-workflow summary mostly uses
// those themed colors, but Push notifications takes a neutral data-visualization color instead of
// `danger` so a normal channel does not read as an error. The email and push funnels have more series
// than there are distinct semantic colors, so they use the data-visualization palette (`data-color-*`),
// which is built for it — except Failed, which always uses `danger` so a failure reads as an error.
export const METRIC_COLORS: Record<string, string> = {
    // Whole-workflow summary
    'In progress': getColorVar('warning'),
    Started: getColorVar('success'),
    Emails: getColorVar('blue'),
    'Push notifications': getColorVar('data-color-3'),
    Messages: getColorVar('blue'),
    Completed: getColorVar('warning'),
    Converted: getColorVar('purple'),
    // Email + push step funnels
    Sent: getColorVar('data-color-1'),
    Delivered: getColorVar('data-color-2'),
    Failed: getColorVar('danger'),
    Opened: getColorVar('data-color-4'),
    'Link clicked': getColorVar('data-color-5'),
    Bounced: getColorVar('data-color-6'),
    'Bounce prevented': getColorVar('data-color-7'),
    Blocked: getColorVar('data-color-8'),
    'Marked as spam': getColorVar('data-color-9'),
    Skipped: getColorVar('data-color-2'),
    // Workflow run + batch-job metrics
    Success: getColorVar('success'),
    Failure: getColorVar('danger'),
    'Rate Limited': getColorVar('warning'),
    Triggered: getColorVar('blue'),
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
        color: METRIC_COLORS['In progress'],
        metricNames: ['in_progress'],
    },
    started: {
        name: 'Started',
        description: 'Total number of workflow runs started',
        color: METRIC_COLORS['Started'],
        metricNames: ['triggered'],
    },
    persons_messaged: {
        name: 'Emails',
        description: 'Total number of emails attempted to be sent by this workflow',
        color: METRIC_COLORS['Emails'],
        metricNames: ['email_sent'],
    },
    completed: {
        name: 'Completed',
        description:
            'Total number of workflow runs that finished — whether they reached the end of the workflow or exited early (for example, by meeting the conversion goal on an exit-on-conversion workflow). This may include runs that began before the selected date range but finished within it.',
        color: METRIC_COLORS['Completed'],
        metricNames: ['succeeded'],
    },
    converted: {
        name: 'Converted',
        description:
            'Total number of conversions recorded for this workflow. A conversion is counted when a person matches the workflow’s conversion goal (property- or event-based), regardless of whether the workflow is set to exit on conversion.',
        color: METRIC_COLORS['Converted'],
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
        color: METRIC_COLORS['Sent'],
        metricNames: ['email_sent'],
    },
    email_delivered: {
        name: 'Delivered',
        description:
            "Total number of emails that were successfully delivered to the recipient's inbox. This is confirmed by the recipient's mail server accepting the email.",
        color: METRIC_COLORS['Delivered'],
        metricNames: ['email_delivered'],
    },
    email_failed: {
        name: 'Failed',
        description:
            'Total number of emails that were not attempted to be sent. This typically indicates the PostHog email service determined the email contained a virus.',
        color: METRIC_COLORS['Failed'],
        metricNames: ['email_failed'],
    },
    email_opened: {
        name: 'Opened',
        description: 'Total number of emails opened',
        color: METRIC_COLORS['Opened'],
        metricNames: ['email_opened'],
    },
    email_link_clicked: {
        name: 'Link clicked',
        description: 'Total number of times links in emails were clicked',
        color: METRIC_COLORS['Link clicked'],
        metricNames: ['email_link_clicked'],
    },
    email_bounced: {
        name: 'Bounced',
        description: 'Total number of emails that bounced',
        color: METRIC_COLORS['Bounced'],
        metricNames: ['email_bounced'],
    },
    email_bounce_prevented: {
        name: 'Bounce prevented',
        description:
            'Total number of emails that were not sent because pre-send validation predicted a hard bounce: the address was malformed or its domain has no mail servers. These sends are skipped before they can hurt deliverability and are not billed.',
        color: METRIC_COLORS['Bounce prevented'],
        metricNames: ['email_bounce_prevented'],
    },
    email_blocked: {
        name: 'Blocked',
        description: 'Total number of emails that were blocked by the recipient server',
        color: METRIC_COLORS['Blocked'],
        metricNames: ['email_blocked'],
    },
    email_spam: {
        name: 'Marked as spam',
        description: 'Total number of emails that were marked as spam by recipient server or recipient email client',
        color: METRIC_COLORS['Marked as spam'],
        metricNames: ['email_spam'],
    },
}

// Push has no delivery-receipt channel like email's SES webhook (FCM/APNs respond synchronously), so
// these three send-time outcomes are all we can observe. "Sent" means the provider accepted the
// notification for delivery, not that the device displayed it.
export const WORKFLOW_PUSH_METRICS: Record<
    PushMetric,
    { name: string; description: string; color: string; metricNames: string[] }
> = {
    push_sent: {
        name: 'Sent',
        description:
            'Total number of push notifications accepted by the provider (FCM or APNs) for delivery. The provider accepting a notification does not guarantee the device displayed it.',
        color: METRIC_COLORS['Sent'],
        metricNames: ['push_sent'],
    },
    push_skipped: {
        name: 'Skipped',
        description:
            'Total number of recipients skipped because they had no registered device token, or their token was reported dead by the provider (for example, the app was uninstalled) and removed.',
        color: METRIC_COLORS['Skipped'],
        metricNames: ['push_skipped'],
    },
    push_failed: {
        name: 'Failed',
        description:
            'Total number of push notifications that could not be sent — for example invalid credentials, a rejected payload, or a provider outage after retries.',
        color: METRIC_COLORS['Failed'],
        metricNames: ['push_failed'],
    },
}

// How each drillable email metric maps onto the Invocations tab. Each SES event also writes a
// per-invocation log entry (see the SES webhook handler); the drill-down filters the tab to runs
// that logged that entry by matching the message text at the right level. The `search` term matches
// the start of the handler's message (e.g. "Permanent bounce to …"). email_failed is left out: its
// two SES events emit differently-worded messages ("Rendering failure …" vs "Message rejected by
// SES …") with no shared substring to match on.
export const EMAIL_METRIC_INVOCATION_FILTERS: Partial<
    Record<EmailMetric, { search: string; levels: LogEntryLevel[] }>
> = {
    email_bounced: { search: 'bounce', levels: ['WARN', 'ERROR'] },
    // MX-validation skips log "Skipping send: …" at INFO (see HogFunctionHandler in the plugin server).
    email_bounce_prevented: { search: 'Skipping send', levels: ['INFO'] },
    email_blocked: { search: 'Complaint', levels: ['WARN', 'ERROR'] },
}

// Build the router search params that point the Invocations tab at the runs behind the given email
// metric over the metrics view's current timeframe.
export function buildEmailMetricInvocationSearchParams(
    metricKey: EmailMetric,
    dateFrom: string,
    dateTo: string
): Record<string, string> | null {
    const filter = EMAIL_METRIC_INVOCATION_FILTERS[metricKey]
    if (!filter) {
        return null
    }
    return buildHogInvocationsSearchParams({
        date_from: dateFrom,
        date_to: dateTo,
        // Drives the unified Invocations search box: the message term goes in `search`, and
        // `log_levels` narrows the message match to the levels that distinguish this outcome.
        search: filter.search,
        log_levels: filter.levels,
    })
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
    'email_bounce_prevented',
    'email_blocked',
    'email_spam',
]

const PUSH_METRICS: PushMetric[] = ['push_sent', 'push_skipped', 'push_failed']

export interface WorkflowMetricsSummaryLogicProps {
    logicKey: string
    id: string
    appSourceId?: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowMetricsSummaryLogicValues {
    appMetricsTrends: AppMetricsTimeSeriesResponse | null // appMetricsLogic
    appMetricsTrendsLoading: boolean // appMetricsLogic
    completedLoading: boolean // appMetricsLogic
    completedTrends: AppMetricsTimeSeriesResponse | null // appMetricsLogic
    currentTeam: TeamPublicType | TeamType | null // appMetricsLogic
    getCompletedSingleTrendSeries: (name: string, previousPeriod?: boolean) => AppMetricsTimeSeriesResponse | null // appMetricsLogic
    getDateRangeAbsolute: () => {
        dateFrom: Dayjs
        dateTo: Dayjs
        diffMs: number
    } // appMetricsLogic
    getSingleTrendSeries: (name: string, previousPeriod?: boolean) => AppMetricsTimeSeriesResponse | null // appMetricsLogic
    params: Partial<AppMetricsCommonParams> // appMetricsLogic
    workflow: HogFlow // workflowLogic
    conversionRate: number
    conversionStats: {
        conversions: number
        started: number
    }
    conversionStatsLoading: boolean
    convertedUsersUrl: string
    emailActions: ({
        config: {
            inputs: Record<
                string,
                {
                    bytecode?: any
                    order?: number | undefined
                    secret?: boolean | undefined
                    templating?: 'hog' | 'liquid' | undefined
                    value: any
                }
            >
            message_category_id?: string | undefined
            message_category_type?: 'marketing' | 'transactional' | undefined
            template_id: 'template-email'
            template_uuid?: string | undefined
        }
        created_at?: number | undefined
        description: string
        filters?:
            | {
                  actions?: any[] | undefined
                  events?: any[] | undefined
                  properties?: any[] | undefined
              }
            | null
            | undefined
        id: string
        name: string
        on_error?: 'abort' | 'continue' | null | undefined
        output_variable?:
            | {
                  key: string
                  label?: string | null | undefined
                  result_path?: string | null | undefined
                  spread?: boolean | null | undefined
              }
            | {
                  key: string
                  label?: string | null | undefined
                  result_path?: string | null | undefined
                  spread?: boolean | null | undefined
              }[]
            | null
            | undefined
        type: 'function_email'
        updated_at?: number | undefined
    } & Record<string, unknown>)[]
    emailMetricsRows: EmailMetricRow[]
    emailTotalsByActionId: Record<string, Partial<Record<EmailMetric, number>>>
    emailTotalsByActionIdLoading: boolean
    hasConversionGoal: boolean
    inProgressTotal: number
    inProgressTotalLoading: boolean
    loading: boolean
    messagingChannels: {
        hasEmail: boolean
        hasPush: boolean
    }
    metricNameBySummaryMetric: Record<WorkflowSummaryMetric, string>
    pushActions: ({
        config: {
            inputs: Record<
                string,
                {
                    bytecode?: any
                    order?: number | undefined
                    secret?: boolean | undefined
                    templating?: 'hog' | 'liquid' | undefined
                    value: any
                }
            >
            message_category_id?: string | undefined
            message_category_type?: 'marketing' | 'transactional' | undefined
            template_id: 'template-native-push'
            template_uuid?: string | undefined
        }
        created_at?: number | undefined
        description: string
        filters?:
            | {
                  actions?: any[] | undefined
                  events?: any[] | undefined
                  properties?: any[] | undefined
              }
            | null
            | undefined
        id: string
        name: string
        on_error?: 'abort' | 'continue' | null | undefined
        output_variable?:
            | {
                  key: string
                  label?: string | null | undefined
                  result_path?: string | null | undefined
                  spread?: boolean | null | undefined
              }
            | {
                  key: string
                  label?: string | null | undefined
                  result_path?: string | null | undefined
                  spread?: boolean | null | undefined
              }[]
            | null
            | undefined
        type: 'function_push'
        updated_at?: number | undefined
    } & Record<string, unknown>)[]
    pushMetricsRows: PushMetricRow[]
    pushTotalsByActionId: Record<string, Partial<Record<PushMetric, number>>>
    pushTotalsByActionIdLoading: boolean
    sentSummaryLabel: string
    summaryMetricKeys: WorkflowSummaryMetric[]
    workflowSummaryTrends: AppMetricsTimeSeriesResponse | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowMetricsSummaryLogicActions {
    loadAppMetricsTrendsSuccess: (
        appMetricsTrends: AppMetricsTimeSeriesResponse,
        payload?:
            | {
                  value: true
              }
            | undefined
    ) => {
        appMetricsTrends: AppMetricsTimeSeriesResponse
        payload?: {
            value: true
        }
    } // appMetricsLogic
    setParams: (params: Partial<AppMetricsCommonParams>) => {
        params: Partial<AppMetricsCommonParams>
    } // appMetricsLogic
    loadConversionStats: (_: any) => any
    loadConversionStatsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadConversionStatsSuccess: (
        conversionStats: {
            conversions: number
            started: number
        },
        payload?: any
    ) => {
        conversionStats: {
            conversions: number
            started: number
        }
        payload?: any
    }
    loadEmailTotals: (_: any) => any
    loadEmailTotalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEmailTotalsSuccess: (
        emailTotalsByActionId: Record<string, Partial<Record<EmailMetric, number>>>,
        payload?: any
    ) => {
        emailTotalsByActionId: Record<string, Partial<Record<EmailMetric, number>>>
        payload?: any
    }
    loadInProgressTotal: (_: any) => any
    loadInProgressTotalFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadInProgressTotalSuccess: (
        inProgressTotal: number,
        payload?: any
    ) => {
        inProgressTotal: number
        payload?: any
    }
    loadPushTotals: (_: any) => any
    loadPushTotalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPushTotalsSuccess: (
        pushTotalsByActionId: Record<string, Partial<Record<PushMetric, number>>>,
        payload?: any
    ) => {
        pushTotalsByActionId: Record<string, Partial<Record<PushMetric, number>>>
        payload?: any
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowMetricsSummaryLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        loading: (appMetricsTrendsLoading: boolean, completedLoading: boolean) => boolean
        emailActions: (workflow: HogFlow) => ({
            config: {
                inputs: Record<
                    string,
                    {
                        bytecode?: any
                        order?: number | undefined
                        secret?: boolean | undefined
                        templating?: 'hog' | 'liquid' | undefined
                        value: any
                    }
                >
                message_category_id?: string | undefined
                message_category_type?: 'marketing' | 'transactional' | undefined
                template_id: 'template-email'
                template_uuid?: string | undefined
            }
            created_at?: number | undefined
            description: string
            filters?:
                | {
                      actions?: any[] | undefined
                      events?: any[] | undefined
                      properties?: any[] | undefined
                  }
                | null
                | undefined
            id: string
            name: string
            on_error?: 'abort' | 'continue' | null | undefined
            output_variable?:
                | {
                      key: string
                      label?: string | null | undefined
                      result_path?: string | null | undefined
                      spread?: boolean | null | undefined
                  }
                | {
                      key: string
                      label?: string | null | undefined
                      result_path?: string | null | undefined
                      spread?: boolean | null | undefined
                  }[]
                | null
                | undefined
            type: 'function_email'
            updated_at?: number | undefined
        } & Record<string, unknown>)[]
        pushActions: (workflow: HogFlow) => ({
            config: {
                inputs: Record<
                    string,
                    {
                        bytecode?: any
                        order?: number | undefined
                        secret?: boolean | undefined
                        templating?: 'hog' | 'liquid' | undefined
                        value: any
                    }
                >
                message_category_id?: string | undefined
                message_category_type?: 'marketing' | 'transactional' | undefined
                template_id: 'template-native-push'
                template_uuid?: string | undefined
            }
            created_at?: number | undefined
            description: string
            filters?:
                | {
                      actions?: any[] | undefined
                      events?: any[] | undefined
                      properties?: any[] | undefined
                  }
                | null
                | undefined
            id: string
            name: string
            on_error?: 'abort' | 'continue' | null | undefined
            output_variable?:
                | {
                      key: string
                      label?: string | null | undefined
                      result_path?: string | null | undefined
                      spread?: boolean | null | undefined
                  }
                | {
                      key: string
                      label?: string | null | undefined
                      result_path?: string | null | undefined
                      spread?: boolean | null | undefined
                  }[]
                | null
                | undefined
            type: 'function_push'
            updated_at?: number | undefined
        } & Record<string, unknown>)[]
        messagingChannels: (appMetricsTrends: AppMetricsTimeSeriesResponse | null) => {
            hasEmail: boolean
            hasPush: boolean
        }
        sentSummaryLabel: (messagingChannels: { hasEmail: boolean; hasPush: boolean }) => string
        metricNameBySummaryMetric: (
            appMetricsTrends: AppMetricsTimeSeriesResponse | null
        ) => Record<WorkflowSummaryMetric, string>
        conversionRate: (conversionStats: { conversions: number; started: number }) => number
        hasConversionGoal: (workflow: HogFlow) => boolean
        convertedUsersUrl: (
            getDateRangeAbsolute: () => {
                dateFrom: Dayjs
                dateTo: Dayjs
                diffMs: number
            }, // appMetricsLogic
            arg: string
        ) => string
        workflowSummaryTrends: (
            appMetricsTrends: AppMetricsTimeSeriesResponse | null,
            completedTrends: AppMetricsTimeSeriesResponse | null,
            metricNameBySummaryMetric: Record<WorkflowSummaryMetric, string>,
            getCompletedSingleTrendSeries: (
                name: string,
                previousPeriod?: boolean
            ) => AppMetricsTimeSeriesResponse | null, // appMetricsLogic
            messagingChannels: {
                hasEmail: boolean
                hasPush: boolean
            },
            sentSummaryLabel: string
        ) => AppMetricsTimeSeriesResponse | null
        emailMetricsRows: (
            emailActions: ({
                config: {
                    inputs: Record<
                        string,
                        {
                            bytecode?: any
                            order?: number | undefined
                            secret?: boolean | undefined
                            templating?: 'hog' | 'liquid' | undefined
                            value: any
                        }
                    >
                    message_category_id?: string | undefined
                    message_category_type?: 'marketing' | 'transactional' | undefined
                    template_id: 'template-email'
                    template_uuid?: string | undefined
                }
                created_at?: number | undefined
                description: string
                filters?:
                    | {
                          actions?: any[] | undefined
                          events?: any[] | undefined
                          properties?: any[] | undefined
                      }
                    | null
                    | undefined
                id: string
                name: string
                on_error?: 'abort' | 'continue' | null | undefined
                output_variable?:
                    | {
                          key: string
                          label?: string | null | undefined
                          result_path?: string | null | undefined
                          spread?: boolean | null | undefined
                      }
                    | {
                          key: string
                          label?: string | null | undefined
                          result_path?: string | null | undefined
                          spread?: boolean | null | undefined
                      }[]
                    | null
                    | undefined
                type: 'function_email'
                updated_at?: number | undefined
            } & Record<string, unknown>)[],
            emailTotalsByActionId: Record<string, Partial<Record<EmailMetric, number>>>
        ) => EmailMetricRow[]
        pushMetricsRows: (
            pushActions: ({
                config: {
                    inputs: Record<
                        string,
                        {
                            bytecode?: any
                            order?: number | undefined
                            secret?: boolean | undefined
                            templating?: 'hog' | 'liquid' | undefined
                            value: any
                        }
                    >
                    message_category_id?: string | undefined
                    message_category_type?: 'marketing' | 'transactional' | undefined
                    template_id: 'template-native-push'
                    template_uuid?: string | undefined
                }
                created_at?: number | undefined
                description: string
                filters?:
                    | {
                          actions?: any[] | undefined
                          events?: any[] | undefined
                          properties?: any[] | undefined
                      }
                    | null
                    | undefined
                id: string
                name: string
                on_error?: 'abort' | 'continue' | null | undefined
                output_variable?:
                    | {
                          key: string
                          label?: string | null | undefined
                          result_path?: string | null | undefined
                          spread?: boolean | null | undefined
                      }
                    | {
                          key: string
                          label?: string | null | undefined
                          result_path?: string | null | undefined
                          spread?: boolean | null | undefined
                      }[]
                    | null
                    | undefined
                type: 'function_push'
                updated_at?: number | undefined
            } & Record<string, unknown>)[],
            pushTotalsByActionId: Record<string, Partial<Record<PushMetric, number>>>
        ) => PushMetricRow[]
    }
}

export type workflowMetricsSummaryLogicType = MakeLogicType<
    workflowMetricsSummaryLogicValues,
    workflowMetricsSummaryLogicActions,
    WorkflowMetricsSummaryLogicProps,
    workflowMetricsSummaryLogicMeta
>

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
        pushTotalsByActionId: [
            {} as Record<string, Partial<Record<PushMetric, number>>>,
            {
                loadPushTotals: async (_, breakpoint) => {
                    await breakpoint(10)
                    const dateRange = values.getDateRangeAbsolute()
                    const request: AppMetricsTotalsRequest = {
                        appSource: values.params.appSource,
                        appSourceId: values.params.appSourceId,
                        breakdownBy: ['instance_id', 'metric_name'],
                        metricName: [...PUSH_METRICS],
                        dateFrom: dateRange.dateFrom.toISOString(),
                        dateTo: dateRange.dateTo.toISOString(),
                    }

                    const totalsResponse = await loadAppMetricsTotals(request, values.currentTeam?.timezone ?? 'UTC')
                    await breakpoint(10)

                    return mapPushMetricsToActions(totalsResponse)
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

        emailActions: [
            (s) => [s.workflow],
            (workflow: import('./hogflows/types').HogFlow) => workflow.actions.filter(isEmailAction),
        ],

        pushActions: [
            (s) => [s.workflow],
            (workflow: import('./hogflows/types').HogFlow) => workflow.actions.filter(isPushAction),
        ],

        // Which messaging channels actually produced "sent" metrics in the fetched window. Drives the
        // channel-aware "sent" summary tile + chart, so a push-only flow says "Push notifications".
        messagingChannels: [
            (s) => [s.appMetricsTrends],
            (appMetricsTrends: AppMetricsTimeSeriesResponse | null): { hasEmail: boolean; hasPush: boolean } =>
                detectMessagingChannels(appMetricsTrends),
        ],

        // "Emails" for email-only, "Push notifications" for push-only, "Messages" for both.
        sentSummaryLabel: [
            (s) => [s.messagingChannels],
            (messagingChannels: { hasEmail: boolean; hasPush: boolean }): string => channelSentLabel(messagingChannels),
        ],

        metricNameBySummaryMetric: [
            (s) => [s.appMetricsTrends],
            (appMetricsTrends: AppMetricsTimeSeriesResponse | null): Record<WorkflowSummaryMetric, string> =>
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
            (workflow: import('./hogflows/types').HogFlow): boolean => {
                const filters = workflow.conversion?.filters
                const hasPropertyGoal = Array.isArray(filters) && filters.length > 0
                const hasEventGoal = (workflow.conversion?.events?.length ?? 0) > 0
                return hasPropertyGoal || hasEventGoal
            },
        ],

        convertedUsersUrl: [
            (s) => [s.getDateRangeAbsolute, (_, p: WorkflowMetricsSummaryLogicProps) => p.id],
            (
                getDateRangeAbsolute: () => {
                    dateFrom: import('lib/dayjs').Dayjs
                    dateTo: import('lib/dayjs').Dayjs
                    diffMs: number
                },
                id: string
            ): string => {
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
                s.messagingChannels,
                s.sentSummaryLabel,
            ],
            (
                appMetricsTrends: AppMetricsTimeSeriesResponse | null,
                completedTrends: AppMetricsTimeSeriesResponse | null,
                metricNameBySummaryMetric: Record<WorkflowSummaryMetric, string>,
                getCompletedSingleTrendSeries: (
                    name: string,
                    previousPeriod?: boolean
                ) => AppMetricsTimeSeriesResponse | null,
                messagingChannels: { hasEmail: boolean; hasPush: boolean },
                sentSummaryLabel: string
            ): AppMetricsTimeSeriesResponse | null => {
                if (!appMetricsTrends && !completedTrends) {
                    return null
                }

                const labels = appMetricsTrends?.labels ?? completedTrends?.labels ?? []
                const zero = (): number[] => Array.from({ length: labels.length }, () => 0)
                const seriesFor = (metricName: string): number[] =>
                    appMetricsTrends?.series.find((x: { name: string }) => x.name === metricName)?.values ?? zero()
                const completedValues = getCompletedSingleTrendSeries('succeeded')?.series[0]?.values ?? zero()

                return {
                    labels,
                    series: SUMMARY_METRIC_KEYS.flatMap((summaryMetric) => {
                        if (summaryMetric === 'completed') {
                            return [{ name: WORKFLOW_SUMMARY_METRICS.completed.name, values: completedValues }]
                        }

                        // Channel-aware "sent": split into separate Emails + Push notifications lines when
                        // both channels sent, otherwise a single line labelled for whichever channel did.
                        if (summaryMetric === 'persons_messaged') {
                            const { hasEmail, hasPush } = messagingChannels
                            if (hasEmail && hasPush) {
                                return [
                                    { name: 'Emails', values: seriesFor('email_sent') },
                                    { name: 'Push notifications', values: seriesFor('push_sent') },
                                ]
                            }
                            return [{ name: sentSummaryLabel, values: seriesFor(hasPush ? 'push_sent' : 'email_sent') }]
                        }

                        return [
                            {
                                name: WORKFLOW_SUMMARY_METRICS[summaryMetric].name,
                                values: seriesFor(metricNameBySummaryMetric[summaryMetric]),
                            },
                        ]
                    }),
                }
            },
        ],

        emailMetricsRows: [
            (s) => [s.emailActions, s.emailTotalsByActionId],
            (
                emailActions: ({
                    config: {
                        inputs: Record<
                            string,
                            {
                                bytecode?: any
                                order?: number | undefined
                                secret?: boolean | undefined
                                templating?: 'hog' | 'liquid' | undefined
                                value: any
                            }
                        >
                        message_category_id?: string | undefined
                        message_category_type?: 'marketing' | 'transactional' | undefined
                        template_id: 'template-email'
                        template_uuid?: string | undefined
                    }
                    created_at?: number | undefined
                    description: string
                    filters?:
                        | {
                              actions?: any[] | undefined
                              events?: any[] | undefined
                              properties?: any[] | undefined
                          }
                        | null
                        | undefined
                    id: string
                    name: string
                    on_error?: 'abort' | 'continue' | null | undefined
                    output_variable?:
                        | {
                              key: string
                              label?: string | null | undefined
                              result_path?: string | null | undefined
                              spread?: boolean | null | undefined
                          }
                        | {
                              key: string
                              label?: string | null | undefined
                              result_path?: string | null | undefined
                              spread?: boolean | null | undefined
                          }[]
                        | null
                        | undefined
                    type: 'function_email'
                    updated_at?: number | undefined
                } & Record<string, unknown>)[],
                emailTotalsByActionId: Record<string, Partial<Record<EmailMetric, number>>>
            ): EmailMetricRow[] => buildEmailMetricRows(emailActions, emailTotalsByActionId),
        ],

        pushMetricsRows: [
            (s) => [s.pushActions, s.pushTotalsByActionId],
            (
                pushActions: ({
                    config: {
                        inputs: Record<
                            string,
                            {
                                bytecode?: any
                                order?: number | undefined
                                secret?: boolean | undefined
                                templating?: 'hog' | 'liquid' | undefined
                                value: any
                            }
                        >
                        message_category_id?: string | undefined
                        message_category_type?: 'marketing' | 'transactional' | undefined
                        template_id: 'template-native-push'
                        template_uuid?: string | undefined
                    }
                    created_at?: number | undefined
                    description: string
                    filters?:
                        | {
                              actions?: any[] | undefined
                              events?: any[] | undefined
                              properties?: any[] | undefined
                          }
                        | null
                        | undefined
                    id: string
                    name: string
                    on_error?: 'abort' | 'continue' | null | undefined
                    output_variable?:
                        | {
                              key: string
                              label?: string | null | undefined
                              result_path?: string | null | undefined
                              spread?: boolean | null | undefined
                          }
                        | {
                              key: string
                              label?: string | null | undefined
                              result_path?: string | null | undefined
                              spread?: boolean | null | undefined
                          }[]
                        | null
                        | undefined
                    type: 'function_push'
                    updated_at?: number | undefined
                } & Record<string, unknown>)[],
                pushTotalsByActionId: Record<string, Partial<Record<PushMetric, number>>>
            ): PushMetricRow[] => buildPushMetricRows(pushActions, pushTotalsByActionId),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadEmailTotals({})
        actions.loadPushTotals({})
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
            actions.loadPushTotals({})
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

// Which messaging channels produced "sent" metrics in the fetched window, keyed off the trend series.
export function detectMessagingChannels(appMetricsTrends: AppMetricsTimeSeriesResponse | null): {
    hasEmail: boolean
    hasPush: boolean
} {
    return {
        hasEmail: !!appMetricsTrends?.series.some((x: { name: string }) => x.name === 'email_sent'),
        hasPush: !!appMetricsTrends?.series.some((x: { name: string }) => x.name === 'push_sent'),
    }
}

// "Emails" for email-only, "Push notifications" for push-only, "Messages" for both.
export function channelSentLabel({ hasEmail, hasPush }: { hasEmail: boolean; hasPush: boolean }): string {
    return hasEmail && hasPush ? 'Messages' : hasPush ? 'Push notifications' : 'Emails'
}

export function buildEmailMetricRows(
    emailActions: { id: string; name: string }[],
    emailTotalsByActionId: Record<string, Partial<Record<EmailMetric, number>>>
): EmailMetricRow[] {
    return emailActions.map((action) => {
        const totals = emailTotalsByActionId[action.id] || {}
        const sent = totals.email_sent ?? 0
        const bounced = totals.email_bounced ?? 0
        const blocked = totals.email_blocked ?? 0
        return {
            id: action.id,
            email: action.name,
            // Fallback to calculating delivered as sent - bounced - blocked if email_delivered metric is not available, since we were not always collecting this metric
            delivered: totals.email_delivered ?? Math.max(0, sent - bounced - blocked),
            sent,
            opened: totals.email_opened ?? 0,
            linkClicked: totals.email_link_clicked ?? 0,
            bounced,
            bouncePrevented: totals.email_bounce_prevented ?? 0,
            blocked,
        }
    })
}

export function buildPushMetricRows(
    pushActions: { id: string; name: string }[],
    pushTotalsByActionId: Record<string, Partial<Record<PushMetric, number>>>
): PushMetricRow[] {
    return pushActions.map((action) => {
        const totals = pushTotalsByActionId[action.id] || {}
        return {
            id: action.id,
            push: action.name,
            sent: totals.push_sent ?? 0,
            skipped: totals.push_skipped ?? 0,
            failed: totals.push_failed ?? 0,
        }
    })
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

function mapPushMetricsToActions(
    totalsResponse: AppMetricsTotalsResponse
): Record<string, Partial<Record<PushMetric, number>>> {
    const result: Record<string, Partial<Record<PushMetric, number>>> = {}

    Object.values(totalsResponse).forEach(({ total, breakdowns }) => {
        const [instanceId, metricName] = breakdowns
        if (!instanceId || !isPushMetric(metricName)) {
            return
        }

        result[instanceId] = result[instanceId] || {}
        result[instanceId][metricName] = total
    })

    return result
}

function isPushMetric(metricName: string): metricName is PushMetric {
    return PUSH_METRICS.includes(metricName as PushMetric)
}
