/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 9 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * The thinned CI failure logs for a pull request, grouped by failed job. Resolves the PR to its workflow runs via the pull_requests association (all of the PR's pushes, not just the latest commit), then reads the Logs product joined on run_id. Returns failed jobs only (the worker fetches logs for failures); logs_available is false when CI hasn't failed, the logs aged out of the short Logs retention, or a fork PR has no run association. Each line carries its original 1-based line number in the full pre-thinning log; lines are the failure region (errors plus surrounding context, with omission markers), capped per job and overall.
 */
export const EngineeringAnalyticsCiFailureLogsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsCiFailureLogsQueryParams = /* @__PURE__ */ zod.object({
    pr_number: zod.number().describe('Pull request number whose CI failure logs to fetch.'),
    repo: zod.string().describe("'owner/name' repository the pull request belongs to."),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * The flaky-test leaderboard: backend tests ranked by flakiness signal from the per-test CI spans, over a window (default -7d, maximum 30 days). A test qualifies by passing on retry at least min_rerun_passes times OR failing on at least min_failed_prs distinct PRs. All figures are absolute counts, never rates: fast passing runs are not emitted, so denominators are biased. Pass-on-retry counts only flow from CI lanes running with reruns enabled; in other lanes a flake surfaces as a plain failure, which the distinct-PR count catches.
 */
export const EngineeringAnalyticsFlakyTestsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsFlakyTestsQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .optional()
        .describe(
            "Window start: relative ('-7d', '-30d') or ISO8601. Defaults to -7d; the window may span at most 30 days."
        ),
    date_to: zod.string().optional().describe('Window end: relative or ISO8601. Defaults to now.'),
    limit: zod.number().optional().describe('Maximum number of tests to return (1-200). Defaults to 50.'),
    min_failed_prs: zod
        .number()
        .optional()
        .describe(
            'A test qualifies once it failed on at least this many distinct pull requests in the window (OR-ed with min_rerun_passes). Minimum 1. Defaults to 3.'
        ),
    min_rerun_passes: zod
        .number()
        .optional()
        .describe(
            'A test qualifies once it passed on retry at least this many times in the window (OR-ed with min_failed_prs). Minimum 1. Defaults to 1.'
        ),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * Estimated CI cost for a pull request, summed over the jobs of all its workflow runs. Billable self-hosted Linux runners only — provider-hosted (free GitHub-hosted) and non-Linux jobs are excluded. Every figure is zero/null with `jobs_available` false when the job-level source isn't synced yet.
 */
export const EngineeringAnalyticsPrCostParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsPrCostQueryParams = /* @__PURE__ */ zod.object({
    pr_number: zod.number().describe('Pull request number to estimate cost for.'),
    repo: zod.string().describe("'owner/name' repository the pull request belongs to."),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * The timeline of a single pull request: header plus ordered events (opened, CI started/finished, merged or closed). Use this to answer 'where is this PR stuck and what happened to it'. This is a partial view: review and comment events are not yet available.
 */
export const EngineeringAnalyticsPrLifecycleParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsPrLifecycleQueryParams = /* @__PURE__ */ zod.object({
    pr_number: zod.number().describe('Pull request number to inspect.'),
    repo: zod.string().describe("'owner/name' repository the pull request belongs to."),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * Open pull requests plus any merged or closed since date_from (default -30d), newest first, each with its head-SHA CI rollup. The list is capped; when more match, `truncated` is true and the ci_cards counts can exceed it. open_to_merge_seconds is coarse — it fuses draft and ready-for-review time; CI counts can lag until late completions settle.
 */
export const EngineeringAnalyticsPullRequestsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsPullRequestsQueryParams = /* @__PURE__ */ zod.object({
    author: zod.string().optional().describe("Optional GitHub login to scope the list to one author's pull requests."),
    date_from: zod.string().optional().describe("Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d."),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * The team's connected GitHub data warehouse sources, oldest first. Populate a source picker from this and pass a chosen `id` back as `source_id` to the other endpoints. A team can connect GitHub more than once (e.g. one source per repository); this lists them all, including any whose tables aren't fully synced yet.
 */
export const EngineeringAnalyticsSourcesParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Per-workflow CI health over a window (default last 24 hours, maximum 366 days): run count, success rate, p50/p95 duration, last failure time, latest-run status, and a zero-filled run history bucketed by hour/day/week to fit the window. p50/p95 are over successful runs only, so cancelled (superseded) and failed runs never bias the duration trend. Optionally scope to a single git branch via `branch`, or to attributed pull-request runs via `run_scope=pull_request`. Use this for 'is CI getting slower' and 'which workflow is the long pole'; compare two windows to get a trend.
 */
export const EngineeringAnalyticsWorkflowHealthParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsWorkflowHealthQueryParams = /* @__PURE__ */ zod.object({
    branch: zod
        .string()
        .optional()
        .describe(
            "Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches."
        ),
    date_from: zod.string().optional().describe("Window start: relative ('-24h', '-7d') or ISO8601. Defaults to -24h."),
    date_to: zod.string().optional().describe('Window end: relative or ISO8601. Defaults to now.'),
    run_scope: zod
        .enum(['all', 'pull_request'])
        .optional()
        .describe(
            "Run scope for workflow health: 'all' (default) includes every run; 'pull_request' includes runs attributed to pull requests, excluding default-branch (master/main) runs. Fork PRs carry no PR attribution (a GitHub limitation), so 'pull_request' covers same-repo PRs only. Any other value is a 400."
        ),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * Jobs of a single workflow run attempt, with per-job duration, runner tier, and estimated cost. Scoped to one run_attempt (the latest unless specified) so a re-run's attempts don't merge. Returns an empty list when the job-level source isn't synced yet.
 */
export const EngineeringAnalyticsWorkflowJobsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsWorkflowJobsQueryParams = /* @__PURE__ */ zod.object({
    run_attempt: zod
        .number()
        .optional()
        .describe(
            "Which re-run attempt to scope jobs to. Omit to use the run's latest attempt; pass an explicit attempt to avoid mixing jobs across a re-run's attempts."
        ),
    run_id: zod.number().describe('Workflow run id to list jobs for.'),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * A workflow's estimated CI cost broken down by runner tier over a window (date_from default -30d), highest spend first. Optionally scope to a single git branch via `branch`. Returns an empty list when the job-level source isn't synced.
 */
export const EngineeringAnalyticsWorkflowRunnerCostsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsWorkflowRunnerCostsQueryParams = /* @__PURE__ */ zod.object({
    branch: zod
        .string()
        .optional()
        .describe(
            "Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches."
        ),
    date_from: zod.string().optional().describe("Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d."),
    date_to: zod.string().optional().describe('Window end: relative or ISO8601. Defaults to now.'),
    repo: zod.string().describe("'owner/name' repository the workflow belongs to."),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
    workflow_name: zod.string().describe('Workflow name to break down cost for.'),
})
