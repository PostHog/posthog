import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { logsConfigLogicType } from './logsConfigLogicType'

// Mirrors the backend default in products/logs/backend/models.py — the convention
// documented at https://posthog.com/docs/logs/link-session-replay. Used as the
// pre-load fallback in `PersonLogsTab` so the initial pinned filter matches the
// SDK convention before `logs_config` resolves.
export const DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY = 'posthogDistinctId'

export interface LogsConfig {
    logs_distinct_id_attribute_key: string
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
    })),
    afterMount(({ actions }) => {
        actions.loadLogsConfig()
    }),
])
