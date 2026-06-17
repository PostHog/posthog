/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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

export interface RepoRefApi {
    /** Code host provider, e.g. 'github'. */
    provider: string
    /** Repository owner or organization. */
    owner: string
    /** Repository name. */
    name: string
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

export interface CIStatusRollupApi {
    /** Distinct workflows run on the PR's head SHA. */
    runs: number
    /** Latest runs that completed with conclusion 'success'. */
    passing: number
    /** Latest runs that completed with conclusion 'failure' or 'timed_out'. */
    failing: number
    /** Latest runs not yet completed (queued or in progress). */
    pending: number
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

export interface GitHubSourceApi {
    /** Source id — pass as `source_id` to the other endpoints to read this source. */
    id: string
    /** Connected repository as 'owner/name', or '' if unknown. */
    repo: string
    /** User-chosen warehouse table-name prefix for this source, or '' when none. */
    prefix: string
}

export interface WorkflowHealthDayApi {
    /** UTC calendar day. */
    day: string
    /** Runs started that day. */
    run_count: number
    /** Runs that completed that day. */
    completed: number
    /** Completed runs with conclusion 'success' that day. */
    successes: number
}

export interface WorkflowHealthItemApi {
    /** Repository the workflow runs in. */
    repo: RepoRefApi
    /** Daily run history across the whole window, oldest first, zero-filled. */
    daily: WorkflowHealthDayApi[]
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
     * When the most recent run with conclusion 'failure' started, or null.
     * @nullable
     */
    last_failure_at: string | null
}

export type EngineeringAnalyticsCiCardsParams = {
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
     * Optional 'owner/name' repository to disambiguate when the PR number exists in more than one connected repo.
     */
    repo?: string
    /**
     * Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.
     */
    source_id?: string
}

export type EngineeringAnalyticsPullRequestsParams = {
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

export type EngineeringAnalyticsWorkflowHealthParams = {
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
