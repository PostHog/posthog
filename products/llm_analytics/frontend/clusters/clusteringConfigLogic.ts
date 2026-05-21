import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { AnyPropertyFilter } from '~/types'

import type { clusteringConfigLogicType } from './clusteringConfigLogicType'

/** A filter is valid if it has a key set (not just an empty placeholder row). */
export function isValidFilter(f: AnyPropertyFilter): boolean {
    return 'key' in f && f.key !== undefined && f.key !== ''
}

export interface ClusteringConfig {
    event_filters: AnyPropertyFilter[]
    created_at: string
    updated_at: string
}

export const clusteringConfigLogic = kea<clusteringConfigLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clusteringConfigLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamIdStrict']] })),

    actions({
        openSettingsPanel: true,
        closeSettingsPanel: true,
        setLocalEventFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
    }),

    loaders(({ values }) => ({
        config: [
            { event_filters: [], created_at: '', updated_at: '' } as ClusteringConfig,
            {
                loadConfig: async () => {
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get(
                        `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_config/`
                    )
                    return response as ClusteringConfig
                },
                saveEventFilters: async () => {
                    // nosemgrep: prefer-codegen-api
                    const response = await api.create(
                        `api/environments/${values.currentTeamIdStrict}/llm_analytics/clustering_config/set_event_filters/`,
                        {
                            event_filters: values.localEventFilters,
                        }
                    )
                    return response as ClusteringConfig
                },
            },
        ],
    })),

    reducers({
        isSettingsPanelOpen: [
            false,
            {
                openSettingsPanel: () => true,
                closeSettingsPanel: () => false,
                saveEventFiltersSuccess: () => false,
            },
        ],
        localEventFilters: [
            [] as AnyPropertyFilter[],
            {
                setLocalEventFilters: (_, { filters }) => filters,
                loadConfigSuccess: (_, { config }) => config.event_filters,
            },
        ],
    }),

    listeners(() => ({
        saveEventFiltersSuccess: () => {
            lemonToast.success('Clustering filters saved')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadConfig()
    }),
])
