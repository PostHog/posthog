import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { AnyPropertyFilter } from '~/types'

import type { clusteringConfigLogicType } from './clusteringConfigLogicType'

export interface ClusteringConfig {
    event_filters: AnyPropertyFilter[]
    created_at: string
    updated_at: string
}

const API_PATH = 'api/environments/@current/llm_analytics/clustering_config'

export const clusteringConfigLogic = kea<clusteringConfigLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clusteringConfigLogic']),

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
                    const response = await api.get(API_PATH + '/')
                    return response as ClusteringConfig
                },
                saveEventFilters: async () => {
                    const response = await api.create(API_PATH + '/set_event_filters/', {
                        event_filters: values.localEventFilters,
                    })
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
