import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { Breadcrumb } from '~/types'

import type { clustersLogicType } from './clustersLogicType'
import { Cluster, ClusteringRun, ClusteringRunOption, NOISE_CLUSTER_ID, TraceSummary } from './types'

// Special color for outliers cluster
const OUTLIER_COLOR = '#888888'

export interface ScatterDataset {
    label: string
    data: Array<{ x: number; y: number; traceId?: string; clusterId?: number }>
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
                            ORDER BY timestamp DESC
                            LIMIT 20
                        `,
                        { refresh: 'force_blocking' }
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
                    const response = await api.queryHogQL(hogql`
                        SELECT
                            JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
                            JSONExtractString(properties, '$ai_window_start') as window_start,
                            JSONExtractString(properties, '$ai_window_end') as window_end,
                            JSONExtractInt(properties, '$ai_total_traces_analyzed') as total_traces,
                            JSONExtractRaw(properties, '$ai_clusters') as clusters,
                            timestamp
                        FROM events
                        WHERE event = '$ai_trace_clusters'
                            AND JSONExtractString(properties, '$ai_clustering_run_id') = ${runId}
                        LIMIT 1
                    `)

                    if (!response.results?.length) {
                        return null
                    }

                    const row = response.results[0] as (string | number)[]
                    const clustersData = JSON.parse((row[4] as string) || '[]')

                    return {
                        runId: row[0] as string,
                        windowStart: row[1] as string,
                        windowEnd: row[2] as string,
                        totalTracesAnalyzed: row[3] as number,
                        clusters: clustersData,
                        timestamp: row[5] as string,
                    }
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

            const missingTraceIds = allTraceIds.filter((id) => !values.traceSummaries[id])
            if (missingTraceIds.length === 0) {
                return
            }

            actions.setTraceSummariesLoading(true)

            try {
                const traceIdsList = missingTraceIds.map((id) => `'${id}'`).join(',')
                const response = await api.queryHogQL(hogql`
                    SELECT
                        JSONExtractString(properties, '$ai_trace_id') as trace_id,
                        argMax(JSONExtractString(properties, '$ai_summary_title'), timestamp) as title,
                        argMax(JSONExtractString(properties, '$ai_summary_flow_diagram'), timestamp) as flow_diagram,
                        argMax(JSONExtractString(properties, '$ai_summary_bullets'), timestamp) as bullets,
                        argMax(JSONExtractString(properties, '$ai_summary_interesting_notes'), timestamp) as interesting_notes,
                        max(timestamp) as timestamp
                    FROM events
                    WHERE event = '$ai_trace_summary'
                        AND JSONExtractString(properties, '$ai_trace_id') IN (${hogql.raw(traceIdsList)})
                    GROUP BY trace_id
                    LIMIT 10000
                `)

                const summaries: Record<string, TraceSummary> = {}
                for (const row of response.results || []) {
                    const r = row as string[]
                    summaries[r[0]] = {
                        traceId: r[0],
                        title: r[1] || 'Untitled Trace',
                        flowDiagram: r[2] || '',
                        bullets: r[3] || '',
                        interestingNotes: r[4] || '',
                        timestamp: r[5],
                    }
                }

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
                const cluster = values.currentRun?.clusters.find((c: Cluster) => c.cluster_id === clusterId)
                if (cluster) {
                    const traceIds = Object.keys(cluster.traces)
                    const missingTraceIds = traceIds.filter((id) => !values.traceSummaries[id])
                    if (missingTraceIds.length > 0) {
                        actions.setTraceSummariesLoading(true)

                        try {
                            const traceIdsList = missingTraceIds.map((id) => `'${id}'`).join(',')
                            const response = await api.queryHogQL(hogql`
                                SELECT
                                    JSONExtractString(properties, '$ai_trace_id') as trace_id,
                                    argMax(JSONExtractString(properties, '$ai_summary_title'), timestamp) as title,
                                    argMax(JSONExtractString(properties, '$ai_summary_flow_diagram'), timestamp) as flow_diagram,
                                    argMax(JSONExtractString(properties, '$ai_summary_bullets'), timestamp) as bullets,
                                    argMax(JSONExtractString(properties, '$ai_summary_interesting_notes'), timestamp) as interesting_notes,
                                    max(timestamp) as timestamp
                                FROM events
                                WHERE event = '$ai_trace_summary'
                                    AND JSONExtractString(properties, '$ai_trace_id') IN (${hogql.raw(traceIdsList)})
                                GROUP BY trace_id
                                LIMIT 10000
                            `)

                            const summaries: Record<string, TraceSummary> = {}
                            for (const row of response.results || []) {
                                const r = row as string[]
                                summaries[r[0]] = {
                                    traceId: r[0],
                                    title: r[1] || 'Untitled Trace',
                                    flowDiagram: r[2] || '',
                                    bullets: r[3] || '',
                                    interestingNotes: r[4] || '',
                                    timestamp: r[5],
                                }
                            }

                            actions.setTraceSummaries(summaries)
                        } catch (error) {
                            console.error('Failed to load trace summaries:', error)
                        } finally {
                            actions.setTraceSummariesLoading(false)
                        }
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
