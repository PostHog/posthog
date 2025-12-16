import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { AnyPropertyFilter } from '~/types'

import type { clustersAdminLogicType } from './clustersAdminLogicType'

export interface ClusteringRunParams {
    lookback_days: number
    max_samples: number
    embedding_normalization: 'none' | 'l2'
    dimensionality_reduction_method: 'none' | 'umap' | 'pca'
    dimensionality_reduction_ndims: number
    clustering_method: 'hdbscan' | 'kmeans'
    // HDBSCAN params
    min_cluster_size_fraction: number
    hdbscan_min_samples: number
    // K-means params
    kmeans_min_k: number
    kmeans_max_k: number
    run_label: string
    // Visualization params
    visualization_method: 'umap' | 'pca' | 'tsne'
    // Trace filters - property filters to scope which traces are included
    trace_filters: AnyPropertyFilter[]
}

export interface ClusteringRunResponse {
    workflow_id: string
    status: string
    parameters: ClusteringRunParams & { team_id: number }
}

export const DEFAULT_CLUSTERING_PARAMS: ClusteringRunParams = {
    lookback_days: 7,
    max_samples: 1000,
    embedding_normalization: 'l2',
    dimensionality_reduction_method: 'umap',
    dimensionality_reduction_ndims: 100,
    clustering_method: 'hdbscan',
    min_cluster_size_fraction: 0.01,
    hdbscan_min_samples: 5,
    kmeans_min_k: 2,
    kmeans_max_k: 10,
    run_label: '',
    visualization_method: 'umap',
    trace_filters: [],
}

export const clustersAdminLogic = kea<clustersAdminLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clustersAdminLogic']),

    actions({
        openModal: true,
        closeModal: true,
        setParams: (params: Partial<ClusteringRunParams>) => ({ params }),
        resetParams: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
                triggerClusteringRunSuccess: () => false,
            },
        ],
        params: [
            DEFAULT_CLUSTERING_PARAMS as ClusteringRunParams,
            {
                setParams: (state, { params }) => ({ ...state, ...params }),
                resetParams: () => DEFAULT_CLUSTERING_PARAMS,
            },
        ],
    }),

    loaders(({ values }) => ({
        clusteringRun: [
            null as ClusteringRunResponse | null,
            {
                triggerClusteringRun: async () => {
                    const response = await api.create(
                        'api/environments/@current/llm_analytics/clustering_runs',
                        values.params
                    )
                    return response as ClusteringRunResponse
                },
            },
        ],
    })),

    selectors({
        isRunning: [(s) => [s.clusteringRunLoading], (loading): boolean => loading],
    }),

    listeners(({ actions }) => ({
        triggerClusteringRunSuccess: ({ clusteringRun }) => {
            lemonToast.success(`Clustering workflow started`, {
                toastId: `clustering-run-${clusteringRun?.workflow_id}`,
                button: {
                    label: 'Copy workflow ID',
                    action: () => {
                        void navigator.clipboard.writeText(clusteringRun?.workflow_id || '')
                    },
                },
            })
            actions.resetParams()
        },
    })),
])
