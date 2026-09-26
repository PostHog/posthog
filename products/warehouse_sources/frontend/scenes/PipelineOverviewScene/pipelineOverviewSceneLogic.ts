import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

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

/** Windows `job_stats` accepts. Anything else is a 400. */
export type PipelineStatsWindow = 1 | 7 | 30

/** Most severe first, so the worst pipeline is the one a reader sees. */
const ISSUE_SEVERITY: Record<string, number> = {
    failed: 0,
    billing_limit: 1,
    degraded: 2,
    disabled: 3,
}

export interface pipelineOverviewSceneLogicValues {
    currentTeamId: number | null // teamLogic
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
    loadingFirstTime: boolean
}

export interface pipelineOverviewSceneLogicActions {
    setWindow: (window: PipelineStatsWindow) => { window: PipelineStatsWindow }
    loadJobStats: () => any
    loadRowsStats: () => any
    loadHealthIssues: () => any
    loadRecentFailures: () => any
    refresh: () => { value: true }
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
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        setWindow: (window: PipelineStatsWindow) => ({ window }),
        refresh: true,
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
        recentFailures: [
            null as PipelineActivityResponseApi | null,
            {
                loadRecentFailures: async () =>
                    await dataWarehouseCompletedActivityRetrieve(String(values.currentTeamId), {
                        outcome: 'failed',
                        limit: 10,
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
                [...(healthIssues?.results ?? [])].sort(
                    (a, b) => (ISSUE_SEVERITY[a.status] ?? 99) - (ISSUE_SEVERITY[b.status] ?? 99)
                ),
        ],
        failingSyncCount: [
            (s: any) => [s.healthIssues],
            (healthIssues: DataHealthIssuesResponseApi | null): number =>
                (healthIssues?.results ?? []).filter((issue) => issue.type === 'external_data_sync').length,
        ],
        failedRuns: [
            (s: any) => [s.recentFailures],
            (recentFailures: PipelineActivityResponseApi | null): PipelineActivityRowApi[] =>
                recentFailures?.results ?? [],
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
        setWindow: () => actions.loadJobStats(),
        refresh: () => {
            actions.loadJobStats()
            actions.loadRowsStats()
            actions.loadHealthIssues()
            actions.loadRecentFailures()
        },
    })),
    afterMount(({ actions }: any) => {
        actions.loadJobStats()
        actions.loadRowsStats()
        actions.loadHealthIssues()
        actions.loadRecentFailures()
    }),
])
