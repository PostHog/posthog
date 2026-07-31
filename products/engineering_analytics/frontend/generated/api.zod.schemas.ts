/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const WorkflowCostApi = zod.object({
    workflow_name: zod.string().describe('GitHub Actions workflow name this cost is for.'),
    billable_minutes: zod.number().describe('Billable (self-hosted) minutes for this workflow within the scope.'),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe('Estimated dollar cost for this workflow, or null when nothing was costable.'),
    costed_jobs: zod.number().describe('Costed jobs for this workflow (billable Linux runner, finished).'),
    unsettled_jobs: zod.number().describe('Billable Linux jobs still queued\/running for this workflow.'),
    excluded_jobs: zod.number().describe('Provider-hosted\/non-Linux jobs for this workflow, outside the estimate.'),
})

export type WorkflowCostApi = zod.input<typeof WorkflowCostApi>
export type WorkflowCostApiOutput = zod.output<typeof WorkflowCostApi>

export const BrokenTestRowStateEnumApi = zod
    .enum(['breaking_master', 'novel_burst', 'potentially_resolved', 'flaky', 'pr_only'])
    .describe(
        '\* `breaking_master` - BREAKING_MASTER\n\* `novel_burst` - NOVEL_BURST\n\* `potentially_resolved` - POTENTIALLY_RESOLVED\n\* `flaky` - FLAKY\n\* `pr_only` - PR_ONLY'
    )

export type BrokenTestRowStateEnumApi = zod.input<typeof BrokenTestRowStateEnumApi>
export type BrokenTestRowStateEnumApiOutput = zod.output<typeof BrokenTestRowStateEnumApi>

export const BrokenTestRowApi = zod.object({
    fingerprint: zod
        .string()
        .describe(
            "Stable identity of this distinct failure: the failing test's node id plus a normalized error signature, so the same failure across runs groups into one row."
        ),
    test_id: zod.string().describe("The pytest node id from the CI 'FAILED <id>' line — the failing test."),
    error_signature: zod
        .string()
        .describe(
            'The trailing failure detail with volatile bits (numbers, hashes) normalized, shared across runs of the same failure. Empty when the FAILED line carried no detail.'
        ),
    job_name: zod
        .string()
        .describe(
            'The CI job the failure most recently came from. Matched against default-branch job status to decide whether trunk is currently broken by it.'
        ),
    repo: zod.string().describe("'owner\/name' repository the failure belongs to."),
    state: BrokenTestRowStateEnumApi.describe(
        "The classifier's verdict on how this failure is behaving right now: 'breaking_master' (failing on trunk, latest trunk run still red), 'novel_burst' (new within a day and spreading across branches, not on trunk yet), 'potentially_resolved' (hit trunk but trunk is green again), 'flaky' (sporadic across branches over more than a day), or 'pr_only' (confined to one branch — one PR's own problem).\n\n\* `breaking_master` - BREAKING_MASTER\n\* `novel_burst` - NOVEL_BURST\n\* `potentially_resolved` - POTENTIALLY_RESOLVED\n\* `flaky` - FLAKY\n\* `pr_only` - PR_ONLY"
    ),
    first_seen: zod.iso
        .datetime({ offset: true })
        .describe('Earliest failure line for this fingerprint in the analysis window.'),
    last_seen: zod.iso
        .datetime({ offset: true })
        .describe('Most recent failure line for this fingerprint in the analysis window.'),
    occurrences: zod
        .number()
        .describe(
            "Total failure lines for this fingerprint in the window. An absolute count, never a rate — passing runs aren't in this data."
        ),
    branches: zod.number().describe('Distinct branches the failure appeared on in the window.'),
    master_hits: zod
        .number()
        .describe('Failure lines on the default branch (master\/main). 0 means it never reached trunk.'),
    latest_run_id: zod
        .number()
        .describe(
            'The most recent failing workflow run for this fingerprint — pass it to run_failure_logs to fetch the actual failing log lines.'
        ),
    latest_branch: zod.string().describe('The branch of the most recent failing run.'),
    trend_24h: zod
        .array(zod.number())
        .optional()
        .describe(
            'Hourly failure counts over the last 24 hours, oldest first (fixed 24-slot array), for the row sparkline. All zeros when nothing failed in the last day.'
        ),
})

export type BrokenTestRowApi = zod.input<typeof BrokenTestRowApi>
export type BrokenTestRowApiOutput = zod.output<typeof BrokenTestRowApi>

export const BrokenTestsResultApi = zod.object({
    rows: zod
        .array(BrokenTestRowApi)
        .describe('Classified failures ranked by triage urgency — breaking trunk first, single-PR failures last.'),
    breaking_master_jobs: zod
        .array(zod.string())
        .describe(
            "Default-branch job names whose latest completed run is failing — the 'what's on fire right now' summary. Empty when the job-level source isn't synced or trunk is green."
        ),
    window_days: zod.number().describe('Length in days of the analysis window the counts cover.'),
    truncated: zod
        .boolean()
        .describe('True when more failures qualified than the cap; `rows` is the top `limit` by urgency.'),
    limit: zod.number().describe('Maximum number of rows returned.'),
})

export type BrokenTestsResultApi = zod.input<typeof BrokenTestsResultApi>
export type BrokenTestsResultApiOutput = zod.output<typeof BrokenTestsResultApi>

export const SyncStatusEnumApi = zod
    .enum(['running', 'completed', 'failed'])
    .describe('\* `running` - RUNNING\n\* `completed` - COMPLETED\n\* `failed` - FAILED')

export type SyncStatusEnumApi = zod.input<typeof SyncStatusEnumApi>
export type SyncStatusEnumApiOutput = zod.output<typeof SyncStatusEnumApi>

export const CISignalsConfigApi = zod.object({
    configured: zod.boolean().describe('Whether this project has ever configured CI signals.'),
    enabled: zod.boolean().describe('Whether every CI signal detector is enabled.'),
    sync_status: zod
        .union([SyncStatusEnumApi, zod.null()])
        .describe(
            'Aggregate sync status for pull requests, workflow runs, and workflow jobs.\n\n\* `running` - RUNNING\n\* `completed` - COMPLETED\n\* `failed` - FAILED'
        ),
})

export type CISignalsConfigApi = zod.input<typeof CISignalsConfigApi>
export type CISignalsConfigApiOutput = zod.output<typeof CISignalsConfigApi>

export const CISignalsConfigUpdateApi = zod.object({
    enabled: zod.boolean().describe('Enable or disable every CI signal detector atomically.'),
})

export type CISignalsConfigUpdateApi = zod.input<typeof CISignalsConfigUpdateApi>
export type CISignalsConfigUpdateApiOutput = zod.output<typeof CISignalsConfigUpdateApi>

export const CICardSummaryApi = zod.object({
    open_prs: zod.number().describe('Count of open pull requests.'),
    repos: zod.number().describe('Distinct repositories with at least one open pull request.'),
    stuck: zod.number().describe('Open, non-draft, non-bot pull requests older than 7 days.'),
    failing_ci: zod
        .number()
        .describe(
            'Open pull requests with at least one failing latest CI run. May lag until the workflow_run webhook settles late completions.'
        ),
})

export type CICardSummaryApi = zod.input<typeof CICardSummaryApi>
export type CICardSummaryApiOutput = zod.output<typeof CICardSummaryApi>

export const RepoRefApi = zod.object({
    provider: zod.string().describe("Code host provider, e.g. 'github'."),
    owner: zod.string().describe('Repository owner or organization.'),
    name: zod.string().describe('Repository name.'),
})

export type RepoRefApi = zod.input<typeof RepoRefApi>
export type RepoRefApiOutput = zod.output<typeof RepoRefApi>

export const CIFailureLogLineApi = zod.object({
    original_line: zod
        .number()
        .nullable()
        .describe(
            "1-based line number in the full pre-thinning job log, or null for a '... N lines omitted ...' marker. The gap between consecutive values is how many lines were elided."
        ),
    text: zod.string().describe('The log line text, or the omission-marker text.'),
})

export type CIFailureLogLineApi = zod.input<typeof CIFailureLogLineApi>
export type CIFailureLogLineApiOutput = zod.output<typeof CIFailureLogLineApi>

export const CIJobFailureLogApi = zod.object({
    lines: zod
        .array(CIFailureLogLineApi)
        .describe('The thinned failure-log lines in original order, with omission markers.'),
    job_id: zod.number().describe('GitHub Actions job id of the failed job.'),
    run_id: zod.number().describe('Workflow run id the job belongs to.'),
    conclusion: zod.string().describe("Job conclusion ('failure', 'timed_out', ...). Only failed jobs have logs."),
    branch: zod.string().describe("Git branch the run was triggered on, or '' when unknown."),
    original_total_lines: zod
        .number()
        .describe(
            "Total lines in the full job log before thinning (the denominator for each line's original_line); 0 when unknown."
        ),
    line_count: zod.number().describe('Number of lines returned for this job (after the per-job cap).'),
    truncated: zod.boolean().describe('True when the job had more failure lines than the per-job cap.'),
})

export type CIJobFailureLogApi = zod.input<typeof CIJobFailureLogApi>
export type CIJobFailureLogApiOutput = zod.output<typeof CIJobFailureLogApi>

export const CIFailureLogsApi = zod.object({
    repo: RepoRefApi.describe('Repository the pull request belongs to.'),
    jobs: zod.array(CIJobFailureLogApi).describe('Failed CI jobs with their thinned failure logs, grouped by job.'),
    pr_number: zod.number().describe('Pull request number the failure logs are for.'),
    runs_attributed: zod
        .number()
        .describe('Workflow runs attributed to the PR (across all its pushes) that were searched for logs.'),
    logs_available: zod
        .boolean()
        .describe(
            "False when no failure logs were found — CI hasn't failed, the logs aged out of the short Logs retention, or a fork PR carries no run association to resolve."
        ),
    truncated: zod.boolean().describe('True when the overall line cap across all jobs was hit.'),
})

export type CIFailureLogsApi = zod.input<typeof CIFailureLogsApi>
export type CIFailureLogsApiOutput = zod.output<typeof CIFailureLogsApi>

export const CurrentBranchHealthApi = zod.object({
    default_branch: zod
        .string()
        .describe("Detected default branch ('master' or 'main') from runs in the same 24-hour window."),
    settled_workflows: zod.number().describe('Workflows with at least one completed run in the last 24 hours.'),
    failing_workflows: zod
        .number()
        .describe('Workflows whose latest completed run in the last 24 hours failed or timed out.'),
    failing_workflow_names: zod
        .array(zod.string())
        .describe(
            'Alphabetical preview of failing workflow names, capped at 20; use failing_workflows for the complete count.'
        ),
})

export type CurrentBranchHealthApi = zod.input<typeof CurrentBranchHealthApi>
export type CurrentBranchHealthApiOutput = zod.output<typeof CurrentBranchHealthApi>

export const CITestRunnerEnumApi = zod.enum(['pytest', 'jest']).describe('\* `pytest` - PYTEST\n\* `jest` - JEST')

export type CITestRunnerEnumApi = zod.input<typeof CITestRunnerEnumApi>
export type CITestRunnerEnumApiOutput = zod.output<typeof CITestRunnerEnumApi>

export const FlakyTestItemClassificationEnumApi = zod
    .enum(['confirmed_flake', 'suspected_regression', 'quarantined'])
    .describe(
        '\* `confirmed_flake` - CONFIRMED_FLAKE\n\* `suspected_regression` - SUSPECTED_REGRESSION\n\* `quarantined` - QUARANTINED'
    )

export type FlakyTestItemClassificationEnumApi = zod.input<typeof FlakyTestItemClassificationEnumApi>
export type FlakyTestItemClassificationEnumApiOutput = zod.output<typeof FlakyTestItemClassificationEnumApi>

export const FlakyTestItemApi = zod.object({
    runner: CITestRunnerEnumApi.describe(
        "Test runner that emitted this signal: 'pytest' or 'jest'.\n\n\* `pytest` - PYTEST\n\* `jest` - JEST"
    ),
    nodeid: zod
        .string()
        .describe(
            'Runner-specific stable test identity (the CI span name). This is a grouping key, not necessarily runnable; use `selector` to run or quarantine the test.'
        ),
    selector: zod
        .string()
        .describe(
            'Runnable pytest or Jest selector. Exact when the CI reporter emitted it; older pytest spans use a best-effort reconstruction from the nodeid.'
        ),
    classification: FlakyTestItemClassificationEnumApi.describe(
        'confirmed_flake: one commit both failed and passed the test (a re-run attempt went green, or an in-job retry recovered it), so it is provably nondeterministic. quarantined: a tolerated failure was recorded while it was masked. suspected_regression: only failures were recorded, which is absence of proof, not proof that it is a real break.\n\n\* `confirmed_flake` - CONFIRMED_FLAKE\n\* `suspected_regression` - SUSPECTED_REGRESSION\n\* `quarantined` - QUARANTINED'
    ),
    same_commit_recovery_run_count: zod
        .number()
        .describe(
            "Runs where one commit both failed and passed the test: a 'Re-run failed jobs' attempt went green on the same commit, or an in-job pytest retry (tests hand-marked @pytest.mark.flaky(reruns=N)) recovered it. A pass in a different run is a different commit and never counts."
        ),
    failed_run_count: zod
        .number()
        .describe(
            'Distinct CI runs whose recorded outcome was failed or error. A run counts once however many matrix legs it failed in.'
        ),
    failed_pr_count: zod
        .number()
        .describe(
            'Distinct pull requests among the failed runs. Failures on master or unattributed branches carry no PR number and are excluded here (still in failed_run_count).'
        ),
    master_failed_run_count: zod
        .number()
        .describe(
            "Failed runs on the default branch (master\/main approximation): the 'matters right now' signal that a test is breaking the trunk, not just PR branches."
        ),
    quarantined_failed_run_count: zod
        .number()
        .describe(
            'Runs where the test recorded a tolerated failure while quarantined: already masked in CI, still failing.'
        ),
    last_signal_at: zod.iso
        .datetime({ offset: true })
        .describe('Most recent failure, recovery, or quarantined-failure run for this test in the window.'),
})

export type FlakyTestItemApi = zod.input<typeof FlakyTestItemApi>
export type FlakyTestItemApiOutput = zod.output<typeof FlakyTestItemApi>

export const FlakyTestListApi = zod.object({
    items: zod
        .array(FlakyTestItemApi)
        .describe('Tests worth acting on now, ranked by blast radius: master failures, then PRs hit, then runs.'),
    truncated: zod
        .boolean()
        .describe('True when more tests qualified than the cap; `items` is the highest-ranked `limit` rows.'),
    limit: zod.number().describe('Maximum number of tests returned in `items`.'),
})

export type FlakyTestListApi = zod.input<typeof FlakyTestListApi>
export type FlakyTestListApiOutput = zod.output<typeof FlakyTestListApi>

export const WorkflowJobAggregateApi = zod.object({
    job_name: zod
        .string()
        .describe(
            "De-sharded job name: the matrix '(G\/N)' suffix is stripped and unexpanded '${{ matrix.\* }}' templates are collapsed, so shards of one matrix aggregate together."
        ),
    job_count: zod.number().describe('Job instances observed in the window (all shards, all attempts).'),
    shard_count: zod.number().describe('Distinct raw job names inside the group - the observed matrix width.'),
    runs_in: zod.number().describe('Distinct workflow runs the job appeared in.'),
    run_share: zod
        .number()
        .nullable()
        .describe(
            "runs_in divided by the workflow's total runs in the window; below 1.0 means the job is conditional and skips some runs. Null when the workflow had no runs."
        ),
    queue_p50_seconds: zod
        .number()
        .nullable()
        .describe(
            'Median queue wait (created to started) in seconds - where runner-capacity problems hide. Null when nothing started.'
        ),
    p50_seconds: zod
        .number()
        .nullable()
        .describe(
            'Median duration of successful job instances, in seconds — cancelled and failed instances end early and would bias the percentile. Null if none succeeded.'
        ),
    p95_seconds: zod
        .number()
        .nullable()
        .describe(
            '95th-percentile duration of successful job instances, in seconds — cancelled and failed instances end early and would bias the percentile. Null if none succeeded.'
        ),
    failure_rate: zod
        .number()
        .nullable()
        .describe("Decisive failures ('failure', 'timed_out') over completed instances (0-1). Null if none completed."),
    retry_job_count: zod.number().describe('Job instances that ran on a 2nd+ run attempt - retry pressure.'),
    billable_minutes: zod
        .number()
        .nullable()
        .describe(
            "Billable (self-hosted) minutes across the group's instances; null when every instance ran on an unknown tier."
        ),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe(
            'Estimated cost in USD via the runner-tier rate ladder; null when every instance ran on an unknown tier.'
        ),
})

export type WorkflowJobAggregateApi = zod.input<typeof WorkflowJobAggregateApi>
export type WorkflowJobAggregateApiOutput = zod.output<typeof WorkflowJobAggregateApi>

export const MasterFailureGroupApi = zod.object({
    repo: RepoRefApi.describe('Repository the failures occurred in.'),
    workflow_name: zod.string().describe('GitHub Actions workflow name the failing runs belong to.'),
    failed_job: zod
        .string()
        .describe(
            "De-sharded failing job name (matrix '(G\/N)' suffix stripped) — the group's failure signature together with the workflow. '' when the job-level source isn't synced and the group degrades to workflow level."
        ),
    run_count: zod.number().describe('Distinct failing default-branch runs in this group within the window.'),
    first_seen: zod.iso.datetime({ offset: true }).describe('When the oldest failing run in the group started.'),
    last_seen: zod.iso.datetime({ offset: true }).describe('When the newest failing run in the group started.'),
    latest_run_id: zod.number().describe('Run id of the newest failing run — the drill-down anchor.'),
})

export type MasterFailureGroupApi = zod.input<typeof MasterFailureGroupApi>
export type MasterFailureGroupApiOutput = zod.output<typeof MasterFailureGroupApi>

export const RunCostApi = zod.object({
    run_id: zod.number().describe('GitHub Actions run id this cost is for.'),
    run_attempt: zod.number().describe('Re-run attempt number; 1 for the first attempt.'),
    billable_minutes: zod.number().describe('Billable (self-hosted) minutes for this run attempt.'),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe('Estimated dollar cost for this run attempt, or null when nothing was costable.'),
})

export type RunCostApi = zod.input<typeof RunCostApi>
export type RunCostApiOutput = zod.output<typeof RunCostApi>

export const PRLLMSpendApi = zod.object({
    cost_usd: zod
        .number()
        .describe(
            'Total agent LLM token cost in USD attributed to this PR (sum of $ai_total_cost_usd over the matched $ai_generation events).'
        ),
    input_tokens: zod.number().describe('Total input (prompt) tokens across the attributed generations.'),
    output_tokens: zod.number().describe('Total output (completion) tokens across the attributed generations.'),
    generations: zod
        .number()
        .describe('Number of $ai_generation events attributed to this PR by git branch ($ai_git_branch).'),
})

export type PRLLMSpendApi = zod.input<typeof PRLLMSpendApi>
export type PRLLMSpendApiOutput = zod.output<typeof PRLLMSpendApi>

export const PRCostSummaryApi = zod.object({
    by_workflow: zod.array(WorkflowCostApi).describe('Same spend broken down per workflow.'),
    by_run: zod.array(RunCostApi).describe('Same spend broken down per workflow run, keyed by (run_id, run_attempt).'),
    llm_spend: zod
        .union([PRLLMSpendApi, zod.null()])
        .optional()
        .describe(
            'Agent LLM token spend attributed to this PR by git branch ($ai_git_branch), or null when no generation matched — independent of the CI cost figures, so it can be present even when jobs_available is false. The UI hides the row when null.'
        ),
    jobs_available: zod
        .boolean()
        .describe(
            "False when the job-level source (github_workflow_jobs) isn't synced — every figure is then zero\/null and the cost cards should be hidden."
        ),
    billable_minutes: zod
        .number()
        .describe(
            "Billable CI minutes: each costed (self-hosted) job's elapsed time, summed. Parallel jobs add up, so this is compute time spent, not wall-clock run duration."
        ),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe(
            'Estimated dollar cost (sum of per-job estimates: elapsed x tier multiplier x reference rate). Null when no job was costable.'
        ),
    costed_jobs: zod.number().describe('Jobs counted in the estimate (billable Linux runner, finished).'),
    unsettled_jobs: zod
        .number()
        .describe('Billable Linux jobs still queued\/running (no elapsed) — excluded from the estimate.'),
    excluded_jobs: zod
        .number()
        .describe('Jobs on provider-hosted (GitHub-hosted, free) or non-Linux runners — outside the estimate.'),
})

export type PRCostSummaryApi = zod.input<typeof PRCostSummaryApi>
export type PRCostSummaryApiOutput = zod.output<typeof PRCostSummaryApi>

export const AuthorApi = zod.object({
    handle: zod.string().describe('Login handle of the pull request author.'),
    display_name: zod.string().describe('Human-readable name; equals the handle in v1.'),
    avatar_url: zod.string().describe("URL of the author's avatar image."),
    is_bot: zod.boolean().describe('True if the author is a bot (handle ends in [bot] or is a known bot).'),
})

export type AuthorApi = zod.input<typeof AuthorApi>
export type AuthorApiOutput = zod.output<typeof AuthorApi>

export const EngineeringAnalyticsPRStateEnumApi = zod
    .enum(['open', 'closed', 'merged'])
    .describe('\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED')

export type EngineeringAnalyticsPRStateEnumApi = zod.input<typeof EngineeringAnalyticsPRStateEnumApi>
export type EngineeringAnalyticsPRStateEnumApiOutput = zod.output<typeof EngineeringAnalyticsPRStateEnumApi>

export const PullRequestApi = zod.object({
    author: AuthorApi.describe('The pull request author.'),
    repo: RepoRefApi.describe('Repository the pull request belongs to.'),
    id: zod.number().describe('GitHub pull request id.'),
    number: zod.number().describe('Pull request number within the repository.'),
    title: zod.string().describe('Pull request title.'),
    state: EngineeringAnalyticsPRStateEnumApi.describe(
        "Derived state: 'open', 'closed', or 'merged'.\n\n\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED"
    ),
    is_draft: zod.boolean().describe('True if the pull request is a draft.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the pull request was opened.'),
    merged_at: zod.iso.datetime({ offset: true }).nullable().describe('When the pull request was merged, or null.'),
    closed_at: zod.iso.datetime({ offset: true }).nullable().describe('When the pull request was closed, or null.'),
})

export type PullRequestApi = zod.input<typeof PullRequestApi>
export type PullRequestApiOutput = zod.output<typeof PullRequestApi>

export const PRLifecycleEventKindEnumApi = zod
    .enum(['opened', 'ci_started', 'ci_finished', 'merged', 'closed'])
    .describe(
        '\* `opened` - OPENED\n\* `ci_started` - CI_STARTED\n\* `ci_finished` - CI_FINISHED\n\* `merged` - MERGED\n\* `closed` - CLOSED'
    )

export type PRLifecycleEventKindEnumApi = zod.input<typeof PRLifecycleEventKindEnumApi>
export type PRLifecycleEventKindEnumApiOutput = zod.output<typeof PRLifecycleEventKindEnumApi>

export const PRLifecycleEventApi = zod.object({
    kind: PRLifecycleEventKindEnumApi.describe(
        'Event kind: opened, ci_started, ci_finished, merged, or closed.\n\n\* `opened` - OPENED\n\* `ci_started` - CI_STARTED\n\* `ci_finished` - CI_FINISHED\n\* `merged` - MERGED\n\* `closed` - CLOSED'
    ),
    at: zod.iso.datetime({ offset: true }).describe('When the event occurred.'),
    detail: zod.string().nullish().describe('Optional detail, e.g. workflow name and conclusion for CI events.'),
    run_id: zod
        .number()
        .nullish()
        .describe('GitHub Actions run id for ci_started\/ci_finished events, null otherwise.'),
})

export type PRLifecycleEventApi = zod.input<typeof PRLifecycleEventApi>
export type PRLifecycleEventApiOutput = zod.output<typeof PRLifecycleEventApi>

export const MetricQualityEnumApi = zod
    .enum(['precise', 'coarse', 'partial'])
    .describe('\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL')

export type MetricQualityEnumApi = zod.input<typeof MetricQualityEnumApi>
export type MetricQualityEnumApiOutput = zod.output<typeof MetricQualityEnumApi>

export const PRLifecycleApi = zod.object({
    pull_request: PullRequestApi.describe('The pull request header.'),
    events: zod.array(PRLifecycleEventApi).describe('Lifecycle events ordered by time.'),
    metric_quality: MetricQualityEnumApi.optional().describe(
        "Always 'partial' — CI events only; reviews and comments are not yet available.\n\n\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL"
    ),
})

export type PRLifecycleApi = zod.input<typeof PRLifecycleApi>
export type PRLifecycleApiOutput = zod.output<typeof PRLifecycleApi>

export const WorkflowRunDetailApi = zod.object({
    repo: RepoRefApi.describe('Repository the run belongs to.'),
    id: zod.number().describe('GitHub Actions run id.'),
    workflow_name: zod.string().describe('GitHub Actions workflow name.'),
    head_sha: zod.string().describe('Commit SHA the run was triggered on.'),
    head_branch: zod.string().describe('Git branch the run was triggered on.'),
    status: zod.string().describe("Raw run status: 'queued', 'in_progress', 'completed', etc."),
    conclusion: zod
        .string()
        .nullable()
        .describe(
            "Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', 'action_required', ...), or null while still in progress."
        ),
    run_started_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the run started, or null for a queued\/barely-started run.'),
    updated_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the run was last updated (its finish time once completed), or null when unstarted.'),
    duration_seconds: zod.number().nullable().describe('Wall-clock duration in seconds; null until the run completes.'),
    run_attempt: zod.number().describe('Re-run attempt number; 1 for the first attempt.'),
    pr_number: zod
        .number()
        .describe(
            "Pull request this run ran for, from the run's own-repo PR association; 0 when unattributed (a default-branch push, or a fork PR)."
        ),
    commit_pr_number: zod
        .number()
        .nullable()
        .describe(
            "Pull request whose merge produced this run's head commit, resolved through the merged pull request's merge commit and falling back to the commit subject's '(#NNNN)' suffix. Null when neither resolves. The only PR attribution a default-branch push has: read pr_number first and fall back to this."
        ),
})

export type WorkflowRunDetailApi = zod.input<typeof WorkflowRunDetailApi>
export type WorkflowRunDetailApiOutput = zod.output<typeof WorkflowRunDetailApi>

export const CIStatusRollupApi = zod.object({
    runs: zod.number().describe("Distinct workflows run on the PR's head SHA."),
    passing: zod.number().describe("Latest runs that completed with conclusion 'success'."),
    failing: zod.number().describe("Latest runs that completed with conclusion 'failure' or 'timed_out'."),
    pending: zod.number().describe('Latest runs not yet completed (queued or in progress).'),
    failing_workflows: zod
        .array(zod.string())
        .optional()
        .describe(
            'The workflow names behind `failing`, sorted - names what is failing instead of leaving a bare count.'
        ),
})

export type CIStatusRollupApi = zod.input<typeof CIStatusRollupApi>
export type CIStatusRollupApiOutput = zod.output<typeof CIStatusRollupApi>

export const PushCISampleApi = zod.object({
    head_sha: zod.string().describe('Head commit SHA of this push (CI round).'),
    started_at: zod.iso.datetime({ offset: true }).describe('Earliest workflow-run start on this push.'),
    wall_seconds: zod
        .number()
        .nullable()
        .describe(
            'Wall-clock CI seconds for this push: earliest run start to latest completed run end. Null while nothing has completed.'
        ),
    failed: zod
        .boolean()
        .describe("True when any latest-per-workflow run on this push concluded 'failure' or 'timed_out'."),
    pending: zod.boolean().describe("True when any latest-per-workflow run on this push hasn't completed yet."),
})

export type PushCISampleApi = zod.input<typeof PushCISampleApi>
export type PushCISampleApiOutput = zod.output<typeof PushCISampleApi>

export const PullRequestListItemApi = zod.object({
    author: AuthorApi.describe('The pull request author.'),
    repo: RepoRefApi.describe('Repository the pull request belongs to.'),
    ci: CIStatusRollupApi.describe('CI status from the latest workflow runs on the head SHA.'),
    push_history: zod
        .array(PushCISampleApi)
        .describe(
            "This PR's CI rounds oldest-first, capped to the most recent pushes - one sample per push for the push-history sparkline. `pushes` stays the uncapped count."
        ),
    number: zod.number().describe('Pull request number within the repository.'),
    title: zod.string().describe('Pull request title.'),
    state: EngineeringAnalyticsPRStateEnumApi.describe(
        "Derived state: 'open', 'closed', or 'merged'.\n\n\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED"
    ),
    is_draft: zod.boolean().describe('True if the pull request is a draft.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the pull request was opened.'),
    merged_at: zod.iso.datetime({ offset: true }).nullable().describe('When the pull request was merged, or null.'),
    open_to_merge_seconds: zod
        .number()
        .nullable()
        .describe(
            'Coarse open-to-merge time in seconds (merged_at - created_at; fuses draft and ready-for-review time). Null until merged.'
        ),
    labels: zod.array(zod.string()).describe('GitHub label names on the pull request.'),
    pushes: zod
        .number()
        .describe(
            'CI triggers attributed to this PR: distinct head SHAs across its workflow runs. Fork-PR runs are unattributed.'
        ),
    rerun_cycles: zod.number().describe('Workflow runs attributed to this PR that were a 2nd+ attempt (a re-run).'),
    estimated_cost_usd: zod
        .number()
        .nullish()
        .describe(
            "Estimated CI cost in USD summed over this PR's jobs (billable runners only). Null when nothing was costable or the job-level source isn't synced."
        ),
    billable_minutes: zod
        .number()
        .nullish()
        .describe("Billable (self-hosted) minutes summed over this PR's jobs. Null when the job source isn't synced."),
})

export type PullRequestListItemApi = zod.input<typeof PullRequestListItemApi>
export type PullRequestListItemApiOutput = zod.output<typeof PullRequestListItemApi>

export const PullRequestListApi = zod.object({
    items: zod.array(PullRequestListItemApi).describe('Pull requests, newest first, capped at `limit`.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more pull requests match than the cap; `items` is the newest `limit` rows and the aggregate counts in ci_cards can exceed it.'
        ),
    limit: zod.number().describe('Maximum number of pull requests returned in `items`.'),
})

export type PullRequestListApi = zod.input<typeof PullRequestListApi>
export type PullRequestListApiOutput = zod.output<typeof PullRequestListApi>

export const QuarantineModeEnumApi = zod.enum(['run', 'skip']).describe('\* `run` - RUN\n\* `skip` - SKIP')

export type QuarantineModeEnumApi = zod.input<typeof QuarantineModeEnumApi>
export type QuarantineModeEnumApiOutput = zod.output<typeof QuarantineModeEnumApi>

export const LifecycleEnumApi = zod
    .enum(['active', 'expiring_soon', 'in_grace', 'overdue'])
    .describe(
        '\* `active` - ACTIVE\n\* `expiring_soon` - EXPIRING_SOON\n\* `in_grace` - IN_GRACE\n\* `overdue` - OVERDUE'
    )

export type LifecycleEnumApi = zod.input<typeof LifecycleEnumApi>
export type LifecycleEnumApiOutput = zod.output<typeof LifecycleEnumApi>

export const SelectorKindEnumApi = zod
    .enum(['product', 'file', 'directory', 'test'])
    .describe('\* `product` - PRODUCT\n\* `file` - FILE\n\* `directory` - DIRECTORY\n\* `test` - TEST')

export type SelectorKindEnumApi = zod.input<typeof SelectorKindEnumApi>
export type SelectorKindEnumApiOutput = zod.output<typeof SelectorKindEnumApi>

export const QuarantineEntryApi = zod.object({
    id: zod
        .string()
        .describe("Test selector: an exact test id, a file, a directory, a class prefix, or 'product:<dashed-name>'."),
    runner: zod.string().describe("Test runner the selector targets, e.g. 'pytest' or 'jest'."),
    reason: zod.string().describe('Why the test was quarantined.'),
    owner: zod.string().describe('GitHub team or user handle responsible for the fix.'),
    issue: zod.string().describe('Tracking issue URL, or empty when none was filed.'),
    added: zod.iso.date().describe('ISO date the entry was added.'),
    expires: zod.iso.date().describe('ISO date the quarantine expires; past it the test blocks CI normally again.'),
    mode: QuarantineModeEnumApi.describe(
        "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all).\n\n\* `run` - RUN\n\* `skip` - SKIP"
    ),
    lifecycle: LifecycleEnumApi.describe(
        "Expiry classification: 'active' (>7 days left), 'expiring_soon' (0-7 days left), 'in_grace' (expired up to 7 days ago), 'overdue' (expired beyond the grace period).\n\n\* `active` - ACTIVE\n\* `expiring_soon` - EXPIRING_SOON\n\* `in_grace` - IN_GRACE\n\* `overdue` - OVERDUE"
    ),
    days_until_expiry: zod.number().describe('Days until the entry expires; negative once past expiry.'),
    selector_kind: SelectorKindEnumApi.describe(
        "What the selector covers: 'test' (contains '::'), 'file', 'directory', or 'product'.\n\n\* `product` - PRODUCT\n\* `file` - FILE\n\* `directory` - DIRECTORY\n\* `test` - TEST"
    ),
})

export type QuarantineEntryApi = zod.input<typeof QuarantineEntryApi>
export type QuarantineEntryApiOutput = zod.output<typeof QuarantineEntryApi>

export const QuarantineFileApi = zod.object({
    entries: zod
        .array(QuarantineEntryApi)
        .describe(
            'Quarantined selectors, most urgent first (overdue, in_grace, expiring_soon, active), then by soonest expiry.'
        ),
    repo: zod
        .union([RepoRefApi, zod.null()])
        .describe(
            "Repository the file was read from. Null in local-dev mode, where the server's own checkout is read."
        ),
    available: zod
        .boolean()
        .describe('False when the repository has no quarantine file (not an error) or it could not be fetched.'),
    parse_errors: zod
        .array(zod.string())
        .describe(
            'Contract violations (malformed JSON, bad entries) or fetch failures. Malformed entries are dropped; well-formed ones are kept.'
        ),
    parse_warnings: zod.array(zod.string()).describe('Forward-compatibility notices, e.g. unknown entry fields.'),
    source_url: zod
        .string()
        .describe('GitHub blob URL of the quarantine file, or empty when read locally or unavailable.'),
    generated_at: zod.iso
        .datetime({ offset: true })
        .describe('When this snapshot was computed (UTC); expiry math uses this clock.'),
})

export type QuarantineFileApi = zod.input<typeof QuarantineFileApi>
export type QuarantineFileApiOutput = zod.output<typeof QuarantineFileApi>

export const OperationEnumApi = zod
    .enum(['quarantine', 'extend', 'remove'])
    .describe('\* `quarantine` - QUARANTINE\n\* `extend` - EXTEND\n\* `remove` - REMOVE')

export type OperationEnumApi = zod.input<typeof OperationEnumApi>
export type OperationEnumApiOutput = zod.output<typeof OperationEnumApi>

export const QuarantineRequestRunnerEnumApi = zod
    .enum(['pytest', 'jest', 'playwright'])
    .describe('\* `pytest` - PYTEST\n\* `jest` - JEST\n\* `playwright` - PLAYWRIGHT')

export type QuarantineRequestRunnerEnumApi = zod.input<typeof QuarantineRequestRunnerEnumApi>
export type QuarantineRequestRunnerEnumApiOutput = zod.output<typeof QuarantineRequestRunnerEnumApi>

export const QuarantineRequestApi = zod.object({
    operation: OperationEnumApi.describe(
        "What to do: 'quarantine' (add or replace an entry and file a tracking issue), 'extend' (re-stamp an existing entry's expiry, reusing its issue), or 'remove' (delete the entry). All three open a pull request.\n\n\* `quarantine` - QUARANTINE\n\* `extend` - EXTEND\n\* `remove` - REMOVE"
    ),
    selector: zod
        .string()
        .describe(
            "Test selector to act on: an exact test id, a file, a directory, a class prefix, or 'product:<dashed-name>'."
        ),
    runner: zod
        .union([QuarantineRequestRunnerEnumApi, zod.null()])
        .optional()
        .describe(
            "Test runner the selector targets: 'pytest', 'jest', or 'playwright'. Existing entries and Jest file extensions are inferred for older clients that omit it; other selectors default to 'pytest'.\n\n\* `pytest` - PYTEST\n\* `jest` - JEST\n\* `playwright` - PLAYWRIGHT"
        ),
    repo: zod
        .string()
        .nullish()
        .describe("Optional 'owner\/name' repository override; defaults to the team's most active repo."),
    reason: zod
        .string()
        .optional()
        .describe('Why the test is quarantined. Required for quarantine and extend; ignored by remove.'),
    owner: zod
        .string()
        .optional()
        .describe(
            "GitHub team or user handle responsible for the fix, e.g. '@PostHog\/team-x'. Required for quarantine and extend."
        ),
    issue: zod
        .string()
        .optional()
        .describe(
            'Existing tracking issue URL, carried forward on extend and remove. Ignored by quarantine, which files a fresh issue.'
        ),
    expires: zod.iso
        .date()
        .nullish()
        .describe(
            'ISO date the quarantine expires (at most 30 days out). Defaults to 14 days from today. Ignored by remove.'
        ),
    mode: QuarantineModeEnumApi.optional().describe(
        "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all). Defaults to 'run'.\n\n\* `run` - RUN\n\* `skip` - SKIP"
    ),
})

export type QuarantineRequestApi = zod.input<typeof QuarantineRequestApi>
export type QuarantineRequestApiOutput = zod.output<typeof QuarantineRequestApi>

export const QuarantineRequestResultApi = zod.object({
    pr_url: zod.string().describe('URL of the opened pull request that edits the quarantine file.'),
    issue_url: zod
        .string()
        .describe('URL of the tracking issue filed for a new quarantine; empty for extend and remove.'),
    branch: zod.string().describe('Branch the pull request was opened from.'),
})

export type QuarantineRequestResultApi = zod.input<typeof QuarantineRequestResultApi>
export type QuarantineRequestResultApiOutput = zod.output<typeof QuarantineRequestResultApi>

export const CostPerMergeBucketApi = zod.object({
    bucket_start: zod.iso
        .datetime({ offset: true })
        .describe('Bucket start, aligned to cost_series_granularity (top of hour, midnight, or Monday).'),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe(
            "Estimated Depot CI cost (USD) of all runs started in this bucket. Null when nothing was costable (no billable self-hosted Linux jobs) or the job source isn't synced."
        ),
    merges: zod.number().describe('PRs merged in this bucket (all authors, bots included).'),
    cost_per_merge_usd: zod
        .number()
        .nullable()
        .describe(
            'Rolling ratio: trailing-window CI cost divided by trailing-window merges (24 h \/ 7 d \/ 4 w to match the granularity). Null when the trailing window had no merges or no costable cost.'
        ),
})

export type CostPerMergeBucketApi = zod.input<typeof CostPerMergeBucketApi>
export type CostPerMergeBucketApiOutput = zod.output<typeof CostPerMergeBucketApi>

export const TimeToGreenBucketApi = zod.object({
    bucket_start: zod.iso
        .datetime({ offset: true })
        .describe('Bucket start, aligned to time_to_green_series_granularity (top of hour, midnight, or Monday).'),
    p50_seconds: zod
        .number()
        .nullable()
        .describe(
            'Median wall-clock seconds of successful PR-attributed CI runs started in this bucket. Null when the bucket had no successful PR run (a gap, not instant CI).'
        ),
})

export type TimeToGreenBucketApi = zod.input<typeof TimeToGreenBucketApi>
export type TimeToGreenBucketApiOutput = zod.output<typeof TimeToGreenBucketApi>

export const PassRateBucketApi = zod.object({
    bucket_start: zod.iso
        .datetime({ offset: true })
        .describe('Bucket start, aligned to success_rate_series_granularity (top of hour, midnight, or Monday).'),
    success_rate: zod
        .number()
        .nullable()
        .describe(
            'Fraction (0-1) of completed runs started in this bucket that succeeded. Null when the bucket had no completed run (a gap, not a 0% pass rate).'
        ),
})

export type PassRateBucketApi = zod.input<typeof PassRateBucketApi>
export type PassRateBucketApiOutput = zod.output<typeof PassRateBucketApi>

export const OpenToMergeBucketApi = zod.object({
    bucket_start: zod.iso
        .datetime({ offset: true })
        .describe('Bucket start, aligned to open_to_merge_series_granularity (top of hour, midnight, or Monday).'),
    p50_seconds: zod
        .number()
        .nullable()
        .describe(
            'Median merged_at - created_at seconds over PRs merged in this bucket, bots and drafts excluded. Null when nothing merged in the bucket (a gap, not instant merges).'
        ),
})

export type OpenToMergeBucketApi = zod.input<typeof OpenToMergeBucketApi>
export type OpenToMergeBucketApiOutput = zod.output<typeof OpenToMergeBucketApi>

export const RepoOverviewApi = zod.object({
    cost_series: zod
        .array(CostPerMergeBucketApi)
        .describe(
            "CI cost per merged PR across the window, oldest first, zero-filled, bucketed by cost_series_granularity. Empty when the job-level source isn't synced or include_series=false."
        ),
    time_to_green_series: zod
        .array(TimeToGreenBucketApi)
        .describe(
            'Median time-to-green (p50 successful PR-attributed CI run duration) per bucket across the window, oldest first, bucketed by time_to_green_series_granularity. Empty buckets carry null; the whole series is empty when include_series=false.'
        ),
    success_rate_series: zod
        .array(PassRateBucketApi)
        .describe(
            'CI pass rate (completed runs that succeeded, all branches) per bucket across the window, oldest first, bucketed by success_rate_series_granularity. Empty buckets carry null; the whole series is empty when include_series=false.'
        ),
    open_to_merge_series: zod
        .array(OpenToMergeBucketApi)
        .describe(
            'Median time-to-merge (p50 open_to_merge_seconds, bots\/drafts excluded) per bucket across the window, oldest first, bucketed by open_to_merge_series_granularity. Empty buckets carry null; the whole series is empty when include_series=false.'
        ),
    run_count: zod.number().describe('Workflow runs started in the window, all branches and workflows.'),
    run_count_prev: zod
        .number()
        .describe('Same count over the equal-length window immediately before date_from — the delta baseline.'),
    success_rate: zod
        .number()
        .nullable()
        .describe('Fraction of completed runs that succeeded (0-1) in the window. Null if none completed.'),
    success_rate_prev: zod
        .number()
        .nullable()
        .describe('Success rate over the previous window. Null if none completed.'),
    rerun_cycles: zod.number().describe('Runs in the window that were a 2nd+ attempt (attempt > 1).'),
    rerun_cycles_prev: zod.number().describe('Re-run cycles over the previous window.'),
    merged_pr_count: zod
        .number()
        .describe(
            'PRs merged in the window, all authors and bots included — the merge population that triggered the CI spend, so it divides cleanly into billable_minutes and estimated_cost_usd.'
        ),
    merged_pr_count_prev: zod.number().describe('Merged-PR count over the previous window.'),
    median_open_to_merge_seconds: zod
        .number()
        .nullable()
        .describe(
            'Median merged_at - created_at over PRs merged in the window, bots and drafts excluded. Coarse by design: draft and ready-for-review time are fused. Null when nothing merged.'
        ),
    median_open_to_merge_seconds_prev: zod
        .number()
        .nullable()
        .describe('The same median over the previous window. Null when nothing merged.'),
    billable_minutes: zod
        .number()
        .nullable()
        .describe("Billable (self-hosted) job minutes in the window; null when the job-level source isn't synced."),
    billable_minutes_prev: zod
        .number()
        .nullable()
        .describe("Billable minutes over the previous window; null when the job-level source isn't synced."),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe(
            "Estimated CI cost in USD (billable minutes x runner-tier rate); null when the job-level source isn't synced."
        ),
    estimated_cost_usd_prev: zod
        .number()
        .nullable()
        .describe("Estimated cost over the previous window; null when the job-level source isn't synced."),
    jobs_available: zod.boolean().describe('Whether the job-level source is synced (cost and queue figures exist).'),
    default_branch: zod.string().describe("'master' or 'main', picked by observed run volume in the window."),
    cost_series_granularity: zod
        .string()
        .describe("Bucket width of the cost_series trend, chosen to fit the window: 'hour', 'day', or 'week'."),
    time_to_green_series_granularity: zod
        .string()
        .describe("Bucket width of the time_to_green_series trend: 'hour', 'day', or 'week'."),
    success_rate_series_granularity: zod
        .string()
        .describe("Bucket width of the success_rate_series trend: 'hour', 'day', or 'week'."),
    open_to_merge_series_granularity: zod
        .string()
        .describe("Bucket width of the open_to_merge_series trend: 'hour', 'day', or 'week'."),
})

export type RepoOverviewApi = zod.input<typeof RepoOverviewApi>
export type RepoOverviewApiOutput = zod.output<typeof RepoOverviewApi>

export const WorkflowRunActivityPointApi = zod.object({
    run_id: zod.number().describe('GitHub Actions run id.'),
    conclusion: zod
        .string()
        .nullable()
        .describe(
            "Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', ...), or null while still in progress."
        ),
    run_started_at: zod.iso
        .datetime({ offset: true })
        .describe(
            "When the run started. Never null on this endpoint: runs without a parseable start timestamp are excluded from the window (they can't be plotted on the chart's time axis)."
        ),
    duration_seconds: zod.number().nullable().describe('Wall-clock duration in seconds; null until the run completes.'),
    head_branch: zod.string().describe("Git branch the run was triggered on, or '' when unknown."),
    pr_number: zod.number().describe('Attributed pull request number, or 0 when unattributed.'),
    head_sha: zod.string().describe("Head commit SHA of the run\/commit, or '' when unknown."),
})

export type WorkflowRunActivityPointApi = zod.input<typeof WorkflowRunActivityPointApi>
export type WorkflowRunActivityPointApiOutput = zod.output<typeof WorkflowRunActivityPointApi>

export const WorkflowRunActivityApi = zod.object({
    points: zod.array(WorkflowRunActivityPointApi).describe('Per-run chart points, newest first, capped at `limit`.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more runs matched than the cap; `points` is the newest `limit` runs, so the chart covers only the most recent activity, not the full window.'
        ),
    limit: zod.number().describe('Maximum number of run points returned in `points`.'),
})

export type WorkflowRunActivityApi = zod.input<typeof WorkflowRunActivityApi>
export type WorkflowRunActivityApiOutput = zod.output<typeof WorkflowRunActivityApi>

export const BranchPRMatchApi = zod.object({
    repo: zod.string().describe("Repository the pull request belongs to, as 'owner\/name'."),
    number: zod.number().describe('Pull request number within the repository — pair with `repo` to link to it.'),
    title: zod.string().nullable().describe('Pull request title, or null when the snapshot carries no title.'),
    state: zod
        .string()
        .nullable()
        .describe("Derived PR state ('open', 'closed', 'merged'), or null when the snapshot carries no state."),
})

export type BranchPRMatchApi = zod.input<typeof BranchPRMatchApi>
export type BranchPRMatchApiOutput = zod.output<typeof BranchPRMatchApi>

export const RunFailureLogsApi = zod.object({
    jobs: zod
        .array(CIJobFailureLogApi)
        .describe('Failed CI jobs of this run with their thinned failure logs, grouped by job.'),
    run_id: zod.number().describe('Workflow run id the failure logs are for.'),
    logs_available: zod
        .boolean()
        .describe(
            "False when no failure logs were found — the run didn't fail, or its logs aged out of the short Logs retention."
        ),
    truncated: zod.boolean().describe('True when the overall line cap across all jobs was hit.'),
})

export type RunFailureLogsApi = zod.input<typeof RunFailureLogsApi>
export type RunFailureLogsApiOutput = zod.output<typeof RunFailureLogsApi>

export const GitHubSourceApi = zod.object({
    id: zod.string().describe('Source id — pass back as `source_id` (with `repo`) to read this repository.'),
    repo: zod
        .string()
        .describe(
            "Repository as 'owner\/name' — pass back as `repo` to scope to it. One entry per repository a source syncs; '' if unknown."
        ),
    prefix: zod.string().describe("User-chosen warehouse table-name prefix for this source, or '' when none."),
    synced: zod
        .boolean()
        .optional()
        .describe(
            'Whether this repo has both pull_requests and workflow_runs synced (readable now). Default the picker to the first synced entry so its label matches the resolved repo.'
        ),
})

export type GitHubSourceApi = zod.input<typeof GitHubSourceApi>
export type GitHubSourceApiOutput = zod.output<typeof GitHubSourceApi>

export const TeamTestSignalApi = zod.object({
    runner: CITestRunnerEnumApi.describe(
        "Test runner that emitted this signal: 'pytest' or 'jest'.\n\n\* `pytest` - PYTEST\n\* `jest` - JEST"
    ),
    nodeid: zod.string().describe('Runner-specific test identity (the CI span name), a stable grouping key.'),
    selector: zod.string().describe('Runnable pytest or Jest selector; exact for newly emitted spans.'),
    signal_count: zod
        .number()
        .describe(
            'Runs in the current window where the test failed, errored, or a retry recovered it (quarantined failures excluded).'
        ),
    signal_count_prior: zod.number().describe('Same count over the equal-length window before date_from.'),
    last_seen_at: zod.iso
        .datetime({ offset: true })
        .describe('Most recent failure, recovery, or quarantined-failure run for this test, either window.'),
})

export type TeamTestSignalApi = zod.input<typeof TeamTestSignalApi>
export type TeamTestSignalApiOutput = zod.output<typeof TeamTestSignalApi>

export const TeamCIActivityApi = zod.object({
    tests: zod
        .array(TeamTestSignalApi)
        .describe(
            "The team's owned tests with signal in either window, ranked by the stronger window's count (the current-vs-prior pairs behind a before\/after comparison)."
        ),
    owner_team: zod.string().describe("The team slug this activity is scoped to, or 'unowned'."),
    truncated_tests: zod.boolean().describe('True when more owned tests had signal than the test cap.'),
})

export type TeamCIActivityApi = zod.input<typeof TeamCIActivityApi>
export type TeamCIActivityApiOutput = zod.output<typeof TeamCIActivityApi>

export const TeamCIHealthItemApi = zod.object({
    owner_team: zod
        .string()
        .describe(
            "Owning team slug (the CODEOWNERS handle minus '@PostHog\/', e.g. 'team-replay'), or the literal 'unowned' for tests whose spans carry no ownership stamp."
        ),
    flaky_test_count: zod
        .number()
        .describe(
            'Owned tests one commit was seen both failing and passing in the window: the same proof, and the same word, that flaky_tests calls a confirmed_flake. Compare with flaky_test_count_prior for the delta.'
        ),
    flaky_test_count_prior: zod
        .number()
        .describe('Same count over the equal-length window immediately before date_from.'),
    regression_test_count: zod
        .number()
        .describe(
            'Owned tests that failed with no recorded same-commit recovery and still hit the blast-radius bar (a master\/main failure, or min_failed_prs distinct PRs). Not flakes: absence of proof, not proof.'
        ),
    regression_test_count_prior: zod.number().describe('Same count over the prior window.'),
    failed_run_count: zod
        .number()
        .describe(
            "CI runs (not spans) where an owned test's recorded outcome was failed or error. An absolute count, not a rate: fast passing runs are not emitted."
        ),
    failed_run_count_prior: zod.number().describe('Same count over the prior window.'),
    same_commit_recovery_run_count: zod
        .number()
        .describe(
            'Runs where one commit both failed and passed an owned test: a re-run attempt went green, or an in-job retry recovered it.'
        ),
    same_commit_recovery_run_count_prior: zod.number().describe('Same count over the prior window.'),
    quarantined_failed_run_count: zod
        .number()
        .describe(
            'Runs where an owned test recorded a tolerated failure while quarantined: masked in CI, still failing.'
        ),
    quarantined_failed_run_count_prior: zod.number().describe('Same count over the prior window.'),
    last_seen_at: zod.iso
        .datetime({ offset: true })
        .describe(
            "Most recent failure, recovery, or quarantined-failure run across the team's owned tests, either window."
        ),
})

export type TeamCIHealthItemApi = zod.input<typeof TeamCIHealthItemApi>
export type TeamCIHealthItemApiOutput = zod.output<typeof TeamCIHealthItemApi>

export const TeamCIHealthListApi = zod.object({
    items: zod
        .array(TeamCIHealthItemApi)
        .describe(
            'Owning teams ranked by current flaky + failure signal, heaviest first, capped at `limit`. Teams are organizational owners of code surfaces; this never aggregates by author.'
        ),
    truncated: zod.boolean().describe('True when more teams had signal than the cap.'),
    limit: zod.number().describe('Maximum number of teams returned in `items`.'),
})

export type TeamCIHealthListApi = zod.input<typeof TeamCIHealthListApi>
export type TeamCIHealthListApiOutput = zod.output<typeof TeamCIHealthListApi>

export const TeamMergeTrendPointApi = zod.object({
    day: zod.iso.datetime({ offset: true }).describe('Start of the day bucket (team timezone), keyed on merged_at.'),
    median_seconds: zod
        .number()
        .nullable()
        .describe(
            "Median open→merge seconds of the PRs this team's members merged that day; null on a day the team merged nothing."
        ),
    average_seconds: zod
        .number()
        .nullable()
        .describe(
            'Average open→merge seconds over the same merges; diverges above the median when a few long-running PRs drag the mean. Null on a day the team merged nothing.'
        ),
    merged_count: zod.number().describe("Merged PRs behind that day's median and average."),
})

export type TeamMergeTrendPointApi = zod.input<typeof TeamMergeTrendPointApi>
export type TeamMergeTrendPointApiOutput = zod.output<typeof TeamMergeTrendPointApi>

export const TeamMergeTrendApi = zod.object({
    points: zod
        .array(TeamMergeTrendPointApi)
        .describe(
            "Daily median and average open→merge over the PRs this team's members merged, ascending by day. Coarse timing (open→merge combines draft and review time); bots excluded."
        ),
    owner_team: zod.string().describe('The team slug this trend is scoped to.'),
    has_membership_data: zod
        .boolean()
        .describe(
            'False when the GitHub source has no team_members snapshot synced: the trend then has no honest team attribution and `points` is empty.'
        ),
})

export type TeamMergeTrendApi = zod.input<typeof TeamMergeTrendApi>
export type TeamMergeTrendApiOutput = zod.output<typeof TeamMergeTrendApi>

export const WorkflowHealthBucketApi = zod.object({
    bucket_start: zod.iso
        .datetime({ offset: true })
        .describe("Bucket start, aligned to the item's granularity (top of hour, midnight, or Monday)."),
    run_count: zod.number().describe('Runs started in this bucket.'),
    completed: zod.number().describe('Runs that completed in this bucket.'),
    successes: zod.number().describe("Completed runs with conclusion 'success' in this bucket."),
    failures: zod
        .number()
        .describe(
            "Completed runs that failed in this bucket (conclusion 'failure' or 'timed_out'); excludes skipped, cancelled, and action_required runs."
        ),
})

export type WorkflowHealthBucketApi = zod.input<typeof WorkflowHealthBucketApi>
export type WorkflowHealthBucketApiOutput = zod.output<typeof WorkflowHealthBucketApi>

export const WorkflowHealthItemApi = zod.object({
    repo: RepoRefApi.describe('Repository the workflow runs in.'),
    buckets: zod
        .array(WorkflowHealthBucketApi)
        .describe('Run history across the whole window, oldest first, zero-filled, bucketed by granularity.'),
    workflow_name: zod.string().describe('GitHub Actions workflow name.'),
    run_count: zod.number().describe('Total runs started in the window.'),
    successful_run_count: zod.number(),
    conclusive_run_count: zod.number(),
    success_rate: zod
        .number()
        .nullable()
        .describe('Fraction of completed runs that succeeded (0-1). Null if no completed runs.'),
    p50_seconds: zod
        .number()
        .nullable()
        .describe(
            'Median duration in seconds over successful runs only — cancelled (superseded) and failed runs end early and would bias the percentile. Null if no run succeeded in the window.'
        ),
    p95_seconds: zod
        .number()
        .nullable()
        .describe(
            '95th-percentile duration in seconds over successful runs only — cancelled (superseded) and failed runs end early and would bias the percentile. Null if no run succeeded in the window.'
        ),
    last_failure_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe("When the most recent failing run (conclusion 'failure' or 'timed_out') started, or null."),
    latest_run_failed: zod
        .boolean()
        .nullable()
        .describe(
            "Whether the most recent completed run was a decisive failure (conclusion 'failure' or 'timed_out'). Null when no run has completed in the window. Powers the OK\/RED status badge."
        ),
    latest_run_conclusion: zod
        .string()
        .nullable()
        .describe(
            "Raw conclusion of the most recent completed run ('success', 'cancelled', 'skipped', ...), so a real pass can be told from a non-failure non-success. Null when none completed."
        ),
    latest_run_id: zod.number().nullable(),
    latest_run_attempt: zod.number().nullable(),
    granularity: zod
        .string()
        .describe("Bucket width of the `buckets` series, chosen to fit the window: 'hour', 'day', or 'week'."),
    billable_minutes: zod
        .number()
        .nullish()
        .describe(
            "Billable (self-hosted) minutes over this workflow's jobs in the window. Null when the job-level source isn't synced."
        ),
    estimated_cost_usd: zod
        .number()
        .nullish()
        .describe(
            "Estimated cost in USD over this workflow's jobs in the window. Null when nothing was costable or the job source isn't synced."
        ),
    rerun_cycles: zod
        .number()
        .optional()
        .describe('Runs in the window that were a 2nd+ attempt - retry pressure, a flakiness proxy.'),
    success_rate_prev: zod
        .number()
        .nullish()
        .describe(
            'Success rate over the equal-length window before date_from - the delta baseline. Null when that window had no completed runs.'
        ),
    percentile_run_count: zod.number().optional(),
})

export type WorkflowHealthItemApi = zod.input<typeof WorkflowHealthItemApi>
export type WorkflowHealthItemApiOutput = zod.output<typeof WorkflowHealthItemApi>

export const WorkflowJobApi = zod.object({
    id: zod.number().describe('GitHub Actions job id.'),
    run_id: zod.number().describe('The workflow run id this job belongs to.'),
    name: zod.string().describe('Job name.'),
    status: zod.string().describe("Raw job status: 'queued', 'in_progress', 'completed', etc."),
    conclusion: zod
        .string()
        .nullable()
        .describe("Job conclusion ('success', 'failure', 'cancelled', 'skipped', ...), or null while running."),
    started_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the job started, or null while still queued.'),
    completed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the job completed, or null while still running.'),
    duration_seconds: zod.number().nullable().describe('Wall-clock duration in seconds; null until the job completes.'),
    runner_provider: zod
        .string()
        .describe("Where the job ran: 'github_hosted' (free for open source), 'self_hosted' (billable), or 'unknown'."),
    runner_label: zod
        .string()
        .describe("Runner tier the job ran on (e.g. '16-core' or 'ubuntu-latest'), or '' when unknown."),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe(
            "Estimated cost in USD from runner tier + elapsed time; null when the tier is unknown or the job hasn't finished."
        ),
})

export type WorkflowJobApi = zod.input<typeof WorkflowJobApi>
export type WorkflowJobApiOutput = zod.output<typeof WorkflowJobApi>

export const WorkflowRunnerCostApi = zod.object({
    provider: zod.string().describe("'self_hosted' (billable), 'github_hosted' (free), or 'unknown'."),
    runner_label: zod.string().describe("Runner tier, e.g. '16-core' or 'ubuntu-latest'."),
    job_count: zod.number().describe('Jobs that ran on this tier for the workflow.'),
    billable_minutes: zod.number().describe('Billable minutes on this tier.'),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe('Estimated cost in USD on this tier; null for non-billable (github-hosted\/non-Linux).'),
})

export type WorkflowRunnerCostApi = zod.input<typeof WorkflowRunnerCostApi>
export type WorkflowRunnerCostApiOutput = zod.output<typeof WorkflowRunnerCostApi>
