/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface WorkflowCostApi {
    /** GitHub Actions workflow name this cost is for. */
    workflow_name: string
    /** Billable (self-hosted) minutes for this workflow within the scope. */
    billable_minutes: number
    /**
     * Estimated dollar cost for this workflow, or null when nothing was costable.
     * @nullable
     */
    estimated_cost_usd: number | null
    /** Costed jobs for this workflow (billable Linux runner, finished). */
    costed_jobs: number
    /** Billable Linux jobs still queued/running for this workflow. */
    unsettled_jobs: number
    /** Provider-hosted/non-Linux jobs for this workflow, outside the estimate. */
    excluded_jobs: number
}

export interface CICardSummaryApi {
    /** Count of open pull requests. */
    open_prs: number
    /** Distinct repositories with at least one open pull request. */
    repos: number
    /** Open, non-draft, non-bot pull requests older than 7 days. */
    stuck: number
    /** Open pull requests with at least one failing latest CI run. May lag until the workflow_run webhook settles late completions. */
    failing_ci: number
}

export interface RepoRefApi {
    /** Code host provider, e.g. 'github'. */
    provider: string
    /** Repository owner or organization. */
    owner: string
    /** Repository name. */
    name: string
}

export interface CIFailureLogLineApi {
    /**
     * 1-based line number in the full pre-thinning job log, or null for a '... N lines omitted ...' marker. The gap between consecutive values is how many lines were elided.
     * @nullable
     */
    original_line: number | null
    /** The log line text, or the omission-marker text. */
    text: string
}

export interface CIJobFailureLogApi {
    /** The thinned failure-log lines in original order, with omission markers. */
    lines: CIFailureLogLineApi[]
    /** GitHub Actions job id of the failed job. */
    job_id: number
    /** Workflow run id the job belongs to. */
    run_id: number
    /** Job conclusion ('failure', 'timed_out', ...). Only failed jobs have logs. */
    conclusion: string
    /** Git branch the run was triggered on, or '' when unknown. */
    branch: string
    /** Total lines in the full job log before thinning (the denominator for each line's original_line); 0 when unknown. */
    original_total_lines: number
    /** Number of lines returned for this job (after the per-job cap). */
    line_count: number
    /** True when the job had more failure lines than the per-job cap. */
    truncated: boolean
}

export interface CIFailureLogsApi {
    /** Repository the pull request belongs to. */
    repo: RepoRefApi
    /** Failed CI jobs with their thinned failure logs, grouped by job. */
    jobs: CIJobFailureLogApi[]
    /** Pull request number the failure logs are for. */
    pr_number: number
    /** Workflow runs attributed to the PR (across all its pushes) that were searched for logs. */
    runs_attributed: number
    /** False when no failure logs were found — CI hasn't failed, the logs aged out of the short Logs retention, or a fork PR carries no run association to resolve. */
    logs_available: boolean
    /** True when the overall line cap across all jobs was hit. */
    truncated: boolean
}

export interface FlakyTestItemApi {
    /** Reconstructed pytest nodeid (the CI span name), e.g. 'posthog/api/test/test_event/TestEvents::test_x'. A stable grouping key, not a runnable selector — use `selector` to run or quarantine the test. */
    nodeid: string
    /** Runnable pytest selector, e.g. 'posthog/api/test/test_event.py::TestEvents::test_x'. Exact when the CI reporter emitted it; otherwise reconstructed from the nodeid, where the file/class boundary is a best-effort guess. */
    selector: string
    /** Times the test failed, then passed on an automatic retry — the strongest flaky signal. Only CI lanes running with reruns enabled emit it; a flake in a no-rerun lane shows up in failed_count instead. */
    rerun_passed_count: number
    /** Spans whose final outcome was 'failed' or 'error' in the window. An absolute count, not a rate — fast passing runs are not emitted, so denominators are biased. */
    failed_count: number
    /** Distinct pull requests among the failed/error spans. Failures on master or unattributed branches carry no PR number and are excluded here (still in failed_count). */
    failed_pr_count: number
    /** Distinct git branches across all of the test's flaky-signal spans in the window. */
    branch_count: number
    /** Runs where the test failed while quarantined (xfail) — already masked in CI but still flaky. */
    xfailed_count: number
    /** Most recent flaky-signal span for this test in the window. */
    last_seen_at: string
}

export interface FlakyTestListApi {
    /** Qualifying tests ranked by flakiness signal, strongest first, capped at `limit`. */
    items: FlakyTestItemApi[]
    /** True when more tests qualified than the cap; `items` is the strongest `limit` rows. */
    truncated: boolean
    /** Maximum number of tests returned in `items`. */
    limit: number
}

export interface WorkflowJobAggregateApi {
    /** De-sharded job name: the matrix '(G/N)' suffix is stripped and unexpanded '${{ matrix.* }}' templates are collapsed, so shards of one matrix aggregate together. */
    job_name: string
    /** Job instances observed in the window (all shards, all attempts). */
    job_count: number
    /** Distinct raw job names inside the group - the observed matrix width. */
    shard_count: number
    /** Distinct workflow runs the job appeared in. */
    runs_in: number
    /**
     * runs_in divided by the workflow's total runs in the window; below 1.0 means the job is conditional and skips some runs. Null when the workflow had no runs.
     * @nullable
     */
    run_share: number | null
    /**
     * Median queue wait (created to started) in seconds - where runner-capacity problems hide. Null when nothing started.
     * @nullable
     */
    queue_p50_seconds: number | null
    /**
     * Median duration of completed job instances, in seconds. Null if none completed.
     * @nullable
     */
    p50_seconds: number | null
    /**
     * 95th-percentile duration of completed job instances, in seconds. Null if none completed.
     * @nullable
     */
    p95_seconds: number | null
    /**
     * Decisive failures ('failure', 'timed_out') over completed instances (0-1). Null if none completed.
     * @nullable
     */
    failure_rate: number | null
    /** Job instances that ran on a 2nd+ run attempt - retry pressure. */
    retry_job_count: number
    /**
     * Billable (self-hosted) minutes across the group's instances; null when every instance ran on an unknown tier.
     * @nullable
     */
    billable_minutes: number | null
    /**
     * Estimated cost in USD via the runner-tier rate ladder; null when every instance ran on an unknown tier.
     * @nullable
     */
    estimated_cost_usd: number | null
}

export interface MasterFailureGroupApi {
    /** Repository the failures occurred in. */
    repo: RepoRefApi
    /** GitHub Actions workflow name the failing runs belong to. */
    workflow_name: string
    /** De-sharded failing job name (matrix '(G/N)' suffix stripped) — the group's failure signature together with the workflow. '' when the job-level source isn't synced and the group degrades to workflow level. */
    failed_job: string
    /** Distinct failing default-branch runs in this group within the window. */
    run_count: number
    /** When the oldest failing run in the group started. */
    first_seen: string
    /** When the newest failing run in the group started. */
    last_seen: string
    /** Run id of the newest failing run — the drill-down anchor. */
    latest_run_id: number
}

export interface RunCostApi {
    /** GitHub Actions run id this cost is for. */
    run_id: number
    /** Re-run attempt number; 1 for the first attempt. */
    run_attempt: number
    /** Billable (self-hosted) minutes for this run attempt. */
    billable_minutes: number
    /**
     * Estimated dollar cost for this run attempt, or null when nothing was costable.
     * @nullable
     */
    estimated_cost_usd: number | null
}

export interface PRCostSummaryApi {
    /** Same spend broken down per workflow. */
    by_workflow: WorkflowCostApi[]
    /** Same spend broken down per workflow run, keyed by (run_id, run_attempt). */
    by_run: RunCostApi[]
    /** False when the job-level source (github_workflow_jobs) isn't synced — every figure is then zero/null and the cost cards should be hidden. */
    jobs_available: boolean
    /** Billable CI minutes: each costed (self-hosted) job's elapsed time, summed. Parallel jobs add up, so this is compute time spent, not wall-clock run duration. */
    billable_minutes: number
    /**
     * Estimated dollar cost (sum of per-job estimates: elapsed x tier multiplier x reference rate). Null when no job was costable.
     * @nullable
     */
    estimated_cost_usd: number | null
    /** Jobs counted in the estimate (billable Linux runner, finished). */
    costed_jobs: number
    /** Billable Linux jobs still queued/running (no elapsed) — excluded from the estimate. */
    unsettled_jobs: number
    /** Jobs on provider-hosted (GitHub-hosted, free) or non-Linux runners — outside the estimate. */
    excluded_jobs: number
}

export interface AuthorApi {
    /** Login handle of the pull request author. */
    handle: string
    /** Human-readable name; equals the handle in v1. */
    display_name: string
    /** URL of the author's avatar image. */
    avatar_url: string
    /** True if the author is a bot (handle ends in [bot] or is a known bot). */
    is_bot: boolean
}

/**
 * * `open` - OPEN
 * * `closed` - CLOSED
 * * `merged` - MERGED
 */
export type EngineeringAnalyticsPRStateEnumApi =
    (typeof EngineeringAnalyticsPRStateEnumApi)[keyof typeof EngineeringAnalyticsPRStateEnumApi]

export const EngineeringAnalyticsPRStateEnumApi = {
    Open: 'open',
    Closed: 'closed',
    Merged: 'merged',
} as const

export interface PullRequestApi {
    /** The pull request author. */
    author: AuthorApi
    /** Repository the pull request belongs to. */
    repo: RepoRefApi
    /** GitHub pull request id. */
    id: number
    /** Pull request number within the repository. */
    number: number
    /** Pull request title. */
    title: string
    /** Derived state: 'open', 'closed', or 'merged'.
     *
     * * `open` - OPEN
     * * `closed` - CLOSED
     * * `merged` - MERGED */
    state: EngineeringAnalyticsPRStateEnumApi
    /** True if the pull request is a draft. */
    is_draft: boolean
    /** When the pull request was opened. */
    created_at: string
    /**
     * When the pull request was merged, or null.
     * @nullable
     */
    merged_at: string | null
    /**
     * When the pull request was closed, or null.
     * @nullable
     */
    closed_at: string | null
}

/**
 * * `opened` - OPENED
 * * `ci_started` - CI_STARTED
 * * `ci_finished` - CI_FINISHED
 * * `merged` - MERGED
 * * `closed` - CLOSED
 */
export type PRLifecycleEventKindEnumApi = (typeof PRLifecycleEventKindEnumApi)[keyof typeof PRLifecycleEventKindEnumApi]

export const PRLifecycleEventKindEnumApi = {
    Opened: 'opened',
    CiStarted: 'ci_started',
    CiFinished: 'ci_finished',
    Merged: 'merged',
    Closed: 'closed',
} as const

export interface PRLifecycleEventApi {
    /** Event kind: opened, ci_started, ci_finished, merged, or closed.
     *
     * * `opened` - OPENED
     * * `ci_started` - CI_STARTED
     * * `ci_finished` - CI_FINISHED
     * * `merged` - MERGED
     * * `closed` - CLOSED */
    kind: PRLifecycleEventKindEnumApi
    /** When the event occurred. */
    at: string
    /**
     * Optional detail, e.g. workflow name and conclusion for CI events.
     * @nullable
     */
    detail?: string | null
    /**
     * GitHub Actions run id for ci_started/ci_finished events, null otherwise.
     * @nullable
     */
    run_id?: number | null
}

/**
 * * `precise` - PRECISE
 * * `coarse` - COARSE
 * * `partial` - PARTIAL
 */
export type MetricQualityEnumApi = (typeof MetricQualityEnumApi)[keyof typeof MetricQualityEnumApi]

export const MetricQualityEnumApi = {
    Precise: 'precise',
    Coarse: 'coarse',
    Partial: 'partial',
} as const

export interface PRLifecycleApi {
    /** The pull request header. */
    pull_request: PullRequestApi
    /** Lifecycle events ordered by time. */
    events: PRLifecycleEventApi[]
    /** Always 'partial' — CI events only; reviews and comments are not yet available.
     *
     * * `precise` - PRECISE
     * * `coarse` - COARSE
     * * `partial` - PARTIAL */
    metric_quality?: MetricQualityEnumApi
}

export interface WorkflowRunDetailApi {
    /** Repository the run belongs to. */
    repo: RepoRefApi
    /** GitHub Actions run id. */
    id: number
    /** GitHub Actions workflow name. */
    workflow_name: string
    /** Commit SHA the run was triggered on. */
    head_sha: string
    /** Git branch the run was triggered on. */
    head_branch: string
    /** Raw run status: 'queued', 'in_progress', 'completed', etc. */
    status: string
    /**
     * Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', 'action_required', ...), or null while still in progress.
     * @nullable
     */
    conclusion: string | null
    /**
     * When the run started, or null for a queued/barely-started run.
     * @nullable
     */
    run_started_at: string | null
    /**
     * When the run was last updated (its finish time once completed), or null when unstarted.
     * @nullable
     */
    updated_at: string | null
    /**
     * Wall-clock duration in seconds; null until the run completes.
     * @nullable
     */
    duration_seconds: number | null
    /** Re-run attempt number; 1 for the first attempt. */
    run_attempt: number
    /** Attributed pull request number, or 0 when unattributed. */
    pr_number: number
}

export interface CIStatusRollupApi {
    /** Distinct workflows run on the PR's head SHA. */
    runs: number
    /** Latest runs that completed with conclusion 'success'. */
    passing: number
    /** Latest runs that completed with conclusion 'failure' or 'timed_out'. */
    failing: number
    /** Latest runs not yet completed (queued or in progress). */
    pending: number
    /** The workflow names behind `failing`, sorted - names what is failing instead of leaving a bare count. */
    failing_workflows?: string[]
}

export interface PullRequestListItemApi {
    /** The pull request author. */
    author: AuthorApi
    /** Repository the pull request belongs to. */
    repo: RepoRefApi
    /** CI status from the latest workflow runs on the head SHA. */
    ci: CIStatusRollupApi
    /** Pull request number within the repository. */
    number: number
    /** Pull request title. */
    title: string
    /** Derived state: 'open', 'closed', or 'merged'.
     *
     * * `open` - OPEN
     * * `closed` - CLOSED
     * * `merged` - MERGED */
    state: EngineeringAnalyticsPRStateEnumApi
    /** True if the pull request is a draft. */
    is_draft: boolean
    /** When the pull request was opened. */
    created_at: string
    /**
     * When the pull request was merged, or null.
     * @nullable
     */
    merged_at: string | null
    /**
     * Coarse open-to-merge time in seconds (merged_at - created_at; fuses draft and ready-for-review time). Null until merged.
     * @nullable
     */
    open_to_merge_seconds: number | null
    /** GitHub label names on the pull request. */
    labels: string[]
    /** CI triggers attributed to this PR: distinct head SHAs across its workflow runs. Fork-PR runs are unattributed. */
    pushes: number
    /** Workflow runs attributed to this PR that were a 2nd+ attempt (a re-run). */
    rerun_cycles: number
    /**
     * Estimated CI cost in USD summed over this PR's jobs (billable runners only). Null when nothing was costable or the job-level source isn't synced.
     * @nullable
     */
    estimated_cost_usd?: number | null
    /**
     * Billable (self-hosted) minutes summed over this PR's jobs. Null when the job source isn't synced.
     * @nullable
     */
    billable_minutes?: number | null
}

export interface PullRequestListApi {
    /** Pull requests, newest first, capped at `limit`. */
    items: PullRequestListItemApi[]
    /** True when more pull requests match than the cap; `items` is the newest `limit` rows and the aggregate counts in ci_cards can exceed it. */
    truncated: boolean
    /** Maximum number of pull requests returned in `items`. */
    limit: number
}

/**
 * * `run` - RUN
 * * `skip` - SKIP
 */
export type QuarantineModeEnumApi = (typeof QuarantineModeEnumApi)[keyof typeof QuarantineModeEnumApi]

export const QuarantineModeEnumApi = {
    Run: 'run',
    Skip: 'skip',
} as const

/**
 * * `active` - ACTIVE
 * * `expiring_soon` - EXPIRING_SOON
 * * `in_grace` - IN_GRACE
 * * `overdue` - OVERDUE
 */
export type LifecycleEnumApi = (typeof LifecycleEnumApi)[keyof typeof LifecycleEnumApi]

export const LifecycleEnumApi = {
    Active: 'active',
    ExpiringSoon: 'expiring_soon',
    InGrace: 'in_grace',
    Overdue: 'overdue',
} as const

/**
 * * `product` - PRODUCT
 * * `file` - FILE
 * * `directory` - DIRECTORY
 * * `test` - TEST
 */
export type SelectorKindEnumApi = (typeof SelectorKindEnumApi)[keyof typeof SelectorKindEnumApi]

export const SelectorKindEnumApi = {
    Product: 'product',
    File: 'file',
    Directory: 'directory',
    Test: 'test',
} as const

export interface QuarantineEntryApi {
    /** Test selector: an exact test id, a file, a directory, a class prefix, or 'product:<dashed-name>'. */
    id: string
    /** Test runner the selector targets, e.g. 'pytest' or 'jest'. */
    runner: string
    /** Why the test was quarantined. */
    reason: string
    /** GitHub team or user handle responsible for the fix. */
    owner: string
    /** Tracking issue URL, or empty when none was filed. */
    issue: string
    /** ISO date the entry was added. */
    added: string
    /** ISO date the quarantine expires; past it the test blocks CI normally again. */
    expires: string
    /** 'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all).
     *
     * * `run` - RUN
     * * `skip` - SKIP */
    mode: QuarantineModeEnumApi
    /** Expiry classification: 'active' (>7 days left), 'expiring_soon' (0-7 days left), 'in_grace' (expired up to 7 days ago), 'overdue' (expired beyond the grace period).
     *
     * * `active` - ACTIVE
     * * `expiring_soon` - EXPIRING_SOON
     * * `in_grace` - IN_GRACE
     * * `overdue` - OVERDUE */
    lifecycle: LifecycleEnumApi
    /** Days until the entry expires; negative once past expiry. */
    days_until_expiry: number
    /** What the selector covers: 'test' (contains '::'), 'file', 'directory', or 'product'.
     *
     * * `product` - PRODUCT
     * * `file` - FILE
     * * `directory` - DIRECTORY
     * * `test` - TEST */
    selector_kind: SelectorKindEnumApi
}

export interface QuarantineFileApi {
    /** Quarantined selectors, most urgent first (overdue, in_grace, expiring_soon, active), then by soonest expiry. */
    entries: QuarantineEntryApi[]
    /** Repository the file was read from. Null in local-dev mode, where the server's own checkout is read. */
    repo: RepoRefApi | null
    /** False when the repository has no quarantine file (not an error) or it could not be fetched. */
    available: boolean
    /** Contract violations (malformed JSON, bad entries) or fetch failures. Malformed entries are dropped; well-formed ones are kept. */
    parse_errors: string[]
    /** Forward-compatibility notices, e.g. unknown entry fields. */
    parse_warnings: string[]
    /** GitHub blob URL of the quarantine file, or empty when read locally or unavailable. */
    source_url: string
    /** When this snapshot was computed (UTC); expiry math uses this clock. */
    generated_at: string
}

/**
 * * `quarantine` - QUARANTINE
 * * `extend` - EXTEND
 * * `remove` - REMOVE
 */
export type OperationEnumApi = (typeof OperationEnumApi)[keyof typeof OperationEnumApi]

export const OperationEnumApi = {
    Quarantine: 'quarantine',
    Extend: 'extend',
    Remove: 'remove',
} as const

export interface QuarantineRequestApi {
    /** What to do: 'quarantine' (add or replace an entry and file a tracking issue), 'extend' (re-stamp an existing entry's expiry, reusing its issue), or 'remove' (delete the entry). All three open a pull request.
     *
     * * `quarantine` - QUARANTINE
     * * `extend` - EXTEND
     * * `remove` - REMOVE */
    operation: OperationEnumApi
    /** Test selector to act on: an exact test id, a file, a directory, a class prefix, or 'product:<dashed-name>'. */
    selector: string
    /**
     * Optional 'owner/name' repository override; defaults to the team's most active repo.
     * @nullable
     */
    repo?: string | null
    /** Why the test is quarantined. Required for quarantine and extend; ignored by remove. */
    reason?: string
    /** GitHub team or user handle responsible for the fix, e.g. '@PostHog/team-x'. Required for quarantine and extend. */
    owner?: string
    /** Existing tracking issue URL, carried forward on extend and remove. Ignored by quarantine, which files a fresh issue. */
    issue?: string
    /**
     * ISO date the quarantine expires (at most 30 days out). Defaults to 14 days from today. Ignored by remove.
     * @nullable
     */
    expires?: string | null
    /** 'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all). Defaults to 'run'.
     *
     * * `run` - RUN
     * * `skip` - SKIP */
    mode?: QuarantineModeEnumApi
}

export interface QuarantineRequestResultApi {
    /** URL of the opened pull request that edits the quarantine file. */
    pr_url: string
    /** URL of the tracking issue filed for a new quarantine; empty for extend and remove. */
    issue_url: string
    /** Branch the pull request was opened from. */
    branch: string
}

export interface CostPerMergeBucketApi {
    /** Bucket start, aligned to cost_series_granularity (top of hour, midnight, or Monday). */
    bucket_start: string
    /**
     * Estimated Depot CI cost (USD) of all runs started in this bucket. Null when nothing was costable (no billable self-hosted Linux jobs) or the job source isn't synced.
     * @nullable
     */
    estimated_cost_usd: number | null
    /** PRs merged in this bucket (all authors, bots included). */
    merges: number
    /**
     * Rolling ratio: trailing-window CI cost divided by trailing-window merges (24 h / 7 d / 4 w to match the granularity). Null when the trailing window had no merges or no costable cost.
     * @nullable
     */
    cost_per_merge_usd: number | null
}

export interface RepoOverviewApi {
    /** CI cost per merged PR across the window, oldest first, zero-filled, bucketed by cost_series_granularity. Empty when the job-level source isn't synced. */
    cost_series: CostPerMergeBucketApi[]
    /** Workflow runs started in the window, all branches and workflows. */
    run_count: number
    /** Same count over the equal-length window immediately before date_from — the delta baseline. */
    run_count_prev: number
    /**
     * Fraction of completed runs that succeeded (0-1) in the window. Null if none completed.
     * @nullable
     */
    success_rate: number | null
    /**
     * Success rate over the previous window. Null if none completed.
     * @nullable
     */
    success_rate_prev: number | null
    /** Runs in the window that were a 2nd+ attempt (attempt > 1). */
    rerun_cycles: number
    /** Re-run cycles over the previous window. */
    rerun_cycles_prev: number
    /**
     * Median merged_at - created_at over PRs merged in the window, bots and drafts excluded. Coarse by design: draft and ready-for-review time are fused. Null when nothing merged.
     * @nullable
     */
    median_open_to_merge_seconds: number | null
    /**
     * The same median over the previous window. Null when nothing merged.
     * @nullable
     */
    median_open_to_merge_seconds_prev: number | null
    /**
     * Billable (self-hosted) job minutes in the window; null when the job-level source isn't synced.
     * @nullable
     */
    billable_minutes: number | null
    /**
     * Billable minutes over the previous window; null when the job-level source isn't synced.
     * @nullable
     */
    billable_minutes_prev: number | null
    /**
     * Estimated CI cost in USD (billable minutes x runner-tier rate); null when the job-level source isn't synced.
     * @nullable
     */
    estimated_cost_usd: number | null
    /**
     * Estimated cost over the previous window; null when the job-level source isn't synced.
     * @nullable
     */
    estimated_cost_usd_prev: number | null
    /** Whether the job-level source is synced (cost and queue figures exist). */
    jobs_available: boolean
    /** 'master' or 'main', picked by observed run volume in the window. */
    default_branch: string
    /** Bucket width of the cost_series trend, chosen to fit the window: 'hour', 'day', or 'week'. */
    cost_series_granularity: string
}

export interface WorkflowRunActivityPointApi {
    /** GitHub Actions run id. */
    run_id: number
    /**
     * Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', ...), or null while still in progress.
     * @nullable
     */
    conclusion: string | null
    /** When the run started. Never null on this endpoint: runs without a parseable start timestamp are excluded from the window (they can't be plotted on the chart's time axis). */
    run_started_at: string
    /**
     * Wall-clock duration in seconds; null until the run completes.
     * @nullable
     */
    duration_seconds: number | null
    /** Git branch the run was triggered on, or '' when unknown. */
    head_branch: string
    /** Attributed pull request number, or 0 when unattributed. */
    pr_number: number
}

export interface WorkflowRunActivityApi {
    /** Per-run chart points, newest first, capped at `limit`. */
    points: WorkflowRunActivityPointApi[]
    /** True when more runs matched than the cap; `points` is the newest `limit` runs, so the chart covers only the most recent activity, not the full window. */
    truncated: boolean
    /** Maximum number of run points returned in `points`. */
    limit: number
}

export interface RunFailureLogsApi {
    /** Failed CI jobs of this run with their thinned failure logs, grouped by job. */
    jobs: CIJobFailureLogApi[]
    /** Workflow run id the failure logs are for. */
    run_id: number
    /** False when no failure logs were found — the run didn't fail, or its logs aged out of the short Logs retention. */
    logs_available: boolean
    /** True when the overall line cap across all jobs was hit. */
    truncated: boolean
}

export interface GitHubSourceApi {
    /** Source id — pass as `source_id` to the other endpoints to read this source. */
    id: string
    /** Connected repository as 'owner/name', or '' if unknown. */
    repo: string
    /** User-chosen warehouse table-name prefix for this source, or '' when none. */
    prefix: string
}

export interface WorkflowHealthBucketApi {
    /** Bucket start, aligned to the item's granularity (top of hour, midnight, or Monday). */
    bucket_start: string
    /** Runs started in this bucket. */
    run_count: number
    /** Runs that completed in this bucket. */
    completed: number
    /** Completed runs with conclusion 'success' in this bucket. */
    successes: number
    /** Completed runs that failed in this bucket (conclusion 'failure' or 'timed_out'); excludes skipped, cancelled, and action_required runs. */
    failures: number
}

export interface WorkflowHealthItemApi {
    /** Repository the workflow runs in. */
    repo: RepoRefApi
    /** Run history across the whole window, oldest first, zero-filled, bucketed by granularity. */
    buckets: WorkflowHealthBucketApi[]
    /** GitHub Actions workflow name. */
    workflow_name: string
    /** Total runs started in the window. */
    run_count: number
    /**
     * Fraction of completed runs that succeeded (0-1). Null if no completed runs.
     * @nullable
     */
    success_rate: number | null
    /**
     * Median duration of completed runs, in seconds. Null if none completed.
     * @nullable
     */
    p50_seconds: number | null
    /**
     * 95th-percentile duration of completed runs, in seconds. Null if none completed.
     * @nullable
     */
    p95_seconds: number | null
    /**
     * When the most recent failing run (conclusion 'failure' or 'timed_out') started, or null.
     * @nullable
     */
    last_failure_at: string | null
    /**
     * Whether the most recent completed run was a decisive failure (conclusion 'failure' or 'timed_out'). Null when no run has completed in the window. Powers the OK/RED status badge.
     * @nullable
     */
    latest_run_failed: boolean | null
    /**
     * Raw conclusion of the most recent completed run ('success', 'cancelled', 'skipped', ...), so a real pass can be told from a non-failure non-success. Null when none completed.
     * @nullable
     */
    latest_run_conclusion: string | null
    /** Bucket width of the `buckets` series, chosen to fit the window: 'hour', 'day', or 'week'. */
    granularity: string
    /**
     * Billable (self-hosted) minutes over this workflow's jobs in the window. Null when the job-level source isn't synced.
     * @nullable
     */
    billable_minutes?: number | null
    /**
     * Estimated cost in USD over this workflow's jobs in the window. Null when nothing was costable or the job source isn't synced.
     * @nullable
     */
    estimated_cost_usd?: number | null
    /** Runs in the window that were a 2nd+ attempt - retry pressure, a flakiness proxy. */
    rerun_cycles?: number
    /**
     * Success rate over the equal-length window before date_from - the delta baseline. Null when that window had no completed runs.
     * @nullable
     */
    success_rate_prev?: number | null
}

export interface WorkflowJobApi {
    /** GitHub Actions job id. */
    id: number
    /** The workflow run id this job belongs to. */
    run_id: number
    /** Job name. */
    name: string
    /** Raw job status: 'queued', 'in_progress', 'completed', etc. */
    status: string
    /**
     * Job conclusion ('success', 'failure', 'cancelled', 'skipped', ...), or null while running.
     * @nullable
     */
    conclusion: string | null
    /**
     * When the job started, or null while still queued.
     * @nullable
     */
    started_at: string | null
    /**
     * When the job completed, or null while still running.
     * @nullable
     */
    completed_at: string | null
    /**
     * Wall-clock duration in seconds; null until the job completes.
     * @nullable
     */
    duration_seconds: number | null
    /** Where the job ran: 'github_hosted' (free for open source), 'self_hosted' (billable), or 'unknown'. */
    runner_provider: string
    /** Runner tier the job ran on (e.g. '16-core' or 'ubuntu-latest'), or '' when unknown. */
    runner_label: string
    /**
     * Estimated cost in USD from runner tier + elapsed time; null when the tier is unknown or the job hasn't finished.
     * @nullable
     */
    estimated_cost_usd: number | null
}

export interface WorkflowRunnerCostApi {
    /** 'self_hosted' (billable), 'github_hosted' (free), or 'unknown'. */
    provider: string
    /** Runner tier, e.g. '16-core' or 'ubuntu-latest'. */
    runner_label: string
    /** Jobs that ran on this tier for the workflow. */
    job_count: number
    /** Billable minutes on this tier. */
    billable_minutes: number
    /**
     * Estimated cost in USD on this tier; null for non-billable (github-hosted/non-Linux).
     * @nullable
     */
    estimated_cost_usd: number | null
}

export type EngineeringAnalyticsAuthorWorkflowCostsParams = {
    /**
     * GitHub handle whose CI spend to break down.
     */
    author: string
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsCiCardsParams = {
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsCiFailureLogsParams = {
    /**
     * Pull request number whose CI failure logs to fetch.
     */
    pr_number: number
    /**
     * 'owner/name' repository the pull request belongs to.
     */
    repo: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsFlakyTestsParams = {
    /**
     * Window start: relative ('-7d', '-30d') or ISO8601. Defaults to -7d; the window may span at most 30 days.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Maximum number of tests to return (1-200). Defaults to 50.
     */
    limit?: number
    /**
     * A test qualifies once it failed on at least this many distinct pull requests in the window (OR-ed with min_rerun_passes). Minimum 1. Defaults to 3.
     */
    min_failed_prs?: number
    /**
     * A test qualifies once it passed on retry at least this many times in the window (OR-ed with min_failed_prs). Minimum 1. Defaults to 1.
     */
    min_rerun_passes?: number
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsJobAggregatesParams = {
    /**
     * Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches.
     */
    branch?: string
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
    /**
     * Workflow name to aggregate jobs for.
     */
    workflow_name: string
}

export type EngineeringAnalyticsMasterFailuresParams = {
    /**
     * Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches.
     */
    branch?: string
    /**
     * Window start: relative ('-24h', '-7d') or ISO8601. Defaults to -24h.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsPrCostParams = {
    /**
     * Pull request number to estimate cost for.
     */
    pr_number: number
    /**
     * 'owner/name' repository the pull request belongs to.
     */
    repo: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsPrLifecycleParams = {
    /**
     * Pull request number to inspect.
     */
    pr_number: number
    /**
     * 'owner/name' repository the pull request belongs to.
     */
    repo: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsPrRunsParams = {
    /**
     * Pull request number whose runs to list.
     */
    pr_number: number
    /**
     * 'owner/name' repository the pull request belongs to.
     */
    repo: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsPullRequestsParams = {
    /**
     * Optional GitHub login to scope the list to one author's pull requests.
     */
    author?: string
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsQuarantineParams = {
    /**
     * Optional 'owner/name' repository to read the quarantine file from. Defaults to the connected GitHub source's most active repo over the last 30 days.
     */
    repo?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsRepoOverviewParams = {
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsRepoRunActivityParams = {
    /**
     * Optional exact git branch (head_branch) to chart, e.g. 'main'. Omit or leave blank to use the repo's detected default branch.
     */
    branch?: string
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsRunFailureLogsParams = {
    /**
     * Workflow run id whose failure logs to fetch.
     */
    run_id: number
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsWorkflowHealthParams = {
    /**
     * Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches.
     */
    branch?: string
    /**
     * Window start: relative ('-24h', '-7d') or ISO8601. Defaults to -24h.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsWorkflowJobsParams = {
    /**
     * Which re-run attempt to scope jobs to. Omit to use the run's latest attempt; pass an explicit attempt to avoid mixing jobs across a re-run's attempts.
     */
    run_attempt?: number
    /**
     * Workflow run id to list jobs for.
     */
    run_id: number
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsWorkflowRunParams = {
    /**
     * GitHub Actions run id to inspect.
     */
    run_id: number
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsWorkflowRunActivityParams = {
    /**
     * Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches.
     */
    branch?: string
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * 'owner/name' repository the workflow belongs to.
     */
    repo: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
    /**
     * Workflow name to load run activity for.
     */
    workflow_name: string
}

export type EngineeringAnalyticsWorkflowRunnerCostsParams = {
    /**
     * Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches.
     */
    branch?: string
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * 'owner/name' repository the workflow belongs to.
     */
    repo: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
    /**
     * Workflow name to break down cost for.
     */
    workflow_name: string
}

export type EngineeringAnalyticsWorkflowRunsParams = {
    /**
     * Optional exact git branch (head_branch) to scope results to, e.g. 'main'. Omit or leave blank to aggregate across all branches.
     */
    branch?: string
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * 'owner/name' repository the workflow belongs to.
     */
    repo: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
    /**
     * Workflow name to list runs for.
     */
    workflow_name: string
}
