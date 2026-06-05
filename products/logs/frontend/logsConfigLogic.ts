import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { logsConfigLogicType } from './logsConfigLogicType'

// Mirrors the backend default in products/logs/backend/models.py. Used as the pre-load
// fallback in `PersonLogsTab` so the initial pinned filter matches the SDK convention
// (the JS / React Native SDKs auto-attach `posthogDistinctId` to every log) before
// `logs_config` resolves.
export const DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS = ['posthogDistinctId']

// Common identifier attribute keys we know teams use across the OTel ecosystem. Surfaced
// in the settings picker even when the team hasn't ingested any logs under them yet —
// they're the canonical PostHog-link conventions plus the OTel-spec equivalents the
// Logs viewer's defensive matcher already understands (see products/logs/frontend/utils.tsx
// `DISTINCT_ID_KEYS`). Picking one of these in the settings UI matches what a freshly
// integrated backend will emit.
export const SUGGESTED_DISTINCT_ID_ATTRIBUTE_KEYS = [
    'posthogDistinctId',
    'posthog.distinct_id',
    'posthog_distinct_id',
    'distinct_id',
    'distinctId',
    'user.id',
    'userId',
    'user_id',
]

export interface LogsConfig {
    logs_distinct_id_attribute_keys: string[]
}

interface AttributeOption {
    name: string
}

export const logsConfigLogic = kea<logsConfigLogicType>([
    path(['products', 'logs', 'frontend', 'logsConfigLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    loaders(({ values }) => ({
        logsConfig: [
            null as LogsConfig | null,
            {
                loadLogsConfig: async (): Promise<LogsConfig> => {
                    // nosemgrep: prefer-codegen-api
                    return await api.get(`api/projects/${values.currentTeamId}/logs_config/`)
                },
                updateLogsConfig: async (patch: Partial<LogsConfig>): Promise<LogsConfig> => {
                    // nosemgrep: prefer-codegen-api
                    return await api.update(`api/projects/${values.currentTeamId}/logs_config/`, patch)
                },
            },
        ],
        // Recent log + resource attribute keys the team's pipeline has actually emitted,
        // used to populate the "Link to person" settings picker with autocomplete options.
        // Falls back to the static `SUGGESTED_DISTINCT_ID_ATTRIBUTE_KEYS` list on error so
        // teams configuring before any logs land still get sensible suggestions.
        attributeKeyOptions: [
            [] as string[],
            {
                loadAttributeKeyOptions: async (): Promise<string[]> => {
                    const dateRange = JSON.stringify({
                        date_from: dayjs().subtract(30, 'day').toISOString(),
                        date_to: dayjs().toISOString(),
                    })
                    const fetchType = async (attribute_type: 'log' | 'resource'): Promise<string[]> => {
                        try {
                            const url = combineUrl(`api/projects/${values.currentTeamId}/logs/attributes`, {
                                attribute_type,
                                dateRange,
                            }).url
                            // nosemgrep: prefer-codegen-api
                            const response: { results: AttributeOption[] } = await api.get(url)
                            return response.results.map((r) => r.name)
                        } catch {
                            return []
                        }
                    }
                    const [logs, resource] = await Promise.all([fetchType('log'), fetchType('resource')])
                    return Array.from(new Set([...logs, ...resource]))
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadLogsConfig()
        actions.loadAttributeKeyOptions()
    }),
])
