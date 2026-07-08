import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'

import type { ActivityRun } from '../components/RunActivityChart'
import {
    engineeringAnalyticsMasterFailures,
    engineeringAnalyticsRepoOverview,
    engineeringAnalyticsRepoRunActivity,
    engineeringAnalyticsRunFailureLogs,
} from '../generated/api'
import type {
    MasterFailureGroupApi,
    RepoOverviewApi,
    RunFailureLogsApi,
    WorkflowRunActivityApi,
} from '../generated/api.schemas'
import { ciStatusOf } from '../lib/ci'
import { HUB_PREVIEW_MAX, HUB_PREVIEW_ROWS, HUB_PREVIEW_STEP } from '../lib/preview'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
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
        loadLogsForRun: (runId: number) => ({ runId }),
        showMorePrs: true,
        showMoreWorkflows: true,
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
        // One collapsed point per default-branch commit (all its workflows folded together) for the
        // master-health scatter — the backend owns the collapse, so the UI just plots the points.
        repoActivity: [
            { points: [], truncated: false, limit: 0 } as WorkflowRunActivityApi,
            {
                loadRepoActivity: async (): Promise<WorkflowRunActivityApi> =>
                    await engineeringAnalyticsRepoRunActivity(projectId(), {
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
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
        // Without this, a failed activity fetch is indistinguishable from a quiet branch — the scene
        // would show the "no runs" empty state over a real error.
        repoActivityFailed: [
            false,
            {
                loadRepoActivity: () => false,
                loadRepoActivitySuccess: () => false,
                loadRepoActivityFailure: () => true,
            },
        ],
        // How many rows the hub's preview tables show. Start short (HUB_PREVIEW_ROWS), grow by a fixed
        // step on "Show more", capped so the hub stays a preview — the full tables live on the dedicated
        // pages. No reset on reload: slicing tolerates any list length, and keeping the user's expansion
        // across a window change is less surprising than snapping back.
        prPreviewCount: [
            HUB_PREVIEW_ROWS,
            { showMorePrs: (count) => Math.min(HUB_PREVIEW_MAX, count + HUB_PREVIEW_STEP) },
        ],
        workflowPreviewCount: [
            HUB_PREVIEW_ROWS,
            { showMoreWorkflows: (count) => Math.min(HUB_PREVIEW_MAX, count + HUB_PREVIEW_STEP) },
        ],
    }),

    selectors({
        jobsAvailable: [(s) => [s.overview], (overview): boolean => overview?.jobs_available ?? false],
        defaultBranch: [(s) => [s.overview], (overview): string => overview?.default_branch ?? 'master'],
        failingWorkflowCount: [
            (s) => [s.masterFailures],
            (masterFailures): number => new Set(masterFailures.map((group) => group.workflow_name)).size,
        ],
        // Backend-collapsed commit points, mapped to the shared chart shape (one dot per default-branch
        // commit: start time, wall-clock CI duration, overall verdict).
        activityRuns: [
            (s) => [s.repoActivity],
            (repoActivity): ActivityRun[] =>
                repoActivity.points.map((point) => ({
                    runId: point.run_id,
                    conclusion: point.conclusion,
                    startedAt: point.run_started_at,
                    durationSeconds: point.duration_seconds,
                    headBranch: point.head_branch,
                    prNumber: point.pr_number,
                })),
        ],
        activityTruncated: [(s) => [s.repoActivity], (repoActivity): boolean => repoActivity.truncated],
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
        // Cost-per-merged-PR trend for the Cost section — the "is CI spend per shipped change creeping
        // up" chart. The backend delivers a trailing rolling ratio, so a null only means the whole
        // trailing window shipped nothing; plotted as 0 to keep the axis anchored. Null when the series
        // is empty (job source unsynced), so the section falls back to its existing empty state.
        costPerMergeSeries: [
            (s) => [s.overview],
            (overview): { values: number[]; labels: string[] } | null => {
                const series = overview?.cost_series ?? []
                if (!series.length) {
                    return null
                }
                const fmt = overview?.cost_series_granularity === 'hour' ? 'MMM D HH:mm' : 'MMM D'
                return {
                    values: series.map((bucket) => bucket.cost_per_merge_usd ?? 0),
                    labels: series.map((bucket) => dayjs(bucket.bucket_start).format(fmt)),
                }
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadLogsForRun: ({ runId }) => {
            if (!(runId in values.failureLogs)) {
                actions.loadFailureLogs({ runId })
            }
        },
        // The failures feed is pinned to -24h, so it only re-reads on source change / refresh; the
        // activity scatter follows the shared window like the overview tiles.
        [engineeringAnalyticsFiltersLogic.actionTypes.setDateRange]: () => {
            actions.loadOverview()
            actions.loadRepoActivity()
        },
        [engineeringAnalyticsLogic.actionTypes.setSourceId]: () => {
            actions.loadOverview()
            actions.loadMasterFailures()
            actions.loadRepoActivity()
        },
        [engineeringAnalyticsLogic.actionTypes.refresh]: () => {
            actions.loadOverview()
            actions.loadMasterFailures()
            actions.loadRepoActivity()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadOverview()
        actions.loadMasterFailures()
        actions.loadRepoActivity()
    }),
])
