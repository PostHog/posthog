import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { Breadcrumb } from '~/types'

import { loadClusterMetrics } from './clusterMetricsLoader'
import type { clustersLogicType } from './clustersLogicType'
import { MAX_CLUSTERING_RUNS, NOISE_CLUSTER_ID, OUTLIER_COLOR } from './constants'
import { loadTraceSummaries } from './traceSummaryLoader'
import {
    Cluster,
    ClusterMetrics,
    ClusteringLevel,
    ClusteringParams,
    ClusteringRun,
    ClusteringRunOption,
    TraceSummary,
    getLevelFromRunId,
    getTimestampBoundsFromRunId,
} from './types'

export interface ScatterDataset {
    label: string
    data: Array<{
        x: number
        y: number
        traceId?: string
        generationId?: string
        clusterId?: number
        timestamp?: string
    }>
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
        setClusteringLevel: (level: ClusteringLevel) => ({ level }),
        syncClusteringLevelFromRun: (level: ClusteringLevel) => ({ level }),
        setSelectedRunId: (runId: string | null) => ({ runId }),
        toggleClusterExpanded: (clusterId: number) => ({ clusterId }),
        toggleScatterPlotExpanded: true,
        setTraceSummaries: (summaries: Record<string, TraceSummary>) => ({ summaries }),
        setTraceSummariesLoading: (loading: boolean) => ({ loading }),
        loadTraceSummariesForRun: (run: ClusteringRun) => ({ run }),
        setClusterMetrics: (metrics: Record<number, ClusterMetrics>) => ({ metrics }),
        setClusterMetricsLoading: (loading: boolean) => ({ loading }),
        loadClusterMetricsForRun: (run: ClusteringRun) => ({ run }),
    }),

    reducers({
        clusteringLevel: [
            'trace' as ClusteringLevel,
            {
                setClusteringLevel: (_, { level }) => level,
                // Sync from run without triggering reload (used when loading a run from URL)
                syncClusteringLevelFromRun: (_, { level }) => level,
            },
        ],
        selectedRunId: [
            null as string | null,
            {
                setSelectedRunId: (_, { runId }) => runId,
                // Clear selected run when level changes
                setClusteringLevel: () => null,
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
        clusterMetrics: [
            {} as Record<number, ClusterMetrics>,
            {
                setClusterMetrics: (_, { metrics }) => metrics,
                // Clear metrics when level changes (new run will load fresh metrics)
                setClusteringLevel: () => ({}),
            },
        ],
        clusterMetricsLoading: [
            false,
            {
                setClusterMetricsLoading: (_, { loading }) => loading,
            },
        ],
    }),

    loaders(({ values }) => ({
        clusteringRuns: [
            [] as ClusteringRunOption[],
            {
                loadClusteringRuns: async () => {
                    const eventName =
                        values.clusteringLevel === 'generation' ? '$ai_generation_clusters' : '$ai_trace_clusters'

                    const response = await api.queryHogQL(
                        hogql`
                            SELECT
                                JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                                JSONExtractString(properties, '$ai_window_end') as window_end,
                                timestamp
                            FROM events
                            WHERE event = ${eventName}
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
                    // Derive level from runId to ensure correct event is queried even on direct URL navigation
                    const level = getLevelFromRunId(runId)
                    const eventName = level === 'generation' ? '$ai_generation_clusters' : '$ai_trace_clusters'

                    const response = await api.queryHogQL(
                        hogql`
                            SELECT
                                JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                                JSONExtractString(properties, '$ai_window_start') as window_start,
                                JSONExtractString(properties, '$ai_window_end') as window_end,
                                JSONExtractInt(properties, '$ai_total_items_analyzed') as total_items,
                                JSONExtractRaw(properties, '$ai_clusters') as clusters,
                                timestamp,
                                JSONExtractRaw(properties, '$ai_clustering_params') as clustering_params,
                                JSONExtractString(properties, '$ai_clustering_level') as clustering_level
                            FROM events
                            WHERE event = ${eventName}
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
                        totalItemsAnalyzed: row[3] as number,
                        clusters: clustersData,
                        timestamp: row[5] as string,
                        clusteringParams,
                        level: (row[7] as ClusteringLevel) || level,
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
                const itemDatasets: ScatterDataset[] = []
                const centroidDatasets: ScatterDataset[] = []

                for (const cluster of clusters) {
                    const isOutlier = cluster.cluster_id === NOISE_CLUSTER_ID
                    const color = isOutlier ? OUTLIER_COLOR : getSeriesColor(cluster.cluster_id)
                    const label = cluster.title || `Cluster ${cluster.cluster_id}`

                    // Item points (traces or generations)
                    itemDatasets.push({
                        label,
                        data: Object.entries(cluster.traces).map(([itemKey, itemInfo]) => ({
                            x: itemInfo.x,
                            y: itemInfo.y,
                            // Use explicit trace_id/generation_id from backend if available
                            // Fall back to itemKey for backwards compatibility
                            traceId: itemInfo.trace_id || itemKey,
                            generationId: itemInfo.generation_id,
                            timestamp: itemInfo.timestamp,
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

                return [...itemDatasets, ...centroidDatasets]
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setClusteringLevel: ({ level }) => {
            posthog.capture('llma clusters level changed', { level })
            // Reload runs when level changes
            actions.loadClusteringRuns()
        },

        loadClusterMetricsForRun: async ({ run }) => {
            if (!run.clusters || run.clusters.length === 0) {
                return
            }

            actions.setClusterMetricsLoading(true)

            try {
                const metrics = await loadClusterMetrics(
                    run.clusters,
                    run.windowStart,
                    run.windowEnd,
                    run.level || values.clusteringLevel
                )
                actions.setClusterMetrics(metrics)
            } catch (error) {
                console.error('Failed to load cluster metrics:', error)
            } finally {
                actions.setClusterMetricsLoading(false)
            }
        },

        loadTraceSummariesForRun: async ({ run }) => {
            // Collect all item IDs from all clusters
            const allItemIds: string[] = []
            for (const cluster of run.clusters) {
                allItemIds.push(...Object.keys(cluster.traces))
            }

            actions.setTraceSummariesLoading(true)

            try {
                const summaries = await loadTraceSummaries(
                    allItemIds,
                    values.traceSummaries,
                    run.windowStart,
                    run.windowEnd,
                    values.clusteringLevel
                )
                actions.setTraceSummaries(summaries)
            } catch (error) {
                console.error('Failed to load trace summaries:', error)
            } finally {
                actions.setTraceSummariesLoading(false)
            }
        },

        toggleClusterExpanded: async ({ clusterId }) => {
            posthog.capture('llma clusters cluster expanded', {
                cluster_id: clusterId,
                run_id: values.effectiveRunId,
            })
            // Load summaries when expanding a cluster (fallback for lazy loading)
            if (values.expandedClusterIds.has(clusterId)) {
                const run = values.currentRun
                const cluster = run?.clusters.find((c: Cluster) => c.cluster_id === clusterId)
                if (cluster && run) {
                    const itemIds = Object.keys(cluster.traces)

                    actions.setTraceSummariesLoading(true)

                    try {
                        const summaries = await loadTraceSummaries(
                            itemIds,
                            values.traceSummaries,
                            run.windowStart,
                            run.windowEnd,
                            values.clusteringLevel
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
            // Sync clusteringLevel with the loaded run's level (without triggering reload)
            // This handles direct URL navigation to a run with a different level
            if (currentRun?.level && currentRun.level !== values.clusteringLevel) {
                actions.syncClusteringLevelFromRun(currentRun.level)
                // Reload runs for the correct level so the dropdown shows proper labels
                actions.loadClusteringRuns()
            }
            // Load all trace summaries when a run is loaded for scatter plot tooltips
            if (currentRun) {
                actions.loadTraceSummariesForRun(currentRun)
                // Load cluster metrics for displaying averages in cluster cards
                actions.loadClusterMetricsForRun(currentRun)
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

        toggleScatterPlotExpanded: () => {
            posthog.capture('llma clusters scatter plot toggled', {
                expanded: values.isScatterPlotExpanded,
            })
        },

        setSelectedRunId: ({ runId }) => {
            if (runId) {
                posthog.capture('llma clusters run selected', { run_id: runId })
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
