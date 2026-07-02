import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'

import {
    engineeringAnalyticsMasterFailures,
    engineeringAnalyticsRepoOverview,
    engineeringAnalyticsRunFailureLogs,
} from '../generated/api'
import type { MasterFailureGroupApi, RepoOverviewApi, RunFailureLogsApi } from '../generated/api.schemas'
import { ciStatusOf } from '../lib/ci'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { PullRequestRow, STUCK_AFTER_DAYS, engineeringAnalyticsLogic, isStuck } from './engineeringAnalyticsLogic'
import type { repoOverviewLogicType } from './repoOverviewLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

// The triage section is deliberately pinned to the last 24 hours regardless of the shared window — at
// this repo's volume a week of failures is a firehose; "Now" means now.
const MASTER_FAILURES_WINDOW = '-24h'

// Leaderboard cards stay readable at this depth; the full lists live on the list pages.
const TOP_COST_WORKFLOWS = 5

export interface MasterHealthSeries {
    /** Success-rate percentages per bucket (0–100); null-free — bucket without completions maps to null-safe 100. */
    successRate: number[]
    /** Decisive failures (completed − successes) per bucket. */
    failures: number[]
    completed: number[]
    labels: string[]
}

export interface CostShareRow {
    workflowName: string | null
    costUsd: number
    share: number
}

function bucketLabel(bucketStart: string, granularity: string): string {
    const at = dayjs(bucketStart)
    if (granularity === 'hour') {
        return at.format('MMM D, HH:mm')
    }
    if (granularity === 'week') {
        return `Week of ${at.format('MMM D')}`
    }
    return at.format('MMM D')
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
        // Fired by the failures table on caret expand; loads that group's latest run's logs once.
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
        // Per-run failure-log excerpts, fetched lazily on first expand. 'unavailable' marks a fetch that
        // failed (e.g. the Logs product has no table locally) so we don't retry on every expand.
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
        // Genuine (non-400) failure of the hub's own headline loader; the shared 400 "not connected"
        // state comes from engineeringAnalyticsLogic, whose loaders this page also renders.
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
        // Distinct workflows currently failing on the default branch — the hub's one-glance verdict.
        failingWorkflowCount: [
            (s) => [s.masterFailures],
            (masterFailures): number => new Set(masterFailures.map((group) => group.workflow_name)).size,
        ],
        masterHealth: [
            (s) => [s.overview],
            (overview): MasterHealthSeries | null => {
                if (!overview || overview.default_branch_buckets.length < 2) {
                    return null
                }
                const buckets = overview.default_branch_buckets
                return {
                    successRate: buckets.map((b) => (b.completed > 0 ? (b.successes / b.completed) * 100 : 100)),
                    failures: buckets.map((b) => Math.max(0, b.completed - b.successes)),
                    completed: buckets.map((b) => b.completed),
                    labels: buckets.map((b) => bucketLabel(b.bucket_start, overview.granularity)),
                }
            },
        ],
        // The attention slice of the open backlog: failing CI or stuck (open >7d, non-draft, non-bot).
        // Never the full open list — that's the PR list page.
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
        // The shared window scopes the overview; the failures feed is pinned to -24h and only re-reads on
        // source changes (via engineeringAnalyticsLogic.refresh → its own loaders, mirrored here).
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
