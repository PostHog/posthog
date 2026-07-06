import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    CICardSummaryApi,
    CIFailureLogsApi,
    EngineeringAnalyticsAuthorWorkflowCostsParams,
    EngineeringAnalyticsCiCardsParams,
    EngineeringAnalyticsCiFailureLogsParams,
    EngineeringAnalyticsJobAggregatesParams,
    EngineeringAnalyticsMasterFailuresParams,
    EngineeringAnalyticsPrCostParams,
    EngineeringAnalyticsPrLifecycleParams,
    EngineeringAnalyticsPrRunsParams,
    EngineeringAnalyticsPullRequestsParams,
    EngineeringAnalyticsQuarantineParams,
    EngineeringAnalyticsRepoOverviewParams,
    EngineeringAnalyticsRunFailureLogsParams,
    EngineeringAnalyticsWorkflowHealthParams,
    EngineeringAnalyticsWorkflowJobsParams,
    EngineeringAnalyticsWorkflowRunActivityParams,
    EngineeringAnalyticsWorkflowRunParams,
    EngineeringAnalyticsWorkflowRunnerCostsParams,
    EngineeringAnalyticsWorkflowRunsParams,
    GitHubSourceApi,
    MasterFailureGroupApi,
    PRCostSummaryApi,
    PRLifecycleApi,
    PullRequestListApi,
    QuarantineFileApi,
    QuarantineRequestApi,
    QuarantineRequestResultApi,
    RepoOverviewApi,
    RunFailureLogsApi,
    WorkflowCostApi,
    WorkflowHealthItemApi,
    WorkflowJobAggregateApi,
    WorkflowJobApi,
    WorkflowRunActivityApi,
    WorkflowRunDetailApi,
    WorkflowRunnerCostApi,
} from './api.schemas'

export const getEngineeringAnalyticsAuthorWorkflowCostsUrl = (
    projectId: string,
    params: EngineeringAnalyticsAuthorWorkflowCostsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/author_workflow_costs/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/author_workflow_costs/`
}

/**
 * One author's estimated CI cost split by workflow over a window (date_from default -30d), highest spend first. Runs are attributed to the author through their pull requests (attribution is by PR number). Returns an empty list when the job-level source isn't synced.
 */
export const engineeringAnalyticsAuthorWorkflowCosts = async (
    projectId: string,
    params: EngineeringAnalyticsAuthorWorkflowCostsParams,
    options?: RequestInit
): Promise<WorkflowCostApi[]> => {
    return apiMutator<WorkflowCostApi[]>(getEngineeringAnalyticsAuthorWorkflowCostsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsCiCardsUrl = (projectId: string, params?: EngineeringAnalyticsCiCardsParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/ci_cards/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/ci_cards/`
}

/**
 * Headline counts for the open-PR backlog: open PRs, distinct repos, stuck PRs (open, non-draft, non-bot, older than 7 days), and PRs with failing CI. The failing-CI count rests on the head-SHA join and can lag until late CI completions settle.
 */
export const engineeringAnalyticsCiCards = async (
    projectId: string,
    params?: EngineeringAnalyticsCiCardsParams,
    options?: RequestInit
): Promise<CICardSummaryApi> => {
    return apiMutator<CICardSummaryApi>(getEngineeringAnalyticsCiCardsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsCiFailureLogsUrl = (
    projectId: string,
    params: EngineeringAnalyticsCiFailureLogsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/ci_failure_logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/ci_failure_logs/`
}

/**
 * The thinned CI failure logs for a pull request, grouped by failed job. Resolves the PR to its workflow runs via the pull_requests association (all of the PR's pushes, not just the latest commit), then reads the Logs product joined on run_id. Returns failed jobs only (the worker fetches logs for failures); logs_available is false when CI hasn't failed, the logs aged out of the short Logs retention, or a fork PR has no run association. Each line carries its original 1-based line number in the full pre-thinning log; lines are the failure region (errors plus surrounding context, with omission markers), capped per job and overall.
 */
export const engineeringAnalyticsCiFailureLogs = async (
    projectId: string,
    params: EngineeringAnalyticsCiFailureLogsParams,
    options?: RequestInit
): Promise<CIFailureLogsApi> => {
    return apiMutator<CIFailureLogsApi>(getEngineeringAnalyticsCiFailureLogsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsJobAggregatesUrl = (
    projectId: string,
    params: EngineeringAnalyticsJobAggregatesParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/job_aggregates/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/job_aggregates/`
}

/**
 * Per-job aggregates for one workflow over a window (default -30d), one row per de-sharded job name (matrix shards aggregate together), busiest first: queue p50, duration p50/p95, failure rate, retry pressure, run share (below 1.0 = conditional job), and billable cost. Jobs always need their run as context — this is the aggregate view; use workflow_jobs for one run's jobs. Empty when the job-level source isn't synced.
 */
export const engineeringAnalyticsJobAggregates = async (
    projectId: string,
    params: EngineeringAnalyticsJobAggregatesParams,
    options?: RequestInit
): Promise<WorkflowJobAggregateApi[]> => {
    return apiMutator<WorkflowJobAggregateApi[]>(getEngineeringAnalyticsJobAggregatesUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsMasterFailuresUrl = (
    projectId: string,
    params?: EngineeringAnalyticsMasterFailuresParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/master_failures/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/master_failures/`
}

/**
 * Default-branch failures over a window (default -24h), grouped error-tracking style by (workflow, de-sharded failing job) with a run count and first/last seen, newest group first. `branch` overrides the detected default branch. PR-branch failures are deliberately excluded — at monorepo volume a flat feed is a firehose; those surface per PR. Groups degrade to workflow level (failed_job '') when the job-level source isn't synced.
 */
export const engineeringAnalyticsMasterFailures = async (
    projectId: string,
    params?: EngineeringAnalyticsMasterFailuresParams,
    options?: RequestInit
): Promise<MasterFailureGroupApi[]> => {
    return apiMutator<MasterFailureGroupApi[]>(getEngineeringAnalyticsMasterFailuresUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsPrCostUrl = (projectId: string, params: EngineeringAnalyticsPrCostParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/pr_cost/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/pr_cost/`
}

/**
 * Estimated CI cost for a pull request, summed over the jobs of all its workflow runs. Billable self-hosted Linux runners only — provider-hosted (free GitHub-hosted) and non-Linux jobs are excluded. Every figure is zero/null with `jobs_available` false when the job-level source isn't synced yet.
 */
export const engineeringAnalyticsPrCost = async (
    projectId: string,
    params: EngineeringAnalyticsPrCostParams,
    options?: RequestInit
): Promise<PRCostSummaryApi> => {
    return apiMutator<PRCostSummaryApi>(getEngineeringAnalyticsPrCostUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsPrLifecycleUrl = (
    projectId: string,
    params: EngineeringAnalyticsPrLifecycleParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/pr_lifecycle/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/pr_lifecycle/`
}

/**
 * The timeline of a single pull request: header plus ordered events (opened, CI started/finished, merged or closed). Use this to answer 'where is this PR stuck and what happened to it'. This is a partial view: review and comment events are not yet available.
 */
export const engineeringAnalyticsPrLifecycle = async (
    projectId: string,
    params: EngineeringAnalyticsPrLifecycleParams,
    options?: RequestInit
): Promise<PRLifecycleApi> => {
    return apiMutator<PRLifecycleApi>(getEngineeringAnalyticsPrLifecycleUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsPrRunsUrl = (projectId: string, params: EngineeringAnalyticsPrRunsParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/pr_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/pr_runs/`
}

/**
 * Every workflow run attributed to a pull request, across all its commits (grouped by head SHA client-side), newest first. Run-level only.
 */
export const engineeringAnalyticsPrRuns = async (
    projectId: string,
    params: EngineeringAnalyticsPrRunsParams,
    options?: RequestInit
): Promise<WorkflowRunDetailApi[]> => {
    return apiMutator<WorkflowRunDetailApi[]>(getEngineeringAnalyticsPrRunsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsPullRequestsUrl = (
    projectId: string,
    params?: EngineeringAnalyticsPullRequestsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/pull_requests/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/pull_requests/`
}

/**
 * Open pull requests plus any merged or closed since date_from (default -30d), newest first, each with its head-SHA CI rollup. The list is capped; when more match, `truncated` is true and the ci_cards counts can exceed it. open_to_merge_seconds is coarse — it fuses draft and ready-for-review time; CI counts can lag until late completions settle.
 */
export const engineeringAnalyticsPullRequests = async (
    projectId: string,
    params?: EngineeringAnalyticsPullRequestsParams,
    options?: RequestInit
): Promise<PullRequestListApi> => {
    return apiMutator<PullRequestListApi>(getEngineeringAnalyticsPullRequestsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsQuarantineUrl = (
    projectId: string,
    params?: EngineeringAnalyticsQuarantineParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/quarantine/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/quarantine/`
}

/**
 * The repository's checked-in .test_quarantine.json: flaky tests temporarily quarantined with a hard expiry, classified by urgency (overdue, in grace, expiring soon, active). `available` is false when the repo has no quarantine file — that is not an error. Parsing is fail-open: malformed entries are reported in parse_errors while well-formed ones are kept.
 * @summary Flaky-test quarantine file
 */
export const engineeringAnalyticsQuarantine = async (
    projectId: string,
    params?: EngineeringAnalyticsQuarantineParams,
    options?: RequestInit
): Promise<QuarantineFileApi> => {
    return apiMutator<QuarantineFileApi>(getEngineeringAnalyticsQuarantineUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsQuarantineRequestUrl = (projectId: string) => {
    return `/api/projects/${projectId}/engineering_analytics/quarantine/request/`
}

/**
 * Opens a pull request that edits the repository's checked-in .test_quarantine.json — and, for a new quarantine, a tracking issue the PR links but does not close. The file stays the source of truth that CI enforces; this never bypasses it. A quarantine only affects CI runs that start after the PR merges.
 * @summary Quarantine, extend, or unquarantine a flaky test
 */
export const engineeringAnalyticsQuarantineRequest = async (
    projectId: string,
    quarantineRequestApi: QuarantineRequestApi,
    options?: RequestInit
): Promise<QuarantineRequestResultApi> => {
    return apiMutator<QuarantineRequestResultApi>(getEngineeringAnalyticsQuarantineRequestUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(quarantineRequestApi),
    })
}

export const getEngineeringAnalyticsRepoOverviewUrl = (
    projectId: string,
    params?: EngineeringAnalyticsRepoOverviewParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/repo_overview/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/repo_overview/`
}

/**
 * Repo-level headline aggregates over a window (default -30d): run count, success rate, re-run cycles, median PR open-to-merge (bots and drafts excluded; coarse — draft and ready time fused), and billable minutes + estimated cost — each with its equal-length previous-window twin so a caller can render honest deltas. Also carries the detected default branch and its completed-run history series. Cost figures are null until the job-level source is synced.
 */
export const engineeringAnalyticsRepoOverview = async (
    projectId: string,
    params?: EngineeringAnalyticsRepoOverviewParams,
    options?: RequestInit
): Promise<RepoOverviewApi> => {
    return apiMutator<RepoOverviewApi>(getEngineeringAnalyticsRepoOverviewUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsRunFailureLogsUrl = (
    projectId: string,
    params: EngineeringAnalyticsRunFailureLogsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/run_failure_logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/run_failure_logs/`
}

/**
 * The thinned CI failure logs of one workflow run, grouped by failed job — the run-scoped twin of ci_failure_logs for surfaces that aren't PR-scoped (default-branch failures, the run page). logs_available is false when the run didn't fail or its logs aged out of the short Logs retention.
 */
export const engineeringAnalyticsRunFailureLogs = async (
    projectId: string,
    params: EngineeringAnalyticsRunFailureLogsParams,
    options?: RequestInit
): Promise<RunFailureLogsApi> => {
    return apiMutator<RunFailureLogsApi>(getEngineeringAnalyticsRunFailureLogsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsSourcesUrl = (projectId: string) => {
    return `/api/projects/${projectId}/engineering_analytics/sources/`
}

/**
 * The team's connected GitHub data warehouse sources, oldest first. Populate a source picker from this and pass a chosen `id` back as `source_id` to the other endpoints. A team can connect GitHub more than once (e.g. one source per repository); this lists them all, including any whose tables aren't fully synced yet.
 */
export const engineeringAnalyticsSources = async (
    projectId: string,
    options?: RequestInit
): Promise<GitHubSourceApi[]> => {
    return apiMutator<GitHubSourceApi[]>(getEngineeringAnalyticsSourcesUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowHealthUrl = (
    projectId: string,
    params?: EngineeringAnalyticsWorkflowHealthParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_health/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_health/`
}

/**
 * Per-workflow CI health over a window (default last 24 hours, maximum 366 days): run count, success rate, p50/p95 duration over completed runs, last failure time, latest-run status, and a zero-filled run history bucketed by hour/day/week to fit the window. Optionally scope to a single git branch via `branch`. Use this for 'is CI getting slower' and 'which workflow is the long pole'; compare two windows to get a trend.
 */
export const engineeringAnalyticsWorkflowHealth = async (
    projectId: string,
    params?: EngineeringAnalyticsWorkflowHealthParams,
    options?: RequestInit
): Promise<WorkflowHealthItemApi[]> => {
    return apiMutator<WorkflowHealthItemApi[]>(getEngineeringAnalyticsWorkflowHealthUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowJobsUrl = (
    projectId: string,
    params: EngineeringAnalyticsWorkflowJobsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_jobs/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_jobs/`
}

/**
 * Jobs of a single workflow run attempt, with per-job duration, runner tier, and estimated cost. Scoped to one run_attempt (the latest unless specified) so a re-run's attempts don't merge. Returns an empty list when the job-level source isn't synced yet.
 */
export const engineeringAnalyticsWorkflowJobs = async (
    projectId: string,
    params: EngineeringAnalyticsWorkflowJobsParams,
    options?: RequestInit
): Promise<WorkflowJobApi[]> => {
    return apiMutator<WorkflowJobApi[]>(getEngineeringAnalyticsWorkflowJobsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowRunUrl = (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_run/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_run/`
}

/**
 * A single workflow run: status, conclusion, duration, branch, attempt, and the attributed pull request. Run-level only — per-job and per-step detail are not tracked yet.
 */
export const engineeringAnalyticsWorkflowRun = async (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunParams,
    options?: RequestInit
): Promise<WorkflowRunDetailApi> => {
    return apiMutator<WorkflowRunDetailApi>(getEngineeringAnalyticsWorkflowRunUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowRunActivityUrl = (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunActivityParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_run_activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_run_activity/`
}

/**
 * Compact per-run points for a single workflow over a window (date_from default -30d), newest first, for the run-activity chart: each run's start time, duration, conclusion, branch, and attributed PR. Optionally scope to a single git branch via `branch`, matching workflow_runs. Leaner and higher-capped than workflow_runs so the chart spans the full window even on busy workflows; `truncated` is true when the cap is hit, so the chart covers only the most recent runs.
 */
export const engineeringAnalyticsWorkflowRunActivity = async (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunActivityParams,
    options?: RequestInit
): Promise<WorkflowRunActivityApi> => {
    return apiMutator<WorkflowRunActivityApi>(getEngineeringAnalyticsWorkflowRunActivityUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowRunnerCostsUrl = (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunnerCostsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_runner_costs/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_runner_costs/`
}

/**
 * A workflow's estimated CI cost broken down by runner tier over a window (date_from default -30d), highest spend first. Optionally scope to a single git branch via `branch`. Returns an empty list when the job-level source isn't synced.
 */
export const engineeringAnalyticsWorkflowRunnerCosts = async (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunnerCostsParams,
    options?: RequestInit
): Promise<WorkflowRunnerCostApi[]> => {
    return apiMutator<WorkflowRunnerCostApi[]>(getEngineeringAnalyticsWorkflowRunnerCostsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowRunsUrl = (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_runs/`
}

/**
 * Runs of a single workflow within a repo over a window (date_from default -30d), newest first. Optionally scope to a single git branch via `branch`. Each row is run-level — per-job and per-step detail are not tracked yet. Use this as the GitHub 'workflow' page between the workflow list and a single run.
 */
export const engineeringAnalyticsWorkflowRuns = async (
    projectId: string,
    params: EngineeringAnalyticsWorkflowRunsParams,
    options?: RequestInit
): Promise<WorkflowRunDetailApi[]> => {
    return apiMutator<WorkflowRunDetailApi[]>(getEngineeringAnalyticsWorkflowRunsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
