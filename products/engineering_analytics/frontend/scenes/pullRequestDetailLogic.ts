import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    engineeringAnalyticsPrCost,
    engineeringAnalyticsPrLifecycle,
    engineeringAnalyticsPrRuns,
    engineeringAnalyticsWorkflowJobs,
} from '../generated/api'
import type { PRCostSummaryApi, PRLifecycleApi, WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { jobCacheKey } from '../lib/jobs'
import {
    LifecycleSummary,
    WorkflowRun,
    isDecisiveFailure,
    isPassingConclusion,
    summarizeLifecycle,
} from '../lib/lifecycle'
import type { WorkflowHealthBucket, WorkflowHealthRow } from './engineeringAnalyticsLogic'
import type { pullRequestDetailLogicType } from './pullRequestDetailLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface PullRequestDetailLogicProps {
    repoOwner: string
    repoName: string
    number: number
    // Which GitHub source the list was scoped to, threaded from `?source=` via paramsToProps.
    sourceId: string | null
}

/** Failures first, then still-running, then passes — the order a reviewer triages in. */
export function sortRunsForTriage(runs: WorkflowRun[]): WorkflowRun[] {
    const rank = (run: WorkflowRun): number =>
        run.conclusion === null ? 1 : isPassingConclusion(run.conclusion) ? 2 : 0
    return [...runs].sort((a, b) => rank(a) - rank(b) || a.workflow.localeCompare(b.workflow))
}

/** A PR's runs for one commit (head SHA) — used to bucket the progression sparkline by push. */
export interface PrCommitRuns {
    headSha: string
    headBranch: string
    runs: WorkflowRun[]
    /** Latest run start in the group, for ordering commits newest-push-first. */
    latestStart: string | null
}

/** A flat run row: a WorkflowRun plus the commit it ran on, shown when a workflow row is expanded. */
export interface PrRunRow extends WorkflowRun {
    headSha: string
    headBranch: string
}

/** Nearest-rank percentile over a small sample (the PR's per-workflow run durations). */
function percentile(values: number[], q: number): number | null {
    if (values.length === 0) {
        return null
    }
    const sorted = [...values].sort((a, b) => a - b)
    return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(q * sorted.length) - 1))]
}

function toWorkflowRun(run: WorkflowRunDetailApi): WorkflowRun {
    return {
        workflow: run.workflow_name,
        conclusion: run.conclusion,
        startedAt: run.run_started_at,
        finishedAt: run.status === 'completed' ? run.updated_at : null,
        durationSeconds: run.duration_seconds,
        runId: run.id,
        runAttempt: run.run_attempt,
    }
}

// Re-exported for the PR detail scene; defined in lib/jobs so the shared RunsTable can read the cache
// without importing scene logic.
export { jobCacheKey }

/** Group a PR's runs by commit, newest push first — so the detail shows CI across all pushes. */
export function groupRunsByCommit(prRuns: WorkflowRunDetailApi[]): PrCommitRuns[] {
    const byCommit = new Map<string, WorkflowRunDetailApi[]>()
    for (const run of prRuns) {
        const group = byCommit.get(run.head_sha) ?? []
        group.push(run)
        byCommit.set(run.head_sha, group)
    }
    const groups = [...byCommit.entries()].map(([headSha, runs]) => ({
        headSha,
        headBranch: runs[0]?.head_branch ?? '',
        runs: runs.map(toWorkflowRun),
        latestStart: runs.reduce<string | null>((max, run) => {
            const started = run.run_started_at
            return started && started > (max ?? '') ? started : max
        }, null),
    }))
    groups.sort((a, b) => (b.latestStart ?? '').localeCompare(a.latestStart ?? ''))
    return groups
}

export const pullRequestDetailLogic = kea<pullRequestDetailLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'pullRequestDetailLogic']),
    props({} as PullRequestDetailLogicProps),
    // sourceId is part of the identity: the same PR number can resolve to a different source.
    key((props) => `${props.repoOwner}/${props.repoName}#${props.number}@${props.sourceId ?? ''}`),

    actions({
        // Row expansion is keyed by a per-row key (re-runs share a run_id); jobs are fetched per run+attempt.
        setRunExpanded: (rowKey: string, expanded: boolean, runId: number | null, runAttempt: number | null) => ({
            rowKey,
            expanded,
            runId,
            runAttempt,
        }),
        // Free-text filter on workflow name, narrowing the per-round run tables.
        setWorkflowFilter: (filter: string) => ({ filter }),
    }),

    loaders(({ props, values }) => ({
        lifecycle: [
            null as PRLifecycleApi | null,
            {
                loadLifecycle: async (): Promise<PRLifecycleApi | null> =>
                    await engineeringAnalyticsPrLifecycle(projectId(), {
                        pr_number: props.number,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        prRuns: [
            [] as WorkflowRunDetailApi[],
            {
                loadPrRuns: async (): Promise<WorkflowRunDetailApi[]> =>
                    await engineeringAnalyticsPrRuns(projectId(), {
                        pr_number: props.number,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        prCost: [
            null as PRCostSummaryApi | null,
            {
                loadPrCost: async (): Promise<PRCostSummaryApi | null> =>
                    await engineeringAnalyticsPrCost(projectId(), {
                        pr_number: props.number,
                        repo: `${props.repoOwner}/${props.repoName}`,
                        source_id: props.sourceId ?? undefined,
                    }),
            },
        ],
        runJobs: [
            {} as Record<string, WorkflowJobApi[]>,
            {
                // Lazy: fetched only on first expand. Keyed by run+attempt; the post-await read of
                // values.runJobs (not a pre-await snapshot) keeps two near-simultaneous first-expands
                // from clobbering each other.
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
                loadLifecycle: () => false,
                loadLifecycleSuccess: () => false,
                loadLifecycleFailure: () => true,
            },
        ],
        // Separate from loadFailed (the header): a runs-load failure shows an error in the CI-runs section
        // instead of the misleading "no runs attributed" empty state, with its own retry.
        prRunsFailed: [
            false,
            {
                loadPrRuns: () => false,
                loadPrRunsSuccess: () => false,
                loadPrRunsFailure: () => true,
            },
        ],
        expandedRunKeys: [
            [] as string[],
            {
                setRunExpanded: (state, { rowKey, expanded }) =>
                    expanded ? Array.from(new Set([...state, rowKey])) : state.filter((key) => key !== rowKey),
            },
        ],
        workflowFilter: ['', { setWorkflowFilter: (_, { filter }) => filter }],
    }),

    listeners(({ actions, values }) => ({
        setRunExpanded: ({ expanded, runId, runAttempt }) => {
            // Fetch a run+attempt's jobs once, on first expand.
            if (expanded && runId != null && !(jobCacheKey(runId, runAttempt) in values.runJobs)) {
                actions.loadJobs({ runId, runAttempt })
            }
        },
    })),

    selectors({
        // Exposed so the scene can build links (commit/run) and preserve `?source=` without waiting on lifecycle.
        sourceId: [() => [(_, p: PullRequestDetailLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        repoOwner: [() => [(_, p: PullRequestDetailLogicProps) => p.repoOwner], (repoOwner): string => repoOwner],
        repoName: [() => [(_, p: PullRequestDetailLogicProps) => p.repoName], (repoName): string => repoName],
        summary: [
            (s) => [s.lifecycle],
            (lifecycle): LifecycleSummary | null => (lifecycle ? summarizeLifecycle(lifecycle.events) : null),
        ],
        // All of the PR's runs, flattened — for the header counts.
        runs: [(s) => [s.prRuns], (prRuns): WorkflowRun[] => prRuns.map(toWorkflowRun)],
        // The PR's runs grouped by commit, newest push first — one collapsible round per commit in the UI.
        commitGroups: [(s) => [s.prRuns], (prRuns): PrCommitRuns[] => groupRunsByCommit(prRuns)],
        // Rounds with their runs narrowed to the workflow filter; rounds with no match drop out.
        filteredCommitGroups: [
            (s) => [s.commitGroups, s.workflowFilter],
            (commitGroups, workflowFilter): PrCommitRuns[] => {
                const query = workflowFilter.trim().toLowerCase()
                if (!query) {
                    return commitGroups
                }
                return commitGroups
                    .map((group) => ({
                        ...group,
                        runs: group.runs.filter((run) => run.workflow.toLowerCase().includes(query)),
                    }))
                    .filter((group) => group.runs.length > 0)
            },
        ],
        // The PR's runs as one flat list (newest push first), each tagged with its commit, narrowed to
        // the workflow filter.
        filteredRuns: [
            (s) => [s.filteredCommitGroups],
            (groups): PrRunRow[] =>
                groups.flatMap((group) =>
                    group.runs.map((run) => ({ ...run, headSha: group.headSha, headBranch: group.headBranch }))
                ),
        ],
        // The PR's runs rolled up per workflow, in the Workflows tab's WorkflowHealthRow shape so the PR
        // page reuses the shared WorkflowHealthTable. Sparkline buckets are the PR's pushes (oldest →
        // newest), zero-filled so every workflow row aligns.
        workflowHealthRows: [
            (s) => [s.commitGroups, s.repoOwner, s.repoName, s.prCost],
            (commitGroups, repoOwner, repoName, prCost): WorkflowHealthRow[] => {
                const costByWorkflow = new Map((prCost?.by_workflow ?? []).map((cost) => [cost.workflow_name, cost]))
                const pushesOldestFirst = [...commitGroups].reverse()
                // Workflow names that ran on the PR, first-seen order (newest push first).
                const workflowNames: string[] = []
                const seen = new Set<string>()
                for (const group of commitGroups) {
                    for (const run of group.runs) {
                        if (!seen.has(run.workflow)) {
                            seen.add(run.workflow)
                            workflowNames.push(run.workflow)
                        }
                    }
                }
                return workflowNames.map((workflowName): WorkflowHealthRow => {
                    const buckets: WorkflowHealthBucket[] = pushesOldestFirst.map((group, index) => {
                        const runs = group.runs.filter((run) => run.workflow === workflowName)
                        return {
                            bucketStart: group.headSha,
                            label: `Push ${index + 1} (${group.headSha.slice(0, 7)})`,
                            runCount: runs.length,
                            completed: runs.filter((run) => run.conclusion !== null).length,
                            successes: runs.filter((run) => run.conclusion === 'success').length,
                            failures: runs.filter((run) => isDecisiveFailure(run.conclusion)).length,
                        }
                    })
                    const all = commitGroups.flatMap((group) =>
                        group.runs.filter((run) => run.workflow === workflowName)
                    )
                    const completedRuns = all.filter((run) => run.conclusion !== null)
                    const durations = completedRuns
                        .map((run) => run.durationSeconds)
                        .filter((d): d is number => d != null)
                    // Latest completed run (by start) drives the status badge, same as workflow health.
                    const latest = [...completedRuns].sort((a, b) =>
                        (b.startedAt ?? '').localeCompare(a.startedAt ?? '')
                    )[0]
                    const failingStarts = all
                        .filter((run) => isDecisiveFailure(run.conclusion))
                        .map((run) => run.startedAt)
                        .filter((at): at is string => !!at)
                    return {
                        repoOwner,
                        repoName,
                        workflowName,
                        runCount: all.length,
                        successRate:
                            completedRuns.length > 0
                                ? all.filter((run) => run.conclusion === 'success').length / completedRuns.length
                                : null,
                        p50Seconds: percentile(durations, 0.5),
                        p95Seconds: percentile(durations, 0.95),
                        lastFailureAt: failingStarts.length
                            ? failingStarts.reduce((max, at) => (at > max ? at : max))
                            : null,
                        latestRunFailed: latest ? isDecisiveFailure(latest.conclusion) : null,
                        latestRunConclusion: latest ? latest.conclusion : null,
                        granularity: 'push',
                        buckets,
                        billableMinutes: costByWorkflow.get(workflowName)?.billable_minutes ?? null,
                        estimatedCostUsd: costByWorkflow.get(workflowName)?.estimated_cost_usd ?? null,
                    }
                })
            },
        ],
        // Per-run cost keyed by jobCacheKey(run_id, run_attempt) — so the expanded runs table shows a cost
        // column per attempt. Empty when the job source isn't synced (prCost.jobs_available false).
        runCostByKey: [
            (s) => [s.prCost],
            (prCost): Record<string, { minutes: number | null; cost: number | null }> => {
                const map: Record<string, { minutes: number | null; cost: number | null }> = {}
                for (const rc of prCost?.by_run ?? []) {
                    map[jobCacheKey(rc.run_id, rc.run_attempt)] = {
                        minutes: rc.billable_minutes,
                        cost: rc.estimated_cost_usd,
                    }
                }
                return map
            },
        ],
        // Workflow health rows narrowed to the workflow-name filter.
        filteredWorkflowHealthRows: [
            (s) => [s.workflowHealthRows, s.workflowFilter],
            (rows: WorkflowHealthRow[], workflowFilter: string): WorkflowHealthRow[] => {
                const query = workflowFilter.trim().toLowerCase()
                return query ? rows.filter((row) => row.workflowName.toLowerCase().includes(query)) : rows
            },
        ],
        // CI triggers: distinct head SHAs across the PR's runs (matches the backend `pushes` definition).
        pushes: [(s) => [s.prRuns], (prRuns): number => new Set(prRuns.map((run) => run.head_sha)).size],
        // Runs that were a 2nd+ attempt — re-run cycles (matches the backend `rerun_cycles` definition).
        rerunCycles: [(s) => [s.prRuns], (prRuns): number => prRuns.filter((run) => (run.run_attempt ?? 1) > 1).length],
        breadcrumbs: [
            (_, p) => [p.repoOwner, p.repoName, p.number],
            (repoOwner, repoName, number): Breadcrumb[] => [
                {
                    key: 'EngineeringAnalytics',
                    name: 'Engineering analytics',
                    path: urls.engineeringAnalytics(),
                    iconType: 'health',
                },
                {
                    key: ['EngineeringAnalyticsPullRequest', `${repoOwner}/${repoName}#${number}`],
                    name: `${repoOwner}/${repoName} #${number}`,
                    iconType: 'health',
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadLifecycle()
        actions.loadPrRuns()
        actions.loadPrCost()
    }),
])
