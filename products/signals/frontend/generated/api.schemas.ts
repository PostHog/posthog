/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface PauseStateResponseApi {
    /**
     * The timestamp the pipeline is paused until, or null if not paused/not running.
     * @nullable
     */
    paused_until: string | null
}

export interface PaginatedPauseStateResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PauseStateResponseApi[]
}

export interface PauseUntilRequestApi {
    /** Pause the grouping pipeline until this timestamp (ISO 8601). */
    timestamp: string
}

export interface PauseResponseApi {
    /** Always 'paused'. */
    status: string
    /** The timestamp the pipeline is paused until. */
    paused_until: string
}

/**
 * * `potential` - Potential
 * `candidate` - Candidate
 * `in_progress` - In Progress
 * `pending_input` - Pending Input
 * `ready` - Ready
 * `resolved` - Resolved
 * `failed` - Failed
 * `deleted` - Deleted
 * `suppressed` - Suppressed
 */
export type SignalReportStatusEnumApi = (typeof SignalReportStatusEnumApi)[keyof typeof SignalReportStatusEnumApi]

export const SignalReportStatusEnumApi = {
    Potential: 'potential',
    Candidate: 'candidate',
    InProgress: 'in_progress',
    PendingInput: 'pending_input',
    Ready: 'ready',
    Resolved: 'resolved',
    Failed: 'failed',
    Deleted: 'deleted',
    Suppressed: 'suppressed',
} as const

export interface SignalReportApi {
    readonly id: string
    /** @nullable */
    readonly title: string | null
    /** @nullable */
    readonly summary: string | null
    readonly status: SignalReportStatusEnumApi
    readonly total_weight: number
    readonly signal_count: number
    readonly signals_at_run: number
    readonly created_at: string
    readonly updated_at: string
    readonly artefact_count: number
    /**
     * P0–P4 from the latest priority judgment artefact (when present).
     * @nullable
     */
    readonly priority: string | null
    /**
     * Actionability choice from the latest actionability judgment artefact (when present).
     * @nullable
     */
    readonly actionability: string | null
    /**
     * Whether the issue appears already fixed, from the actionability judgment artefact.
     * @nullable
     */
    readonly already_addressed: boolean | null
    readonly is_suggested_reviewer: boolean
    /** Distinct source products contributing signals to this report (from ClickHouse). */
    readonly source_products: readonly string[]
    /**
     * PR URL from the latest implementation task run, if available.
     * @nullable
     */
    readonly implementation_pr_url: string | null
}

export interface PaginatedSignalReportListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SignalReportApi[]
}

/**
 * * `video_segment` - Video Segment
 * `safety_judgment` - Safety Judgment
 * `actionability_judgment` - Actionability Judgment
 * `priority_judgment` - Priority Judgment
 * `signal_finding` - Signal Finding
 * `repo_selection` - Repo Selection
 * `suggested_reviewers` - Suggested Reviewers
 * `dismissal` - Dismissal
 */
export type SignalReportArtefactTypeEnumApi =
    (typeof SignalReportArtefactTypeEnumApi)[keyof typeof SignalReportArtefactTypeEnumApi]

export const SignalReportArtefactTypeEnumApi = {
    VideoSegment: 'video_segment',
    SafetyJudgment: 'safety_judgment',
    ActionabilityJudgment: 'actionability_judgment',
    PriorityJudgment: 'priority_judgment',
    SignalFinding: 'signal_finding',
    RepoSelection: 'repo_selection',
    SuggestedReviewers: 'suggested_reviewers',
    Dismissal: 'dismissal',
} as const

/**
 * Parsed artefact payload. Shape varies by `type`. For `suggested_reviewers`, returns a list of `{github_login, github_name, relevant_commits, user}` entries where `user` is the enriched PostHog org-member profile (or null when no user is linked to that GitHub login).
 */
export type SignalReportArtefactApiContent = { [key: string]: unknown } | unknown[]

export interface SignalReportArtefactApi {
    /** Stable identifier for the artefact row. */
    readonly id: string
    /** Kind of artefact (e.g. `suggested_reviewers`, `priority_judgment`, `dismissal`).

  * `video_segment` - Video Segment
  * `safety_judgment` - Safety Judgment
  * `actionability_judgment` - Actionability Judgment
  * `priority_judgment` - Priority Judgment
  * `signal_finding` - Signal Finding
  * `repo_selection` - Repo Selection
  * `suggested_reviewers` - Suggested Reviewers
  * `dismissal` - Dismissal */
    readonly type: SignalReportArtefactTypeEnumApi
    /** Parsed artefact payload. Shape varies by `type`. For `suggested_reviewers`, returns a list of `{github_login, github_name, relevant_commits, user}` entries where `user` is the enriched PostHog org-member profile (or null when no user is linked to that GitHub login). */
    readonly content: SignalReportArtefactApiContent
    /** Timestamp when the artefact was written by the agentic pipeline (or via API). */
    readonly created_at: string
}

export interface PaginatedSignalReportArtefactListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SignalReportArtefactApi[]
}

/**
 * Single entry in a PUT body for a `suggested_reviewers` artefact.

Each entry must identify a reviewer by at least one of `github_login` or `user_uuid`.
The server canonicalizes to a lowercase `github_login` — if `user_uuid` is supplied,
it must map to an org member on this team with a linked GitHub login.
 */
export interface SuggestedReviewerEntryWriteApi {
    /**
     * GitHub login (case-insensitive). Stored lowercased.
     * @maxLength 200
     */
    github_login?: string
    /** PostHog user UUID. Must be an org member on this team with a linked GitHub identity. If supplied together with `github_login`, the server-resolved login from the user wins. */
    user_uuid?: string
    /**
     * Optional human-readable display name. Not backfilled from GitHub by the server.
     * @maxLength 200
     */
    github_name?: string
}

/**
 * PUT body for replacing a `suggested_reviewers` artefact's content.

Only `suggested_reviewers` artefacts may be modified via this endpoint;
the viewset enforces the type check before validation runs.
 */
export interface SignalReportArtefactWriteApi {
    /** Full replacement list of reviewers. Empty list clears the artefact. At most 10 entries. */
    content: SuggestedReviewerEntryWriteApi[]
}

/**
 * * `session_replay` - Session replay
 * `llm_analytics` - LLM analytics
 * `github` - GitHub
 * `linear` - Linear
 * `zendesk` - Zendesk
 * `conversations` - Conversations
 * `error_tracking` - Error tracking
 * `pganalyze` - pganalyze
 */
export type SourceProductEnumApi = (typeof SourceProductEnumApi)[keyof typeof SourceProductEnumApi]

export const SourceProductEnumApi = {
    SessionReplay: 'session_replay',
    LlmAnalytics: 'llm_analytics',
    Github: 'github',
    Linear: 'linear',
    Zendesk: 'zendesk',
    Conversations: 'conversations',
    ErrorTracking: 'error_tracking',
    Pganalyze: 'pganalyze',
} as const

/**
 * * `session_analysis_cluster` - Session analysis cluster
 * `evaluation` - Evaluation
 * `issue` - Issue
 * `ticket` - Ticket
 * `issue_created` - Issue created
 * `issue_reopened` - Issue reopened
 * `issue_spiking` - Issue spiking
 */
export type SignalSourceConfigSourceTypeEnumApi =
    (typeof SignalSourceConfigSourceTypeEnumApi)[keyof typeof SignalSourceConfigSourceTypeEnumApi]

export const SignalSourceConfigSourceTypeEnumApi = {
    SessionAnalysisCluster: 'session_analysis_cluster',
    Evaluation: 'evaluation',
    Issue: 'issue',
    Ticket: 'ticket',
    IssueCreated: 'issue_created',
    IssueReopened: 'issue_reopened',
    IssueSpiking: 'issue_spiking',
} as const

export interface SignalSourceConfigApi {
    readonly id: string
    source_product: SourceProductEnumApi
    source_type: SignalSourceConfigSourceTypeEnumApi
    enabled?: boolean
    config?: unknown
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly status: string | null
}

export interface PaginatedSignalSourceConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SignalSourceConfigApi[]
}

export interface PatchedSignalSourceConfigApi {
    readonly id?: string
    source_product?: SourceProductEnumApi
    source_type?: SignalSourceConfigSourceTypeEnumApi
    enabled?: boolean
    config?: unknown
    readonly created_at?: string
    readonly updated_at?: string
    /** @nullable */
    readonly status?: string | null
}

export interface _UserApi {
    readonly id: number
    readonly uuid: string
    readonly first_name: string
    readonly last_name: string
    readonly email: string
}

/**
 * * `P0` - P0
 * `P1` - P1
 * `P2` - P2
 * `P3` - P3
 * `P4` - P4
 */
export type AutostartPriorityEnumApi = (typeof AutostartPriorityEnumApi)[keyof typeof AutostartPriorityEnumApi]

export const AutostartPriorityEnumApi = {
    P0: 'P0',
    P1: 'P1',
    P2: 'P2',
    P3: 'P3',
    P4: 'P4',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export interface SignalUserAutonomyConfigApi {
    readonly id: string
    readonly user: _UserApi
    autostart_priority?: AutostartPriorityEnumApi | BlankEnumApi | null
    readonly created_at: string
    readonly updated_at: string
}

export type SignalsProcessingListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SignalsReportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Comma-separated ordering clauses. Each clause is a field name optionally prefixed with '-' for descending. Allowed fields: status, is_suggested_reviewer, signal_count, total_weight, priority, created_at, updated_at, id. Defaults to '-is_suggested_reviewer,status,-updated_at'.
     */
    ordering?: string
    /**
     * Case-insensitive substring match against report title and summary.
     */
    search?: string
    /**
     * Comma-separated list of source products to include. Reports are kept if at least one of their contributing signals comes from one of these products (e.g. error_tracking, session_replay).
     */
    source_product?: string
    /**
     * Comma-separated list of statuses to include. Valid values: potential, candidate, in_progress, pending_input, ready, failed, suppressed. Defaults to all statuses except suppressed.
     */
    status?: string
    /**
     * Comma-separated list of PostHog user UUIDs. Reports are kept if their suggested reviewers include any of the given users.
     */
    suggested_reviewers?: string
}

export type SignalsReportsArtefactsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SignalsSourceConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
