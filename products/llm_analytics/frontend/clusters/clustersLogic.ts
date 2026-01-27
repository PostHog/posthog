import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { Breadcrumb } from '~/types'

import type { clustersLogicType } from './clustersLogicType'
import { MAX_CLUSTERING_RUNS, NOISE_CLUSTER_ID } from './constants'
import { loadTraceSummaries } from './traceSummaryLoader'
import {
    Cluster,
    ClusteringParams,
    ClusteringRun,
    ClusteringRunOption,
    TraceSummary,
    getTimestampBoundsFromRunId,
} from './types'

// Special color for outliers cluster
const OUTLIER_COLOR = '#888888'

export interface ScatterDataset {
    label: string
    data: Array<{ x: number; y: number; traceId?: string; clusterId?: number; timestamp?: string }>
    backgroundColor: string
    borderColor: string
    borderWidth: number
    pointRadius: number
    pointHoverRadius: number
    pointStyle?:
        | 'circle'
        | 'cross'
        | 'crossRot'
        | 'dash'
        | 'line'
        | 'rect'
        | 'rectRounded'
        | 'rectRot'
        | 'star'
        | 'triangle'
}

export const clustersLogic = kea<clustersLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clustersLogic']),

    actions({
        setSelectedRunId: (runId: string | null) => ({ runId }),
        toggleClusterExpanded: (clusterId: number) => ({ clusterId }),
        toggleScatterPlotExpanded: true,
        setTraceSummaries: (summaries: Record<string, TraceSummary>) => ({ summaries }),
        setTraceSummariesLoading: (loading: boolean) => ({ loading }),
        loadTraceSummariesForRun: (run: ClusteringRun) => ({ run }),
    }),

    reducers({
        selectedRunId: [
            null as string | null,
            {
                setSelectedRunId: (_, { runId }) => runId,
            },
        ],
        expandedClusterIds: [
            new Set<number>() as Set<number>,
            {
                toggleClusterExpanded: (state, { clusterId }) => {
                    const newSet = new Set(state)
                    if (newSet.has(clusterId)) {
                        newSet.delete(clusterId)
                    } else {
                        newSet.add(clusterId)
                    }
                    return newSet
                },
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
        isScatterPlotExpanded: [
            true,
            {
                toggleScatterPlotExpanded: (state) => !state,
            },
        ],
    }),

    loaders(() => ({
        clusteringRuns: [
            [] as ClusteringRunOption[],
            {
                loadClusteringRuns: async () => {
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT
                                JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                                JSONExtractString(properties, '$ai_window_end') as window_end,
                                timestamp
                            FROM events
                            WHERE event = '$ai_trace_clusters'
                                AND timestamp >= now() - INTERVAL 7 DAY
                            ORDER BY timestamp DESC
                            LIMIT ${MAX_CLUSTERING_RUNS}
                        `,
                        { productKey: 'llm_analytics', scene: 'LLMAnalyticsClusters' },
                        {
                            refresh: 'force_blocking',
                            // Run IDs are generated in UTC, so compare timestamps in UTC
                            queryParams: { modifiers: { convertToProjectTimezone: false } },
                        }
                    )

                    return (response.results || []).map((row: string[]) => ({
                        runId: row[0],
                        windowEnd: row[1],
                        label: dayjs(row[2]).format('MMM D, YYYY h:mm A'),
                    }))
                },
            },
        ],

        currentRun: [
            null as ClusteringRun | null,
            {
                loadClusteringRun: async (runId: string) => {
                    const { dayStart, dayEnd } = getTimestampBoundsFromRunId(runId)

                    const response = await api.queryHogQL(
                        hogql`
                            SELECT
                                JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                                JSONExtractString(properties, '$ai_window_start') as window_start,
                                JSONExtractString(properties, '$ai_window_end') as window_end,
                                JSONExtractInt(properties, '$ai_total_traces_analyzed') as total_traces,
                                JSONExtractRaw(properties, '$ai_clusters') as clusters,
                                timestamp,
                                JSONExtractRaw(properties, '$ai_clustering_params') as clustering_params
                            FROM events
                            WHERE event = '$ai_trace_clusters'
                                AND timestamp >= ${dayStart}
                                AND timestamp <= ${dayEnd}
                                AND JSONExtractString(properties, '$ai_clustering_run_id') = ${runId}
                            LIMIT 1
                        `,
                        { productKey: 'llm_analytics', scene: 'LLMAnalyticsClusters' },
                        // Run IDs and bounds are in UTC, so compare timestamps in UTC
                        { queryParams: { modifiers: { convertToProjectTimezone: false } } }
                    )

                    if (!response.results?.length) {
                        return null
                    }

                    const row = response.results[0] as (string | number)[]

                    let clustersData: Cluster[] = []
                    try {
                        clustersData = JSON.parse((row[4] as string) || '[]')
                    } catch {
                        console.error('Failed to parse clusters data')
                        return null
                    }

                    let clusteringParams: ClusteringParams | undefined
                    const clusteringParamsRaw = row[6] as string | null
                    if (clusteringParamsRaw) {
                        try {
                            clusteringParams = JSON.parse(clusteringParamsRaw)
                        } catch {
                            // Non-critical, continue without params
                        }
                    }

                    return {
                        runId: row[0] as string,
                        windowStart: row[1] as string,
                        windowEnd: row[2] as string,
                        totalTracesAnalyzed: row[3] as number,
                        clusters: clustersData,
                        timestamp: row[5] as string,
                        clusteringParams,
                    } as ClusteringRun
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
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
            ],
        ],

        effectiveRunId: [
            (s) => [s.selectedRunId, s.clusteringRuns],
            (selectedRunId: string | null, runs: ClusteringRunOption[]): string | null => {
                if (selectedRunId) {
                    return selectedRunId
                }
                return runs.length > 0 ? runs[0].runId : null
            },
        ],

        sortedClusters: [
            (s) => [s.currentRun],
            (currentRun: ClusteringRun | null): Cluster[] => {
                if (!currentRun?.clusters) {
                    return []
                }
                return [...currentRun.clusters].sort((a, b) => b.size - a.size)
            },
        ],

        isClusterExpanded: [
            (s) => [s.expandedClusterIds],
            (expandedIds: Set<number>) =>
                (clusterId: number): boolean =>
                    expandedIds.has(clusterId),
        ],

        traceToClusterTitle: [
            (s) => [s.sortedClusters],
            (clusters: Cluster[]): Record<string, string> => {
                const map: Record<string, string> = {}
                for (const cluster of clusters) {
                    const clusterTitle = cluster.title || `Cluster ${cluster.cluster_id}`
                    for (const traceId of Object.keys(cluster.traces)) {
                        map[traceId] = clusterTitle
                    }
                }
                return map
            },
        ],

        scatterPlotDatasets: [
            (s) => [s.sortedClusters],
            (clusters: Cluster[]): ScatterDataset[] => {
                const traceDatasets: ScatterDataset[] = []
                const centroidDatasets: ScatterDataset[] = []

                for (const cluster of clusters) {
                    const isOutlier = cluster.cluster_id === NOISE_CLUSTER_ID
                    const color = isOutlier ? OUTLIER_COLOR : getSeriesColor(cluster.cluster_id)
                    const label = cluster.title || `Cluster ${cluster.cluster_id}`

                    // Trace points
                    traceDatasets.push({
                        label,
                        data: Object.entries(cluster.traces).map(([traceId, traceInfo]) => ({
                            x: traceInfo.x,
                            y: traceInfo.y,
                            traceId,
                            timestamp: traceInfo.timestamp,
                        })),
                        backgroundColor: `${color}80`,
                        borderColor: color,
                        borderWidth: 1,
                        pointRadius: isOutlier ? 4 : 4,
                        pointHoverRadius: isOutlier ? 6 : 6,
                        pointStyle: isOutlier ? 'crossRot' : 'circle', // X shape for outliers
                    })

                    // Centroid marker (skip for outliers - they don't have a real centroid)
                    if (!isOutlier) {
                        centroidDatasets.push({
                            label: `${label} (centroid)`,
                            data: [{ x: cluster.centroid_x, y: cluster.centroid_y, clusterId: cluster.cluster_id }],
                            backgroundColor: `${color}40`,
                            borderColor: color,
                            borderWidth: 2,
                            pointRadius: 8,
                            pointHoverRadius: 10,
                        })
                    }
                }

                return [...traceDatasets, ...centroidDatasets]
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadTraceSummariesForRun: async ({ run }) => {
            // Collect all trace IDs from all clusters
            const allTraceIds: string[] = []
            for (const cluster of run.clusters) {
                allTraceIds.push(...Object.keys(cluster.traces))
            }

            actions.setTraceSummariesLoading(true)

            try {
                const summaries = await loadTraceSummaries(
                    allTraceIds,
                    values.traceSummaries,
                    run.windowStart,
                    run.windowEnd
                )
                actions.setTraceSummaries(summaries)
            } catch (error) {
                console.error('Failed to load trace summaries:', error)
            } finally {
                actions.setTraceSummariesLoading(false)
            }
        },

        toggleClusterExpanded: async ({ clusterId }) => {
            // Load trace summaries when expanding a cluster (fallback for lazy loading)
            if (values.expandedClusterIds.has(clusterId)) {
                const run = values.currentRun
                const cluster = run?.clusters.find((c: Cluster) => c.cluster_id === clusterId)
                if (cluster && run) {
                    const traceIds = Object.keys(cluster.traces)

                    actions.setTraceSummariesLoading(true)

                    try {
                        const summaries = await loadTraceSummaries(
                            traceIds,
                            values.traceSummaries,
                            run.windowStart,
                            run.windowEnd
                        )
                        actions.setTraceSummaries(summaries)
                    } catch (error) {
                        console.error('Failed to load trace summaries:', error)
                    } finally {
                        actions.setTraceSummariesLoading(false)
                    }
                }
            }
        },

        loadClusteringRunSuccess: ({ currentRun }) => {
            // Load all trace summaries when a run is loaded for scatter plot tooltips
            if (currentRun) {
                actions.loadTraceSummariesForRun(currentRun)
            }
        },

        loadClusteringRunFailure: () => {
            lemonToast.error('Failed to load clustering run')
        },

        loadClusteringRunsSuccess: ({ clusteringRuns }) => {
            // Auto-load the first run if available and no run is selected
            if (clusteringRuns.length > 0 && !values.selectedRunId) {
                actions.loadClusteringRun(clusteringRuns[0].runId)
            }
        },

        setSelectedRunId: ({ runId }) => {
            if (runId) {
                actions.loadClusteringRun(runId)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadClusteringRuns()
    }),

    urlToAction(({ actions }) => ({
        '/llm-analytics/clusters': () => {
            actions.setSelectedRunId(null)
        },
        '/llm-analytics/clusters/:runId': ({ runId }: { runId?: string }) => {
            // Decode the URL-encoded runId
            actions.setSelectedRunId(runId ? decodeURIComponent(runId) : null)
        },
    })),

    actionToUrl(({ values }) => ({
        setSelectedRunId: () => {
            if (values.selectedRunId) {
                return urls.llmAnalyticsClusters(values.selectedRunId)
            }
            return urls.llmAnalyticsClusters()
        },
    })),
])
