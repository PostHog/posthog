import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    engineeringAnalyticsCiFailureLogs,
    engineeringAnalyticsPrCost,
    engineeringAnalyticsPrLifecycle,
    engineeringAnalyticsPrRuns,
    engineeringAnalyticsWorkflowJobs,
} from '../generated/api'
import type {
    CIFailureLogsApi,
    PRCostSummaryApi,
    PRLifecycleApi,
    WorkflowJobApi,
    WorkflowRunDetailApi,
} from '../generated/api.schemas'
import { failedShardsLabel, groupJobs } from '../lib/jobGroups'
import { jobCacheKey } from '../lib/jobs'
import {
    LifecycleSummary,
    WorkflowRun,
    isDecisiveFailure,
    isPassingConclusion,
    summarizeLifecycle,
} from '../lib/lifecycle'
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

// A broken push shouldn't fan the eager "what failed" job fetches out into dozens of requests.
const MAX_FAILING_JOB_FETCHES = 6

/** The latest run per workflow on the newest push — what the "CI verdict · latest push" tile counts. */
export interface LatestPushStats {
    headSha: string
    total: number
    green: number
    running: number
    failingWorkflows: string[]
}

export function computeLatestPushStats(group: PrCommitRuns | undefined): LatestPushStats | null {
    if (!group) {
        return null
    }
    const latestByWorkflow = new Map<string, WorkflowRun>()
    for (const run of group.runs) {
        const seen = latestByWorkflow.get(run.workflow)
        if (!seen || (run.startedAt ?? '') > (seen.startedAt ?? '')) {
            latestByWorkflow.set(run.workflow, run)
        }
    }
    const latest = Array.from(latestByWorkflow.values())
    return {
        headSha: group.headSha,
        total: latest.length,
        green: latest.filter((run) => run.conclusion != null && isPassingConclusion(run.conclusion)).length,
        running: latest.filter((run) => run.conclusion == null).length,
        failingWorkflows: latest
            .filter((run) => run.conclusion != null && !isPassingConclusion(run.conclusion))
            .map((run) => run.workflow)
            .sort(),
    }
}

/** Each workflow's latest run on the PR (across pushes) — drives the CI-runs table's verdict column. */
export function latestRunPerWorkflow(runs: PrRunRow[]): Map<string, PrRunRow> {
    const latest = new Map<string, PrRunRow>()
    for (const run of runs) {
        const seen = latest.get(run.workflow)
        if (!seen || (run.startedAt ?? '') > (seen.startedAt ?? '')) {
            latest.set(run.workflow, run)
        }
    }
    return latest
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

/** One row of the PR page's workflows table — its verdict/failed-job columns derive separately. */
export interface PrWorkflowRow {
    workflowName: string
    runCount: number
    p50Seconds: number | null
    estimatedCostUsd: number | null
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

export { jobCacheKey }

/** Group a PR's runs by commit, newest push first. */
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
        // Fetched only once a decisive failure is known; 'unavailable' = the fetch itself failed.
        failureLogs: [
            null as CIFailureLogsApi | 'unavailable' | null,
            {
                loadFailureLogs: async (): Promise<CIFailureLogsApi | 'unavailable'> => {
                    try {
                        return await engineeringAnalyticsCiFailureLogs(projectId(), {
                            pr_number: props.number,
                            repo: `${props.repoOwner}/${props.repoName}`,
                            source_id: props.sourceId ?? undefined,
                        })
                    } catch {
                        return 'unavailable'
                    }
                },
            },
        ],
        runJobs: [
            {} as Record<string, WorkflowJobApi[]>,
            {
                // The post-await read of values.runJobs (not a pre-await snapshot) keeps two
                // near-simultaneous first-expands from clobbering each other.
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
        // Separate from loadFailed so a runs-load failure errors the CI-runs section, not the header.
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
            if (expanded && runId != null && !(jobCacheKey(runId, runAttempt) in values.runJobs)) {
                actions.loadJobs({ runId, runAttempt })
            }
        },
        // Failure logs only exist once something failed — skip the Logs query otherwise.
        loadPrRunsSuccess: () => {
            if (values.prRuns.some((run) => isDecisiveFailure(run.conclusion))) {
                actions.loadFailureLogs()
            }
            // Eagerly fetch each failing workflow's latest run's jobs so the table can name what failed.
            Array.from(latestRunPerWorkflow(values.filteredRuns).values())
                .filter((run) => run.conclusion != null && !isPassingConclusion(run.conclusion))
                .slice(0, MAX_FAILING_JOB_FETCHES)
                .forEach((run) => {
                    if (run.runId != null && !(jobCacheKey(run.runId, run.runAttempt) in values.runJobs)) {
                        actions.loadJobs({ runId: run.runId, runAttempt: run.runAttempt })
                    }
                })
        },
    })),

    selectors({
        sourceId: [() => [(_, p: PullRequestDetailLogicProps) => p.sourceId], (sourceId): string | null => sourceId],
        repoOwner: [() => [(_, p: PullRequestDetailLogicProps) => p.repoOwner], (repoOwner): string => repoOwner],
        repoName: [() => [(_, p: PullRequestDetailLogicProps) => p.repoName], (repoName): string => repoName],
        summary: [
            (s) => [s.lifecycle],
            (lifecycle): LifecycleSummary | null => (lifecycle ? summarizeLifecycle(lifecycle.events) : null),
        ],
        runs: [(s) => [s.prRuns], (prRuns): WorkflowRun[] => prRuns.map(toWorkflowRun)],
        commitGroups: [(s) => [s.prRuns], (prRuns): PrCommitRuns[] => groupRunsByCommit(prRuns)],
        // Groups with their runs narrowed to the workflow filter; groups with no match drop out.
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
        // Flat run list (newest push first), each run tagged with its commit.
        filteredRuns: [
            (s) => [s.filteredCommitGroups],
            (groups): PrRunRow[] =>
                groups.flatMap((group) =>
                    group.runs.map((run) => ({ ...run, headSha: group.headSha, headBranch: group.headBranch }))
                ),
        ],
        // One row per workflow on the PR (first-seen order) — just what the workflows table renders;
        // the verdict column derives from latestRunPerWorkflow separately.
        prWorkflowRows: [
            (s) => [s.commitGroups, s.prCost],
            (commitGroups, prCost): PrWorkflowRow[] => {
                const costByWorkflow = new Map((prCost?.by_workflow ?? []).map((cost) => [cost.workflow_name, cost]))
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
                return workflowNames.map((workflowName): PrWorkflowRow => {
                    const all = commitGroups.flatMap((group) =>
                        group.runs.filter((run) => run.workflow === workflowName)
                    )
                    const durations = all
                        .filter((run) => run.conclusion !== null)
                        .map((run) => run.durationSeconds)
                        .filter((d): d is number => d != null)
                    return {
                        workflowName,
                        runCount: all.length,
                        p50Seconds: percentile(durations, 0.5),
                        estimatedCostUsd: costByWorkflow.get(workflowName)?.estimated_cost_usd ?? null,
                    }
                })
            },
        ],
        // Per-run cost keyed by jobCacheKey(run_id, run_attempt); empty when the job source isn't synced.
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
        filteredPrWorkflowRows: [
            (s) => [s.prWorkflowRows, s.workflowFilter],
            (rows: PrWorkflowRow[], workflowFilter: string): PrWorkflowRow[] => {
                const query = workflowFilter.trim().toLowerCase()
                return query ? rows.filter((row) => row.workflowName.toLowerCase().includes(query)) : rows
            },
        ],
        latestPushStats: [
            (s) => [s.commitGroups],
            (commitGroups): LatestPushStats | null => computeLatestPushStats(commitGroups[0]),
        ],
        // workflow → "what failed" label (de-sharded failing job names); missing = jobs not loaded yet.
        failingJobLabelByWorkflow: [
            (s) => [s.filteredRuns, s.runJobs],
            (filteredRuns, runJobs): Record<string, string> => {
                const labels: Record<string, string> = {}
                for (const [workflow, run] of latestRunPerWorkflow(filteredRuns)) {
                    if (run.conclusion == null || isPassingConclusion(run.conclusion) || run.runId == null) {
                        continue
                    }
                    const jobs = runJobs[jobCacheKey(run.runId, run.runAttempt)]
                    if (!jobs) {
                        continue
                    }
                    const failing = groupJobs(jobs).filter((group) => group.failed.length > 0)
                    if (failing.length) {
                        labels[workflow] = failing
                            .map((group) =>
                                group.jobs.length > 1 ? `${group.base} (${failedShardsLabel(group)})` : group.base
                            )
                            .join(' · ')
                    }
                }
                return labels
            },
        ],
        // Both match the backend definitions (`pushes`, `rerun_cycles`).
        pushes: [(s) => [s.prRuns], (prRuns): number => new Set(prRuns.map((run) => run.head_sha)).size],
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
