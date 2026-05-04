import { afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ErrorTrackingRateLimitConfig } from 'lib/components/Errors/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { HogQLQueryResponse, NodeKind, ProductKey } from '~/queries/schema/schema-general'

import type { rateLimitConfigLogicType } from './rateLimitConfigLogicType'

export interface RateLimitConfigForm {
    project_rate_limit_value: number | null
    project_rate_limit_bucket_size_minutes: number
}

export const DEFAULT_BUCKET_MINUTES = 60

const DEFAULT_CONFIG: RateLimitConfigForm = {
    project_rate_limit_value: null,
    project_rate_limit_bucket_size_minutes: DEFAULT_BUCKET_MINUTES,
}

export interface BucketOption {
    label: string
    minutes: number
    bucketCount: number
}

export const BUCKET_OPTIONS: BucketOption[] = [
    { label: '15 minutes', minutes: 15, bucketCount: 96 },
    { label: '30 minutes', minutes: 30, bucketCount: 96 },
    { label: '1 hour', minutes: 60, bucketCount: 168 },
    { label: '1 day', minutes: 1440, bucketCount: 30 },
    { label: '1 week', minutes: 10080, bucketCount: 12 },
]

export function getBucketOption(minutes: number): BucketOption {
    return BUCKET_OPTIONS.find((o) => o.minutes === minutes) ?? BUCKET_OPTIONS[2]
}

export interface ExceptionVolumeBucket {
    bucket: string
    count: number
}

export const rateLimitConfigLogic = kea<rateLimitConfigLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'rate_limit',
        'rateLimitConfigLogic',
    ]),

    reducers({
        hasLoadedConfig: [
            false,
            {
                loadConfigSuccess: () => true,
            },
        ],
    }),

    loaders({
        config: [
            null as ErrorTrackingRateLimitConfig | null,
            {
                loadConfig: async () => {
                    return await api.errorTracking.getRateLimitConfig()
                },
            },
        ],
        volume: [
            [] as ExceptionVolumeBucket[],
            {
                loadVolume: async (bucketMinutes: number) => {
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
    }),

    forms(({ actions }) => ({
        configForm: {
            defaults: DEFAULT_CONFIG,
            errors: ({ project_rate_limit_value }) => ({
                project_rate_limit_value:
                    project_rate_limit_value !== null && project_rate_limit_value < 1
                        ? 'Rate limit must be at least 1'
                        : undefined,
            }),
            submit: async ({ project_rate_limit_value, project_rate_limit_bucket_size_minutes }) => {
                try {
                    const payload = {
                        project_rate_limit_value,
                        project_rate_limit_bucket_size_minutes:
                            project_rate_limit_value === null ? null : project_rate_limit_bucket_size_minutes,
                    }
                    const updated = await api.errorTracking.updateRateLimitConfig(payload)
                    actions.loadConfigSuccess(updated)
                    posthog.capture('error_tracking_rate_limit_settings_updated', payload)
                    lemonToast.success('Rate limit settings saved')
                } catch (e) {
                    lemonToast.error('Failed to save rate limit settings')
                    throw e
                }
            },
        },
    })),

    listeners(({ actions }) => ({
        loadConfigSuccess: ({ config }) => {
            if (config) {
                const bucket = config.project_rate_limit_bucket_size_minutes ?? DEFAULT_BUCKET_MINUTES
                actions.resetConfigForm({
                    project_rate_limit_value: config.project_rate_limit_value,
                    project_rate_limit_bucket_size_minutes: bucket,
                })
                actions.loadVolume(bucket)
            }
        },
        setConfigFormValue: ({ name, value }) => {
            if (name === 'project_rate_limit_bucket_size_minutes' && typeof value === 'number') {
                actions.loadVolume(value)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.hasLoadedConfig) {
            actions.loadConfig()
        }
        actions.loadVolume(DEFAULT_BUCKET_MINUTES)
    }),
])
