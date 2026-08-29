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

/**
 * * `breaking_master` - BREAKING_MASTER
 * * `blocking_merge_queue` - BLOCKING_MERGE_QUEUE
 * * `novel_burst` - NOVEL_BURST
 * * `potentially_resolved` - POTENTIALLY_RESOLVED
 * * `flaky` - FLAKY
 * * `pr_only` - PR_ONLY
 */
export type BrokenTestRowStateEnumApi = (typeof BrokenTestRowStateEnumApi)[keyof typeof BrokenTestRowStateEnumApi]

export const BrokenTestRowStateEnumApi = {
    BreakingMaster: 'breaking_master',
    BlockingMergeQueue: 'blocking_merge_queue',
    NovelBurst: 'novel_burst',
    PotentiallyResolved: 'potentially_resolved',
    Flaky: 'flaky',
    PrOnly: 'pr_only',
} as const

export interface BrokenTestRowApi {
    /** Stable identity of this distinct failure: the failing test's node id plus a normalized error signature, so the same failure across runs groups into one row. */
    fingerprint: string
    /** The pytest node id from the CI 'FAILED <id>' line — the failing test. */
    test_id: string
    /** The trailing failure detail with volatile bits (numbers, hashes) normalized, shared across runs of the same failure. Empty when the FAILED line carried no detail. */
    error_signature: string
    /** The CI job the failure most recently came from. Matched against default-branch job status to decide whether trunk is currently broken by it. */
    job_name: string
    /** 'owner/name' repository the failure belongs to. */
    repo: string
    /** The classifier's verdict on how this failure is behaving right now: 'breaking_master' (failing on trunk, latest trunk run still red), 'blocking_merge_queue' (stopped a merge on a commit that already passed the PR's own CI, trunk still green), 'novel_burst' (new within a day and spreading across branches, not on trunk yet), 'potentially_resolved' (hit trunk but trunk is green again), 'flaky' (sporadic across branches over more than a day), or 'pr_only' (confined to one branch — one PR's own problem).
     *
     * * `breaking_master` - BREAKING_MASTER
     * * `blocking_merge_queue` - BLOCKING_MERGE_QUEUE
     * * `novel_burst` - NOVEL_BURST
     * * `potentially_resolved` - POTENTIALLY_RESOLVED
     * * `flaky` - FLAKY
     * * `pr_only` - PR_ONLY */
    state: BrokenTestRowStateEnumApi
    /** Earliest failure line for this fingerprint in the analysis window. */
    first_seen: string
    /** Most recent failure line for this fingerprint in the analysis window. */
    last_seen: string
    /** Total failure lines for this fingerprint in the window. An absolute count, never a rate — passing runs aren't in this data. */
    occurrences: number
    /** Distinct branches the failure appeared on in the window. */
    branches: number
    /** Failure lines on the default branch (master/main). 0 means it never reached trunk. */
    master_hits: number
    /** The most recent failing workflow run for this fingerprint — pass it to run_failure_logs to fetch the actual failing log lines. */
    latest_run_id: number
    /** The branch of the most recent failing run. */
    latest_branch: string
    /** Hourly failure counts over the last 24 hours, oldest first (fixed 24-slot array), for the row sparkline. All zeros when nothing failed in the last day. */
    trend_24h?: number[]
}

export interface BrokenTestsResultApi {
    /** Classified failures ranked by triage urgency — breaking trunk first, single-PR failures last. */
    rows: BrokenTestRowApi[]
    /** Default-branch job names whose latest completed run is failing — the 'what's on fire right now' summary. Empty when the job-level source isn't synced or trunk is green. */
    breaking_master_jobs: string[]
    /** Length in days of the analysis window the counts cover. */
    window_days: number
    /** True when more failures qualified than the cap; `rows` is the top `limit` by urgency. */
    truncated: boolean
    /** Maximum number of rows returned. */
    limit: number
}

/**
 * * `running` - RUNNING
 * * `completed` - COMPLETED
 * * `failed` - FAILED
 */
export type SyncStatusEnumApi = (typeof SyncStatusEnumApi)[keyof typeof SyncStatusEnumApi]

export const SyncStatusEnumApi = {
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
} as const

export interface CISignalsConfigApi {
    /** Whether this project has ever configured CI signals. */
    configured: boolean
    /** Whether every CI signal detector is enabled. */
    enabled: boolean
    /** Aggregate sync status for pull requests, workflow runs, and workflow jobs.
     *
     * * `running` - RUNNING
     * * `completed` - COMPLETED
     * * `failed` - FAILED */
    sync_status: SyncStatusEnumApi | null
}

export interface CISignalsConfigUpdateApi {
    /** Enable or disable every CI signal detector atomically. */
    enabled: boolean
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

export interface CurrentBranchHealthApi {
    /** Detected default branch ('master' or 'main') from runs in the same 24-hour window. */
    default_branch: string
    /** Workflows with at least one completed run in the last 24 hours. */
    settled_workflows: number
    /** Workflows whose latest completed run in the last 24 hours failed or timed out. */
    failing_workflows: number
    /** Alphabetical preview of failing workflow names, capped at 20; use failing_workflows for the complete count. */
    failing_workflow_names: string[]
}

export interface DeploymentFrequencyBucketApi {
    /** Bucket start, aligned to series_granularity (top of hour, midnight, or Monday). */
    bucket_start: string
    /** Deployments whose first success status landed in this bucket, within the environment scope. Zero-filled: 0 means nothing shipped. */
    deployment_count: number
}

export interface MergeToDeployBucketApi {
    /** Bucket start, aligned to series_granularity (top of hour, midnight, or Monday). Keyed on deploy time: a PR lands in the bucket its first post-merge deploy succeeded in. */
    bucket_start: string
    /** PRs whose first post-merge successful deployment landed in this bucket (bots and drafts excluded; narrowed by github_team when given). */
    deployed_pr_count: number
    /**
     * Fastest merge-to-deploy in this bucket, in seconds. Null when nothing deployed.
     * @nullable
     */
    min_seconds: number | null
    /**
     * 25th percentile merge-to-deploy seconds. Null when nothing deployed.
     * @nullable
     */
    p25_seconds: number | null
    /**
     * Median merge-to-deploy seconds. Null when nothing deployed.
     * @nullable
     */
    p50_seconds: number | null
    /**
     * Mean merge-to-deploy seconds. Null when nothing deployed.
     * @nullable
     */
    mean_seconds: number | null
    /**
     * 75th percentile merge-to-deploy seconds. Null when nothing deployed.
     * @nullable
     */
    p75_seconds: number | null
    /**
     * Slowest merge-to-deploy in this bucket, in seconds. Null when nothing deployed.
     * @nullable
     */
    max_seconds: number | null
}

export interface DoraOverviewApi {
    /** Successful deployments per bucket across the window, oldest first, zero-filled, bucketed by series_granularity. Empty when the deploy tables aren't synced. */
    deployment_frequency_series: DeploymentFrequencyBucketApi[]
    /** Merge-to-deploy distribution per bucket across the window, oldest first — the box-plot series (min/p25/p50/mean/p75/max seconds per bucket). Empty when the deploy tables aren't synced, or when github_team was passed without membership data synced. */
    merge_to_deploy_series: MergeToDeployBucketApi[]
    /** False when the deployments/deployment_statuses tables aren't synced for the selected repo; every other field is then empty or null, never a fake zero. */
    deploy_data_available: boolean
    /** What the environment filter resolved to: 'production' (deployments GitHub marks production_environment), an exact environment name (the one passed, or the busiest persistent environment when nothing is marked production), or 'persistent' (no persistent environment deployed in the window, so every non-transient one counts). Transient environments (ephemeral per-PR previews) never join a default scope. The scope resolves from deployments in the scan window, so two different windows can resolve different scopes and are not always comparable. */
    environment_scope: string
    /** Distinct persistent environments deployed to in the scan window, most-deployed first — the environment picker's options. Transient environments are omitted but stay reachable by exact name. */
    environments: string[]
    /** True when the optional team-membership snapshot is synced. When false, a github_team filter cannot be honored and the merge-to-deploy figures go empty rather than silently unfiltered. */
    has_membership_data: boolean
    /** Distinct GitHub team slugs from the membership snapshot, sorted — the team picker's options. Empty when membership isn't synced. */
    github_teams: string[]
    /** Deployments whose first success status landed in the window, within the environment scope. */
    deployment_count: number
    /** Same count over the equal-length window before date_from. */
    deployment_count_prev: number
    /**
     * deployment_count normalized by the window length in days. Null only when the deploy tables aren't synced.
     * @nullable
     */
    deployments_per_day: number | null
    /**
     * Previous-window twin of deployments_per_day. Null only when the deploy tables aren't synced.
     * @nullable
     */
    deployments_per_day_prev: number | null
    /**
     * Median seconds from a PR's merge to the first successful deployment containing it (bots/drafts excluded; narrowed by github_team when given). Containment is resolved through the deploy's head commit, not the deploy's success time. Keyed on deploy time. This is merge-to-deploy, not full commit-to-deploy DORA lead time. Null when nothing deployed in the window.
     * @nullable
     */
    median_merge_to_deploy_seconds: number | null
    /**
     * Previous-window twin of median_merge_to_deploy_seconds.
     * @nullable
     */
    median_merge_to_deploy_seconds_prev: number | null
    /** PRs first deployed in the window — the population behind the merge-to-deploy median and box plot. */
    deployed_pr_count: number
    /** Previous-window twin of deployed_pr_count. */
    deployed_pr_count_prev: number
    /** Deployments with at least one failure/error status, keyed on the first failure time. */
    failed_deployment_count: number
    /** Previous-window twin of failed_deployment_count. */
    failed_deployment_count_prev: number
    /**
     * Failed deployments over deployments that reached any outcome (success or failure). A change-failure proxy: no incident data is linked, so a deploy that succeeded but broke production is not counted. Null when nothing reached an outcome.
     * @nullable
     */
    failed_deployment_share: number | null
    /**
     * Previous-window twin of failed_deployment_share.
     * @nullable
     */
    failed_deployment_share_prev: number | null
    /**
     * Median seconds from a deployment's first failure status to the next successful deployment in the same environment. A time-to-restore proxy: recovery by anything other than a deploy is invisible, and failures not yet recovered are excluded. Null when no failed deploy recovered in the window.
     * @nullable
     */
    median_failed_deploy_to_next_success_seconds: number | null
    /**
     * Previous-window twin of median_failed_deploy_to_next_success_seconds.
     * @nullable
     */
    median_failed_deploy_to_next_success_seconds_prev: number | null
    /** PRs merged in the window (bots and drafts excluded; narrowed by github_team when given) — the denominator behind unattributed_merged_pr_share. */
    merged_pr_count: number
    /**
     * Share of merged_pr_count no successful in-scope deployment attributed: recent merges still waiting for their deploy, plus merges whose deploy the scope or scan bounds miss. Null when nothing merged in the window.
     * @nullable
     */
    unattributed_merged_pr_share: number | null
    /**
     * The newest deployment status row synced, any environment — how fresh the deploy data is. Windows ending after this instant undercount. Null when the deploy tables are empty.
     * @nullable
     */
    latest_deploy_status_at: string | null
    /** Bucket width of both series, chosen to fit the window: 'hour', 'day', or 'week'. */
    series_granularity: string
}

/**
 * * `pytest` - PYTEST
 * * `jest` - JEST
 */
export type CITestRunnerEnumApi = (typeof CITestRunnerEnumApi)[keyof typeof CITestRunnerEnumApi]

export const CITestRunnerEnumApi = {
    Pytest: 'pytest',
    Jest: 'jest',
} as const

/**
 * * `confirmed_flake` - CONFIRMED_FLAKE
 * * `suspected_regression` - SUSPECTED_REGRESSION
 * * `quarantined` - QUARANTINED
 */
export type FlakyTestItemClassificationEnumApi =
    (typeof FlakyTestItemClassificationEnumApi)[keyof typeof FlakyTestItemClassificationEnumApi]

export const FlakyTestItemClassificationEnumApi = {
    ConfirmedFlake: 'confirmed_flake',
    SuspectedRegression: 'suspected_regression',
    Quarantined: 'quarantined',
} as const

export interface FlakyTestItemApi {
    /** Test runner that emitted this signal: 'pytest' or 'jest'.
     *
     * * `pytest` - PYTEST
     * * `jest` - JEST */
    runner: CITestRunnerEnumApi
    /** Runner-specific stable test identity (the CI span name). This is a grouping key, not necessarily runnable; use `selector` to run or quarantine the test. */
    nodeid: string
    /** Runnable pytest or Jest selector. Exact when the CI reporter emitted it; older pytest spans use a best-effort reconstruction from the nodeid. */
    selector: string
    /** confirmed_flake: one commit both failed and passed the test (a re-run attempt went green, or an in-job retry recovered it), so it is provably nondeterministic. quarantined: a tolerated failure was recorded while it was masked. suspected_regression: only failures were recorded, which is absence of proof, not proof that it is a real break.
     *
     * * `confirmed_flake` - CONFIRMED_FLAKE
     * * `suspected_regression` - SUSPECTED_REGRESSION
     * * `quarantined` - QUARANTINED */
    classification: FlakyTestItemClassificationEnumApi
    /** Runs where one commit both failed and passed the test: a 'Re-run failed jobs' attempt went green on the same commit, or an in-job pytest retry (tests hand-marked @pytest.mark.flaky(reruns=N)) recovered it. A pass in a different run is a different commit and never counts. */
    same_commit_recovery_run_count: number
    /** Distinct CI runs whose recorded outcome was failed or error. A run counts once however many matrix legs it failed in. */
    failed_run_count: number
    /** Distinct pull requests among the failed runs. Failures on master or unattributed branches carry no PR number and are excluded here (still in failed_run_count). */
    failed_pr_count: number
    /** Failed runs on the default branch (master/main approximation): the 'matters right now' signal that a test is breaking the trunk, not just PR branches. */
    master_failed_run_count: number
    /** Runs where the test recorded a tolerated failure while quarantined: already masked in CI, still failing. */
    quarantined_failed_run_count: number
    /** Most recent failure, recovery, or quarantined-failure run for this test in the window. */
    last_signal_at: string
}

export interface FlakyTestListApi {
    /** Tests worth acting on now, ranked by blast radius: master failures, then PRs hit, then runs. */
    items: FlakyTestItemApi[]
    /** True when more tests qualified than the cap; `items` is the highest-ranked `limit` rows. */
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
     * Median duration of successful job instances, in seconds — cancelled and failed instances end early and would bias the percentile. Null if none succeeded.
     * @nullable
     */
    p50_seconds: number | null
    /**
     * 95th-percentile duration of successful job instances, in seconds — cancelled and failed instances end early and would bias the percentile. Null if none succeeded.
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

export interface PRLLMSpendApi {
    /** Total agent LLM token cost in USD attributed to this PR (sum of $ai_total_cost_usd over the matched $ai_generation events). */
    cost_usd: number
    /** Total input (prompt) tokens across the attributed generations. */
    input_tokens: number
    /** Total output (completion) tokens across the attributed generations. */
    output_tokens: number
    /** Number of $ai_generation events attributed to this PR by git branch ($ai_git_branch). */
    generations: number
}

export interface PRCostSummaryApi {
    /** Same spend broken down per workflow. */
    by_workflow: WorkflowCostApi[]
    /** Same spend broken down per workflow run, keyed by (run_id, run_attempt). */
    by_run: RunCostApi[]
    /** Agent LLM token spend attributed to this PR by git branch ($ai_git_branch), or null when no generation matched — independent of the CI cost figures, so it can be present even when jobs_available is false. The UI hides the row when null. */
    llm_spend?: PRLLMSpendApi | null
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
 * * `ready_for_review` - READY_FOR_REVIEW
 * * `converted_to_draft` - CONVERTED_TO_DRAFT
 * * `ci_started` - CI_STARTED
 * * `ci_finished` - CI_FINISHED
 * * `merged` - MERGED
 * * `closed` - CLOSED
 */
export type PRLifecycleEventKindEnumApi = (typeof PRLifecycleEventKindEnumApi)[keyof typeof PRLifecycleEventKindEnumApi]

export const PRLifecycleEventKindEnumApi = {
    Opened: 'opened',
    ReadyForReview: 'ready_for_review',
    ConvertedToDraft: 'converted_to_draft',
    CiStarted: 'ci_started',
    CiFinished: 'ci_finished',
    Merged: 'merged',
    Closed: 'closed',
} as const

export interface PRLifecycleEventApi {
    /** Event kind: opened, ready_for_review, converted_to_draft, ci_started, ci_finished, merged, or closed.
     *
     * * `opened` - OPENED
     * * `ready_for_review` - READY_FOR_REVIEW
     * * `converted_to_draft` - CONVERTED_TO_DRAFT
     * * `ci_started` - CI_STARTED
     * * `ci_finished` - CI_FINISHED
     * * `merged` - MERGED
     * * `closed` - CLOSED */
    kind: PRLifecycleEventKindEnumApi
    /** When the event occurred. */
    at: string
    /**
     * Optional detail: workflow name and conclusion for CI events, the acting user's login for draft/ready transitions.
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
    /** Pull request this run ran for, from the run's own-repo PR association; 0 when unattributed (a default-branch push, or a fork PR). */
    pr_number: number
    /**
     * Pull request whose merge produced this run's head commit, resolved through the merged pull request's merge commit and falling back to the commit subject's '(#NNNN)' suffix. Null when neither resolves. The only PR attribution a default-branch push has: read pr_number first and fall back to this.
     * @nullable
     */
    commit_pr_number: number | null
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

export interface PushCISampleApi {
    /** Head commit SHA of this push (CI round). */
    head_sha: string
    /** Earliest workflow-run start on this push. */
    started_at: string
    /**
     * Wall-clock CI seconds for this push: earliest run start to latest completed run end. Null while nothing has completed.
     * @nullable
     */
    wall_seconds: number | null
    /** True when any latest-per-workflow run on this push concluded 'failure' or 'timed_out'. */
    failed: boolean
    /** True when any latest-per-workflow run on this push hasn't completed yet. */
    pending: boolean
}

export interface PullRequestListItemApi {
    /** The pull request author. */
    author: AuthorApi
    /** Repository the pull request belongs to. */
    repo: RepoRefApi
    /** CI status from the latest workflow runs on the head SHA. */
    ci: CIStatusRollupApi
    /** This PR's CI rounds oldest-first, capped to the most recent pushes - one sample per push for the push-history sparkline. `pushes` stays the uncapped count. */
    push_history: PushCISampleApi[]
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
    /**
     * True ready-to-merge cycle time in seconds: merged_at minus the last observed ready_for_review transition (only the last draft/ready switch counts), or minus created_at for a merged PR verifiably never drafted. Null when unmerged or not observed (the PR's life isn't fully inside the synced issue-event window) - null never means zero.
     * @nullable
     */
    ready_to_merge_seconds: number | null
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

/**
 * * `pytest` - PYTEST
 * * `jest` - JEST
 * * `playwright` - PLAYWRIGHT
 */
export type QuarantineRequestRunnerEnumApi =
    (typeof QuarantineRequestRunnerEnumApi)[keyof typeof QuarantineRequestRunnerEnumApi]

export const QuarantineRequestRunnerEnumApi = {
    Pytest: 'pytest',
    Jest: 'jest',
    Playwright: 'playwright',
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
    /** Test runner the selector targets: 'pytest', 'jest', or 'playwright'. Existing entries and Jest file extensions are inferred for older clients that omit it; other selectors default to 'pytest'.
     *
     * * `pytest` - PYTEST
     * * `jest` - JEST
     * * `playwright` - PLAYWRIGHT */
    runner?: QuarantineRequestRunnerEnumApi | null
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

export interface TimeToGreenBucketApi {
    /** Bucket start, aligned to time_to_green_series_granularity (top of hour, midnight, or Monday). */
    bucket_start: string
    /**
     * Median wall-clock seconds from a PR push round's first run start until every workflow on that head SHA first completed benign, over rounds started in this bucket (merge-queue gates and partially-attributed fork rounds excluded). Null when the bucket had no fully green round (a gap, not instant CI).
     * @nullable
     */
    p50_seconds: number | null
}

export interface PassRateBucketApi {
    /** Bucket start, aligned to success_rate_series_granularity (top of hour, midnight, or Monday). */
    bucket_start: string
    /**
     * Fraction (0-1) of completed runs started in this bucket that succeeded. Null when the bucket had no completed run (a gap, not a 0% pass rate).
     * @nullable
     */
    success_rate: number | null
}

export interface OpenToMergeBucketApi {
    /** Bucket start, aligned to open_to_merge_series_granularity (top of hour, midnight, or Monday). */
    bucket_start: string
    /**
     * Median merged_at - created_at seconds over PRs merged in this bucket, bots and drafts excluded. Null when nothing merged in the bucket (a gap, not instant merges).
     * @nullable
     */
    p50_seconds: number | null
}

export interface ReadyToMergeBucketApi {
    /** Bucket start, aligned to ready_to_merge_series_granularity (top of hour, midnight, or Monday). */
    bucket_start: string
    /**
     * Median per-PR ready_to_merge_seconds (merged_at minus the last observed ready-for-review transition) over PRs merged in this bucket, bots and drafts excluded. Null when nothing merged with an observed value (a gap, never zero).
     * @nullable
     */
    p50_seconds: number | null
}

export interface RepoOverviewApi {
    /** CI cost per merged PR across the window, oldest first, zero-filled, bucketed by cost_series_granularity. Empty when the job-level source isn't synced or include_series=false. */
    cost_series: CostPerMergeBucketApi[]
    /** Median time-to-green (p50 wall clock for a PR push round to settle fully green) per bucket across the window, oldest first, bucketed by time_to_green_series_granularity. Empty buckets carry null; the whole series is empty when include_series=false. */
    time_to_green_series: TimeToGreenBucketApi[]
    /** CI pass rate (completed runs that succeeded, all branches) per bucket across the window, oldest first, bucketed by success_rate_series_granularity. Empty buckets carry null; the whole series is empty when include_series=false. */
    success_rate_series: PassRateBucketApi[]
    /** Median time-to-merge (p50 open_to_merge_seconds, bots/drafts excluded) per bucket across the window, oldest first, bucketed by open_to_merge_series_granularity. Empty buckets carry null; the whole series is empty when include_series=false. */
    open_to_merge_series: OpenToMergeBucketApi[]
    /** Median cycle time (p50 per-PR ready_to_merge_seconds, bots/drafts excluded) per bucket across the window, oldest first, bucketed by ready_to_merge_series_granularity. Empty buckets carry null; the whole series is empty when the issue-events table isn't synced or include_series=false, so fall back to open_to_merge_series. */
    ready_to_merge_series: ReadyToMergeBucketApi[]
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
    /** PRs merged in the window, all authors and bots included — the merge population that triggered the CI spend, so it divides cleanly into billable_minutes and estimated_cost_usd. */
    merged_pr_count: number
    /** Merged-PR count over the previous window. */
    merged_pr_count_prev: number
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
     * Median per-PR ready_to_merge_seconds (the true cycle time: merged_at minus the last observed ready-for-review transition) over PRs merged in the window, bots and drafts excluded. Null when the issue-events table isn't synced or no merged PR has an observed value; fall back to median_open_to_merge_seconds and label it open-to-merge.
     * @nullable
     */
    median_ready_to_merge_seconds: number | null
    /**
     * The same median over the previous window. Null when not observed.
     * @nullable
     */
    median_ready_to_merge_seconds_prev: number | null
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
    /**
     * estimated_cost_usd divided by merged_pr_count — the window's CI cost per merged PR. Null when the job-level source isn't synced or nothing merged.
     * @nullable
     */
    cost_per_merge_usd: number | null
    /**
     * The same ratio over the previous window. Null when the job-level source isn't synced or nothing merged.
     * @nullable
     */
    cost_per_merge_usd_prev: number | null
    /**
     * Slice of billable_minutes spent on merge-queue batch branches (trunk-merge/**); null when the job-level source isn't synced.
     * @nullable
     */
    merge_queue_billable_minutes: number | null
    /**
     * Merge-queue billable minutes over the previous window; null when the job-level source isn't synced.
     * @nullable
     */
    merge_queue_billable_minutes_prev: number | null
    /** PRs merged in the window with at least one corroborated merge-queue gate run — the population behind every merge_queue_* landing stat. All authors, bots included. */
    merge_queue_merged_pr_count: number
    /** Queue-landed merges over the previous window. */
    merge_queue_merged_pr_count_prev: number
    /**
     * Median seconds from a PR's first observed merge-queue gate run starting to the PR merging. Pending time before gate testing starts is not included. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_median_first_gate_to_merge_seconds: number | null
    /**
     * The same median over the previous window. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_median_first_gate_to_merge_seconds_prev: number | null
    /**
     * p90 of the same first-gate-run-to-merge measure — the tail, where queue pain concentrates. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_p90_first_gate_to_merge_seconds: number | null
    /**
     * The same p90 over the previous window. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_p90_first_gate_to_merge_seconds_prev: number | null
    /**
     * p95 of the same first-gate-run-to-merge measure. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_p95_first_gate_to_merge_seconds: number | null
    /**
     * The same p95 over the previous window. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_p95_first_gate_to_merge_seconds_prev: number | null
    /**
     * p99 of the same first-gate-run-to-merge measure. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_p99_first_gate_to_merge_seconds: number | null
    /**
     * The same p99 over the previous window. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_p99_first_gate_to_merge_seconds_prev: number | null
    /**
     * Mean distinct gate attempts (distinct gate branches, flake-bisection branches collapsed) per queue-landed merge. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_avg_attempts_per_merge: number | null
    /**
     * The same mean over the previous window. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_avg_attempts_per_merge_prev: number | null
    /**
     * Fraction (0-1) of queue-landed merges that needed more than one gate attempt. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_multi_attempt_merge_share: number | null
    /**
     * The same fraction over the previous window. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_multi_attempt_merge_share_prev: number | null
    /**
     * Fraction (0-1) of queue-landed merges with at least one failed gate run before merging. Derived from CI run conclusions, not the queue's own eviction records. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_failed_gate_merge_share: number | null
    /**
     * The same fraction over the previous window. Null when no queue-landed merges.
     * @nullable
     */
    merge_queue_failed_gate_merge_share_prev: number | null
    /** Whether the team's TrunkIo warehouse source has the opt-in merge-queue endpoint synced and readable by the requesting user. When false, every merge_queue_failed_or_cancelled_* and merge_queue_skip_the_line_* field is null; fall back to merge_queue_failed_gate_merge_share. */
    merge_queue_trunk_available: boolean
    /**
     * Fraction (0-1) of concluded queue entries (merged, failed, or cancelled) that ended failed or cancelled, from the queue's own records. Windowed on each entry's last state change. Null when the Trunk source isn't synced or nothing concluded.
     * @nullable
     */
    merge_queue_failed_or_cancelled_share: number | null
    /**
     * The same fraction over the previous window. Null when the Trunk source isn't synced or nothing concluded.
     * @nullable
     */
    merge_queue_failed_or_cancelled_share_prev: number | null
    /**
     * Queue entries flagged skip-the-line (prioritized past the queue order) in the window, whatever state they reached. Null when the Trunk source isn't synced.
     * @nullable
     */
    merge_queue_skip_the_line_count: number | null
    /**
     * Skip-the-line entries over the previous window. Null when the Trunk source isn't synced.
     * @nullable
     */
    merge_queue_skip_the_line_count_prev: number | null
    /**
     * Median wall clock for a PR push round to settle fully green over the window — the window-level twin of time_to_green_series, same population and exclusions. Null when no fully green rounds.
     * @nullable
     */
    median_time_to_green_seconds: number | null
    /**
     * The same median over the previous window. Null when no fully green rounds.
     * @nullable
     */
    median_time_to_green_seconds_prev: number | null
    /** Whether the job-level source is synced (cost and queue figures exist). */
    jobs_available: boolean
    /** 'master' or 'main', picked by observed run volume in the window. */
    default_branch: string
    /** Bucket width of the cost_series trend, chosen to fit the window: 'hour', 'day', or 'week'. */
    cost_series_granularity: string
    /** Bucket width of the time_to_green_series trend: 'hour', 'day', or 'week'. */
    time_to_green_series_granularity: string
    /** Bucket width of the success_rate_series trend: 'hour', 'day', or 'week'. */
    success_rate_series_granularity: string
    /** Bucket width of the open_to_merge_series trend: 'hour', 'day', or 'week'. */
    open_to_merge_series_granularity: string
    /** Bucket width of the ready_to_merge_series trend: 'hour', 'day', or 'week'. */
    ready_to_merge_series_granularity: string
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
    /** Head commit SHA of the run/commit, or '' when unknown. */
    head_sha: string
}

export interface WorkflowRunActivityApi {
    /** Per-run chart points, newest first, capped at `limit`. */
    points: WorkflowRunActivityPointApi[]
    /** True when more runs matched than the cap; `points` is the newest `limit` runs, so the chart covers only the most recent activity, not the full window. */
    truncated: boolean
    /** Maximum number of run points returned in `points`. */
    limit: number
}

export interface BranchPRMatchApi {
    /** Repository the pull request belongs to, as 'owner/name'. */
    repo: string
    /** Pull request number within the repository — pair with `repo` to link to it. */
    number: number
    /**
     * Pull request title, or null when the snapshot carries no title.
     * @nullable
     */
    title: string | null
    /**
     * Derived PR state ('open', 'closed', 'merged'), or null when the snapshot carries no state.
     * @nullable
     */
    state: string | null
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
    /** Source id — pass back as `source_id` (with `repo`) to read this repository. */
    id: string
    /** Repository as 'owner/name' — pass back as `repo` to scope to it. One entry per repository a source syncs; '' if unknown. */
    repo: string
    /** User-chosen warehouse table-name prefix for this source, or '' when none. */
    prefix: string
    /** Whether this repo has both pull_requests and workflow_runs synced (readable now). Default the picker to the first synced entry so its label matches the resolved repo. */
    synced?: boolean
}

export interface TeamTestSignalApi {
    /** Test runner that emitted this signal: 'pytest' or 'jest'.
     *
     * * `pytest` - PYTEST
     * * `jest` - JEST */
    runner: CITestRunnerEnumApi
    /** Runner-specific test identity (the CI span name), a stable grouping key. */
    nodeid: string
    /** Runnable pytest or Jest selector; exact for newly emitted spans. */
    selector: string
    /** Runs in the current window where the test failed, errored, or a retry recovered it (quarantined failures excluded). */
    signal_count: number
    /** Same count over the equal-length window before date_from. */
    signal_count_prior: number
    /** Most recent failure, recovery, or quarantined-failure run for this test, either window. */
    last_seen_at: string
}

export interface TeamCIActivityApi {
    /** The team's owned tests with signal in either window, ranked by the stronger window's count (the current-vs-prior pairs behind a before/after comparison). */
    tests: TeamTestSignalApi[]
    /** The team slug this activity is scoped to, or 'unowned'. */
    owner_team: string
    /** True when more owned tests had signal than the test cap. */
    truncated_tests: boolean
}

export interface TeamCIHealthItemApi {
    /** Owning team slug (the CODEOWNERS handle minus '@PostHog/', e.g. 'team-replay'), or the literal 'unowned' for tests whose spans carry no ownership stamp. */
    owner_team: string
    /** Owned tests one commit was seen both failing and passing in the window: the same proof, and the same word, that flaky_tests calls a confirmed_flake. Compare with flaky_test_count_prior for the delta. */
    flaky_test_count: number
    /** Same count over the equal-length window immediately before date_from. */
    flaky_test_count_prior: number
    /** Owned tests that failed with no recorded same-commit recovery and still hit the blast-radius bar (a master/main failure, or min_failed_prs distinct PRs). Not flakes: absence of proof, not proof. */
    regression_test_count: number
    /** Same count over the prior window. */
    regression_test_count_prior: number
    /** CI runs (not spans) where an owned test's recorded outcome was failed or error. An absolute count, not a rate: fast passing runs are not emitted. */
    failed_run_count: number
    /** Same count over the prior window. */
    failed_run_count_prior: number
    /** Runs where one commit both failed and passed an owned test: a re-run attempt went green, or an in-job retry recovered it. */
    same_commit_recovery_run_count: number
    /** Same count over the prior window. */
    same_commit_recovery_run_count_prior: number
    /** Runs where an owned test recorded a tolerated failure while quarantined: masked in CI, still failing. */
    quarantined_failed_run_count: number
    /** Same count over the prior window. */
    quarantined_failed_run_count_prior: number
    /** Most recent failure, recovery, or quarantined-failure run across the team's owned tests, either window. */
    last_seen_at: string
}

export interface TeamCIHealthListApi {
    /** Owning teams ranked by current flaky + failure signal, heaviest first, capped at `limit`. Teams are organizational owners of code surfaces; this never aggregates by author. */
    items: TeamCIHealthItemApi[]
    /** True when more teams had signal than the cap. */
    truncated: boolean
    /** Maximum number of teams returned in `items`. */
    limit: number
}

export interface TeamMergeTrendPointApi {
    /** Start of the day bucket (team timezone), keyed on merged_at. */
    day: string
    /**
     * Median open→merge seconds of the PRs this team's members merged that day; null on a day the team merged nothing.
     * @nullable
     */
    median_seconds: number | null
    /**
     * Average open→merge seconds over the same merges; diverges above the median when a few long-running PRs drag the mean. Null on a day the team merged nothing.
     * @nullable
     */
    average_seconds: number | null
    /** Merged PRs behind that day's median and average. */
    merged_count: number
}

export interface TeamMergeTrendApi {
    /** Daily median and average open→merge over the PRs this team's members merged, ascending by day. Coarse timing (open→merge combines draft and review time); bots excluded. */
    points: TeamMergeTrendPointApi[]
    /** The team slug this trend is scoped to. */
    owner_team: string
    /** False when the GitHub source has no team_members snapshot synced: the trend then has no honest team attribution and `points` is empty. */
    has_membership_data: boolean
}

export interface TrunkQuarantineTeamDebtApi {
    /** Owning team slug, or 'unowned'. */
    owner_team: string
    /** Tests this team owns that Trunk currently quarantines. */
    test_count: number
    /** Of those, tests quarantined longer than ttl_days. */
    overdue_count: number
    /** Age in days of the team's oldest standing quarantine. */
    oldest_age_days: number
}

export interface TrunkQuarantinedTestApi {
    /** Test runner: 'pytest' or 'jest'. */
    runner: string
    /** Runner-native test id reconstructed from Trunk's (file, classname, name) key. */
    nodeid: string
    /** Repo-relative path of the test file, as Trunk reports it. */
    file: string
    /** Owning team slug from the per-test CI spans' emission-time stamp, or 'unowned' when no in-retention span carries one. */
    owner_team: string
    /** Trunk's current health verdict on the test, e.g. 'FLAKY' or 'BROKEN'. */
    status: string
    /** How the quarantine was applied in Trunk, e.g. 'AUTO_QUARANTINE'. */
    quarantine_setting: string
    /** When Trunk quarantined the test. */
    quarantined_at: string
    /** Whole days since the quarantine started. */
    age_days: number
    /** True once age_days exceeds ttl_days: the quarantine has outlived the TTL. */
    overdue: boolean
    /**
     * The Trunk app's page for this test; null when the connected source has no organization slug or the row carries no test case id.
     * @nullable
     */
    trunk_url: string | null
}

export interface TrunkQuarantineDebtApi {
    /** Per-team rollup, most indebted first: overdue count, then test count, then oldest age. */
    teams: TrunkQuarantineTeamDebtApi[]
    /** Every currently quarantined test, oldest first. */
    tests: TrunkQuarantinedTestApi[]
    /** False when no TrunkIo source has the QuarantinedTests endpoint synced; not an error. */
    available: boolean
    /** Days a quarantine may stand before it counts as overdue. */
    ttl_days: number
    /** The 'owner/name' repository the debt was read for; test file paths are relative to it. */
    repository: string
    /**
     * The Trunk app's flaky-tests page for this repository; null when the connected source has no organization slug.
     * @nullable
     */
    trunk_url: string | null
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
    successful_run_count: number
    conclusive_run_count: number
    /**
     * Fraction of completed runs that succeeded (0-1). Null if no completed runs.
     * @nullable
     */
    success_rate: number | null
    /**
     * Median duration in seconds over successful runs only — cancelled (superseded) and failed runs end early and would bias the percentile. Null if no run succeeded in the window.
     * @nullable
     */
    p50_seconds: number | null
    /**
     * 95th-percentile duration in seconds over successful runs only — cancelled (superseded) and failed runs end early and would bias the percentile. Null if no run succeeded in the window.
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
    /** @nullable */
    latest_run_id: number | null
    /** @nullable */
    latest_run_attempt: number | null
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
    percentile_run_count?: number
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
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsBrokenTestsParams = {
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsCiCardsParams = {
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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

export type EngineeringAnalyticsCurrentBranchHealthParams = {
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsDoraParams = {
    /**
     * Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Exact deploy environment to scope to (from the response's `environments` list). Omit to scope to production-marked deployments, falling back to every persistent (non-transient) environment when none are marked production.
     */
    environment?: string
    /**
     * GitHub team slug (from the response's `github_teams` list) to narrow the PR-scoped merge-to-deploy figures to that team's authors. Deploy counts stay repo-wide. Needs the team-membership snapshot synced; without it the merge-to-deploy figures return empty rather than silently unfiltered.
     */
    github_team?: string
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
     * A test with no recorded recovery qualifies once it failed on at least this many distinct pull requests in the window. Minimum 1. Defaults to 3.
     */
    min_failed_prs?: number
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
    /**
     * Optional test runner to return: 'pytest' or 'jest'.
     */
    runner?: EngineeringAnalyticsFlakyTestsRunner
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsFlakyTestsRunner =
    (typeof EngineeringAnalyticsFlakyTestsRunner)[keyof typeof EngineeringAnalyticsFlakyTestsRunner]

export const EngineeringAnalyticsFlakyTestsRunner = {
    Jest: 'jest',
    Pytest: 'pytest',
} as const

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
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
     * Set false to skip the chart series (cost_series, time_to_green_series, success_rate_series, open_to_merge_series return empty) and their query cost — for headline-only consumers like the weekly digest. Defaults to true.
     */
    include_series?: boolean
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsResolveBranchParams = {
    /**
     * Git branch (the PR's head ref) to resolve. Open PRs are returned first, then most recently updated.
     */
    branch: string
    /**
     * Optional 'owner/name' repository to narrow matching to a single repo.
     */
    repo?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
    /**
     * Optional ISO8601 timestamp, e.g. the trace's capture time. When a branch name has been reused across PRs over time, the PR whose lifetime window contains this moment is ranked first so the result matches the PR that was active when the trace was captured. A preference only, not a filter; omit to rank purely by open state then recency.
     */
    timestamp?: string
}

export type EngineeringAnalyticsRunFailureLogsParams = {
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
    /**
     * Workflow run id whose failure logs to fetch.
     */
    run_id: number
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsTeamCiActivityParams = {
    /**
     * Window start: relative ('-14d', '-7d') or ISO8601. Defaults to -14d; the window may span at most 30 days. An equal-length prior window feeds the *_prior twins; near the 30-day ceiling that prior window can reach past Traces retention, deflating *_prior counts.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Owning team slug to scope to (as returned by team_ci_health), e.g. 'team-replay', or the literal 'unowned' for tests with no ownership stamp.
     */
    owner_team: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
    /**
     * Maximum number of per-test signal rows to return (1-100). Defaults to 25.
     */
    test_limit?: number
}

export type EngineeringAnalyticsTeamCiHealthParams = {
    /**
     * Window start: relative ('-14d', '-7d') or ISO8601. Defaults to -14d; the window may span at most 30 days. An equal-length prior window is scanned for the *_prior twins; near the 30-day ceiling that prior window can reach past Traces retention, deflating *_prior counts and overstating deltas.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Maximum number of teams to return (1-200). Defaults to 100.
     */
    limit?: number
    /**
     * An unrecovered test counts toward regression_test_count once it failed on at least this many distinct pull requests in the window. Minimum 1. Defaults to 3. Does not affect flaky_test_count, which needs proof, not a threshold.
     */
    min_failed_prs?: number
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsTeamMergeTrendParams = {
    /**
     * Window start: relative ('-14d', '-7d') or ISO8601. Defaults to -14d; the window may span at most 30 days.
     */
    date_from?: string
    /**
     * Window end: relative or ISO8601. Defaults to now.
     */
    date_to?: string
    /**
     * Team slug to scope to (as returned by team_ci_health), matched against the GitHub org team slug of the source's team_members snapshot. The literal 'unowned' names an ownership gap, not an org team, and has no merge trend.
     */
    owner_team: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsTrunkQuarantineParams = {
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
    /**
     * Run scope for workflow health: 'all' (default) includes every run; 'pull_request' includes runs attributed to pull requests, excluding default-branch (master/main) runs. Fork PRs carry no PR attribution (a GitHub limitation), so 'pull_request' covers same-repo PRs only. Any other value is a 400.
     */
    run_scope?: EngineeringAnalyticsWorkflowHealthRunScope
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsWorkflowHealthRunScope =
    (typeof EngineeringAnalyticsWorkflowHealthRunScope)[keyof typeof EngineeringAnalyticsWorkflowHealthRunScope]

export const EngineeringAnalyticsWorkflowHealthRunScope = {
    All: 'all',
    PullRequest: 'pull_request',
} as const

export type EngineeringAnalyticsWorkflowJobsParams = {
    /**
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
     * 'owner/name' repository to scope to when the selected source syncs several repositories (from the `sources` list). Defaults to the source's first repository.
     */
    repo?: string
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
