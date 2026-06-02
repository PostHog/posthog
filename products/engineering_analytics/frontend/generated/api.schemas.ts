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

export type EngineeringAnalyticsPrLifecycleParams = {
    /**
     * Pull request number to inspect.
     */
    pr_number: number
    /**
     * Optional 'owner/name' repository to disambiguate when the PR number exists in more than one connected repo.
     */
    repo?: string
}
