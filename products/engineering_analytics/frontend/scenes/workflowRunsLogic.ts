import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { ActivityRun } from '../components/RunActivityChart'
import {
    engineeringAnalyticsJobAggregates,
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRunActivity,
    engineeringAnalyticsWorkflowRunnerCosts,
    engineeringAnalyticsWorkflowRuns,
} from '../generated/api'
import type {
    WorkflowJobAggregateApi,
    WorkflowJobApi,
    WorkflowRunActivityApi,
    WorkflowRunDetailApi,
    WorkflowRunnerCostApi,
} from '../generated/api.schemas'
import { jobCacheKey } from '../lib/jobs'
import { type CostSummary, type HealthSummary, computeHealthSummary } from '../lib/runHealth'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import type { workflowRunsLogicType } from './workflowRunsLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

// Mirrors the backend runs-list cap (`workflow_run_list.py` `_LIMIT`).
const RUN_LIST_LIMIT = 200

/** RunRowBase fields plus this page's lead-column data (run id, branch, attributed PR). */
export interface WorkflowRunRow {
    runId: number | null
    runAttempt: number | null
    conclusion: string | null
    durationSeconds: number | null
    startedAt: string | null
    id: number
    headBranch: string | null
    headSha: string
    prNumber: number
    repoOwner: string
    repoName: string
}

export interface WorkflowRunsLogicProps {
    repoOwner: string
    repoName: string
    workflowName: string
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
}

export const workflowRunsLogic = kea<workflowRunsLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'workflowRunsLogic']),
    props({} as WorkflowRunsLogicProps),
    key((props) => `${props.repoOwner}/${props.repoName}/${props.workflowName}@${props.sourceId ?? ''}`),

    // Same window and branch scope as the Workflows tab, so drilling in keeps the scope instead of
    // silently widening back to all branches.
    connect(() => ({
        values: [engineeringAnalyticsFiltersLogic, ['dateFrom', 'dateTo', 'appliedBranch']],
    })),

    actions({
        // Row expansion is keyed by a per-row key (re-runs share a run_id); jobs are fetched per run+attempt.
        setRunExpanded: (rowKey: string, expanded: boolean, runId: number | null, runAttempt: number | null) => ({
            rowKey,
            expanded,
            runId,
            runAttempt,
        }),
    }),

    loaders(({ props, values }) => ({
        runs: [
            [] as WorkflowRunDetailApi[],
            {
                loadRuns: async (): Promise<WorkflowRunDetailApi[]> =>
                    await engineeringAnalyticsWorkflowRuns(projectId(), {
                        workflow_name: props.workflowName,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
                        branch: values.appliedBranch || undefined,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        // Activity-chart points at a higher cap than the runs table, so the chart spans the full window
        // on busy workflows where 200 runs collapse to a sub-day slice.
        runActivity: [
            { points: [], truncated: false, limit: 0 } as WorkflowRunActivityApi,
            {
                loadRunActivity: async (): Promise<WorkflowRunActivityApi> =>
                    await engineeringAnalyticsWorkflowRunActivity(projectId(), {
                        workflow_name: props.workflowName,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
                        branch: values.appliedBranch || undefined,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        // Cost split by runner tier; [] when the job-level source isn't synced.
        runnerCosts: [
            [] as WorkflowRunnerCostApi[],
            {
                loadRunnerCosts: async (): Promise<WorkflowRunnerCostApi[]> =>
                    await engineeringAnalyticsWorkflowRunnerCosts(projectId(), {
                        workflow_name: props.workflowName,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
                        branch: values.appliedBranch || undefined,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        // Per-job rollups; [] when the job-level source isn't synced.
        jobAggregates: [
            [] as WorkflowJobAggregateApi[],
            {
                loadJobAggregates: async (): Promise<WorkflowJobAggregateApi[]> =>
                    await engineeringAnalyticsJobAggregates(projectId(), {
                        workflow_name: props.workflowName,
                        date_from: values.dateFrom ?? undefined,
                        date_to: values.dateTo ?? undefined,
                        branch: values.appliedBranch || undefined,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        runJobs: [
            {} as Record<string, WorkflowJobApi[]>,
            {
                // Reads the post-await values.runJobs so near-simultaneous first-expands don't clobber.
                loadJobs: async ({
                    runId,
                    runAttempt,
                }: {
                    runId: number
                    runAttempt: number | null
                }): Promise<Record<string, WorkflowJobApi[]>> => {
                    const jobs = await engineeringAnalyticsWorkflowJobs(projectId(), {
                        run_id: runId,
                        run_attempt: runAttempt ?? undefined,
                        source_id: props.sourceId ?? undefined,
                    })
                    return { ...values.runJobs, [jobCacheKey(runId, runAttempt)]: jobs }
                },
            },
        ],
    })),

    reducers({
        loadFailed: [
            false,
            {
                loadRuns: () => false,
                loadRunsSuccess: () => false,
                loadRunsFailure: () => true,
            },
        ],
        expandedRunKeys: [
            [] as string[],
            {
                setRunExpanded: (state, { rowKey, expanded }) =>
                    expanded ? Array.from(new Set([...state, rowKey])) : state.filter((key) => key !== rowKey),
            },
        ],
    }),

    selectors({
        sourceId: [() => [(_, p: WorkflowRunsLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        repoOwner: [() => [(_, p: WorkflowRunsLogicProps) => p.repoOwner], (repoOwner): string => repoOwner],
        repoName: [() => [(_, p: WorkflowRunsLogicProps) => p.repoName], (repoName): string => repoName],
        workflowName: [
            () => [(_, p: WorkflowRunsLogicProps) => p.workflowName],
            (workflowName): string => workflowName,
        ],
        runRows: [
            (s) => [s.runs],
            (runs: WorkflowRunDetailApi[]): WorkflowRunRow[] =>
                runs.map((run) => ({
                    runId: run.id,
                    runAttempt: run.run_attempt,
                    conclusion: run.conclusion,
                    durationSeconds: run.duration_seconds,
                    startedAt: run.run_started_at,
                    id: run.id,
                    headBranch: run.head_branch,
                    headSha: run.head_sha,
                    prNumber: run.pr_number,
                    repoOwner: run.repo.owner,
                    repoName: run.repo.name,
                })),
        ],
        activityRuns: [
            (s) => [s.runActivity],
            (runActivity: WorkflowRunActivityApi): ActivityRun[] =>
                runActivity.points.map((point) => ({
                    runId: point.run_id,
                    conclusion: point.conclusion,
                    startedAt: point.run_started_at,
                    durationSeconds: point.duration_seconds,
                    headBranch: point.head_branch,
                    prNumber: point.pr_number,
                })),
        ],
        // The chart's own cap, distinct from `runsTruncated` (the table's smaller cap).
        activityTruncated: [
            (s) => [s.runActivity],
            (runActivity: WorkflowRunActivityApi): boolean => runActivity.truncated,
        ],
        healthSummary: [(s) => [s.runRows], (runRows): HealthSummary => computeHealthSummary(runRows)],
        // Latest completed master/main run's conclusion; null when the window has none (PR-only workflow).
        masterConclusion: [
            (s) => [s.runRows],
            (runRows): string | null => {
                const masterRuns = runRows
                    .filter(
                        (run) =>
                            (run.headBranch === 'master' || run.headBranch === 'main') &&
                            run.conclusion != null &&
                            run.startedAt != null
                    )
                    .sort((a, b) => (b.startedAt ?? '').localeCompare(a.startedAt ?? ''))
                return masterRuns[0]?.conclusion ?? null
            },
        ],
        // Median queue wait across jobs, weighted by how often each job runs. Null until jobs are synced.
        queueP50Seconds: [
            (s) => [s.jobAggregates],
            (jobAggregates): number | null => {
                const weighted: { value: number; weight: number }[] = jobAggregates
                    .filter((row) => row.queue_p50_seconds != null)
                    .map((row) => ({ value: row.queue_p50_seconds as number, weight: row.job_count }))
                    .sort((a, b) => a.value - b.value)
                const total = weighted.reduce((sum, entry) => sum + entry.weight, 0)
                if (!total) {
                    return null
                }
                let acc = 0
                for (const entry of weighted) {
                    acc += entry.weight
                    if (acc >= total / 2) {
                        return entry.value
                    }
                }
                return weighted[weighted.length - 1].value
            },
        ],
        runsTruncated: [(s) => [s.runRows], (runRows): boolean => runRows.length >= RUN_LIST_LIMIT],
        costSummary: [
            (s) => [s.runnerCosts],
            (runnerCosts): CostSummary | null => {
                if (runnerCosts.length === 0) {
                    return null
                }
                // Free runners report null — a bare sum would turn "no cost data" into a misleading $0.00.
                const hasBillable = runnerCosts.some((cost) => cost.billable_minutes != null)
                const hasEstimatedCost = runnerCosts.some((cost) => cost.estimated_cost_usd != null)
                return {
                    billableMinutes: hasBillable
                        ? runnerCosts.reduce((sum, cost) => sum + (cost.billable_minutes ?? 0), 0)
                        : null,
                    estimatedCostUsd: hasEstimatedCost
                        ? runnerCosts.reduce((sum, cost) => sum + (cost.estimated_cost_usd ?? 0), 0)
                        : null,
                }
            },
        ],
        breadcrumbs: [
            (_, p) => [p.repoOwner, p.repoName, p.workflowName],
            (repoOwner, repoName, workflowName): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'Engineering analytics',
                    path: urls.engineeringAnalytics(),
                    iconType: 'health',
                },
                {
                    key: ['EngineeringAnalyticsWorkflowRuns', `${repoOwner}/${repoName}/${workflowName}`],
                    name: `${repoOwner}/${repoName} · ${workflowName}`,
                    iconType: 'health',
                },
            ],
        ],
    }),

    listeners(({ actions, values }) => ({
        setRunExpanded: ({ expanded, runId, runAttempt }) => {
            if (expanded && runId != null && !(jobCacheKey(runId, runAttempt) in values.runJobs)) {
                actions.loadJobs({ runId, runAttempt })
            }
        },
        [engineeringAnalyticsFiltersLogic.actionTypes.setDateRange]: () => {
            actions.loadRuns()
            actions.loadRunActivity()
            actions.loadRunnerCosts()
            actions.loadJobAggregates()
        },
        [engineeringAnalyticsFiltersLogic.actionTypes.setAppliedBranch]: () => {
            actions.loadRuns()
            actions.loadRunActivity()
            actions.loadRunnerCosts()
            actions.loadJobAggregates()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadRunActivity()
        actions.loadRunnerCosts()
        actions.loadJobAggregates()
    }),
])
