import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EventsQuery, NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { AnyPropertyFilter, Breadcrumb, PropertyFilterType, PropertyOperator } from '~/types'

import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { clusterDetailLogicType } from './clusterDetailLogicType'
import { loadClusterMetrics } from './clusterMetricsLoader'
import {
    FILTER_QUERY_MAX_ROWS,
    LLM_ANALYTICS_CLUSTER_SCENE_TAG,
    LLM_ANALYTICS_CLUSTER_URL_PATTERN,
    NOISE_CLUSTER_ID,
    OUTLIER_COLOR,
    SAFE_ID_RE,
    TRACES_PER_PAGE,
} from './constants'
import { loadTraceSummaries } from './traceSummaryLoader'
import {
    Cluster,
    ClusterItemInfo,
    ClusterMetrics,
    ClusteringLevel,
    TraceSummary,
    getTimestampBoundsFromRunId,
    parseClusterMetrics,
} from './types'

export interface ClusterDetailLogicProps {
    runId: string
    clusterId: number
    tabId?: string
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
    key((props) => `${props.runId}:${props.clusterId}::${props.tabId ?? 'default'}`),
    connect((props: ClusterDetailLogicProps) => ({
        values: [llmAnalyticsSharedLogic({ tabId: props.tabId }), ['propertyFilters', 'shouldFilterTestAccounts']],
        actions: [
            teamLogic,
            ['addProductIntent'],
            llmAnalyticsSharedLogic({ tabId: props.tabId }),
            ['setPropertyFilters', 'setShouldFilterTestAccounts', 'applyUrlState'],
        ],
    })),

    actions({
        setPage: (page: number) => ({ page }),
        loadMoreTraces: true,
        setTraceSummaries: (summaries: Record<string, TraceSummary>) => ({ summaries }),
        setTraceSummariesLoading: (loading: boolean) => ({ loading }),
        setClusterMetrics: (metrics: ClusterMetrics | null) => ({ metrics }),
        setClusterMetricsLoading: (loading: boolean) => ({ loading }),
        loadClusterMetricsForCluster: true,
        // Declared explicitly so kea-typegen generates a no-arg signature for the
        // loader action below — without this, the `(_, breakpoint)` loader signature
        // forces every call site to pass a placeholder argument.
        loadFilteredItemIds: true,
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

    loaders(({ props, values }) => ({
        // Subset of cluster item IDs that match the user's active property filters
        // (cohorts, person properties, etc.). Null when no filters are active —
        // selectors treat null as "show everything", which avoids forcing every
        // unfiltered cluster view to round-trip an EventsQuery on mount.
        filteredItemIds: [
            null as Set<string> | null,
            {
                loadFilteredItemIds: async (_, breakpoint) => {
                    // Debounce to coalesce overlapping filter changes (e.g. quick toggles
                    // of the test-accounts switch or successive cohort selections) into a
                    // single EventsQuery round-trip.
                    await breakpoint(150)

                    const propertyFilters: AnyPropertyFilter[] = values.propertyFilters || []
                    const shouldFilterTestAccounts: boolean = values.shouldFilterTestAccounts
                    const cluster = values.cluster
                    const windowStart = values.windowStart
                    const windowEnd = values.windowEnd
                    const clusteringLevel: ClusteringLevel = values.clusteringLevel

                    if (!cluster || !windowStart || !windowEnd) {
                        return null
                    }

                    if (propertyFilters.length === 0 && !shouldFilterTestAccounts) {
                        return null
                    }

                    // Eval clusters key on $ai_evaluation event UUIDs, which don't carry the
                    // person/cohort fields the user filters by. Skip filtering for now rather
                    // than silently producing empty results.
                    if (clusteringLevel === 'evaluation') {
                        return null
                    }

                    const clusterIds = Object.keys(cluster.traces).filter((id) => SAFE_ID_RE.test(id))
                    if (clusterIds.length === 0) {
                        return new Set<string>()
                    }

                    // For clusters larger than the server's row cap we'd silently miss matches,
                    // which would render a misleading partial result. Skip filtering instead and
                    // surface a warning — a future change can paginate via offset if this becomes
                    // a real-world hit rather than a theoretical one.
                    if (clusterIds.length > FILTER_QUERY_MAX_ROWS) {
                        console.warn(
                            `Cluster has ${clusterIds.length} items, exceeding the ${FILTER_QUERY_MAX_ROWS}-row cap for filter queries. Filters not applied.`
                        )
                        return null
                    }

                    const idPropertyKey = clusteringLevel === 'generation' ? '$ai_generation_id' : '$ai_trace_id'
                    const idSelectExpression = `properties['${idPropertyKey}']`

                    // Constrain to cluster items via a typed event-property filter rather than a
                    // raw HogQL `where` clause: `properties.$ai_generation_id` doesn't parse cleanly
                    // as a column reference because of the leading `$`, which would 500 the
                    // EventsQuery. The typed filter routes through `property_to_expr` which knows
                    // how to escape it.
                    const idsFilter: AnyPropertyFilter = {
                        type: PropertyFilterType.Event,
                        key: idPropertyKey,
                        operator: PropertyOperator.Exact,
                        value: clusterIds,
                    }

                    const eventsQuery: EventsQuery = {
                        kind: NodeKind.EventsQuery,
                        // The Set accumulator below already dedupes, so we don't need DISTINCT —
                        // and `DISTINCT col` is not a valid HogQL select expression anyway (it's a
                        // query-level modifier, not a per-column prefix).
                        select: [idSelectExpression],
                        event: '$ai_generation',
                        properties: [idsFilter, ...propertyFilters],
                        after: windowStart,
                        before: windowEnd,
                        filterTestAccounts: shouldFilterTestAccounts,
                        limit: clusterIds.length + 1,
                        // Required for the query runner to populate the `product` ClickHouse
                        // tag — without it the dev-mode `UntaggedQueryError` enforcement 500s
                        // every request.
                        tags: { productKey: ProductKey.LLM_ANALYTICS, scene: LLM_ANALYTICS_CLUSTER_SCENE_TAG },
                    }

                    const response = await api.query(eventsQuery)
                    breakpoint()

                    const matched = new Set<string>()
                    for (const row of response.results || []) {
                        const id = (row as unknown[])[0]
                        if (typeof id === 'string' && id) {
                            matched.add(id)
                        }
                    }
                    return matched
                },
            },
        ],

        clusterData: [
            null as ClusterData | null,
            {
                loadClusterData: async () => {
                    const { dayStart, dayEnd } = getTimestampBoundsFromRunId(props.runId)

                    // Query all three cluster event types so a single URL works regardless of level
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
                            WHERE event IN ('$ai_trace_clusters', '$ai_generation_clusters', '$ai_evaluation_clusters')
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
                        const rawClusters: Array<Record<string, unknown>> = JSON.parse(row[3] || '[]')
                        // Normalize snake_case metrics dict to camelCase ClusterMetrics — matches
                        // clustersLogic so the detail page's cluster object has the same shape as
                        // the list page's cluster cards.
                        clustersData = rawClusters.map((raw) => {
                            const { metrics: rawMetrics, ...rest } = raw as {
                                metrics?: unknown
                            } & Record<string, unknown>
                            const parsed = parseClusterMetrics(rawMetrics)
                            return {
                                ...(rest as unknown as Cluster),
                                ...(parsed ? { metrics: parsed } : {}),
                            }
                        })
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
            (s) => [s.cluster, s.filteredItemIds],
            (cluster: Cluster | null, filteredItemIds: Set<string> | null): string[] => {
                if (!cluster) {
                    return []
                }
                const entries = Object.entries(cluster.traces)
                const filtered = filteredItemIds ? entries.filter(([id]) => filteredItemIds.has(id)) : entries
                return filtered
                    .sort(([, a], [, b]) => (a as ClusterItemInfo).rank - (b as ClusterItemInfo).rank)
                    .map(([traceId]) => traceId)
            },
        ],

        totalTraces: [(s) => [s.sortedTraceIds], (sortedTraceIds: string[]): number => sortedTraceIds.length],

        unfilteredTotalTraces: [
            (s) => [s.cluster],
            (cluster: Cluster | null): number => (cluster ? Object.keys(cluster.traces).length : 0),
        ],

        hasActiveFilters: [
            (s) => [s.propertyFilters, s.shouldFilterTestAccounts],
            (propertyFilters: AnyPropertyFilter[], shouldFilterTestAccounts: boolean): boolean =>
                (propertyFilters?.length ?? 0) > 0 || shouldFilterTestAccounts,
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
                    iconType: 'llm_clusters',
                },
                {
                    key: 'LLMAnalyticsClustersRun',
                    name: dayjs(runId.split('_')[1] || runId).isValid()
                        ? dayjs(runId.split('_')[1] || runId).format('MMM D, YYYY')
                        : 'Run',
                    path: urls.llmAnalyticsClusters(runId),
                    iconType: 'llm_clusters',
                },
                {
                    key: 'LLMAnalyticsCluster',
                    name: cluster?.title || 'Cluster',
                    iconType: 'llm_clusters',
                },
            ],
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadClusterDataSuccess: () => {
            actions.setPage(1)
            actions.loadClusterMetricsForCluster()
            actions.loadFilteredItemIds()

            void actions.addProductIntent({
                product_type: ProductKey.LLM_CLUSTERS,
                intent_context: ProductIntentContext.LLM_CLUSTER_EXPLORED,
            })
        },

        // Filter-change listeners only kick the loader; resetting the page and reloading
        // summaries waits for the loader's success path so we don't burn a round-trip on
        // summaries for items the user is about to filter out. Both `setPropertyFilters`
        // and `applyUrlState` are needed: the first covers UI clicks (where actionToUrl
        // updates the URL but doesn't re-fire applyUrlState), the second covers deep
        // links and browser back/forward where applyUrlState is the only dispatch.
        setPropertyFilters: () => actions.loadFilteredItemIds(),
        setShouldFilterTestAccounts: () => actions.loadFilteredItemIds(),
        applyUrlState: () => actions.loadFilteredItemIds(),

        loadFilteredItemIdsSuccess: () => {
            // Resetting to page 1 fans out to the setPage listener, which loads summaries
            // for the now-correct first-page IDs. Doing it here keeps a single source of
            // truth for paging-reset-and-resummarize across both initial load and filter
            // changes.
            actions.setPage(1)
        },

        loadClusterMetricsForCluster: async () => {
            const { cluster, windowStart, windowEnd, clusteringLevel } = values
            if (!cluster || !windowStart || !windowEnd) {
                return
            }

            // Evaluation clusters ship with metrics baked into the event — use them
            // directly rather than re-computing via the HogQL items query. Matches
            // clustersLogic's short-circuit.
            if (clusteringLevel === 'evaluation') {
                actions.setClusterMetrics(cluster.metrics || null)
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

    tabAwareUrlToAction(({ actions, props }) => ({
        [LLM_ANALYTICS_CLUSTER_URL_PATTERN]: ({ runId, clusterId }: { runId?: string; clusterId?: string }) => {
            const decodedRunId = runId ? decodeURIComponent(runId) : ''
            const parsedClusterId = clusterId ? parseInt(clusterId, 10) : 0

            if (decodedRunId !== props.runId || parsedClusterId !== props.clusterId) {
                // Props don't match URL, component should remount with new props
                actions.loadClusterData()
            }
        },
    })),
])
