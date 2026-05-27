/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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
 * `closed` - CLOSED
 * `merged` - MERGED
 */
export type PullRequestStateEnumApi = (typeof PullRequestStateEnumApi)[keyof typeof PullRequestStateEnumApi]

export const PullRequestStateEnumApi = {
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

  * `open` - OPEN
  * `closed` - CLOSED
  * `merged` - MERGED */
    state: PullRequestStateEnumApi
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
 * `ci_started` - CI_STARTED
 * `ci_finished` - CI_FINISHED
 * `merged` - MERGED
 * `closed` - CLOSED
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

  * `opened` - OPENED
  * `ci_started` - CI_STARTED
  * `ci_finished` - CI_FINISHED
  * `merged` - MERGED
  * `closed` - CLOSED */
    kind: PRLifecycleEventKindEnumApi
    /** When the event occurred. */
    at: string
    /**
     * Optional detail, e.g. workflow name and conclusion for CI events.
     * @nullable
     */
    detail?: string | null
}

/**
 * * `precise` - PRECISE
 * `coarse` - COARSE
 * `partial` - PARTIAL
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

  * `precise` - PRECISE
  * `coarse` - COARSE
  * `partial` - PARTIAL */
    metric_quality?: MetricQualityEnumApi
}

/**
 * * `all` - ALL
 * `author` - AUTHOR
 */
export type BucketKindEnumApi = (typeof BucketKindEnumApi)[keyof typeof BucketKindEnumApi]

export const BucketKindEnumApi = {
    All: 'all',
    Author: 'author',
} as const

export interface TimeToMergeRowApi {
    /** 'all', or an author handle when grouping by author. */
    bucket: string
    /** Whether this row aggregates all PRs ('all') or one author ('author').

  * `all` - ALL
  * `author` - AUTHOR */
    bucket_kind: BucketKindEnumApi
    /** Number of merged pull requests in the bucket. */
    pr_count: number
    /** Median seconds from PR open to merge. */
    median_seconds: number
    /** 95th-percentile seconds from PR open to merge. */
    p95_seconds: number
}

export interface TimeToMergeApi {
    /** One row for 'all', or one per author when grouping by author. */
    rows: TimeToMergeRowApi[]
    /** Repository the result is labeled with, if a repo filter was supplied. */
    repo?: RepoRefApi | null
    /** Start of the window, echoed from the request (relative string or ISO8601). */
    date_from: string
    /**
     * End of the window, echoed from the request; null means 'now'.
     * @nullable
     */
    date_to: string | null
    /** Whether rows are split per author. */
    group_by_author: boolean
    /** Always 'coarse' — measures PR open to merge, combining draft and ready-for-review time.

  * `precise` - PRECISE
  * `coarse` - COARSE
  * `partial` - PARTIAL */
    metric_quality?: MetricQualityEnumApi
}

export interface WorkflowReportRowApi {
    /** GitHub Actions workflow name. */
    workflow_name: string
    /** Number of runs of this workflow in the window. */
    total_runs: number
    /** Fraction of runs that concluded 'success', from 0.0 to 1.0. */
    success_rate: number
    /** Median run duration in seconds. */
    median_duration_seconds: number
    /** 95th-percentile run duration in seconds. */
    p95_duration_seconds: number
    /**
     * Timestamp of the most recent failed run, or null if none failed in the window.
     * @nullable
     */
    last_failed_at: string | null
}

export interface WorkflowReportApi {
    /** Workflows in the window, slowest median duration first. */
    rows: WorkflowReportRowApi[]
    /** Repository the report is labeled with, if a repo filter was supplied. */
    repo?: RepoRefApi | null
    /** Start of the window, echoed from the request (relative string or ISO8601). */
    date_from: string
    /**
     * End of the window, echoed from the request; null means 'now'.
     * @nullable
     */
    date_to: string | null
    /** Always 'precise' — computed directly from CI run records.

  * `precise` - PRECISE
  * `coarse` - COARSE
  * `partial` - PARTIAL */
    metric_quality?: MetricQualityEnumApi
}

export type EngineeringAnalyticsPrLifecycleParams = {
    /**
     * Pull request number to inspect.
     */
    pr_number: number
    /**
     * Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows.
     */
    repo?: string
}

export type EngineeringAnalyticsTimeToMergeParams = {
    /**
     * Start of the window: a relative string like '-7d' or an ISO8601 timestamp. Defaults to '-7d'.
     */
    date_from?: string
    /**
     * End of the window: a relative string or ISO8601 timestamp. Omit for 'now'.
     */
    date_to?: string
    /**
     * Split results per author handle instead of one overall bucket.
     */
    group_by_author?: boolean
    /**
     * Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows.
     */
    repo?: string
}

export type EngineeringAnalyticsWorkflowReportParams = {
    /**
     * Start of the window: a relative string like '-7d' or an ISO8601 timestamp. Defaults to '-7d'.
     */
    date_from?: string
    /**
     * End of the window: a relative string or ISO8601 timestamp. Omit for 'now'.
     */
    date_to?: string
    /**
     * Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows.
     */
    repo?: string
}
