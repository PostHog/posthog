import { actions, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'

import { Cluster, NOISE_CLUSTER_ID } from '../clusters/types'
import type { clustersTabContentLogicType } from './clustersTabContentLogicType'

export interface ClusterInfo {
    runId: string
    runTimestamp: string
    clusterId: number
    clusterTitle: string
    clusterSize: number
    isOutlier: boolean
}

export interface ClustersTabContentLogicProps {
    traceId: string
}

export const clustersTabContentLogic = kea<clustersTabContentLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'components', 'clustersTabContentLogic']),
    props({} as ClustersTabContentLogicProps),
    key((props) => props.traceId),

    actions({
        refreshClusters: true,
    }),

    loaders(({ props }) => ({
        clusters: [
            [] as ClusterInfo[],
            {
                loadClusters: async () => {
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT
                                JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                                JSONExtractRaw(properties, '$ai_clusters') as clusters_json,
                                timestamp
                            FROM events
                            WHERE event = '$ai_trace_clusters'
                                AND timestamp >= now() - INTERVAL 7 DAY
                            ORDER BY timestamp DESC
                            LIMIT 20
                        `,
                        { refresh: 'force_blocking' }
                    )

                    const foundClusters: ClusterInfo[] = []

                    for (const row of response.results || []) {
                        const [runId, clustersJson, timestamp] = row as [string, string, string]
                        try {
                            const clustersData = JSON.parse(clustersJson || '[]') as Cluster[]
                            for (const cluster of clustersData) {
                                if (cluster.traces && props.traceId in cluster.traces) {
                                    foundClusters.push({
                                        runId,
                                        runTimestamp: timestamp,
                                        clusterId: cluster.cluster_id,
                                        clusterTitle: cluster.title || `Cluster ${cluster.cluster_id}`,
                                        clusterSize: cluster.size,
                                        isOutlier: cluster.cluster_id === NOISE_CLUSTER_ID,
                                    })
                                }
                            }
                        } catch {
                            // Skip malformed JSON
                        }
                    }

                    return foundClusters
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadClusters()
    }),
])
