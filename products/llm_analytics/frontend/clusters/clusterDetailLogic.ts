import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { Breadcrumb } from '~/types'

import type { clusterDetailLogicType } from './clusterDetailLogicType'
import { NOISE_CLUSTER_ID, TRACES_PER_PAGE } from './constants'
import { loadTraceSummaries } from './traceSummaryLoader'
import { Cluster, ClusterTraceInfo, TraceSummary, getTimestampBoundsFromRunId } from './types'

export interface ClusterDetailLogicProps {
    runId: string
    clusterId: number
}

export interface TraceWithSummary {
    traceId: string
    traceInfo: ClusterTraceInfo
    summary?: TraceSummary
}

export const clusterDetailLogic = kea<clusterDetailLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clusterDetailLogic']),
    props({} as ClusterDetailLogicProps),
    key((props) => `${props.runId}:${props.clusterId}`),

    actions({
        setPage: (page: number) => ({ page }),
        loadMoreTraces: true,
        setTraceSummaries: (summaries: Record<string, TraceSummary>) => ({ summaries }),
        setTraceSummariesLoading: (loading: boolean) => ({ loading }),
    }),

    reducers({
        currentPage: [
            1,
            {
                setPage: (_, { page }) => page,
            },
        ],
        traceSummaries: [
            {} as Record<string, TraceSummary>,
            {
                setTraceSummaries: (state, { summaries }) => ({ ...state, ...summaries }),
            },
        ],
        traceSummariesLoading: [
            false,
            {
                setTraceSummariesLoading: (_, { loading }) => loading,
            },
        ],
    }),

    loaders(({ props }) => ({
        clusterData: [
            null as { cluster: Cluster; runTimestamp: string; windowStart: string; windowEnd: string } | null,
            {
                loadClusterData: async () => {
                    const { dayStart, dayEnd } = getTimestampBoundsFromRunId(props.runId)

                    const response = await api.queryHogQL(
                        hogql`
                            SELECT
                                JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                                JSONExtractString(properties, '$ai_window_start') as window_start,
                                JSONExtractString(properties, '$ai_window_end') as window_end,
                                JSONExtractRaw(properties, '$ai_clusters') as clusters,
                                timestamp
                            FROM events
                            WHERE event = '$ai_trace_clusters'
                                AND timestamp >= ${dayStart}
                                AND timestamp <= ${dayEnd}
                                AND JSONExtractString(properties, '$ai_clustering_run_id') = ${props.runId}
                            LIMIT 1
                        `,
                        { productKey: 'llm_analytics', scene: 'LLMAnalyticsCluster' }
                    )

                    if (!response.results?.length) {
                        return null
                    }

                    const row = response.results[0] as string[]
                    const clustersData = JSON.parse(row[3] || '[]') as Cluster[]

                    const cluster = clustersData.find((c) => c.cluster_id === props.clusterId)
                    if (!cluster) {
                        return null
                    }

                    return {
                        cluster,
                        runTimestamp: row[4],
                        windowStart: row[1],
                        windowEnd: row[2],
                    }
                },
            },
        ],
    })),

    selectors({
        cluster: [
            (s) => [s.clusterData],
            (
                clusterData: { cluster: Cluster; runTimestamp: string; windowStart: string; windowEnd: string } | null
            ): Cluster | null => clusterData?.cluster || null,
        ],

        runTimestamp: [
            (s) => [s.clusterData],
            (
                clusterData: { cluster: Cluster; runTimestamp: string; windowStart: string; windowEnd: string } | null
            ): string => clusterData?.runTimestamp || '',
        ],

        windowStart: [
            (s) => [s.clusterData],
            (
                clusterData: { cluster: Cluster; runTimestamp: string; windowStart: string; windowEnd: string } | null
            ): string => clusterData?.windowStart || '',
        ],

        windowEnd: [
            (s) => [s.clusterData],
            (
                clusterData: { cluster: Cluster; runTimestamp: string; windowStart: string; windowEnd: string } | null
            ): string => clusterData?.windowEnd || '',
        ],

        isOutlierCluster: [
            (s) => [s.cluster],
            (cluster: Cluster | null): boolean => cluster?.cluster_id === NOISE_CLUSTER_ID,
        ],

        sortedTraceIds: [
            (s) => [s.cluster],
            (cluster: Cluster | null): string[] => {
                if (!cluster) {
                    return []
                }
                return Object.entries(cluster.traces)
                    .sort(([, a], [, b]) => (a as ClusterTraceInfo).rank - (b as ClusterTraceInfo).rank)
                    .map(([traceId]) => traceId)
            },
        ],

        totalTraces: [
            (s) => [s.cluster],
            (cluster: Cluster | null): number => (cluster ? Object.keys(cluster.traces).length : 0),
        ],

        totalPages: [(s) => [s.totalTraces], (totalTraces: number): number => Math.ceil(totalTraces / TRACES_PER_PAGE)],

        paginatedTraceIds: [
            (s) => [s.sortedTraceIds, s.currentPage],
            (sortedTraceIds: string[], currentPage: number): string[] => {
                const start = (currentPage - 1) * TRACES_PER_PAGE
                const end = start + TRACES_PER_PAGE
                return sortedTraceIds.slice(start, end)
            },
        ],

        paginatedTracesWithSummaries: [
            (s) => [s.paginatedTraceIds, s.cluster, s.traceSummaries],
            (
                paginatedTraceIds: string[],
                cluster: Cluster | null,
                summaries: Record<string, TraceSummary>
            ): TraceWithSummary[] => {
                if (!cluster) {
                    return []
                }
                return paginatedTraceIds.map((traceId: string) => ({
                    traceId,
                    traceInfo: cluster.traces[traceId],
                    summary: summaries[traceId],
                }))
            },
        ],

        breadcrumbs: [
            (s, p) => [s.cluster, p.runId],
            (cluster: Cluster | null, runId: string): Breadcrumb[] => [
                {
                    key: 'LLMAnalytics',
                    name: 'LLM analytics',
                    path: urls.llmAnalyticsDashboard(),
                },
                {
                    key: 'LLMAnalyticsClusters',
                    name: 'Clusters',
                    path: urls.llmAnalyticsClusters(),
                },
                {
                    key: 'LLMAnalyticsClustersRun',
                    name: dayjs(runId.split('_')[1] || runId).isValid()
                        ? dayjs(runId.split('_')[1] || runId).format('MMM D, YYYY')
                        : 'Run',
                    path: urls.llmAnalyticsClusters(runId),
                },
                {
                    key: 'LLMAnalyticsCluster',
                    name: cluster?.title || 'Cluster',
                },
            ],
        ],
    }),

    listeners(({ actions, values }) => ({
        loadClusterDataSuccess: async () => {
            // Load summaries for the first page of traces
            await actions.setPage(1)
        },

        setPage: async () => {
            // Load trace summaries for the current page
            const traceIds = values.paginatedTraceIds
            const { windowStart, windowEnd } = values

            if (!windowStart || !windowEnd) {
                return
            }

            actions.setTraceSummariesLoading(true)

            try {
                const summaries = await loadTraceSummaries(traceIds, values.traceSummaries, windowStart, windowEnd)
                actions.setTraceSummaries(summaries)
            } catch (error) {
                console.error('Failed to load trace summaries:', error)
            } finally {
                actions.setTraceSummariesLoading(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadClusterData()
    }),

    urlToAction(({ actions, props }) => ({
        '/llm-analytics/clusters/:runId/:clusterId': ({ runId, clusterId }: { runId?: string; clusterId?: string }) => {
            const decodedRunId = runId ? decodeURIComponent(runId) : ''
            const parsedClusterId = clusterId ? parseInt(clusterId, 10) : 0

            if (decodedRunId !== props.runId || parsedClusterId !== props.clusterId) {
                // Props don't match URL, component should remount with new props
                actions.loadClusterData()
            }
        },
    })),
])
