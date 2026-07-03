import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    engineeringAnalyticsMasterFailures,
    engineeringAnalyticsRepoOverview,
    engineeringAnalyticsRunFailureLogs,
} from '../generated/api'
import type {
    GitHubSourceApi,
    MasterFailureGroupApi,
    RepoOverviewApi,
    RunFailureLogsApi,
} from '../generated/api.schemas'
import { ciStatusOf } from '../lib/ci'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { PullRequestRow, STUCK_AFTER_DAYS, engineeringAnalyticsLogic, isStuck } from './engineeringAnalyticsLogic'
import type { repoOverviewLogicType } from './repoOverviewLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

// Pinned to 24h regardless of the shared window — a week of failures is a firehose at monorepo volume.
const MASTER_FAILURES_WINDOW = '-24h'

const TOP_COST_WORKFLOWS = 5

export interface CostShareRow {
    workflowName: string | null
    costUsd: number
    share: number
}

// Warehouse timestamps are strings — parse like the curated builders do (repo_overview._BUCKET_SELECT).
const RUN_STARTED_AT = 'parseDateTimeBestEffort(run_started_at)'

// Refuse to interpolate anything but a plain identifier into SQL.
const TABLE_IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/

// Backend granularity ladder (workflow_health._pick_granularity): hour ≤48h, day ≤90d, else week.
function bucketExpr(from: Dayjs, to: Dayjs): string {
    const spanHours = to.diff(from, 'hour')
    if (spanHours <= 48) {
        return `toStartOfHour(${RUN_STARTED_AT})`
    }
    if (spanHours <= 90 * 24) {
        return `toStartOfDay(${RUN_STARTED_AT})`
    }
    return `toStartOfWeek(${RUN_STARTED_AT}, 1)`
}

function masterHealthSql(
    metricSelect: string,
    table: string,
    branch: string,
    dateFrom: string | null,
    dateTo: string | null
): string | null {
    const from = dateStringToDayJs(dateFrom ?? SHARED_DEFAULT_DATE_FROM)
    if (!from) {
        return null
    }
    const to = dateTo ? dateStringToDayJs(dateTo) : null
    const where = [
        `status = 'completed'`,
        `head_branch = '${branch}'`,
        `${RUN_STARTED_AT} >= toDateTime('${from.format('YYYY-MM-DD HH:mm:ss')}')`,
    ]
    if (to) {
        where.push(`${RUN_STARTED_AT} <= toDateTime('${to.format('YYYY-MM-DD HH:mm:ss')}')`)
    }
    return [
        'SELECT',
        `    ${bucketExpr(from, to ?? dayjs())} AS bucket_start,`,
        `    ${metricSelect}`,
        `FROM ${table}`,
        `WHERE ${where.join('\n    AND ')}`,
        'GROUP BY bucket_start',
        'ORDER BY bucket_start',
        'LIMIT 400',
    ].join('\n')
}

function masterHealthNode(sql: string, display: ChartDisplayType, yColumn: string): DataVisualizationNode {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: sql },
        display,
        chartSettings: { xAxis: { column: 'bucket_start' }, yAxis: [{ column: yColumn }] },
    }
}

export const repoOverviewLogic = kea<repoOverviewLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'repoOverviewLogic']),

    connect(() => ({
        values: [
            engineeringAnalyticsFiltersLogic,
            ['dateFrom', 'dateTo'],
            engineeringAnalyticsLogic,
            [
                'sourceId',
                'githubSources',
                'pullRequests',
                'pullRequestsLoading',
                'cards',
                'workflowHealth',
                'workflowHealthLoading',
                'notConnected',
            ],
        ],
    })),

    actions({
        loadLogsForRun: (runId: number) => ({ runId }),
    }),

    loaders(({ values }) => ({
        overview: [
            null as RepoOverviewApi | null,
            {
                loadOverview: async (): Promise<RepoOverviewApi> =>
                    await engineeringAnalyticsRepoOverview(projectId(), {
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
                        source_id: values.sourceId ?? undefined,
                    }),
            },
        ],
        masterFailures: [
            [] as MasterFailureGroupApi[],
            {
                loadMasterFailures: async (): Promise<MasterFailureGroupApi[]> =>
                    await engineeringAnalyticsMasterFailures(projectId(), {
                        date_from: MASTER_FAILURES_WINDOW,
                        source_id: values.sourceId ?? undefined,
                    }),
            },
        ],
        // 'unavailable' marks a failed fetch so we don't retry on every expand.
        failureLogs: [
            {} as Record<number, RunFailureLogsApi | 'unavailable'>,
            {
                loadFailureLogs: async ({
                    runId,
                }: {
                    runId: number
                }): Promise<Record<number, RunFailureLogsApi | 'unavailable'>> => {
                    try {
                        const logs = await engineeringAnalyticsRunFailureLogs(projectId(), {
                            run_id: runId,
                            source_id: values.sourceId ?? undefined,
                        })
                        return { ...values.failureLogs, [runId]: logs }
                    } catch {
                        return { ...values.failureLogs, [runId]: 'unavailable' }
                    }
                },
            },
        ],
    })),

    reducers({
        // Non-400 failure only; the shared 400 "not connected" state comes from engineeringAnalyticsLogic.
        overviewFailed: [
            false,
            {
                loadOverview: () => false,
                loadOverviewSuccess: () => false,
                loadOverviewFailure: () => true,
            },
        ],
    }),

    selectors({
        jobsAvailable: [(s) => [s.overview], (overview): boolean => overview?.jobs_available ?? false],
        defaultBranch: [(s) => [s.overview], (overview): string => overview?.default_branch ?? 'master'],
        failingWorkflowCount: [
            (s) => [s.masterFailures],
            (masterFailures): number => new Set(masterFailures.map((group) => group.workflow_name)).size,
        ],
        // The warehouse table behind the master-health embeds, mirroring the backend's per-team
        // `prefix + github_workflow_runs` resolution (logic/sources.py).
        runsTableName: [
            (s) => [s.githubSources, s.sourceId],
            (githubSources, sourceId): string | null => {
                const source: GitHubSourceApi | undefined = sourceId
                    ? githubSources.find((candidate: GitHubSourceApi) => candidate.id === sourceId)
                    : githubSources[0]
                if (!source) {
                    return null
                }
                const table = `${source.prefix}github_workflow_runs`
                return TABLE_IDENTIFIER.test(table) ? table : null
            },
        ],
        masterSuccessRateQuery: [
            (s) => [s.runsTableName, s.defaultBranch, s.dateFrom, s.dateTo],
            (runsTableName, defaultBranch, dateFrom, dateTo): DataVisualizationNode | null => {
                if (!runsTableName) {
                    return null
                }
                const sql = masterHealthSql(
                    `round(100 * countIf(conclusion = 'success') / count(), 1) AS success_rate`,
                    runsTableName,
                    defaultBranch,
                    dateFrom,
                    dateTo
                )
                return sql ? masterHealthNode(sql, ChartDisplayType.ActionsLineGraph, 'success_rate') : null
            },
        ],
        masterFailedRunsQuery: [
            (s) => [s.runsTableName, s.defaultBranch, s.dateFrom, s.dateTo],
            (runsTableName, defaultBranch, dateFrom, dateTo): DataVisualizationNode | null => {
                if (!runsTableName) {
                    return null
                }
                const sql = masterHealthSql(
                    `countIf(conclusion != 'success') AS failed_runs`,
                    runsTableName,
                    defaultBranch,
                    dateFrom,
                    dateTo
                )
                return sql ? masterHealthNode(sql, ChartDisplayType.ActionsBar, 'failed_runs') : null
            },
        ],
        // Open PRs with failing CI or stuck (open >7d, non-draft, non-bot) — not the full open list.
        attentionPrs: [
            (s) => [s.pullRequests],
            (pullRequests): PullRequestRow[] => {
                const stuckCutoffMs = dayjs().subtract(STUCK_AFTER_DAYS, 'day').valueOf()
                return pullRequests
                    .filter(
                        (row) => row.state === 'open' && (ciStatusOf(row) === 'failing' || isStuck(row, stuckCutoffMs))
                    )
                    .sort((a, b) => Number(ciStatusOf(b) === 'failing') - Number(ciStatusOf(a) === 'failing'))
            },
        ],
        draftCount: [
            (s) => [s.pullRequests],
            (pullRequests): number => pullRequests.filter((row) => row.state === 'open' && row.isDraft).length,
        ],
        costByWorkflow: [
            (s) => [s.workflowHealth],
            (workflowHealth): CostShareRow[] => {
                const costed = workflowHealth.filter((row) => (row.estimatedCostUsd ?? 0) > 0)
                if (!costed.length) {
                    return []
                }
                const total = costed.reduce((sum, row) => sum + (row.estimatedCostUsd ?? 0), 0)
                const top = [...costed]
                    .sort((a, b) => (b.estimatedCostUsd ?? 0) - (a.estimatedCostUsd ?? 0))
                    .slice(0, TOP_COST_WORKFLOWS)
                const rows: CostShareRow[] = top.map((row) => ({
                    workflowName: row.workflowName,
                    costUsd: row.estimatedCostUsd ?? 0,
                    share: (row.estimatedCostUsd ?? 0) / total,
                }))
                const otherCost = total - rows.reduce((sum, row) => sum + row.costUsd, 0)
                if (costed.length > TOP_COST_WORKFLOWS && otherCost > 0) {
                    rows.push({ workflowName: null, costUsd: otherCost, share: otherCost / total })
                }
                return rows
            },
        ],
        otherCostWorkflowCount: [
            (s) => [s.workflowHealth],
            (workflowHealth): number =>
                Math.max(
                    0,
                    workflowHealth.filter((row) => (row.estimatedCostUsd ?? 0) > 0).length - TOP_COST_WORKFLOWS
                ),
        ],
    }),

    listeners(({ actions, values }) => ({
        loadLogsForRun: ({ runId }) => {
            if (!(runId in values.failureLogs)) {
                actions.loadFailureLogs({ runId })
            }
        },
        // The failures feed is pinned to -24h, so it only re-reads on source change / refresh.
        [engineeringAnalyticsFiltersLogic.actionTypes.setDateRange]: () => {
            actions.loadOverview()
        },
        [engineeringAnalyticsLogic.actionTypes.setSourceId]: () => {
            actions.loadOverview()
            actions.loadMasterFailures()
        },
        [engineeringAnalyticsLogic.actionTypes.refresh]: () => {
            actions.loadOverview()
            actions.loadMasterFailures()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadOverview()
        actions.loadMasterFailures()
    }),
])
