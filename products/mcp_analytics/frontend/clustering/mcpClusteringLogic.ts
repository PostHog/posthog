import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { mcpAnalyticsIntentClustersRecompute, mcpAnalyticsIntentClustersRetrieve } from '../generated/api'
import type { MCPIntentClusterApi, MCPIntentClusterSnapshotApi } from '../generated/api.schemas'
import type { mcpClusteringLogicType } from './mcpClusteringLogicType'

const EMPTY_SNAPSHOT: MCPIntentClusterSnapshotApi = {
    status: 'idle',
    error_message: '',
    last_computed_at: null,
    last_computed_by_email: '',
    clusters: [],
    computed_with: null,
}

const POLL_INTERVAL_MS = 3000

// The generated client types the retrieve endpoint as returning an array, but the view actually
// returns a single object. drf-spectacular assumes ViewSet `list` actions return arrays. Normalize.
function normalizeSnapshot(
    response: MCPIntentClusterSnapshotApi | readonly MCPIntentClusterSnapshotApi[] | null | undefined
): MCPIntentClusterSnapshotApi {
    if (!response) {
        return EMPTY_SNAPSHOT
    }
    if (Array.isArray(response)) {
        return response[0] ?? EMPTY_SNAPSHOT
    }
    return response as MCPIntentClusterSnapshotApi
}

export type ClusterSortKey = 'calls' | 'errors' | 'entropy' | 'concentration'

export const mcpClusteringLogic = kea<mcpClusteringLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'clustering', 'mcpClusteringLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        selectCluster: (clusterId: number | null) => ({ clusterId }),
        setSortKey: (sortKey: ClusterSortKey) => ({ sortKey }),
        recompute: true,
        startPolling: true,
        stopPolling: true,
        pollSnapshot: true,
    }),
    loaders(({ values }) => ({
        snapshot: [
            EMPTY_SNAPSHOT as MCPIntentClusterSnapshotApi,
            {
                loadSnapshot: async () => {
                    if (!values.currentProjectId) {
                        return EMPTY_SNAPSHOT
                    }
                    const response = await mcpAnalyticsIntentClustersRetrieve(String(values.currentProjectId))
                    return normalizeSnapshot(response)
                },
                triggerRecompute: async () => {
                    if (!values.currentProjectId) {
                        return EMPTY_SNAPSHOT
                    }
                    const response = await mcpAnalyticsIntentClustersRecompute(String(values.currentProjectId))
                    return normalizeSnapshot(response)
                },
            },
        ],
    })),
    reducers({
        selectedClusterId: [
            null as number | null,
            {
                selectCluster: (_, { clusterId }) => clusterId,
            },
        ],
        sortKey: [
            'calls' as ClusterSortKey,
            {
                setSortKey: (_, { sortKey }) => sortKey,
            },
        ],
    }),
    selectors({
        clusters: [(s) => [s.snapshot], (snapshot): readonly MCPIntentClusterApi[] => snapshot.clusters],
        sortedClusters: [
            (s) => [s.clusters, s.sortKey],
            (clusters, sortKey): MCPIntentClusterApi[] => {
                const arr = [...clusters]
                switch (sortKey) {
                    case 'errors':
                        return arr.sort((a, b) => b.error_rate_pct - a.error_rate_pct)
                    case 'entropy':
                        return arr.sort((a, b) => b.routing_entropy - a.routing_entropy)
                    case 'concentration':
                        return arr.sort(
                            (a, b) => (a.tool_distribution[0]?.pct ?? 0) - (b.tool_distribution[0]?.pct ?? 0)
                        )
                    case 'calls':
                    default:
                        return arr.sort((a, b) => b.call_count - a.call_count)
                }
            },
        ],
        // Tools across the whole snapshot, ordered by total calls desc — these are the heatmap columns.
        toolColumns: [
            (s) => [s.clusters],
            (clusters): string[] => {
                const totals = new Map<string, number>()
                for (const cluster of clusters) {
                    for (const entry of cluster.tool_distribution) {
                        totals.set(entry.tool, (totals.get(entry.tool) ?? 0) + entry.count)
                    }
                }
                return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([tool]) => tool)
            },
        ],
        selectedCluster: [
            (s) => [s.clusters, s.selectedClusterId],
            (clusters, selectedClusterId): MCPIntentClusterApi | null => {
                if (selectedClusterId === null) {
                    return null
                }
                return clusters.find((c) => c.id === selectedClusterId) ?? null
            },
        ],
        // Scorecard derivations — all from existing aggregate fields.
        concentratedRoutes: [
            (s) => [s.clusters],
            (clusters): { focused: number; total: number } => ({
                focused: clusters.filter((c) => (c.tool_distribution[0]?.pct ?? 0) >= 80).length,
                total: clusters.length,
            }),
        ],
        spreadRoutes: [
            (s) => [s.clusters],
            (clusters): number =>
                clusters.filter((c) => {
                    const top = c.tool_distribution[0]?.pct ?? 100
                    return c.tool_distribution.length >= 2 && top < 50
                }).length,
        ],
        topErrorRoute: [
            (s) => [s.clusters],
            (clusters): MCPIntentClusterApi | null => {
                if (clusters.length === 0) {
                    return null
                }
                // Highest traffic-weighted error count — the cluster that loses the most calls to errors.
                return [...clusters].sort(
                    (a, b) => b.call_count * b.error_rate_pct - a.call_count * a.error_rate_pct
                )[0]
            },
        ],
        isComputing: [(s) => [s.snapshot], (snapshot): boolean => snapshot.status === 'computing'],
        hasSnapshot: [
            (s) => [s.snapshot],
            (snapshot): boolean => snapshot.last_computed_at !== null || snapshot.clusters.length > 0,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadSnapshotSuccess: ({ snapshot }) => {
            if (snapshot.status === 'computing') {
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
            if (values.selectedClusterId === null && snapshot.clusters.length > 0) {
                // Auto-select the highest-traffic cluster so the detail pane fills in.
                const top = [...snapshot.clusters].sort((a, b) => b.call_count - a.call_count)[0]
                actions.selectCluster(top.id)
            }
        },
        triggerRecomputeSuccess: ({ snapshot }) => {
            lemonToast.info('Clustering started — this usually takes 30–60 seconds.')
            if (snapshot.status === 'computing') {
                actions.startPolling()
            }
        },
        triggerRecomputeFailure: ({ error }) => {
            lemonToast.error(`Could not start clustering: ${error ?? 'unknown error'}`)
        },
        recompute: () => {
            actions.triggerRecompute()
        },
        startPolling: () => {
            if (cache.pollHandle) {
                return
            }
            cache.pollHandle = window.setInterval(() => {
                actions.pollSnapshot()
            }, POLL_INTERVAL_MS)
        },
        stopPolling: () => {
            if (cache.pollHandle) {
                window.clearInterval(cache.pollHandle)
                cache.pollHandle = null
            }
        },
        pollSnapshot: () => {
            actions.loadSnapshot()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSnapshot()
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),
])
