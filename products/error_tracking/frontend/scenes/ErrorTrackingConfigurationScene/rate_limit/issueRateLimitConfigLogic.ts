import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ErrorTrackingSettings } from 'lib/components/Errors/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { HogQLQueryResponse, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import type { issueRateLimitConfigLogicType } from './issueRateLimitConfigLogicType'
import { DEFAULT_BUCKET_MINUTES, ExceptionVolumeBucket, getBucketOption } from './rateLimitConfigLogic'

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

const TOP_ISSUES_WINDOW_DAYS = 7

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
                loadTopIssues: async () => {
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
                              AND timestamp >= now() - INTERVAL ${TOP_ISSUES_WINDOW_DAYS} DAY
                              AND issue_id_v2 IS NOT NULL
                            GROUP BY issue_id_v2
                            ORDER BY occurrences DESC
                            LIMIT 100
                        `,
                        tags: { productKey: ProductKey.ERROR_TRACKING },
                    })) as HogQLQueryResponse
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
                loadSelectedIssueVolume: async ({
                    issueId,
                    bucketMinutes,
                }: {
                    issueId: string
                    bucketMinutes: number
                }) => {
                    const option = getBucketOption(bucketMinutes)
                    const totalMinutes = option.minutes * option.bucketCount
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                toStartOfInterval(timestamp, INTERVAL ${option.minutes} MINUTE) AS bucket,
                                count() AS count
                            FROM events
                            WHERE event = '$exception'
                              AND timestamp >= now() - INTERVAL ${totalMinutes} MINUTE
                              AND toString(issue_id_v2) = '${issueId}'
                            GROUP BY bucket
                            ORDER BY bucket
                        `,
                        tags: { productKey: ProductKey.ERROR_TRACKING },
                    })) as HogQLQueryResponse
                    return (response.results ?? []).map(([bucket, count]) => ({
                        bucket: String(bucket),
                        count: Number(count),
                    }))
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
            const bucket = config?.per_issue_rate_limit_bucket_size_minutes ?? DEFAULT_BUCKET_MINUTES
            const limit = config?.per_issue_rate_limit_value ?? null
            if (config) {
                actions.resetConfigForm({
                    per_issue_rate_limit_value: limit,
                    per_issue_rate_limit_bucket_size_minutes: bucket,
                })
            }
            actions.loadTopIssues()
        },
        setConfigFormValue: ({ name, value }) => {
            const fieldName = Array.isArray(name) ? name[name.length - 1] : name
            if (
                fieldName === 'per_issue_rate_limit_bucket_size_minutes' &&
                typeof value === 'number' &&
                values.selectedIssueId
            ) {
                actions.loadSelectedIssueVolume({
                    issueId: values.selectedIssueId,
                    bucketMinutes: value,
                })
            }
        },
        selectIssue: ({ issueId }) => {
            if (issueId) {
                actions.loadSelectedIssueVolume({
                    issueId,
                    bucketMinutes: values.configForm.per_issue_rate_limit_bucket_size_minutes,
                })
            }
        },
        loadTopIssuesSuccess: ({ topIssues }) => {
            const first = topIssues[0]
            if (first) {
                actions.selectIssue(first.issue_id)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.hasLoadedConfig) {
            actions.loadConfig()
        }
    }),
])
