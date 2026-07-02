import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { ActivityRun } from '../components/RunActivityChart'
import {
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRunActivity,
    engineeringAnalyticsWorkflowRunnerCosts,
    engineeringAnalyticsWorkflowRuns,
} from '../generated/api'
import type {
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

// Mirrors the backend runs-list cap (`workflow_run_list.py` `_LIMIT`). A full list is likely truncated, so
// the header labels run rollups "recent" rather than full-window.
const RUN_LIST_LIMIT = 200

/** A workflow run mapped to the shared RunsTable shape: the RunRowBase fields the table needs, plus the
 *  lead-column data this page shows (run id, branch, attributed PR). */
export interface WorkflowRunRow {
    runId: number | null
    runAttempt: number | null
    conclusion: string | null
    durationSeconds: number | null
    startedAt: string | null
    id: number
    headBranch: string | null
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

    // The shared CI-analytics window and branch scope both the runs list and the runner-cost breakdown —
    // one window and branch, the same the Workflows tab uses, so drilling in from a branch-scoped tab keeps
    // that scope instead of silently widening back to all branches (which reads as "more runs").
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
        // Compact per-run points for the activity chart, over the full window at a higher cap than the runs
        // table — so the chart spans multiple days (and its focus-lens brush appears) on busy workflows where
        // the 200-run table would collapse to a sub-day slice.
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
        // Cost split by runner tier over the window — "where this workflow's spend goes"; [] when jobs aren't synced.
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
        runJobs: [
            {} as Record<string, WorkflowJobApi[]>,
            {
                // Lazy: fetched only on first expand. Keyed by run+attempt; reads the post-await
                // values.runJobs so two near-simultaneous first-expands don't clobber each other.
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
        // Pass props through as values so the scene reads repo/workflow identity (title, links) without
        // reaching into logic internals, and can preserve `?source=` on outbound links.
        sourceId: [() => [(_, p: WorkflowRunsLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        repoOwner: [() => [(_, p: WorkflowRunsLogicProps) => p.repoOwner], (repoOwner): string => repoOwner],
        repoName: [() => [(_, p: WorkflowRunsLogicProps) => p.repoName], (repoName): string => repoName],
        workflowName: [
            () => [(_, p: WorkflowRunsLogicProps) => p.workflowName],
            (workflowName): string => workflowName,
        ],
        // Runs mapped to the shared RunsTable row shape, reusing the same runs → jobs table the PR detail uses.
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
                    prNumber: run.pr_number,
                    repoOwner: run.repo.owner,
                    repoName: run.repo.name,
                })),
        ],
        // The activity chart's points, mapped to the shape it plots. Sourced from the higher-capped activity
        // endpoint (not the 200-run table) so the chart covers the full window and its brush shows.
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
        // The chart's own cap was hit — it covers only the most recent runs, not the full window. Distinct
        // from `runsTruncated` (the table's smaller cap), so the chart labels itself honestly.
        activityTruncated: [
            (s) => [s.runActivity],
            (runActivity: WorkflowRunActivityApi): boolean => runActivity.truncated,
        ],
        // Verdict + headline stats for the health strip above the chart.
        healthSummary: [(s) => [s.runRows], (runRows): HealthSummary => computeHealthSummary(runRows)],
        // Runs list is capped server-side; when hit, run rollups cover only the most recent runs (cost
        // still comes from the full-window aggregate), so the header labels them as such.
        runsTruncated: [(s) => [s.runRows], (runRows): boolean => runRows.length >= RUN_LIST_LIMIT],
        // Billable minutes + estimated cost summed across runner tiers, for the strip's cost rollup.
        costSummary: [
            (s) => [s.runnerCosts],
            (runnerCosts): CostSummary | null => {
                if (runnerCosts.length === 0) {
                    return null
                }
                // Free (GitHub-hosted) runners report null cost; gate each field so an all-free workflow
                // shows no cost rather than a misleading $0.00 / 0 min from summing nulls as zero.
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
                    key: 'EngineeringAnalyticsWorkflowsTab',
                    name: 'Workflows',
                    path: urls.engineeringAnalyticsWorkflows(),
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
            // Fetch a run+attempt's jobs once, on first expand.
            if (expanded && runId != null && !(jobCacheKey(runId, runAttempt) in values.runJobs)) {
                actions.loadJobs({ runId, runAttempt })
            }
        },
        // The shared window scopes all three reads — reload them together when it changes.
        [engineeringAnalyticsFiltersLogic.actionTypes.setDateRange]: () => {
            actions.loadRuns()
            actions.loadRunActivity()
            actions.loadRunnerCosts()
        },
        [engineeringAnalyticsFiltersLogic.actionTypes.setAppliedBranch]: () => {
            actions.loadRuns()
            actions.loadRunActivity()
            actions.loadRunnerCosts()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadRunActivity()
        actions.loadRunnerCosts()
    }),
])
