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
 * * `session_replay` - Session replay
 * `llm_analytics` - LLM analytics
 * `github` - GitHub
 * `linear` - Linear
 * `zendesk` - Zendesk
 * `conversations` - Conversations
 * `error_tracking` - Error tracking
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

export interface SignalUserAutonomyConfigApi {
    readonly id: string
    readonly user: _UserApi
    autostart_priority?: AutostartPriorityEnumApi | BlankEnumApi | NullEnumApi | null
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
