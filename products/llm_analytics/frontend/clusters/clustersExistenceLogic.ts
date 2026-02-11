import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isDefinitionStale } from 'lib/utils/definitions'

import { EventDefinitionType } from '~/types'

import type { clustersExistenceLogicType } from './clustersExistenceLogicType'

const CLUSTER_EVENT_NAMES = ['$ai_trace_clusters', '$ai_generation_clusters']

/**
 * Lightweight singleton logic that checks whether any cluster events exist
 * via the EventDefinition table (Postgres, fast).
 * Used to conditionally hide the clusters tab/link when there's no data to show.
 */
export const clustersExistenceLogic = kea<clustersExistenceLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clustersExistenceLogic']),

    loaders({
        hasClustersData: [
            false as boolean,
            {
                loadHasClustersData: async (): Promise<boolean> => {
                    const definitions = await api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$ai_',
                    })
                    return definitions.results.some(
                        (r) => CLUSTER_EVENT_NAMES.includes(r.name) && !isDefinitionStale(r)
                    )
                },
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadHasClustersData()
    }),
])
