import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { urls } from 'scenes/urls'

import { EventsQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { AnyPropertyFilter, Breadcrumb, PropertyFilterType, PropertyOperator } from '~/types'

import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import { loadClusterMetrics } from './clusterMetricsLoader'
import type { clustersLogicType } from './clustersLogicType'
import {
    FILTER_QUERY_MAX_ROWS,
    LLM_ANALYTICS_CLUSTERS_SCENE_TAG,
    MAX_CLUSTERING_RUNS,
    NOISE_CLUSTER_ID,
    OUTLIER_COLOR,
    SAFE_ID_RE,
} from './constants'
import {
    EvaluationItemAttributes,
    EvaluationVerdict,
    loadEvaluationItemAttributes,
    loadTraceSummaries,
} from './traceSummaryLoader'
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
    parseClusterMetrics,
} from './types'

/** Map a clustering level to the ClickHouse event name its runs are emitted under. */
function eventNameForLevel(
    level: ClusteringLevel
): '$ai_trace_clusters' | '$ai_generation_clusters' | '$ai_evaluation_clusters' {
    if (level === 'generation') {
        return '$ai_generation_clusters'
    }
    if (level === 'evaluation') {
        return '$ai_evaluation_clusters'
    }
    return '$ai_trace_clusters'
}

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

export interface ClustersLogicProps {
    tabId?: string
}

export const clustersLogic = kea<clustersLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'clusters', 'clustersLogic']),
    props({} as ClustersLogicProps),
    key((props) => props.tabId ?? 'default'),

    connect((props: ClustersLogicProps) => ({
        values: [llmAnalyticsSharedLogic({ tabId: props.tabId }), ['propertyFilters', 'shouldFilterTestAccounts']],
        actions: [
            llmAnalyticsSharedLogic({ tabId: props.tabId }),
            ['setPropertyFilters', 'setShouldFilterTestAccounts', 'applyUrlState'],
        ],
    })),

    actions({
        setClusteringLevel: (level: ClusteringLevel) => ({ level }),
        // Declared explicitly so kea-typegen emits a no-arg signature for the loader
        // action below — without this, the `(_, breakpoint)` loader signature forces
        // every call site to pass a placeholder argument.
        loadPropertyFilteredItemIds: true,
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
        setEvaluationItemAttributes: (attributes: Record<string, EvaluationItemAttributes>) => ({ attributes }),
        loadEvaluationAttributesForRun: (run: ClusteringRun) => ({ run }),
        setEvalEvaluatorNamesFilter: (names: string[]) => ({ names }),
        setEvalVerdictsFilter: (verdicts: EvaluationVerdict[]) => ({ verdicts }),
        clearEvalFilters: true,
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
        evaluationItemAttributes: [
            {} as Record<string, EvaluationItemAttributes>,
            {
                setEvaluationItemAttributes: (_, { attributes }) => attributes,
                // Wipe on level switches so a stale lookup doesn't leak across levels.
                // Wipe on loadClusteringRun (rather than setSelectedRunId) so a run switch
                // doesn't briefly show the previous run's counts in the filter bar before
                // the new attributes load. Using setSelectedRunId would also wipe on the
                // nav-back URL handler that fires setSelectedRunId(null) without reloading,
                // which would leave the filter bar empty and un-refillable.
                setClusteringLevel: () => ({}),
                loadClusteringRun: () => ({}),
            },
        ],
        evalFilterEvaluatorNames: [
            [] as string[],
            {
                setEvalEvaluatorNamesFilter: (_, { names }) => names,
                clearEvalFilters: () => [],
                setClusteringLevel: () => [],
                setSelectedRunId: () => [],
            },
        ],
        evalFilterVerdicts: [
            [] as EvaluationVerdict[],
            {
                setEvalVerdictsFilter: (_, { verdicts }) => verdicts,
                clearEvalFilters: () => [],
                setClusteringLevel: () => [],
                setSelectedRunId: () => [],
            },
        ],
    }),

    loaders(({ values }) => ({
        // Subset of the current run's item IDs that match the user's active property
        // filters (cohorts, person properties, group properties, etc.). Null when no
        // filters are active or filtering can't be applied — selectors treat null as
        // "show everything" so unfiltered runs skip the round-trip.
        propertyFilteredItemIds: [
            null as Set<string> | null,
            {
                loadPropertyFilteredItemIds: async (_, breakpoint) => {
                    // Debounce overlapping filter changes (quick toggles or successive
                    // cohort selections) into a single EventsQuery round-trip.
                    await breakpoint(150)

                    const propertyFilters: AnyPropertyFilter[] = values.propertyFilters || []
                    const shouldFilterTestAccounts: boolean = values.shouldFilterTestAccounts
                    const run = values.currentRun

                    if (!run) {
                        return null
                    }

                    if (propertyFilters.length === 0 && !shouldFilterTestAccounts) {
                        return null
                    }

                    // Eval clusters key on $ai_evaluation event UUIDs which don't carry
                    // the person/cohort fields these filters target. The eval-specific
                    // filter bar handles those.
                    const level = run.level || values.clusteringLevel
                    if (level === 'evaluation') {
                        return null
                    }

                    const allIds: string[] = []
                    for (const cluster of run.clusters) {
                        for (const id of Object.keys(cluster.traces)) {
                            if (SAFE_ID_RE.test(id)) {
                                allIds.push(id)
                            }
                        }
                    }
                    if (allIds.length === 0) {
                        return new Set<string>()
                    }

                    if (allIds.length > FILTER_QUERY_MAX_ROWS) {
                        console.warn(
                            `Run has ${allIds.length} items, exceeding the ${FILTER_QUERY_MAX_ROWS}-row cap for filter queries. Filters not applied.`
                        )
                        return null
                    }

                    const idPropertyKey = level === 'generation' ? '$ai_generation_id' : '$ai_trace_id'
                    const idSelectExpression = `properties['${idPropertyKey}']`

                    // Restrict the events to the cluster's items via a typed event-property
                    // filter rather than a raw HogQL `where` clause: `properties.$ai_generation_id`
                    // doesn't parse cleanly as a column reference because of the leading `$`,
                    // which would 500 the EventsQuery. The typed filter goes through
                    // `property_to_expr` which knows how to escape it.
                    const idsFilter: AnyPropertyFilter = {
                        type: PropertyFilterType.Event,
                        key: idPropertyKey,
                        operator: PropertyOperator.Exact,
                        value: allIds,
                    }

                    const eventsQuery: EventsQuery = {
                        kind: NodeKind.EventsQuery,
                        select: [idSelectExpression],
                        event: '$ai_generation',
                        properties: [idsFilter, ...propertyFilters],
                        after: run.windowStart,
                        before: run.windowEnd,
                        filterTestAccounts: shouldFilterTestAccounts,
                        limit: allIds.length + 1,
                        // Required for the query runner to populate the `product` ClickHouse
                        // tag — without it the dev-mode `UntaggedQueryError` enforcement 500s
                        // every request.
                        tags: { productKey: ProductKey.LLM_ANALYTICS, scene: LLM_ANALYTICS_CLUSTERS_SCENE_TAG },
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

        clusteringRuns: [
            [] as ClusteringRunOption[],
            {
                loadClusteringRuns: async () => {
                    const eventName = eventNameForLevel(values.clusteringLevel)

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
                    const eventName = eventNameForLevel(level)

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
                        const rawClusters: Array<Record<string, unknown>> = JSON.parse((row[4] as string) || '[]')
                        // The backend emits per-cluster aggregate metrics with snake_case
                        // field names (dataclasses.asdict on ClusterAggregateMetrics);
                        // normalize to the frontend's camelCase ClusterMetrics shape here
                        // so consumers don't need to know both conventions.
                        clustersData = rawClusters.map((raw) => {
                            const { metrics: rawMetrics, ...rest } = raw as { metrics?: unknown } & Record<
                                string,
                                unknown
                            >
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
                    iconType: 'llm_clusters',
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

        // True while the loaded run still belongs to the level the user is currently
        // looking at. Goes false the moment the user switches levels, until the new
        // level's first run resolves — gates downstream selectors so we don't paint
        // trace cards on the Generations tab during the load. kea-loaders preserves
        // the previous loader value, so without this check `currentRun` would still
        // be the trace-level run for a few hundred milliseconds.
        //
        // Runs emitted before the `clustering_level` event property existed are inferred
        // as 'trace' by `loadClusteringRun` via `getLevelFromRunId`, so the same default
        // applies here for any path that bypasses the loader (e.g. test fixtures).
        currentRunMatchesLevel: [
            (s) => [s.currentRun, s.clusteringLevel],
            (currentRun: ClusteringRun | null, level: ClusteringLevel): boolean =>
                !!currentRun && (currentRun.level || 'trace') === level,
        ],

        sortedClusters: [
            (s) => [s.currentRun, s.currentRunMatchesLevel],
            (currentRun: ClusteringRun | null, matches: boolean): Cluster[] => {
                if (!matches || !currentRun?.clusters) {
                    return []
                }
                return [...currentRun.clusters].sort((a, b) => b.size - a.size)
            },
        ],

        evalFiltersActive: [
            (s) => [s.clusteringLevel, s.evalFilterEvaluatorNames, s.evalFilterVerdicts],
            (level: ClusteringLevel, names: string[], verdicts: EvaluationVerdict[]): boolean =>
                level === 'evaluation' && (names.length > 0 || verdicts.length > 0),
        ],

        availableEvaluatorNames: [
            (s) => [s.evaluationItemAttributes],
            (attrs: Record<string, EvaluationItemAttributes>): { name: string; count: number }[] => {
                const counts = new Map<string, number>()
                for (const a of Object.values(attrs)) {
                    counts.set(a.evaluatorName, (counts.get(a.evaluatorName) || 0) + 1)
                }
                return Array.from(counts.entries())
                    .map(([name, count]) => ({ name, count }))
                    .sort((a, b) => b.count - a.count)
            },
        ],

        availableVerdictCounts: [
            (s) => [s.evaluationItemAttributes],
            (attrs: Record<string, EvaluationItemAttributes>): Record<EvaluationVerdict, number> => {
                const counts: Record<EvaluationVerdict, number> = { pass: 0, fail: 0, 'n/a': 0, unknown: 0 }
                for (const a of Object.values(attrs)) {
                    counts[a.verdict] = (counts[a.verdict] || 0) + 1
                }
                return counts
            },
        ],

        // Single predicate keeps the filtering rule in one place; consumers (scatter, cards,
        // distribution bar) all derive from this so any divergence is impossible.
        evalFilterPredicate: [
            (s) => [s.clusteringLevel, s.evaluationItemAttributes, s.evalFilterEvaluatorNames, s.evalFilterVerdicts],
            (
                level: ClusteringLevel,
                attrs: Record<string, EvaluationItemAttributes>,
                names: string[],
                verdicts: EvaluationVerdict[]
            ): ((evalId: string) => boolean) => {
                if (level !== 'evaluation' || (names.length === 0 && verdicts.length === 0)) {
                    return () => true
                }
                // Attributes haven't loaded yet — show everything to avoid an empty flash.
                if (Object.keys(attrs).length === 0) {
                    return () => true
                }
                const nameSet = new Set(names)
                const verdictSet = new Set(verdicts)
                return (evalId: string) => {
                    const a = attrs[evalId]
                    if (!a) {
                        return false
                    }
                    if (nameSet.size > 0 && !nameSet.has(a.evaluatorName)) {
                        return false
                    }
                    if (verdictSet.size > 0 && !verdictSet.has(a.verdict)) {
                        return false
                    }
                    return true
                }
            },
        ],

        propertyFiltersActive: [
            (s) => [s.propertyFilters, s.shouldFilterTestAccounts],
            (propertyFilters: AnyPropertyFilter[], shouldFilterTestAccounts: boolean): boolean =>
                (propertyFilters?.length ?? 0) > 0 || shouldFilterTestAccounts,
        ],

        anyFiltersActive: [
            (s) => [s.evalFiltersActive, s.propertyFiltersActive],
            (evalActive: boolean, propertyActive: boolean): boolean => evalActive || propertyActive,
        ],

        // Single predicate combines the eval-specific filter (for evaluation-level clusters)
        // with the cohort/property filter (for trace and generation levels). Cluster cards,
        // scatter plot, and distribution bar all derive from this so the views can never
        // diverge on which items count as "in" the filtered set.
        clusterMembershipPredicate: [
            (s) => [s.evalFilterPredicate, s.propertyFilteredItemIds],
            (
                evalPredicate: (id: string) => boolean,
                propertyFilteredItemIds: Set<string> | null
            ): ((id: string) => boolean) => {
                return (id: string) => {
                    if (!evalPredicate(id)) {
                        return false
                    }
                    if (propertyFilteredItemIds && !propertyFilteredItemIds.has(id)) {
                        return false
                    }
                    return true
                }
            },
        ],

        filteredSortedClusters: [
            (s) => [s.sortedClusters, s.clusterMembershipPredicate, s.anyFiltersActive],
            (clusters: Cluster[], predicate: (id: string) => boolean, active: boolean): Cluster[] => {
                if (!active) {
                    return clusters
                }
                return clusters
                    .map((cluster) => {
                        const filteredTraces = Object.fromEntries(
                            Object.entries(cluster.traces).filter(([id]) => predicate(id))
                        )
                        return {
                            ...cluster,
                            traces: filteredTraces,
                            size: Object.keys(filteredTraces).length,
                        }
                    })
                    .filter((c) => c.size > 0)
            },
        ],

        filteredItemCount: [
            (s) => [s.filteredSortedClusters],
            (clusters: Cluster[]): number => clusters.reduce((sum, c) => sum + c.size, 0),
        ],

        totalItemCount: [
            (s) => [s.sortedClusters],
            (clusters: Cluster[]): number => clusters.reduce((sum, c) => sum + c.size, 0),
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
            (s) => [s.filteredSortedClusters],
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

            const level = run.level || values.clusteringLevel

            // Evaluation clusters ship with metrics baked into the event by the backend
            // (ClusterAggregateMetrics → dataclasses.asdict → $ai_clusters[i].metrics).
            // Use those directly instead of a second HogQL round-trip that tries to
            // recompute from the events table — the backend already joined eval →
            // generation and computed both operational + eval-specific metrics.
            if (level === 'evaluation') {
                const baked: Record<number, ClusterMetrics> = {}
                for (const cluster of run.clusters) {
                    if (cluster.metrics) {
                        baked[cluster.cluster_id] = cluster.metrics
                    }
                }
                actions.setClusterMetrics(baked)
                return
            }

            actions.setClusterMetricsLoading(true)

            try {
                const metrics = await loadClusterMetrics(run.clusters, run.windowStart, run.windowEnd, level)
                actions.setClusterMetrics(metrics)
            } catch (error) {
                console.error('Failed to load cluster metrics:', error)
            } finally {
                actions.setClusterMetricsLoading(false)
            }
        },

        loadEvaluationAttributesForRun: async ({ run }) => {
            if (run.level !== 'evaluation') {
                return
            }
            const allItemIds: string[] = []
            for (const cluster of run.clusters) {
                allItemIds.push(...Object.keys(cluster.traces))
            }
            if (allItemIds.length === 0) {
                return
            }
            try {
                const attrs = await loadEvaluationItemAttributes(allItemIds, run.windowStart, run.windowEnd)
                // Guard against a slow response for a prior run overwriting attributes
                // after the user has switched to a different run. If currentRun has
                // advanced past the one we were loading for, drop the response on the
                // floor — the new run's load will have already fired.
                if (values.currentRun?.runId && values.currentRun.runId !== run.runId) {
                    return
                }
                actions.setEvaluationItemAttributes(attrs)
            } catch (error) {
                console.error('Failed to load evaluation item attributes:', error)
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
                if (currentRun.clusters.length === 0) {
                    posthog.capture('llma clusters empty state shown', {
                        reason: 'no_clusters_in_run',
                        clustering_level: currentRun.level || values.clusteringLevel,
                        run_id: currentRun.runId,
                    })
                }
                actions.loadTraceSummariesForRun(currentRun)
                // Load cluster metrics for displaying averages in cluster cards
                actions.loadClusterMetricsForRun(currentRun)
                // For evaluation runs, also load the per-item (evaluator name, verdict) lookup
                // so the post-hoc filter bar can drive scatter + cluster card filtering.
                actions.loadEvaluationAttributesForRun(currentRun)
                // Re-run the property filter against the new run's items. The shared filter
                // state is preserved across run switches, so a previously filtered view
                // should immediately narrow the new run's clusters.
                actions.loadPropertyFilteredItemIds()
            }
        },

        // Property filter state lives in the shared logic; mirror its updates into a
        // fresh EventsQuery scoped to the current run's items. Both listener entries are
        // needed because the dispatch path differs by trigger:
        //   - UI clicks dispatch `setPropertyFilters` / `setShouldFilterTestAccounts`
        //     directly. The shared logic's `actionToUrl` then echoes the new state into
        //     the URL, but `applySearchParams` short-circuits because URL and state
        //     already agree, so `applyUrlState` is *not* fired in this path.
        //   - Deep links and browser back/forward fire the URL handler first; that
        //     path detects the divergence and dispatches `applyUrlState` (not
        //     `setPropertyFilters`) to sync state.
        // The 150ms breakpoint debounce inside the loader collapses any stray double
        // dispatches into a single round-trip.
        setPropertyFilters: () => actions.loadPropertyFilteredItemIds(),
        setShouldFilterTestAccounts: () => actions.loadPropertyFilteredItemIds(),
        applyUrlState: () => actions.loadPropertyFilteredItemIds(),

        loadClusteringRunFailure: () => {
            lemonToast.error('Failed to load clustering run')
        },

        loadClusteringRunsSuccess: ({ clusteringRuns }) => {
            if (clusteringRuns.length === 0) {
                posthog.capture('llma clusters empty state shown', {
                    reason: 'no_clustering_runs',
                    clustering_level: values.clusteringLevel,
                })
            }
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

    tabAwareUrlToAction(({ actions, values }) => ({
        '/llm-analytics/clusters': () => {
            if (values.selectedRunId !== null) {
                actions.setSelectedRunId(null)
            }
        },
        '/llm-analytics/clusters/:runId': ({ runId }: { runId?: string }) => {
            // Decode the URL-encoded runId. Only re-dispatch when the runId actually
            // changed — a filter change updates the URL's search params (?filters=…)
            // but keeps the same path, and re-firing `setSelectedRunId` here would
            // chain into `loadClusteringRun` → `loadClusteringRunSuccess` →
            // `loadPropertyFilteredItemIds`, which races with the loader the
            // `setPropertyFilters` listener already kicked off and silently aborts it.
            const newRunId = runId ? decodeURIComponent(runId) : null
            if (newRunId !== values.selectedRunId) {
                actions.setSelectedRunId(newRunId)
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => ({
        setSelectedRunId: () => {
            // Preserve any search params already on the URL — `setPropertyFilters` (in the
            // shared logic) writes `?filters=...` and `?filter_test_accounts=...`, and the
            // route handler immediately echoes that back through `setSelectedRunId(currentRunId)`.
            // Returning a bare path here would strip those params, the URL handler would re-fire
            // with an empty `filters` set, and the property filter would be reset on every change.
            const pathname = values.selectedRunId
                ? urls.llmAnalyticsClusters(values.selectedRunId)
                : urls.llmAnalyticsClusters()
            return [pathname, router.values.searchParams]
        },
    })),
])
