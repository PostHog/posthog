import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRunnerCosts,
    engineeringAnalyticsWorkflowRuns,
} from '../generated/api'
import type { WorkflowJobApi, WorkflowRunDetailApi, WorkflowRunnerCostApi } from '../generated/api.schemas'
import { jobCacheKey } from '../lib/jobs'
import type { workflowRunsLogicType } from './workflowRunsLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

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
    tabId?: string
}

export const workflowRunsLogic = kea<workflowRunsLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'workflowRunsLogic']),
    props({} as WorkflowRunsLogicProps),
    key(
        (props) =>
            `${props.tabId ?? 'default'}/${props.repoOwner}/${props.repoName}/${props.workflowName}@${props.sourceId ?? ''}`
    ),

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
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        // Cost split by runner tier — "where this workflow's spend goes"; [] when jobs aren't synced.
        runnerCosts: [
            [] as WorkflowRunnerCostApi[],
            {
                loadRunnerCosts: async (): Promise<WorkflowRunnerCostApi[]> =>
                    await engineeringAnalyticsWorkflowRunnerCosts(projectId(), {
                        workflow_name: props.workflowName,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        runJobs: [
            {} as Record<string, WorkflowJobApi[]>,
            {
                // Lazy: fetched only when a run row is first expanded. Keyed by run+attempt; reads the
                // post-await values.runJobs so two near-simultaneous first-expands don't clobber each other.
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
        // Pass props through as values so the scene reads the repo/workflow identity (for the title and
        // links) without reaching into logic internals, and can preserve `?source=` on outbound links.
        sourceId: [() => [(_, p: WorkflowRunsLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        repoOwner: [() => [(_, p: WorkflowRunsLogicProps) => p.repoOwner], (repoOwner): string => repoOwner],
        repoName: [() => [(_, p: WorkflowRunsLogicProps) => p.repoName], (repoName): string => repoName],
        workflowName: [
            () => [(_, p: WorkflowRunsLogicProps) => p.workflowName],
            (workflowName): string => workflowName,
        ],
        // Runs mapped to the shared RunsTable row shape so this page reuses the same runs → jobs table the
        // PR detail page uses.
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
        breadcrumbs: [
            (_, p) => [p.repoOwner, p.repoName, p.workflowName],
            (repoOwner, repoName, workflowName): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'CI analytics',
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
    })),

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadRunnerCosts()
    }),
])
