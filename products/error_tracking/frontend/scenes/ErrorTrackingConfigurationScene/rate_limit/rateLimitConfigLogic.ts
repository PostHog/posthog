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
    rate_limit_per_hour: number | null
}

const DEFAULT_CONFIG: RateLimitConfigForm = {
    rate_limit_per_hour: null,
}

export interface ExceptionVolumeBucket {
    hour: string
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
                loadVolume: async () => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                toStartOfHour(timestamp) AS hour,
                                count() AS count
                            FROM events
                            WHERE event = '$exception'
                              AND timestamp >= now() - INTERVAL 7 DAY
                            GROUP BY hour
                            ORDER BY hour
                        `,
                        tags: { productKey: ProductKey.ERROR_TRACKING },
                    })) as HogQLQueryResponse
                    return (response.results ?? []).map(([hour, count]) => ({
                        hour: String(hour),
                        count: Number(count),
                    }))
                },
            },
        ],
    }),

    forms(({ actions }) => ({
        configForm: {
            defaults: DEFAULT_CONFIG,
            errors: ({ rate_limit_per_hour }) => ({
                rate_limit_per_hour:
                    rate_limit_per_hour !== null && rate_limit_per_hour < 1
                        ? 'Rate limit must be at least 1'
                        : undefined,
            }),
            submit: async ({ rate_limit_per_hour }) => {
                try {
                    const updated = await api.errorTracking.updateRateLimitConfig({ rate_limit_per_hour })
                    actions.loadConfigSuccess(updated)
                    posthog.capture('error_tracking_rate_limit_settings_updated', { rate_limit_per_hour })
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
                actions.resetConfigForm({ rate_limit_per_hour: config.rate_limit_per_hour })
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.hasLoadedConfig) {
            actions.loadConfig()
        }
        actions.loadVolume()
    }),
])
