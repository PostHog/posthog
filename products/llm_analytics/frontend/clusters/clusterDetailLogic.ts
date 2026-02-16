import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { Breadcrumb } from '~/types'

import type { clusterDetailLogicType } from './clusterDetailLogicType'
import { loadClusterMetrics } from './clusterMetricsLoader'
import { NOISE_CLUSTER_ID, OUTLIER_COLOR, TRACES_PER_PAGE } from './constants'
import { loadTraceSummaries } from './traceSummaryLoader'
import {
    Cluster,
    ClusterItemInfo,
    ClusterMetrics,
    ClusteringLevel,
    TraceSummary,
    getTimestampBoundsFromRunId,
} from './types'

export interface ClusterDetailLogicProps {
    runId: string
    clusterId: number
}

export interface TraceWithSummary {
    traceId: string
    traceInfo: ClusterItemInfo
    summary?: TraceSummary
}

export interface ClusterData {
    cluster: Cluster
    runTimestamp: string
    windowStart: string
    windowEnd: string
    clusteringLevel: ClusteringLevel
}

export interface ScatterDataset {
    label: string
    data: Array<{ x: number; y: number; traceId?: string; generationId?: string; timestamp?: string }>
    backgroundColor: string
    borderColor: string
    borderWidth: number
    pointRadius: number
    pointHoverRadius: number
    pointStyle?: 'circle' | 'crossRot'
}

export const clusterDetailLogic = kea<clusterDetailLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clusterDetailLogic']),
    props({} as ClusterDetailLogicProps),
    key((props) => `${props.runId}:${props.clusterId}`),
    connect(() => ({
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        setPage: (page: number) => ({ page }),
        loadMoreTraces: true,
        setTraceSummaries: (summaries: Record<string, TraceSummary>) => ({ summaries }),
        setTraceSummariesLoading: (loading: boolean) => ({ loading }),
        setClusterMetrics: (metrics: ClusterMetrics | null) => ({ metrics }),
        setClusterMetricsLoading: (loading: boolean) => ({ loading }),
        loadClusterMetricsForCluster: true,
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
        clusterMetrics: [
            null as ClusterMetrics | null,
            {
                setClusterMetrics: (_, { metrics }) => metrics,
            },
        ],
        clusterMetricsLoading: [
            false,
            {
                setClusterMetricsLoading: (_, { loading }) => loading,
            },
        ],
    }),

    loaders(({ props }) => ({
        clusterData: [
            null as ClusterData | null,
            {
                loadClusterData: async () => {
                    const { dayStart, dayEnd } = getTimestampBoundsFromRunId(props.runId)

                    // Query both trace and generation cluster events
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT
                                JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                                JSONExtractString(properties, '$ai_window_start') as window_start,
                                JSONExtractString(properties, '$ai_window_end') as window_end,
                                JSONExtractRaw(properties, '$ai_clusters') as clusters,
                                timestamp,
                                JSONExtractString(properties, '$ai_clustering_level') as clustering_level
                            FROM events
                            WHERE event IN ('$ai_trace_clusters', '$ai_generation_clusters')
                                AND timestamp >= ${dayStart}
                                AND timestamp <= ${dayEnd}
                                AND JSONExtractString(properties, '$ai_clustering_run_id') = ${props.runId}
                            LIMIT 1
                        `,
                        { productKey: 'llm_analytics', scene: 'LLMAnalyticsCluster' },
                        // Run IDs and bounds are in UTC, so compare timestamps in UTC
                        { queryParams: { modifiers: { convertToProjectTimezone: false } } }
                    )

                    if (!response.results?.length) {
                        return null
                    }

                    const row = response.results[0] as string[]

                    let clustersData: Cluster[] = []
                    try {
                        clustersData = JSON.parse(row[3] || '[]') as Cluster[]
                    } catch {
                        console.error('Failed to parse clusters data')
                        return null
                    }

                    const cluster = clustersData.find((c) => c.cluster_id === props.clusterId)
                    if (!cluster) {
                        return null
                    }

                    // Default to 'trace' for backwards compatibility
                    const clusteringLevel = (row[5] as ClusteringLevel) || 'trace'

                    return {
                        cluster,
                        runTimestamp: row[4],
                        windowStart: row[1],
                        windowEnd: row[2],
                        clusteringLevel,
                    }
                },
            },
        ],
    })),

    selectors({
        cluster: [
            (s) => [s.clusterData],
            (clusterData: ClusterData | null): Cluster | null => clusterData?.cluster || null,
        ],

        runTimestamp: [
            (s) => [s.clusterData],
            (clusterData: ClusterData | null): string => clusterData?.runTimestamp || '',
        ],

        windowStart: [
            (s) => [s.clusterData],
            (clusterData: ClusterData | null): string => clusterData?.windowStart || '',
        ],

        windowEnd: [(s) => [s.clusterData], (clusterData: ClusterData | null): string => clusterData?.windowEnd || ''],

        clusteringLevel: [
            (s) => [s.clusterData],
            (clusterData: ClusterData | null): ClusteringLevel => clusterData?.clusteringLevel || 'trace',
        ],

        isOutlierCluster: [
            (s) => [s.cluster],
            (cluster: Cluster | null): boolean => cluster?.cluster_id === NOISE_CLUSTER_ID,
        ],

        scatterPlotDatasets: [
            (s) => [s.cluster, s.isOutlierCluster],
            (cluster: Cluster | null, isOutlier: boolean): ScatterDataset[] => {
                if (!cluster) {
                    return []
                }

                const color = isOutlier ? OUTLIER_COLOR : getSeriesColor(cluster.cluster_id)

                const tracePoints = Object.entries(cluster.traces).map(([itemKey, traceInfo]) => ({
                    x: traceInfo.x,
                    y: traceInfo.y,
                    // Use explicit trace_id/generation_id from backend if available
                    // Fall back to itemKey for backwards compatibility
                    traceId: traceInfo.trace_id || itemKey,
                    generationId: traceInfo.generation_id,
                    timestamp: traceInfo.timestamp,
                }))

                const result: ScatterDataset[] = [
                    {
                        label: cluster.title,
                        data: tracePoints,
                        backgroundColor: `${color}80`,
                        borderColor: color,
                        borderWidth: 1,
                        pointRadius: 5,
                        pointHoverRadius: 7,
                        pointStyle: isOutlier ? 'crossRot' : 'circle',
                    },
                ]

                // Add centroid marker for non-outlier clusters
                if (!isOutlier) {
                    result.push({
                        label: 'Centroid',
                        data: [{ x: cluster.centroid_x, y: cluster.centroid_y }],
                        backgroundColor: `${color}40`,
                        borderColor: color,
                        borderWidth: 2,
                        pointRadius: 10,
                        pointHoverRadius: 12,
                        pointStyle: 'circle',
                    })
                }

                return result
            },
        ],

        sortedTraceIds: [
            (s) => [s.cluster],
            (cluster: Cluster | null): string[] => {
                if (!cluster) {
                    return []
                }
                return Object.entries(cluster.traces)
                    .sort(([, a], [, b]) => (a as ClusterItemInfo).rank - (b as ClusterItemInfo).rank)
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

    listeners(({ actions, values, props }) => ({
        loadClusterDataSuccess: () => {
            actions.setPage(1)
            actions.loadClusterMetricsForCluster()

            void actions.addProductIntent({
                product_type: ProductKey.LLM_CLUSTERS,
                intent_context: ProductIntentContext.LLM_CLUSTER_EXPLORED,
            })
        },

        loadClusterMetricsForCluster: async () => {
            const { cluster, windowStart, windowEnd, clusteringLevel } = values
            if (!cluster || !windowStart || !windowEnd) {
                return
            }

            actions.setClusterMetricsLoading(true)
            try {
                const metricsMap = await loadClusterMetrics([cluster], windowStart, windowEnd, clusteringLevel)
                actions.setClusterMetrics(metricsMap[cluster.cluster_id] || null)
            } catch (error) {
                console.error('Failed to load cluster metrics:', error)
            } finally {
                actions.setClusterMetricsLoading(false)
            }
        },

        setPage: async ({ page }) => {
            posthog.capture('llma clusters page changed', {
                page,
                cluster_id: props.clusterId,
                run_id: props.runId,
            })
            // Load trace summaries for the current page
            const traceIds = values.paginatedTraceIds
            const { windowStart, windowEnd, clusteringLevel } = values

            if (!windowStart || !windowEnd) {
                return
            }

            actions.setTraceSummariesLoading(true)

            try {
                const summaries = await loadTraceSummaries(
                    traceIds,
                    values.traceSummaries,
                    windowStart,
                    windowEnd,
                    clusteringLevel
                )
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
