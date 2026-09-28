import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'

import { loadAppMetricsTotals } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import {
    dataWarehouseCompletedActivityRetrieve,
    dataWarehouseDataHealthIssuesRetrieve,
    dataWarehouseJobStatsRetrieve,
    dataWarehouseTotalRowsStatsRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    DataHealthIssueApi,
    DataHealthIssuesResponseApi,
    PipelineActivityResponseApi,
    PipelineActivityRowApi,
    PipelineJobStatsResponseApi,
    PipelineRowsStatsResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'
import { externalDataDestinationsList } from 'products/warehouse_sources/frontend/generated/api'
import type { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

/** Windows `job_stats` accepts. Anything else is a 400. */
export type PipelineStatsWindow = 1 | 7 | 30

/**
 * `data_health_issues` and `completed_activity` both answer for the whole warehouse, which
 * includes materialized views and batch exports. This scene is about imports and the
 * destinations they write to, so those are filtered out here rather than shown as pipelines
 * the reader cannot act on from this page.
 */
const SYNC_ISSUE_TYPES = ['external_data_sync', 'source', 'destination']

/** `app_source` the import pipeline emits its metrics under. */
const WAREHOUSE_APP_SOURCE = 'warehouse_source_sync'

/**
 * The headline numbers describe work in flight, so they go stale while the page sits open.
 * Long enough not to hammer ClickHouse and Postgres from an idle tab.
 */
const STATS_POLL_INTERVAL_MS = 30_000
const MATERIALIZED_VIEW_ACTIVITY_TYPE = 'Materialized view'

/** Most severe first, so the worst pipeline is the one a reader sees. */
const ISSUE_SEVERITY: Record<string, number> = {
    failed: 0,
    billing_limit: 1,
    degraded: 2,
    disabled: 3,
}

export interface pipelineOverviewSceneLogicValues {
    currentTeamId: number | null // teamLogic
    currentTeam: Record<string, any> | null // teamLogic
    window: PipelineStatsWindow
    jobStats: PipelineJobStatsResponseApi | null
    jobStatsLoading: boolean
    rowsStats: PipelineRowsStatsResponseApi | null
    rowsStatsLoading: boolean
    healthIssues: DataHealthIssuesResponseApi | null
    healthIssuesLoading: boolean
    recentFailures: PipelineActivityResponseApi | null
    recentFailuresLoading: boolean
    breadcrumbs: Breadcrumb[]
    issuesBySeverity: DataHealthIssueApi[]
    failingSyncCount: number
    failedRuns: PipelineActivityRowApi[]
    destinations: ExternalDataDestinationApi[] | null
    destinationsLoading: boolean
    destinationRowTotals: Record<string, { total: number }> | null
    destinationRowTotalsLoading: boolean
    rowsByDestination: { id: string; name: string; type: string; rows: number }[]
    hasIssues: boolean
    loadingFirstTime: boolean
}

export interface pipelineOverviewSceneLogicActions {
    setWindow: (window: PipelineStatsWindow) => { window: PipelineStatsWindow }
    loadJobStats: () => any
    loadRowsStats: () => any
    loadHealthIssues: () => any
    loadRecentFailures: () => any
    loadDestinations: () => any
    loadDestinationRowTotals: () => any
    refresh: () => { value: true }
    loadEverything: () => { value: true }
    pollStats: () => { value: true }
}

export type pipelineOverviewSceneLogicType = MakeLogicType<
    pipelineOverviewSceneLogicValues,
    pipelineOverviewSceneLogicActions
>

export const pipelineOverviewSceneLogic = kea<pipelineOverviewSceneLogicType>([
    path([
        'products',
        'warehouse_sources',
        'frontend',
        'scenes',
        'PipelineOverviewScene',
        'pipelineOverviewSceneLogic',
    ]),
    connect(() => ({ values: [teamLogic, ['currentTeamId', 'currentTeam']] })),
    actions({
        setWindow: (window: PipelineStatsWindow) => ({ window }),
        refresh: true,
        loadEverything: true,
        pollStats: true,
    }),
    reducers({
        window: [
            7 as PipelineStatsWindow,
            { setWindow: (_: unknown, { window }: { window: PipelineStatsWindow }) => window },
        ],
    }),
    loaders(({ values }: any) => ({
        // `null` rather than an empty shape throughout: the scene has to tell "not answered yet"
        // from "answered, and there is nothing", or it renders an empty state over a pending load.
        jobStats: [
            null as PipelineJobStatsResponseApi | null,
            {
                loadJobStats: async () =>
                    await dataWarehouseJobStatsRetrieve(String(values.currentTeamId), { days: values.window }),
            },
        ],
        rowsStats: [
            null as PipelineRowsStatsResponseApi | null,
            { loadRowsStats: async () => await dataWarehouseTotalRowsStatsRetrieve(String(values.currentTeamId)) },
        ],
        healthIssues: [
            null as DataHealthIssuesResponseApi | null,
            { loadHealthIssues: async () => await dataWarehouseDataHealthIssuesRetrieve(String(values.currentTeamId)) },
        ],
        destinations: [
            null as ExternalDataDestinationApi[] | null,
            {
                loadDestinations: async () =>
                    (await externalDataDestinationsList(String(values.currentTeamId))).results ?? [],
            },
        ],
        /**
         * Rows written per destination, across every source. The pipeline emits `rows_synced`
         * three ways per run — keyed by schema, by schema and destination, and by destination
         * alone — so a raw `instance_id` breakdown mixes all three. The destination-keyed rows
         * are picked out in `rowsByDestination` by matching against the team's real destinations.
         */
        destinationRowTotals: [
            null as Record<string, { total: number }> | null,
            {
                loadDestinationRowTotals: async () =>
                    await loadAppMetricsTotals(
                        {
                            appSource: WAREHOUSE_APP_SOURCE,
                            metricName: 'rows_synced',
                            breakdownBy: ['instance_id'],
                            // Both bounds are interpolated into `toDateTime(...)`, so they have to
                            // be absolute timestamps. The upper bound sits an hour ahead because
                            // the comparison is exclusive and rows land continuously.
                            dateFrom: dayjs().subtract(values.window, 'day').toISOString(),
                            dateTo: dayjs().add(1, 'hour').toISOString(),
                            // Bounded so a team with many schemas cannot silently truncate the
                            // destination rows out of the result.
                            limit: 500,
                        },
                        values.currentTeam?.timezone ?? 'UTC'
                    ),
            },
        ],
        recentFailures: [
            null as PipelineActivityResponseApi | null,
            {
                loadRecentFailures: async () =>
                    await dataWarehouseCompletedActivityRetrieve(String(values.currentTeamId), {
                        outcome: 'failed',
                        // Over-fetch: the endpoint has no sync-only filter, so view runs are
                        // dropped client-side and a page of them would otherwise show nothing.
                        limit: 50,
                    }),
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [{ key: 'PipelineOverview', name: 'ETL', iconType: 'data_pipeline' }],
        ],
        issuesBySeverity: [
            (s: any) => [s.healthIssues],
            (healthIssues: DataHealthIssuesResponseApi | null): DataHealthIssueApi[] =>
                (healthIssues?.results ?? [])
                    .filter((issue) => SYNC_ISSUE_TYPES.includes(issue.type))
                    .sort((a, b) => (ISSUE_SEVERITY[a.status] ?? 99) - (ISSUE_SEVERITY[b.status] ?? 99)),
        ],
        failingSyncCount: [
            (s: any) => [s.healthIssues],
            (healthIssues: DataHealthIssuesResponseApi | null): number =>
                (healthIssues?.results ?? []).filter((issue) => issue.type === 'external_data_sync').length,
        ],
        /** Rows written per destination over the window, biggest first. */
        rowsByDestination: [
            (s: any) => [s.destinationRowTotals, s.destinations],
            (
                totals: Record<string, { total: number }> | null,
                destinations: ExternalDataDestinationApi[] | null
            ): { id: string; name: string; type: string; rows: number }[] => {
                if (!totals || !destinations) {
                    return []
                }
                return destinations
                    .map((destination) => ({
                        id: destination.id,
                        name: destination.name,
                        type: destination.type,
                        rows: totals[destination.id]?.total ?? 0,
                    }))
                    .filter((row) => row.rows > 0)
                    .sort((a, b) => b.rows - a.rows)
            },
        ],
        /** Whether anything is wrong. The health section is hidden when nothing is. */
        hasIssues: [(s: any) => [s.issuesBySeverity], (issues: DataHealthIssueApi[]): boolean => issues.length > 0],
        failedRuns: [
            (s: any) => [s.recentFailures],
            (recentFailures: PipelineActivityResponseApi | null): PipelineActivityRowApi[] =>
                (recentFailures?.results ?? []).filter((run) => run.type !== MATERIALIZED_VIEW_ACTIVITY_TYPE),
        ],
        // A first load shows skeletons; a refresh keeps the numbers on screen and dims them, so
        // polling does not make the page flash.
        loadingFirstTime: [
            (s: any) => [s.jobStats, s.jobStatsLoading, s.healthIssues, s.healthIssuesLoading],
            (
                jobStats: unknown,
                jobStatsLoading: boolean,
                healthIssues: unknown,
                healthIssuesLoading: boolean
            ): boolean => (jobStatsLoading && jobStats === null) || (healthIssuesLoading && healthIssues === null),
        ],
    }),
    listeners(({ actions }: any) => ({
        // Only the run counts are windowed. Rows are reported per billing period and health is
        // current state, so neither changes with the window.
        setWindow: () => {
            actions.loadJobStats()
            actions.loadDestinationRowTotals()
        },
        refresh: () => actions.loadEverything(),
        loadEverything: () => {
            actions.loadJobStats()
            actions.loadRowsStats()
            actions.loadHealthIssues()
            actions.loadRecentFailures()
            actions.loadDestinations()
            actions.loadDestinationRowTotals()
        },
        // Only the headline numbers poll. Reloading the tables under someone mid-read moves rows
        // they are looking at, and they change far less often than the counts do.
        pollStats: () => {
            actions.loadJobStats()
            actions.loadHealthIssues()
        },
    })),
    afterMount(({ actions, cache }: any) => {
        actions.loadEverything()
        cache.pollInterval = window.setInterval(() => actions.pollStats(), STATS_POLL_INTERVAL_MS)
    }),
    beforeUnmount(({ cache }: any) => {
        // Without this the timer outlives the scene and keeps querying after navigation.
        if (cache.pollInterval) {
            window.clearInterval(cache.pollInterval)
            cache.pollInterval = undefined
        }
    }),
])
