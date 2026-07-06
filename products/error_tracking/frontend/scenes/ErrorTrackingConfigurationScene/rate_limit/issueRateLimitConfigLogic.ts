import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ErrorTrackingSettings } from 'lib/components/Errors/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { HogQLQueryResponse, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import type { issueRateLimitConfigLogicType } from './issueRateLimitConfigLogicType'
import {
    DEFAULT_BUCKET_MINUTES,
    BYPASSED_METRIC_NAME,
    DROPPED_METRIC_NAME,
    EXCEPTIONS_APP_SOURCE,
    ExceptionVolumeBucket,
    getBucketOption,
    RateLimitChartMode,
    RateLimitHistoryBucket,
    RECORDED_METRIC_NAME,
} from './rateLimitConfigLogic'

export interface IssueRateLimitConfigForm {
    per_issue_rate_limit_value: number | null
    per_issue_rate_limit_bucket_size_minutes: number
}

export interface TopIssue {
    issue_id: string
    name: string | null
    description: string | null
    occurrences: number
}

const DEFAULT_CONFIG: IssueRateLimitConfigForm = {
    per_issue_rate_limit_value: null,
    per_issue_rate_limit_bucket_size_minutes: DEFAULT_BUCKET_MINUTES,
}

export const issueRateLimitConfigLogic = kea<issueRateLimitConfigLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'rate_limit',
        'issueRateLimitConfigLogic',
    ]),

    actions({
        selectIssue: (issueId: string | null) => ({ issueId }),
        setChartMode: (mode: RateLimitChartMode) => ({ mode }),
        refreshChart: true,
    }),

    reducers({
        hasLoadedConfig: [
            false,
            {
                loadConfigSuccess: () => true,
            },
        ],
        selectedIssueId: [
            null as string | null,
            {
                selectIssue: (_, { issueId }) => issueId,
            },
        ],
        chartMode: [
            'simulation' as RateLimitChartMode,
            {
                setChartMode: (_, { mode }) => mode,
            },
        ],
    }),

    loaders(() => ({
        config: [
            null as ErrorTrackingSettings | null,
            {
                loadConfig: async () => {
                    return await api.errorTracking.getSettings()
                },
            },
        ],
        topIssues: [
            [] as TopIssue[],
            {
                loadTopIssues: async ({ bucketMinutes }: { bucketMinutes: number }, breakpoint) => {
                    const option = getBucketOption(bucketMinutes)
                    const totalMinutes = option.minutes * option.bucketCount
                    await breakpoint(300)
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                toString(issue_id_v2) AS issue_id,
                                any(issue_name) AS name,
                                any(issue_description) AS description,
                                count() AS occurrences
                            FROM events
                            WHERE event = '$exception'
                              AND timestamp >= now() - INTERVAL ${totalMinutes} MINUTE
                              AND issue_id_v2 IS NOT NULL
                            GROUP BY issue_id_v2
                            ORDER BY occurrences DESC
                            LIMIT 10
                        `,
                        tags: { productKey: ProductKey.ERROR_TRACKING },
                    })) as HogQLQueryResponse
                    breakpoint()
                    return (response.results ?? []).map(([issue_id, name, description, occurrences]) => ({
                        issue_id: String(issue_id),
                        name: name == null ? null : String(name),
                        description: description == null ? null : String(description),
                        occurrences: Number(occurrences),
                    }))
                },
            },
        ],
        selectedIssueVolume: [
            [] as ExceptionVolumeBucket[],
            {
                loadSelectedIssueVolume: async (
                    {
                        issueId,
                        bucketMinutes,
                        force,
                    }: {
                        issueId: string
                        bucketMinutes: number
                        force?: boolean
                    },
                    breakpoint
                ) => {
                    const option = getBucketOption(bucketMinutes)
                    const totalMinutes = option.minutes * option.bucketCount
                    await breakpoint(300)
                    const response = (await api.query(
                        {
                            kind: NodeKind.HogQLQuery,
                            query: `
                            SELECT
                                toStartOfInterval(timestamp, INTERVAL ${option.minutes} MINUTE) AS bucket,
                                count() AS count
                            FROM events
                            WHERE event = '$exception'
                              AND timestamp >= now() - INTERVAL ${totalMinutes} MINUTE
                              AND toString(issue_id_v2) = {issueId}
                            GROUP BY bucket
                            ORDER BY bucket
                            LIMIT ${option.bucketCount + 1}
                        `,
                            values: { issueId },
                            tags: { productKey: ProductKey.ERROR_TRACKING },
                        },
                        force ? { refresh: 'force_blocking' } : undefined
                    )) as HogQLQueryResponse
                    breakpoint()
                    return (response.results ?? []).map(([bucket, count]) => ({
                        bucket: String(bucket),
                        count: Number(count),
                    }))
                },
            },
        ],
        selectedIssueHistory: [
            [] as RateLimitHistoryBucket[],
            {
                loadSelectedIssueHistory: async (
                    {
                        issueId,
                        bucketMinutes,
                        force,
                    }: {
                        issueId: string
                        bucketMinutes: number
                        force?: boolean
                    },
                    breakpoint
                ) => {
                    const option = getBucketOption(bucketMinutes)
                    const totalMinutes = option.minutes * option.bucketCount
                    await breakpoint(300)
                    // The per-issue rate limiter emits app_metrics2 rows keyed by the issue id directly.
                    const response = (await api.query(
                        {
                            kind: NodeKind.HogQLQuery,
                            query: `
                            SELECT
                                toStartOfInterval(timestamp, INTERVAL ${option.minutes} MINUTE) AS bucket,
                                metric_name,
                                sum(count) AS count
                            FROM app_metrics
                            WHERE app_source = '${EXCEPTIONS_APP_SOURCE}'
                              AND app_source_id = {issueId}
                              AND metric_name IN ('${RECORDED_METRIC_NAME}', '${DROPPED_METRIC_NAME}', '${BYPASSED_METRIC_NAME}')
                              AND timestamp >= now() - INTERVAL ${totalMinutes} MINUTE
                            GROUP BY bucket, metric_name
                            ORDER BY bucket
                            LIMIT ${(option.bucketCount + 1) * 3}
                        `,
                            values: { issueId },
                            tags: { productKey: ProductKey.ERROR_TRACKING },
                        },
                        force ? { refresh: 'force_blocking' } : undefined
                    )) as HogQLQueryResponse
                    breakpoint()
                    const byBucket = new Map<string, RateLimitHistoryBucket>()
                    for (const [bucket, metricName, count] of response.results ?? []) {
                        const key = String(bucket)
                        const entry = byBucket.get(key) ?? { bucket: key, recorded: 0, dropped: 0, bypassed: 0 }
                        if (metricName === RECORDED_METRIC_NAME) {
                            entry.recorded = Number(count)
                        } else if (metricName === DROPPED_METRIC_NAME) {
                            entry.dropped = Number(count)
                        } else if (metricName === BYPASSED_METRIC_NAME) {
                            entry.bypassed = Number(count)
                        }
                        byBucket.set(key, entry)
                    }
                    return [...byBucket.values()]
                },
            },
        ],
    })),

    forms(({ actions }) => ({
        configForm: {
            defaults: DEFAULT_CONFIG,
            errors: ({ per_issue_rate_limit_value }) => ({
                per_issue_rate_limit_value:
                    per_issue_rate_limit_value !== null && per_issue_rate_limit_value < 1
                        ? 'Rate limit must be at least 1'
                        : undefined,
            }),
            submit: async ({ per_issue_rate_limit_value, per_issue_rate_limit_bucket_size_minutes }) => {
                try {
                    const payload = { per_issue_rate_limit_value, per_issue_rate_limit_bucket_size_minutes }
                    await api.errorTracking.updateSettings(payload)
                    actions.resetConfigForm(payload)
                    posthog.capture('error_tracking_per_issue_rate_limit_updated', payload)
                    lemonToast.success('Settings saved')
                } catch (e) {
                    lemonToast.error('Failed to save settings')
                    throw e
                }
            },
        },
    })),

    selectors({
        selectedIssue: [
            (s) => [s.topIssues, s.selectedIssueId],
            (issues, selectedId) => issues.find((i) => i.issue_id === selectedId) ?? null,
        ],
    }),

    listeners(({ actions, values }) => ({
        loadConfigSuccess: ({ config }) => {
            const bucket = getBucketOption(
                config?.per_issue_rate_limit_bucket_size_minutes ?? DEFAULT_BUCKET_MINUTES
            ).minutes
            const limit = config?.per_issue_rate_limit_value ?? null
            if (config) {
                actions.resetConfigForm({
                    per_issue_rate_limit_value: limit,
                    per_issue_rate_limit_bucket_size_minutes: bucket,
                })
            }
            actions.loadTopIssues({ bucketMinutes: bucket })
        },
        setConfigFormValue: ({ name, value }) => {
            const fieldName = Array.isArray(name) ? name[name.length - 1] : name
            if (fieldName === 'per_issue_rate_limit_bucket_size_minutes' && typeof value === 'number') {
                actions.loadTopIssues({ bucketMinutes: value })
            }
        },
        selectIssue: ({ issueId }) => {
            if (!issueId) {
                return
            }
            const bucketMinutes = values.configForm.per_issue_rate_limit_bucket_size_minutes
            // Fetch both charts once per issue; toggling between Simulation and History then reuses
            // them without refetching. The reload button forces a refresh when fresh data is wanted.
            actions.loadSelectedIssueVolume({ issueId, bucketMinutes })
            actions.loadSelectedIssueHistory({ issueId, bucketMinutes })
        },
        loadTopIssuesSuccess: ({ topIssues }) => {
            const current = values.selectedIssueId
            const keep = current && topIssues.some((i) => i.issue_id === current)
            const nextId = keep ? current : (topIssues[0]?.issue_id ?? null)
            if (nextId) {
                actions.selectIssue(nextId)
            }
        },
        refreshChart: () => {
            const issueId = values.selectedIssueId
            if (!issueId) {
                return
            }
            const bucketMinutes = values.configForm.per_issue_rate_limit_bucket_size_minutes
            if (values.chartMode === 'history') {
                actions.loadSelectedIssueHistory({ issueId, bucketMinutes, force: true })
            } else {
                actions.loadSelectedIssueVolume({ issueId, bucketMinutes, force: true })
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.hasLoadedConfig) {
            actions.loadConfig()
        }
    }),
])
