import { actions, afterMount, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { tracingConfigLogicType } from './tracingConfigLogicType'

// Mirrors the backend default in products/tracing/backend/models.py — the same
// convention logs use (https://posthog.com/docs/logs/link-session-replay). Traces
// arrive via plain OTel, so instrumentation must attach the key itself.
export const DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEY = 'posthogDistinctId'

export interface TracingConfig {
    tracing_distinct_id_attribute_key: string
}

/** Server-backed tracing config plus display-only scene preferences (never affects the query). */
export const tracingConfigLogic = kea<tracingConfigLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingConfigLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),

    actions({
        setFacetRailCollapsed: (facetRailCollapsed: boolean) => ({ facetRailCollapsed }),
    }),

    reducers({
        facetRailCollapsed: [
            false,
            { persist: true },
            {
                setFacetRailCollapsed: (_, { facetRailCollapsed }) => facetRailCollapsed,
            },
        ],
    }),

    loaders(({ values }) => ({
        tracingConfig: [
            null as TracingConfig | null,
            {
                loadTracingConfig: async (): Promise<TracingConfig> => {
                    // nosemgrep: prefer-codegen-api
                    return await api.get(`api/projects/${values.currentTeamId}/tracing_config/`)
                },
                updateTracingConfig: async (patch: Partial<TracingConfig>): Promise<TracingConfig> => {
                    // nosemgrep: prefer-codegen-api
                    return await api.update(`api/projects/${values.currentTeamId}/tracing_config/`, patch)
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadTracingConfig()
    }),
])
