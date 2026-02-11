import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'

import type { clustersExistenceLogicType } from './clustersExistenceLogicType'

/**
 * Lightweight singleton logic that checks whether any cluster events exist.
 * Used to conditionally hide the clusters tab/link when there's no data to show.
 */
export const clustersExistenceLogic = kea<clustersExistenceLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clustersExistenceLogic']),

    loaders({
        hasClustersData: [
            null as boolean | null,
            {
                loadHasClustersData: async (): Promise<boolean> => {
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT 1
                            FROM events
                            WHERE event IN ('$ai_trace_clusters', '$ai_generation_clusters')
                                AND timestamp >= now() - INTERVAL 7 DAY
                            LIMIT 1
                        `,
                        { productKey: 'llm_analytics', scene: 'LLMAnalyticsClusters' }
                    )
                    return (response.results?.length ?? 0) > 0
                },
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadHasClustersData()
    }),
])
