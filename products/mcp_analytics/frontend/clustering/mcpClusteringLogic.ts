import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { MCPToolCategoryMapItem, NodeKind } from '~/queries/schema/schema-general'
import { urls } from '~/scenes/urls'

import type { FeatureFlagsSet } from '../../../../frontend/src/lib/logic/featureFlagLogic'
import { mcpAnalyticsIntentClustersRecompute, mcpAnalyticsIntentClustersRetrieve } from '../generated/api'
import type {
    MCPIntentClusterApi,
    MCPIntentClusterSnapshotApi,
    MCPToolOverlapApi,
    MCPToolPivotApi,
    MCPToolPivotClusterEntryApi,
} from '../generated/api.schemas'

const EMPTY_SNAPSHOT: MCPIntentClusterSnapshotApi = {
    status: 'idle',
    error_message: '',
    last_computed_at: null,
    last_computed_by_email: '',
    clusters: [],
    tools: [],
    tool_overlaps: [],
    computed_with: null,
}

const POLL_INTERVAL_MS = 3000

// Categories are read over a fixed window rather than the snapshot's own lookback, which is
// 7 days by default but configurable per run. A wider window can only add tools the snapshot
// never names — harmless — while a narrower one would drop tools from the filter entirely.
const CATEGORY_LOOKBACK = '-30d'
// A failed map load has to be retryable, or one blip leaves the tab unfilterable for the
// session. It cannot retry freely either: urlToAction re-runs on every selection, so an
// unbounded re-arm would refetch on each click. One retry, then the tab stays unscoped.
const MAX_CATEGORY_MAP_ATTEMPTS = 2

/** Segments drawn on a cluster row's routing bar before the rest is aggregated. */
export const ROUTING_BAR_SEGMENTS = 3

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
export type ToolSortKey = 'calls' | 'contested' | 'discovery'
export type ClusteringViewMode = 'intents' | 'tools'

/** How spread out a cluster's calls are across the tools that served it. */
export type RouteShape = 'concentrated' | 'mixed' | 'spread'

export type ClusterFilter = 'all' | RouteShape | 'failing'

/** Cluster counts per route shape, plus the count of clusters that lost calls to errors. */
export interface RouteShapeCounts {
    concentrated: number
    mixed: number
    spread: number
    failing: number
    total: number
}

/**
 * The single definition of a cluster's route shape. Both the scorecard counts and
 * the filter each card applies read it, so a card cannot state one number and
 * filter to a different set.
 */
export function routeShape(cluster: MCPIntentClusterApi): RouteShape {
    // A cluster with no distribution has no shape to report; calling it
    // concentrated would count "we know nothing" as the healthiest bucket.
    if (cluster.tool_distribution.length === 0) {
        return 'mixed'
    }
    const top = cluster.tool_distribution[0].pct
    if (top >= 80) {
        return 'concentrated'
    }
    if (cluster.tool_distribution.length >= 2 && top < 50) {
        return 'spread'
    }
    return 'mixed'
}

export interface RoutingSegment {
    /** null on the aggregated remainder, which stands for `toolCount` tools. */
    tool: string | null
    pct: number
    errorRatePct: number
    toolCount: number
}

/**
 * A cluster's tool distribution reduced to a few drawable segments, with
 * everything past the cap folded into one remainder. Replaces the cluster × tool
 * heatmap: the same routing read, at a width that fits beside a detail pane.
 */
export function routingSegments(cluster: MCPIntentClusterApi, maxSegments = ROUTING_BAR_SEGMENTS): RoutingSegment[] {
    const ordered = [...cluster.tool_distribution].sort((a, b) => b.count - a.count)
    const head = ordered.slice(0, maxSegments).map((entry) => ({
        tool: entry.tool,
        pct: entry.pct,
        errorRatePct: entry.error_rate_pct,
        toolCount: 1,
    }))
    const rest = ordered.slice(maxSegments)
    if (rest.length === 0) {
        return head
    }
    const calls = rest.reduce((sum, entry) => sum + entry.count, 0)
    const errors = rest.reduce((sum, entry) => sum + entry.errors, 0)
    return [
        ...head,
        {
            tool: null,
            pct: rest.reduce((sum, entry) => sum + entry.pct, 0),
            errorRatePct: calls > 0 ? (100 * errors) / calls : 0,
            toolCount: rest.length,
        },
    ]
}

export interface ScatterPoint {
    tool: string
    fit: number
    discoveryRatePct: number
    callCount: number
}

/** Call-weighted mean description fit across a tool's cluster entries, or null when no entry has one. */
export function weightedMeanFit(tool: MCPToolPivotApi): number | null {
    const withFit = tool.clusters.filter((entry) => entry.description_fit !== null)
    if (withFit.length === 0) {
        return null
    }
    const totalCalls = withFit.reduce((sum, entry) => sum + entry.calls, 0)
    if (totalCalls === 0) {
        return null
    }
    return withFit.reduce((sum, entry) => sum + (entry.description_fit as number) * entry.calls, 0) / totalCalls
}

/** An entry joined to the cluster it points at, so the pivot doesn't have to carry a copy. */
export interface ToolClusterRow {
    entry: MCPToolPivotClusterEntryApi
    cluster: MCPIntentClusterApi
}

/**
 * Join a tool's pivot entries to their clusters. Entries whose cluster is absent
 * are dropped rather than rendered label-less: the backend only emits entries for
 * clusters the snapshot carries, so a miss means the two came from different runs.
 */
export function toolClusterRows(tool: MCPToolPivotApi, clusters: readonly MCPIntentClusterApi[]): ToolClusterRow[] {
    const byId = new Map(clusters.map((cluster) => [cluster.id, cluster]))
    return tool.clusters.flatMap((entry) => {
        const cluster = byId.get(entry.cluster_id)
        return cluster ? [{ entry, cluster }] : []
    })
}

// Cosine fits for one server's tools against its own intent centroids sit in a
// narrow band. Anchoring the axis at 0 pushes every bubble against the right edge
// and runs the median line through the pile, defeating the quadrant read.
const FIT_DOMAIN_MIN_SPAN = 0.1
const FIT_DOMAIN_PADDING = 0.1

/** Padded x-domain around the observed fits, with a floor on the span so a single point can't collapse it. */
/**
 * Every category the cluster's tools belong to, in call-volume order so the busiest
 * category leads. A cluster routing across categories is the interesting case — it means
 * one goal is being served by tools the catalog files under different headings.
 */
export function clusterCategories(cluster: MCPIntentClusterApi, categoriesByTool: Record<string, string[]>): string[] {
    const seen = new Set<string>()
    const ordered: string[] = []
    for (const entry of cluster.tool_distribution) {
        for (const category of categoriesByTool[entry.tool] ?? []) {
            if (!seen.has(category)) {
                seen.add(category)
                ordered.push(category)
            }
        }
    }
    return ordered
}

export function fitDomain(fits: number[]): [number, number] {
    if (fits.length === 0) {
        return [0, 1]
    }
    const low = Math.min(...fits)
    const high = Math.max(...fits)
    const pad = Math.max((high - low) * FIT_DOMAIN_PADDING, FIT_DOMAIN_MIN_SPAN / 2)
    return [Math.max(-1, low - pad), Math.min(1, high + pad)]
}

function median(values: number[]): number | null {
    if (values.length === 0) {
        return null
    }
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpClusteringLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentProjectId: number | string // teamLogic
    availableCategories: string[]
    categoriesByTool: Record<string, string[]>
    categoryMap: MCPToolCategoryMapItem[]
    categoryMapAttempts: number
    categoryMapLoading: boolean
    categoryMapRequested: boolean
    categoryScopeOptions: string[]
    clusterFilter: ClusterFilter
    clusters: readonly MCPIntentClusterApi[]
    discoveryMedian: number | null
    filteredClusters: MCPIntentClusterApi[]
    fitMedian: number | null
    hasSnapshot: boolean
    hasToolPivot: boolean
    intentRoutingEnabled: boolean
    isComputing: boolean
    routeShapeCounts: RouteShapeCounts
    scatterPoints: ScatterPoint[]
    scopedClusters: MCPIntentClusterApi[]
    scopedTools: readonly MCPToolPivotApi[]
    searchedClusters: MCPIntentClusterApi[]
    selectedCategories: string[]
    selectedCluster: MCPIntentClusterApi | null
    selectedClusterId: number | null
    selectedTool: MCPToolPivotApi | null
    selectedToolName: string | null
    snapshot: MCPIntentClusterSnapshotApi
    snapshotLoading: boolean
    sortKey: ClusterSortKey
    sortedClusters: MCPIntentClusterApi[]
    sortedTools: MCPToolPivotApi[]
    toolOverlaps: readonly MCPToolOverlapApi[]
    toolSearch: string
    toolSortKey: ToolSortKey
    tools: readonly MCPToolPivotApi[]
    toolsInScope: Set<string> | null
    totalClusterCount: number
    viewMode: ClusteringViewMode
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpClusteringLogicActions {
    keepSelectionVisible: () => {
        value: true
    }
    loadCategoryMap: () => any
    loadCategoryMapFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCategoryMapSuccess: (
        categoryMap: MCPToolCategoryMapItem[],
        payload?: any
    ) => {
        categoryMap: MCPToolCategoryMapItem[]
        payload?: any
    }
    loadSnapshot: () => any
    loadSnapshotFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSnapshotSuccess: (
        snapshot: MCPIntentClusterSnapshotApi,
        payload?: any
    ) => {
        snapshot: MCPIntentClusterSnapshotApi
        payload?: any
    }
    pollSnapshot: () => {
        value: true
    }
    recompute: () => {
        value: true
    }
    selectCluster: (clusterId: number | null) => {
        clusterId: number | null
    }
    selectTool: (toolName: string | null) => {
        toolName: string | null
    }
    setClusterFilter: (clusterFilter: ClusterFilter) => {
        clusterFilter: ClusterFilter
    }
    setSelectedCategories: (categories: string[]) => {
        categories: string[]
    }
    setSortKey: (sortKey: ClusterSortKey) => {
        sortKey: ClusterSortKey
    }
    setToolSearch: (toolSearch: string) => {
        toolSearch: string
    }
    setToolSortKey: (toolSortKey: ToolSortKey) => {
        toolSortKey: ToolSortKey
    }
    setViewMode: (viewMode: ClusteringViewMode) => {
        viewMode: ClusteringViewMode
    }
    startPolling: () => {
        value: true
    }
    stopPolling: () => {
        value: true
    }
    triggerRecompute: () => any
    triggerRecomputeFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    triggerRecomputeSuccess: (
        snapshot: MCPIntentClusterSnapshotApi,
        payload?: any
    ) => {
        snapshot: MCPIntentClusterSnapshotApi
        payload?: any
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpClusteringLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        intentRoutingEnabled: (featureFlags: FeatureFlagsSet) => boolean
        clusters: (snapshot: MCPIntentClusterSnapshotApi) => readonly MCPIntentClusterApi[]
        tools: (snapshot: MCPIntentClusterSnapshotApi) => readonly MCPToolPivotApi[]
        categoriesByTool: (categoryMap: MCPToolCategoryMapItem[]) => Record<string, string[]>
        availableCategories: (categoryMap: MCPToolCategoryMapItem[]) => string[]
        categoryScopeOptions: (availableCategories: string[], selectedCategories: string[]) => string[]
        toolsInScope: (categoryMap: MCPToolCategoryMapItem[], selectedCategories: string[]) => Set<string> | null
        toolOverlaps: (
            snapshot: MCPIntentClusterSnapshotApi,
            toolsInScope: Set<string> | null
        ) => readonly MCPToolOverlapApi[]
        hasToolPivot: (tools: readonly MCPToolPivotApi[]) => boolean
        sortedClusters: (clusters: readonly MCPIntentClusterApi[], sortKey: ClusterSortKey) => MCPIntentClusterApi[]
        scopedClusters: (
            sortedClusters: MCPIntentClusterApi[],
            toolsInScope: Set<string> | null
        ) => MCPIntentClusterApi[]
        searchedClusters: (scopedClusters: MCPIntentClusterApi[], toolSearch: string) => MCPIntentClusterApi[]
        filteredClusters: (
            searchedClusters: MCPIntentClusterApi[],
            clusterFilter: ClusterFilter
        ) => MCPIntentClusterApi[]
        scopedTools: (tools: readonly MCPToolPivotApi[], toolsInScope: Set<string> | null) => readonly MCPToolPivotApi[]
        sortedTools: (
            scopedTools: readonly MCPToolPivotApi[],
            toolSortKey: ToolSortKey,
            toolSearch: string
        ) => MCPToolPivotApi[]
        selectedTool: (tools: readonly MCPToolPivotApi[], selectedToolName: string | null) => MCPToolPivotApi | null
        scatterPoints: (scopedTools: readonly MCPToolPivotApi[]) => ScatterPoint[]
        fitMedian: (scatterPoints: ScatterPoint[]) => number | null
        discoveryMedian: (scatterPoints: ScatterPoint[]) => number | null
        totalClusterCount: (snapshot: MCPIntentClusterSnapshotApi) => number
        selectedCluster: (
            clusters: readonly MCPIntentClusterApi[],
            selectedClusterId: number | null
        ) => MCPIntentClusterApi | null
        routeShapeCounts: (searchedClusters: MCPIntentClusterApi[]) => RouteShapeCounts
        isComputing: (snapshot: MCPIntentClusterSnapshotApi) => boolean
        hasSnapshot: (snapshot: MCPIntentClusterSnapshotApi) => boolean
    }
}

export type mcpClusteringLogicType = MakeLogicType<
    mcpClusteringLogicValues,
    mcpClusteringLogicActions,
    Record<string, any>,
    mcpClusteringLogicMeta
>

export const mcpClusteringLogic = kea<mcpClusteringLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'clustering', 'mcpClusteringLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], teamLogic, ['currentProjectId']],
    })),
    actions({
        selectCluster: (clusterId: number | null) => ({ clusterId }),
        selectTool: (toolName: string | null) => ({ toolName }),
        setSortKey: (sortKey: ClusterSortKey) => ({ sortKey }),
        setToolSortKey: (toolSortKey: ToolSortKey) => ({ toolSortKey }),
        setViewMode: (viewMode: ClusteringViewMode) => ({ viewMode }),
        setToolSearch: (toolSearch: string) => ({ toolSearch }),
        setClusterFilter: (clusterFilter: ClusterFilter) => ({ clusterFilter }),
        setSelectedCategories: (categories: string[]) => ({ categories }),
        keepSelectionVisible: true,
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
                    if (!values.currentProjectId || !values.intentRoutingEnabled) {
                        return EMPTY_SNAPSHOT
                    }
                    const response = await mcpAnalyticsIntentClustersRetrieve(String(values.currentProjectId))
                    return normalizeSnapshot(response)
                },
                triggerRecompute: async () => {
                    if (!values.currentProjectId || !values.intentRoutingEnabled) {
                        return EMPTY_SNAPSHOT
                    }
                    const response = await mcpAnalyticsIntentClustersRecompute(String(values.currentProjectId))
                    return normalizeSnapshot(response)
                },
            },
        ],
        // The snapshot stores tool names but no categories, so the mapping is fetched
        // separately and joined by tool name. Keeping it out of the snapshot means an
        // existing snapshot gains category filtering without being recomputed.
        categoryMap: [
            [] as MCPToolCategoryMapItem[],
            {
                loadCategoryMap: async (): Promise<MCPToolCategoryMapItem[]> => {
                    if (!values.intentRoutingEnabled) {
                        return []
                    }
                    const response = (await api.query({
                        kind: NodeKind.MCPToolCategoryMapQuery,
                        dateRange: { date_from: CATEGORY_LOOKBACK },
                    })) as { results?: MCPToolCategoryMapItem[] } | undefined
                    // An absent map costs only the filter, so it must not take the page down
                    // with it — every view still renders, just unscoped.
                    return response?.results ?? []
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
        selectedToolName: [
            null as string | null,
            {
                selectTool: (_, { toolName }) => toolName,
            },
        ],
        sortKey: [
            'calls' as ClusterSortKey,
            {
                setSortKey: (_, { sortKey }) => sortKey,
            },
        ],
        toolSortKey: [
            'calls' as ToolSortKey,
            {
                setToolSortKey: (_, { toolSortKey }) => toolSortKey,
            },
        ],
        viewMode: [
            'intents' as ClusteringViewMode,
            {
                setViewMode: (_, { viewMode }) => viewMode,
            },
        ],
        toolSearch: [
            '',
            {
                setToolSearch: (_, { toolSearch }) => toolSearch,
            },
        ],
        clusterFilter: [
            'all' as ClusterFilter,
            {
                setClusterFilter: (_, { clusterFilter }) => clusterFilter,
            },
        ],
        selectedCategories: [
            [] as string[],
            {
                setSelectedCategories: (_, { categories }) => categories,
            },
        ],
        // Every selection writes the url back, which re-runs urlToAction. Without this the
        // map would refetch on each click. Set on request, not on success, so an in-flight
        // load is not started twice.
        categoryMapRequested: [
            false,
            {
                loadCategoryMap: () => true,
                // Re-arm on failure so a later navigation can retry; the attempt count is
                // what stops that from becoming a request per click.
                loadCategoryMapFailure: () => false,
            },
        ],
        categoryMapAttempts: [
            0,
            {
                loadCategoryMap: (state: number) => state + 1,
            },
        ],
    }),
    selectors({
        intentRoutingEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_INTENT_ROUTING],
        ],
        clusters: [
            (s) => [s.snapshot],
            (snapshot: MCPIntentClusterSnapshotApi): readonly MCPIntentClusterApi[] => snapshot.clusters,
        ],
        tools: [
            (s) => [s.snapshot],
            (snapshot: MCPIntentClusterSnapshotApi): readonly MCPToolPivotApi[] => snapshot.tools ?? [],
        ],
        // Every category a tool has been called under. A tool recategorised mid-window
        // belongs to both, so filtering by either keeps finding it.
        categoriesByTool: [
            (s) => [s.categoryMap],
            (categoryMap: MCPToolCategoryMapItem[]): Record<string, string[]> => {
                // Tool names come from events, so a call named `__proto__` or `constructor`
                // would resolve `byTool[tool]` to an inherited value and throw on `.includes`.
                // A prototype-free map keys those names as ordinary data.
                const byTool: Record<string, string[]> = Object.create(null)
                for (const { tool, category } of categoryMap) {
                    const existing = byTool[tool]
                    if (!existing) {
                        byTool[tool] = [category]
                    } else if (!existing.includes(category)) {
                        existing.push(category)
                    }
                }
                return byTool
            },
        ],
        // Drawn from the tool map rather than the full category vocabulary, so the selector
        // never offers a category that no tool in the data belongs to.
        availableCategories: [
            (s) => [s.categoryMap],
            (categoryMap: MCPToolCategoryMapItem[]): string[] =>
                Array.from(new Set(categoryMap.map((row) => row.category))).sort((a, b) => a.localeCompare(b)),
        ],
        // What the scope selector offers, which is not the same as what the map knows. A
        // category carried in from the url survives a failed map load, and the selector is
        // the only way to clear it, so the selection is always offered back even when the
        // map contributed nothing.
        categoryScopeOptions: [
            (s) => [s.availableCategories, s.selectedCategories],
            (availableCategories: string[], selectedCategories: string[]): string[] =>
                Array.from(new Set([...availableCategories, ...selectedCategories])).sort((a, b) => a.localeCompare(b)),
        ],
        // Null rather than an empty set means "no scope, show everything". Two cases return it:
        // nothing is selected, or there is no map to scope against — still loading, the query
        // failed, or the project sent no $mcp_tool_category in the window. Without the second
        // guard a category carried in from the url would scope every view down to nothing while
        // the map is absent, and the selector hides itself (no categories to offer), leaving no
        // way to clear it. A real scope only exists once the map has data, so this renders
        // unscoped meanwhile, matching the loader's "an absent map costs only the filter" intent.
        toolsInScope: [
            (s) => [s.categoryMap, s.selectedCategories],
            (categoryMap: MCPToolCategoryMapItem[], selectedCategories: string[]): Set<string> | null => {
                if (selectedCategories.length === 0 || categoryMap.length === 0) {
                    return null
                }
                const wanted = new Set(selectedCategories)
                return new Set(categoryMap.filter((row) => wanted.has(row.category)).map((row) => row.tool))
            },
        ],
        // Either side in scope, not both: the point of a contested pair is spotting a tool
        // competing with one it shouldn't, and that competitor is often in another category.
        toolOverlaps: [
            (s) => [s.snapshot, s.toolsInScope],
            (snapshot: MCPIntentClusterSnapshotApi, toolsInScope: Set<string> | null): readonly MCPToolOverlapApi[] => {
                const overlaps = snapshot.tool_overlaps ?? []
                if (!toolsInScope) {
                    return overlaps
                }
                return overlaps.filter((o) => toolsInScope.has(o.tool_a) || toolsInScope.has(o.tool_b))
            },
        ],
        // Snapshots computed before the per-call pipeline have no tool sections;
        // the tools view offers a recompute instead of rendering empty tables.
        hasToolPivot: [(s) => [s.tools], (tools: readonly MCPToolPivotApi[]): boolean => tools.length > 0],
        sortedClusters: [
            (s) => [s.clusters, s.sortKey],
            (clusters: readonly MCPIntentClusterApi[], sortKey: ClusterSortKey): MCPIntentClusterApi[] => {
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
        // A cluster is in scope when any tool it routes to is, mirroring how the tool
        // search matches. Scoping sits ahead of the search so the scorecards, the search
        // and the list all count the same population.
        scopedClusters: [
            (s) => [s.sortedClusters, s.toolsInScope],
            (sortedClusters: MCPIntentClusterApi[], toolsInScope: Set<string> | null): MCPIntentClusterApi[] => {
                if (!toolsInScope) {
                    return sortedClusters
                }
                return sortedClusters.filter((cluster) =>
                    cluster.tool_distribution.some((entry) => toolsInScope.has(entry.tool))
                )
            },
        ],
        // The tool search narrows the population both the scorecards count and the
        // list filter read. Splitting it out keeps the two in lockstep: the scorecards
        // count shapes within the searched set, and each card's filter draws from it.
        searchedClusters: [
            (s) => [s.scopedClusters, s.toolSearch],
            (scopedClusters: MCPIntentClusterApi[], toolSearch: string): MCPIntentClusterApi[] => {
                const query = toolSearch.trim().toLowerCase()
                if (!query) {
                    return scopedClusters
                }
                return scopedClusters.filter((cluster) =>
                    cluster.tool_distribution.some((e) => e.tool.toLowerCase().includes(query))
                )
            },
        ],
        filteredClusters: [
            (s) => [s.searchedClusters, s.clusterFilter],
            (searchedClusters: MCPIntentClusterApi[], clusterFilter: ClusterFilter): MCPIntentClusterApi[] => {
                return searchedClusters.filter((cluster) => {
                    if (clusterFilter === 'failing') {
                        return cluster.error_count > 0
                    }
                    return clusterFilter === 'all' || routeShape(cluster) === clusterFilter
                })
            },
        ],
        // A tool with no category row is out of scope once a filter is on: it belongs to
        // none of the selected categories, so keeping it would contradict the filter.
        scopedTools: [
            (s) => [s.tools, s.toolsInScope],
            (tools: readonly MCPToolPivotApi[], toolsInScope: Set<string> | null): readonly MCPToolPivotApi[] =>
                toolsInScope ? tools.filter((tool) => toolsInScope.has(tool.tool)) : tools,
        ],
        sortedTools: [
            (s) => [s.scopedTools, s.toolSortKey, s.toolSearch],
            (
                scopedTools: readonly MCPToolPivotApi[],
                toolSortKey: ToolSortKey,
                toolSearch: string
            ): MCPToolPivotApi[] => {
                const query = toolSearch.trim().toLowerCase()
                const arr = scopedTools.filter((tool) => !query || tool.tool.toLowerCase().includes(query))
                switch (toolSortKey) {
                    case 'contested':
                        return arr.sort((a, b) => (b.contested_score ?? -1) - (a.contested_score ?? -1))
                    case 'discovery':
                        // Nulls sink to the bottom so measurable rates lead.
                        return arr.sort((a, b) => (b.discovery_rate_pct ?? -1) - (a.discovery_rate_pct ?? -1))
                    case 'calls':
                    default:
                        return arr.sort((a, b) => b.call_count - a.call_count)
                }
            },
        ],
        selectedTool: [
            (s) => [s.tools, s.selectedToolName],
            (tools: readonly MCPToolPivotApi[], selectedToolName: string | null): MCPToolPivotApi | null => {
                if (selectedToolName === null) {
                    return null
                }
                return tools.find((tool) => tool.tool === selectedToolName) ?? null
            },
        ],
        scatterPoints: [
            (s) => [s.scopedTools],
            (scopedTools: readonly MCPToolPivotApi[]): ScatterPoint[] =>
                scopedTools.flatMap((tool) => {
                    const fit = weightedMeanFit(tool)
                    if (fit === null || tool.discovery_rate_pct === null) {
                        return []
                    }
                    return [
                        {
                            tool: tool.tool,
                            fit,
                            discoveryRatePct: tool.discovery_rate_pct,
                            callCount: tool.call_count,
                        },
                    ]
                }),
        ],
        // Quadrant lines sit at the medians of the plotted tools: data-derived,
        // so no tuned threshold decides what counts as "well described".
        fitMedian: [
            (s) => [s.scatterPoints],
            (scatterPoints: ScatterPoint[]): number | null => median(scatterPoints.map((p) => p.fit)),
        ],
        discoveryMedian: [
            (s) => [s.scatterPoints],
            (scatterPoints: ScatterPoint[]): number | null => median(scatterPoints.map((p) => p.discoveryRatePct)),
        ],
        // The true number of clusters the run found — the snapshot itself only
        // carries the top MAX_SNAPSHOT_CLUSTERS by call volume, so anything
        // reporting "how many clusters exist" must read this, not clusters.length.
        totalClusterCount: [
            (s) => [s.snapshot],
            (snapshot: MCPIntentClusterSnapshotApi): number =>
                Math.max(snapshot.computed_with?.n_clusters ?? 0, snapshot.clusters.length),
        ],
        selectedCluster: [
            (s) => [s.clusters, s.selectedClusterId],
            (
                clusters: readonly MCPIntentClusterApi[],
                selectedClusterId: number | null
            ): MCPIntentClusterApi | null => {
                if (selectedClusterId === null) {
                    return null
                }
                return clusters.find((c) => c.id === selectedClusterId) ?? null
            },
        ],
        // Backs the scorecards. Each count comes from the same `routeShape` the
        // matching filter uses, over the same searched set the list draws from, so
        // clicking a card yields exactly the number it shows — tool search active or not.
        routeShapeCounts: [
            (s) => [s.searchedClusters],
            (searchedClusters: MCPIntentClusterApi[]): RouteShapeCounts => {
                const counts: RouteShapeCounts = {
                    concentrated: 0,
                    mixed: 0,
                    spread: 0,
                    failing: 0,
                    total: searchedClusters.length,
                }
                for (const cluster of searchedClusters) {
                    counts[routeShape(cluster)] += 1
                    if (cluster.error_count > 0) {
                        counts.failing += 1
                    }
                }
                return counts
            },
        ],
        isComputing: [
            (s) => [s.snapshot],
            (snapshot: MCPIntentClusterSnapshotApi): boolean => snapshot.status === 'computing',
        ],
        hasSnapshot: [
            (s) => [s.snapshot],
            (snapshot: MCPIntentClusterSnapshotApi): boolean =>
                snapshot.last_computed_at !== null || snapshot.clusters.length > 0,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        [featureFlagLogic.actionTypes.setFeatureFlags]: () => {
            if (!values.intentRoutingEnabled) {
                cache.snapshotRequested = false
                actions.stopPolling()
                return
            }
            if (!cache.snapshotRequested) {
                cache.snapshotRequested = true
                actions.loadSnapshot()
            }
        },
        loadSnapshotSuccess: ({ snapshot }) => {
            if (snapshot.status === 'computing') {
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
            // Fill or reconcile the selection against the scoped list. A `?cluster=` link, a
            // recompute that reassigned ids, or an active category scope can all leave the
            // selection pointing at a cluster or tool this snapshot no longer shows; follow
            // the list so the detail pane never lands on one the list omits.
            actions.keepSelectionVisible()
        },
        // The category map arrives after the url has already applied the selection, so the
        // scope is only known now. Reconcile against it: without this the list becomes scoped
        // while the selection can sit outside it, leaving the detail pane on an excluded item.
        loadCategoryMapSuccess: () => {
            actions.keepSelectionVisible()
        },
        // Only once the retry is spent: a toast on the first failure would fire twice, and
        // silence would leave a category in the url quietly doing nothing.
        loadCategoryMapFailure: () => {
            if (values.categoryMapAttempts >= MAX_CATEGORY_MAP_ATTEMPTS) {
                lemonToast.error(
                    'Could not load tool categories, so category filtering is unavailable. Refresh the page to try again.'
                )
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
            // Keyed add replaces any existing poller, and the disposables plugin
            // pauses it while the tab is hidden — no full-snapshot refetches in
            // background tabs — and cleans it up on unmount.
            cache.disposables.add(() => {
                const intervalId = window.setInterval(() => {
                    actions.pollSnapshot()
                }, POLL_INTERVAL_MS)
                return () => window.clearInterval(intervalId)
            }, 'snapshotPoll')
        },
        stopPolling: () => {
            cache.disposables.dispose('snapshotPoll')
        },
        pollSnapshot: () => {
            actions.loadSnapshot()
        },
        // Narrowing the list can strand the selection outside it, leaving the detail
        // pane describing a cluster the list no longer offers. Follow the list instead.
        setClusterFilter: () => {
            actions.keepSelectionVisible()
        },
        setToolSearch: () => {
            actions.keepSelectionVisible()
        },
        setSelectedCategories: () => {
            actions.keepSelectionVisible()
        },
        keepSelectionVisible: () => {
            const {
                filteredClusters,
                selectedClusterId,
                clusters,
                scopedClusters,
                sortedTools,
                selectedToolName,
                tools,
                scopedTools,
                categoryMapLoading,
            } = values
            // Reconcile each selection against the list its pane renders: move it to the top of
            // the list when the current one is no longer there, and clear it only when the scope
            // genuinely excludes every row the snapshot carries. While the category map is still
            // loading the scope isn't known, so an empty scoped list means "not ready" rather
            // than "excluded" — leave the selection be so a deep-linked cluster or tool survives
            // until its data arrives. A plain search or filter that matches nothing keeps the
            // selection too; only a category scope that names none of the snapshot's tools clears
            // it, so the detail pane can never describe an item the scope hides.
            const clusterScopeExcludesAll = !categoryMapLoading && clusters.length > 0 && scopedClusters.length === 0
            if (!filteredClusters.some((c) => c.id === selectedClusterId)) {
                if (filteredClusters.length > 0) {
                    actions.selectCluster(filteredClusters[0].id)
                } else if (clusterScopeExcludesAll && selectedClusterId !== null) {
                    actions.selectCluster(null)
                }
            }
            const toolScopeExcludesAll = !categoryMapLoading && tools.length > 0 && scopedTools.length === 0
            if (!sortedTools.some((t) => t.tool === selectedToolName)) {
                if (sortedTools.length > 0) {
                    actions.selectTool(sortedTools[0].tool)
                } else if (toolScopeExcludesAll && selectedToolName !== null) {
                    actions.selectTool(null)
                }
            }
        },
    })),
    // Mirror the selection and view to the url so a cluster or tool can be linked to
    // directly, rather than the recipient landing on whichever has the most calls.
    actionToUrl(({ values }) => {
        const syncUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            const params: Record<string, string | null> = {
                view: values.viewMode === 'tools' ? 'tools' : null,
                cluster: values.selectedClusterId === null ? null : String(values.selectedClusterId),
                tool: values.selectedToolName,
            }
            for (const [key, value] of Object.entries(params)) {
                if (value) {
                    searchParams[key] = value
                } else {
                    delete searchParams[key]
                }
            }
            // An array, not a joined string, so a category containing a comma survives the trip.
            if (values.selectedCategories.length > 0) {
                searchParams.categories = values.selectedCategories
            } else {
                delete searchParams.categories
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            selectCluster: syncUrl,
            selectTool: syncUrl,
            setViewMode: syncUrl,
            setSelectedCategories: syncUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.mcpAnalyticsIntentClustering()]: (_, searchParams) => {
            if (
                values.intentRoutingEnabled &&
                !values.categoryMapRequested &&
                values.categoryMapAttempts < MAX_CATEGORY_MAP_ATTEMPTS
            ) {
                actions.loadCategoryMap()
            }
            const viewMode: ClusteringViewMode = searchParams.view === 'tools' ? 'tools' : 'intents'
            if (viewMode !== values.viewMode) {
                actions.setViewMode(viewMode)
            }
            // Guard the empty param explicitly: Number('') is 0, which would select a real id.
            const rawCluster = searchParams.cluster
            const clusterId = Number(rawCluster)
            if (rawCluster !== undefined && rawCluster !== '' && Number.isInteger(clusterId)) {
                if (clusterId !== values.selectedClusterId) {
                    actions.selectCluster(clusterId)
                }
            }
            if (typeof searchParams.tool === 'string' && searchParams.tool !== values.selectedToolName) {
                actions.selectTool(searchParams.tool)
            }
            // A single category arrives as a bare string rather than a one-element array.
            const categories = Array.isArray(searchParams.categories)
                ? searchParams.categories.map(String)
                : typeof searchParams.categories === 'string' && searchParams.categories
                  ? [searchParams.categories]
                  : []
            if (JSON.stringify(categories) !== JSON.stringify(values.selectedCategories)) {
                actions.setSelectedCategories(categories)
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        if (values.intentRoutingEnabled) {
            cache.snapshotRequested = true
            actions.loadSnapshot()
        }
    }),
])
