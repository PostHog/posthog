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
 * Lightweight projection of a `SignalScoutRun` row used by `search-recent-runs`.

Status and timestamps flow from the linked `tasks.TaskRun`.
 */
export interface SignalScoutRunSummaryApi {
    /** UUID of the bridge row. */
    run_id: string
    /** Canonical skill name the run executed (e.g. `signals-scout-general`). */
    skill_name: string
    /** Skill version snapshotted at run start. */
    skill_version: number
    /** Status from the linked TaskRun: not_started | queued | in_progress | completed | failed | cancelled. */
    status: string
    /** ISO-8601 timestamp the TaskRun was created. */
    started_at: string
    /**
     * ISO-8601 timestamp the TaskRun completed; null while still running.
     * @nullable
     */
    completed_at: string | null
    /**
     * UUID of the Tasks `Task` the scout span ran inside.
     * @nullable
     */
    task_id?: string | null
    /**
     * UUID of the Tasks `TaskRun`. Pairs with `task_id` to deep-link.
     * @nullable
     */
    task_run_id?: string | null
    /**
     * Relative deep-link to the Tasks UI for this run, e.g. `/project/{team_id}/tasks/{task_id}?runId={task_run_id}`.
     * @nullable
     */
    task_url?: string | null
    /** One-paragraph close-out the scout wrote at end-of-run. Empty string for runs that errored before close-out. The dedupe key for non-emitting runs. */
    summary: string
}

/**
 * Full `SignalScoutRun` projection used by `get-run`. Same shape as the summary
today; kept distinct so future detail-only extensions (linked Signal rows,
LLMA token-cost join) can land here without bloating the list response.
 */
export interface SignalScoutRunDetailApi {
    /** UUID of the bridge row. */
    run_id: string
    /** Canonical skill name the run executed (e.g. `signals-scout-general`). */
    skill_name: string
    /** Skill version snapshotted at run start. */
    skill_version: number
    /** Status from the linked TaskRun: not_started | queued | in_progress | completed | failed | cancelled. */
    status: string
    /** ISO-8601 timestamp the TaskRun was created. */
    started_at: string
    /**
     * ISO-8601 timestamp the TaskRun completed; null while still running.
     * @nullable
     */
    completed_at: string | null
    /**
     * UUID of the Tasks `Task` the scout span ran inside.
     * @nullable
     */
    task_id?: string | null
    /**
     * UUID of the Tasks `TaskRun`. Pairs with `task_id` to deep-link.
     * @nullable
     */
    task_run_id?: string | null
    /**
     * Relative deep-link to the Tasks UI for this run, e.g. `/project/{team_id}/tasks/{task_id}?runId={task_run_id}`.
     * @nullable
     */
    task_url?: string | null
    /** One-paragraph close-out the scout wrote at end-of-run. Empty string for runs that errored before close-out. The dedupe key for non-emitting runs. */
    summary: string
}

/**
 * One citation attached to a finding. Mirrors `SignalsScoutEvidenceEntry`.
 */
export interface EvidenceEntryApi {
    /** Source the citation came from (`error_tracking`, `session_replay`, `logs`, ...). */
    source_product: string
    /** One-sentence prose about why this evidence supports the finding. */
    summary: string
    /**
     * Optional ID of the cited entity (issue id, recording id, log query id).
     * @nullable
     */
    entity_id?: string | null
}

/**
 * * `P0` - P0
 * `P1` - P1
 * `P2` - P2
 * `P3` - P3
 * `P4` - P4
 */
export type SignalsScoutSeverityEnumApi = (typeof SignalsScoutSeverityEnumApi)[keyof typeof SignalsScoutSeverityEnumApi]

export const SignalsScoutSeverityEnumApi = {
    P0: 'P0',
    P1: 'P1',
    P2: 'P2',
    P3: 'P3',
    P4: 'P4',
} as const

export interface TimeRangeApi {
    /** ISO-8601 inclusive lower bound for the finding's window. */
    date_from: string
    /** ISO-8601 inclusive upper bound for the finding's window. */
    date_to: string
}

/**
 * Request body for `emit-finding`. Run attribution is taken from the URL path.
 */
export interface EmitFindingRequestApi {
    /** Canonical evidence-bundle prose. Becomes the signal's `description`. */
    description: string
    /**
     * Agent's weight for the signal in [0, 1]. Drives ranking in the inbox.
     * @minimum 0
     * @maximum 1
     */
    weight: number
    /**
     * Agent's confidence the finding is real in [0, 1]. Persisted in `extra`.
     * @minimum 0
     * @maximum 1
     */
    confidence: number
    /**
     * Citations supporting the finding. Capped at 20 entries.
     * @maxItems 20
     */
    evidence: EvidenceEntryApi[]
    /**
     * Optional one-line hypothesis the finding tests.
     * @nullable
     */
    hypothesis?: string | null
    /** Optional severity tag — one of P0, P1, P2, P3, P4. Informational only.

  * `P0` - P0
  * `P1` - P1
  * `P2` - P2
  * `P3` - P3
  * `P4` - P4 */
    severity?: SignalsScoutSeverityEnumApi | null
    /** Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`). */
    dedupe_keys?: string[]
    /** Optional time window the finding refers to. */
    time_range?: TimeRangeApi | null
    /**
     * Optional MCP trace id for cross-system debugging.
     * @nullable
     */
    mcp_trace_id?: string | null
    /**
     * Idempotency key. Re-using the same id within a run short-circuits without re-emitting.
     * @nullable
     */
    finding_id?: string | null
}

export interface EmitFindingResponseApi {
    /** Stable id for the finding (echoed back from request, or generated). */
    finding_id: string
    /** Whether `emit_signal` was actually fired. */
    emitted: boolean
    /**
     * `ai_processing_not_approved` | `source_disabled` | null when emitted normally.
     * @nullable
     */
    skipped_reason: string | null
}

/**
 * `SignalScratchpad` projection used by `search-memory` and `remember`.
 */
export interface ScratchpadEntryApi {
    /** Agent-chosen semantic key, unique per team. */
    key: string
    /** Prose content for prompt injection. */
    content: string
    /**
     * ISO-8601 creation timestamp.
     * @nullable
     */
    created_at: string | null
    /**
     * ISO-8601 last-write timestamp.
     * @nullable
     */
    updated_at: string | null
    /**
     * Run that wrote this entry, or null if human-authored.
     * @nullable
     */
    created_by_run_id: string | null
}

/**
 * Request body for `remember`.
 */
export interface RememberRequestApi {
    /**
     * Agent-chosen semantic key. Re-using a key updates the existing entry in place.
     * @maxLength 300
     */
    key: string
    /** Prose to write. Read verbatim into future prompts. */
    content: string
    /**
     * Run that authored this memory; persisted as `created_by_run_id` for lineage. Must reference a run on this same project — cross-project run UUIDs are rejected.
     * @nullable
     */
    run_id?: string | null
}

/**
 * Request body for `forget`.
 */
export interface ForgetRequestApi {
    /**
     * Memory key to delete.
     * @maxLength 300
     */
    key: string
}

export interface ForgetResponseApi {
    /** Whether a row was actually removed (false if the key didn't exist). */
    deleted: boolean
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
 * `signals_scout` - Signals scout
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
    SignalsScout: 'signals_scout',
} as const

/**
 * * `session_analysis_cluster` - Session analysis cluster
 * `evaluation` - Evaluation
 * `issue` - Issue
 * `ticket` - Ticket
 * `issue_created` - Issue created
 * `issue_reopened` - Issue reopened
 * `issue_spiking` - Issue spiking
 * `cross_source_issue` - Cross source issue
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
    CrossSourceIssue: 'cross_source_issue',
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

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export interface SignalUserAutonomyConfigApi {
    readonly id: string
    readonly user: _UserApi
    autostart_priority?: SignalsScoutSeverityEnumApi | BlankEnumApi | null
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

export type SignalsScoutRunsListParams = {
    /**
     * ISO-8601 inclusive lower bound on `created_at`. Omit to skip the lower bound.
     */
    date_from?: string
    /**
     * ISO-8601 exclusive upper bound on `created_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `started_at` of the oldest run from the prior page).
     */
    date_to?: string
    /**
     * Max rows to return (default 20, hard cap 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Case-insensitive substring match on the scout's end-of-run `summary`. Omit to skip the filter.
     * @minLength 1
     */
    text?: string
}

export type SignalsScoutScratchpadListParams = {
    /**
     * Max rows to return (default 20, hard cap 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * ILIKE substring match against `content`. Omit to return the most recent entries.
     */
    text?: string
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
