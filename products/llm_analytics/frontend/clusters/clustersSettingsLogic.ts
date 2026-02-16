import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils'

import type { AnyPropertyFilter } from '~/types'

import type { clustersSettingsLogicType } from './clustersSettingsLogicType'

export interface ClusteringSettings {
    trace_filters: AnyPropertyFilter[]
}

export const clustersSettingsLogic = kea<clustersSettingsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clustersSettingsLogic']),

    actions({
        setTraceFilters: (traceFilters: AnyPropertyFilter[]) => ({ traceFilters }),
        resetTraceFilters: true,
    }),

    loaders(({ values }) => ({
        clusteringSettings: [
            null as ClusteringSettings | null,
            {
                loadClusteringSettings: async () => {
                    return (await api.get(
                        'api/environments/@current/llm_analytics/clustering_settings'
                    )) as ClusteringSettings
                },
                saveClusteringSettings: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.create('api/environments/@current/llm_analytics/clustering_settings', {
                        trace_filters: values.traceFilters,
                    })
                    return response as ClusteringSettings
                },
            },
        ],
    })),

    reducers({
        traceFilters: [
            [] as AnyPropertyFilter[],
            {
                setTraceFilters: (_, { traceFilters }) => traceFilters,
                loadClusteringSettingsSuccess: (_, { clusteringSettings }) => clusteringSettings?.trace_filters || [],
                saveClusteringSettingsSuccess: (_, { clusteringSettings }) => clusteringSettings?.trace_filters || [],
            },
        ],
        savedTraceFilters: [
            [] as AnyPropertyFilter[],
            {
                loadClusteringSettingsSuccess: (_, { clusteringSettings }) => clusteringSettings?.trace_filters || [],
                saveClusteringSettingsSuccess: (_, { clusteringSettings }) => clusteringSettings?.trace_filters || [],
            },
        ],
    }),

    selectors({
        hasChanges: [
            (s) => [s.traceFilters, s.savedTraceFilters],
            (traceFilters, savedTraceFilters) => !objectsEqual(traceFilters, savedTraceFilters),
        ],
        isLoading: [(s) => [s.clusteringSettingsLoading], (loading) => loading],
        isSaving: [(s) => [s.saveClusteringSettingsLoading], (loading) => loading],
    }),

    listeners(({ actions, values }) => ({
        saveClusteringSettingsSuccess: () => {
            lemonToast.success('Clustering filters saved')
        },
        saveClusteringSettingsFailure: () => {
            lemonToast.error('Failed to save clustering filters')
        },
        loadClusteringSettingsFailure: () => {
            lemonToast.error('Failed to load clustering filters')
        },
        resetTraceFilters: () => {
            actions.setTraceFilters(values.savedTraceFilters)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadClusteringSettings()
    }),
])
