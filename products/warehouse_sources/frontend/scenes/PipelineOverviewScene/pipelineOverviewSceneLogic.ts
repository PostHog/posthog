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

import { loadAppMetricsTimeSeries } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import {
    dataWarehouseCompletedActivityRetrieve,
    dataWarehouseRunningActivityRetrieve,
    dataWarehouseDataHealthIssuesRetrieve,
    dataWarehouseJobStatsRetrieve,
    dataWarehouseTotalRowsStatsRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    DataHealthIssueApi,
    DataHealthIssuesResponseApi,
    PipelineActivityRowApi,
    PipelineJobStatsResponseApi,
    PipelineRowsStatsResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'
import {
    externalDataDestinationsList,
    externalDataSourcesList,
} from 'products/warehouse_sources/frontend/generated/api'
import type {
    ExternalDataDestinationApi,
    ExternalDataSourceSerializersApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

/** Windows `job_stats` accepts. Anything else is a 400. */
export type PipelineStatsWindow = 1 | 7 | 30

/**
 * `data_health_issues` and `completed_activity` both answer for the whole warehouse. Only these
 * two types are imports. The endpoint's `destination` type is a batch export or a CDP
 * destination, not a warehouse destination, and `materialized_view` and `transformation` belong
 * to other products. A warehouse destination that fails does surface here, as an
 * `external_data_sync` issue whose error carries the destination's name.
 */
const SYNC_ISSUE_TYPES = ['external_data_sync', 'source']

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
    recentRuns: { finished: PipelineActivityRowApi[]; running: PipelineActivityRowApi[] } | null
    recentRunsLoading: boolean
    breadcrumbs: Breadcrumb[]
    issuesBySeverity: DataHealthIssueApi[]
    failingSyncCount: number
    recentRunRows: PipelineActivityRowApi[]
    destinations: ExternalDataDestinationApi[] | null
    destinationsLoading: boolean
    sources: ExternalDataSourceSerializersApi[] | null
    sourcesLoading: boolean
    syncingTableCount: number
    lastUpdatedAt: string | null
    destinationRowSeries: { labels: string[]; series: { id: string; values: number[] }[]; total: number[] } | null
    destinationRowSeriesLoading: boolean
    rowsByDestination: { key: string; label: string; data: number[]; type: 'area'; fill: { opacity: number } }[]
    hasIssues: boolean
    loadingFirstTime: boolean
}

export interface pipelineOverviewSceneLogicActions {
    setWindow: (window: PipelineStatsWindow) => { window: PipelineStatsWindow }
    loadJobStats: () => any
    loadRowsStats: () => any
    loadHealthIssues: () => any
    loadRecentRuns: () => any
    loadDestinations: () => any
    loadSources: () => any
    loadDestinationRowSeries: () => any
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
        // Stamped when the polled numbers land, so the page can show that they are live rather
        // than leaving a reader to guess whether a static count is stale.
        lastUpdatedAt: [
            null as string | null,
            {
                loadJobStatsSuccess: () => new Date().toISOString(),
            },
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
        sources: [
            null as ExternalDataSourceSerializersApi[] | null,
            {
                loadSources: async () => {
                    const sources: ExternalDataSourceSerializersApi[] = []
                    let offset = 0
                    let hasNextPage = true

                    while (hasNextPage) {
                        const page = await externalDataSourcesList(String(values.currentTeamId), { limit: 100, offset })
                        sources.push(...(page.results ?? []))
                        offset += page.results?.length ?? 0
                        hasNextPage = Boolean(page.next) && (page.results?.length ?? 0) > 0
                    }

                    return sources
                },
            },
        ],
        destinationRowSeries: [
            null as { labels: string[]; series: { id: string; values: number[] }[]; total: number[] } | null,
            {
                loadDestinationRowSeries: async () => {
                    const destinations = values.destinations ?? []
                    if (destinations.length === 0) {
                        return { labels: [], series: [], total: [] }
                    }
                    const interval = values.window === 1 ? ('hour' as const) : ('day' as const)
                    // Both bounds are interpolated into `toDateTime(...)`, so they have to be
                    // absolute. The upper bound sits an hour ahead because the comparison is
                    // exclusive and rows land continuously.
                    const dateFrom = dayjs().subtract(values.window, 'day').toISOString()
                    const dateTo = dayjs().add(1, 'hour').toISOString()
                    // One request per destination, filtered on `instanceId`, rather than one
                    // breakdown over every instance. The breakdown is capped at 100 rows, and a
                    // team with thousands of tables pushes every destination out of that cap.
                    const common = {
                        appSource: WAREHOUSE_APP_SOURCE,
                        metricName: 'rows_synced',
                        // The time-series query interpolates `breakdownBy` with no fallback, so
                        // omitting it emits `undefined AS breakdown` and the query fails to
                        // resolve. Each request is already pinned to one series by its filter.
                        breakdownBy: 'instance_id' as const,
                        interval,
                        dateFrom,
                        dateTo,
                    }
                    const timezone = values.currentTeam?.timezone ?? 'UTC'
                    const schemaIds = (values.sources ?? []).flatMap((source: ExternalDataSourceSerializersApi) =>
                        (source.schemas ?? []).map((schema) => String(schema.id))
                    )
                    const [answers, total] = await Promise.all([
                        Promise.all(
                            destinations.map(async (destination: ExternalDataDestinationApi) => ({
                                id: destination.id,
                                response: await loadAppMetricsTimeSeries(
                                    { ...common, instanceId: destination.id },
                                    timezone
                                ),
                            }))
                        ),
                        schemaIds.length > 0
                            ? loadAppMetricsTimeSeries(
                                  { ...common, instanceIds: schemaIds, breakdownBy: 'metric_name' },
                                  timezone
                              )
                            : Promise.resolve({ labels: [], interval, timezone, series: [] }),
                    ])
                    return {
                        labels:
                            answers.find((a) => a.response.labels.length > 0)?.response.labels ?? total.labels ?? [],
                        series: answers.map((a) => ({
                            id: a.id,
                            // Without a breakdown the response carries a single unnamed series.
                            values: a.response.series[0]?.values ?? [],
                        })),
                        total: total.series[0]?.values ?? [],
                    }
                },
            },
        ],
        recentRuns: [
            null as { finished: PipelineActivityRowApi[]; running: PipelineActivityRowApi[] } | null,
            {
                loadRecentRuns: async () => {
                    const [finished, running] = await Promise.all([
                        dataWarehouseCompletedActivityRetrieve(String(values.currentTeamId), {
                            // Everything that finished, not just the failures.
                            outcome: 'all',
                            // Imports only. Without this a team with many failing views fills
                            // every page with them and this list renders empty.
                            kind: 'import',
                            // The window control sits in this section's own header. Without this
                            // the endpoint falls back to its own 30-day default.
                            cutoff_days: values.window,
                            limit: 50,
                        }),
                        // In-flight runs come from a separate endpoint, so a sync that started
                        // seconds ago appears at the top rather than waiting until it finishes.
                        dataWarehouseRunningActivityRetrieve(String(values.currentTeamId), {
                            kind: 'import',
                            cutoff_days: values.window,
                            limit: 50,
                        }),
                    ])
                    return {
                        finished: (finished.results ?? []) as PipelineActivityRowApi[],
                        running: (running.results ?? []) as PipelineActivityRowApi[],
                    }
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [{ key: 'PipelineOverview', name: 'ELT', iconType: 'data_pipeline' }],
        ],
        issuesBySeverity: [
            (s: any) => [s.healthIssues],
            (healthIssues: DataHealthIssuesResponseApi | null): DataHealthIssueApi[] =>
                (healthIssues?.results ?? [])
                    .filter((issue) => SYNC_ISSUE_TYPES.includes(issue.type))
                    // A webhook table is pushed to on the vendor's schedule, never pulled on
                    // ours, so it has no last sync and cannot have "stopped".
                    .filter((issue) => issue.sync_type !== 'webhook')
                    .sort((a, b) => (ISSUE_SEVERITY[a.status] ?? 99) - (ISSUE_SEVERITY[b.status] ?? 99)),
        ],
        failingSyncCount: [
            (s: any) => [s.healthIssues],
            (healthIssues: DataHealthIssuesResponseApi | null): number =>
                (healthIssues?.results ?? []).filter((issue) => issue.type === 'external_data_sync').length,
        ],
        /**
         * One chart series per destination, biggest first so the legend matches the stack.
         *
         * The PostHog warehouse series is derived rather than read directly. Runs from before
         * destination attribution landed report no destination at all, and a run that resolves
         * to the warehouse alone still reports none. Those rows only exist keyed by schema, in
         * the total, so the warehouse gets whatever the other destinations did not take.
         */
        rowsByDestination: [
            (s: any) => [s.destinationRowSeries, s.destinations],
            (
                answer: { labels: string[]; series: { id: string; values: number[] }[]; total: number[] } | null,
                destinations: ExternalDataDestinationApi[] | null
            ): {
                key: string
                label: string
                data: number[]
                type: 'area'
                fill: { opacity: number }
            }[] => {
                if (!answer || !destinations) {
                    return []
                }
                const byId = new Map(destinations.map((d) => [d.id, d]))
                const warehouse = destinations.find((d) => d.type === 'PostHogWarehouse')
                const elsewhere = answer.series.filter((s) => s.id !== warehouse?.id)

                const derivedWarehouse = answer.total.map((rows, i) =>
                    Math.max(0, rows - elsewhere.reduce((sum, s) => sum + (s.values[i] ?? 0), 0))
                )

                const series = elsewhere.map((s) => ({ id: s.id, values: s.values }))
                if (warehouse) {
                    series.push({ id: warehouse.id, values: derivedWarehouse })
                }

                return series
                    .map((s) => ({
                        key: s.id,
                        label: byId.get(s.id)?.name ?? s.id,
                        data: s.values,
                        type: 'area' as const,
                        // `fill` is what makes an area series fill; `type` alone draws a line.
                        fill: { opacity: 0.25 },
                        total: s.values.reduce((a, b) => a + b, 0),
                    }))
                    .filter((s) => s.total > 0)
                    .sort((a, b) => b.total - a.total)
                    .map(({ total: _total, ...rest }) => rest)
            },
        ],
        /**
         * Tables PostHog imports on a schedule. Counts schemas switched on rather than every
         * schema a source offers, so it matches what the pipeline actually runs.
         */
        syncingTableCount: [
            (s: any) => [s.sources],
            (sources: ExternalDataSourceSerializersApi[] | null): number =>
                (sources ?? []).reduce(
                    (total, source) =>
                        total +
                        ((source.schemas ?? []) as { should_sync?: boolean }[]).filter((s) => s.should_sync).length,
                    0
                ),
        ],
        /** Whether anything is wrong. The health section is hidden when nothing is. */
        hasIssues: [(s: any) => [s.issuesBySeverity], (issues: DataHealthIssueApi[]): boolean => issues.length > 0],
        /** Running first, then finished newest-first. Model runs are another product's. */
        recentRunRows: [
            (s: any) => [s.recentRuns],
            (
                answer: { finished: PipelineActivityRowApi[]; running: PipelineActivityRowApi[] } | null
            ): PipelineActivityRowApi[] => {
                if (!answer) {
                    return []
                }
                const isImport = (run: PipelineActivityRowApi): boolean => run.type !== MATERIALIZED_VIEW_ACTIVITY_TYPE
                const finished = answer.finished.filter(isImport)
                const finishedIds = new Set(finished.map((run) => run.id))
                return [...answer.running.filter((run) => isImport(run) && !finishedIds.has(run.id)), ...finished]
            },
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
    listeners(({ actions, values }: any) => ({
        // Health is current state and rows are reported per billing period, so neither is
        // windowed. Everything else is.
        setWindow: () => {
            actions.loadJobStats()
            actions.loadDestinationRowSeries()
            actions.loadRecentRuns()
        },
        refresh: () => actions.loadEverything(),
        // The destination and schema lists identify the two attribution key types in app_metrics.
        // Wait for both so the overall request can select schema-keyed rows exactly.
        loadDestinationsSuccess: () => {
            if (values.sources !== null) {
                actions.loadDestinationRowSeries()
            }
        },
        loadSourcesSuccess: () => {
            if (values.destinations !== null) {
                actions.loadDestinationRowSeries()
            }
        },
        loadEverything: () => {
            actions.loadJobStats()
            actions.loadRowsStats()
            actions.loadHealthIssues()
            actions.loadRecentRuns()
            actions.loadDestinations()
            actions.loadSources()
        },
        // Only the headline numbers poll. Reloading the tables under someone mid-read moves rows
        // they are looking at, and they change far less often than the counts do.
        pollStats: () => {
            actions.loadJobStats()
            actions.loadHealthIssues()
            // The runs list is the one table worth moving under the reader: a sync that starts
            // while the page is open should appear without a refresh.
            actions.loadRecentRuns()
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
