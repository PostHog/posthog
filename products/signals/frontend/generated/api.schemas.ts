/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * `SignalScratchpad` projection used by `search-memory` and `remember`.
 */
export interface ScratchpadEntryApi {
    /** Agent-chosen semantic key, unique per team. */
    key: string
    /** Prose content for prompt injection. */
    content: string
    /** Always `agent_inference` in v1; reserved for future human-confirmed entries. */
    authority: string
    /** Free-form tags the agent uses to scope search; matched via Postgres array overlap. */
    tags: string[]
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
     * ISO-8601 expiry timestamp (null = no expiry, reserved for future use).
     * @nullable
     */
    expires_at: string | null
    /**
     * Run that wrote this entry, or null if human-authored.
     * @nullable
     */
    created_by_run_id: string | null
}

export interface PaginatedScratchpadEntryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ScratchpadEntryApi[]
}

/**
 * Request body for `remember`. Authority is always `agent_inference` — humans use Django admin.
 */
export interface RememberRequestApi {
    /**
     * Agent-chosen semantic key. Re-using a key updates the existing entry in place.
     * @maxLength 300
     */
    key: string
    /** Prose to write. Read verbatim into future prompts. */
    content: string
    /** Tags for later search. Empty/whitespace tags are dropped. */
    tags?: string[]
    /**
     * Days until expiry (default 7, hard cap 90).
     * @minimum 1
     * @maximum 90
     */
    ttl_days?: number
    /**
     * Run that authored this memory; persisted as `created_by_run_id` for lineage. Must reference a run on this same project — cross-project run UUIDs are rejected.
     * @nullable
     */
    run_id?: string | null
}

/**
 * Request body for `forget`. Only `agent_inference` keys can be deleted.
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
 * Lightweight projection of a `SignalScoutRun` row used by `search-recent-runs`.
 */
export interface SignalScoutRunSummaryApi {
    /** UUID of the run row. */
    run_id: string
    /** Canonical skill name the run executed (e.g. `signals-scout-general`). */
    skill_name: string
    /** Skill version snapshotted at run start. */
    skill_version: number
    /** Run status: scheduled | running | completed | failed | abandoned. */
    status: string
    /** ISO-8601 timestamp the run row was inserted. */
    started_at: string
    /**
     * ISO-8601 timestamp the run finalized; null while still running.
     * @nullable
     */
    completed_at: string | null
    /** Prose: what this run looked at, found, and skipped. ILIKE search target for dedupe. */
    summary: string
    /** Number of finding entries persisted on the run row. */
    findings_count: number
    /**
     * UUID of the Tasks `Task` the harness span ran inside. Null on aborted rows or rows older than the linkage capture.
     * @nullable
     */
    task_id?: string | null
    /**
     * UUID of the Tasks `TaskRun` (the specific execution of the task). Pairs with `task_id` to deep-link.
     * @nullable
     */
    task_run_id?: string | null
    /**
     * Relative deep-link to the Tasks UI for this run, e.g. `/project/{team_id}/tasks/{task_id}?runId={task_run_id}`. Null when either `task_id` or `task_run_id` is missing.
     * @nullable
     */
    task_url?: string | null
}

export interface PaginatedSignalScoutRunSummaryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SignalScoutRunSummaryApi[]
}

export type SignalScoutRunDetailApiFindingsItem = { [key: string]: unknown }

export type SignalScoutRunDetailApiHypothesesConsideredItem = { [key: string]: unknown }

/**
 * Measured quantities about how the run went, e.g. {runtime_s, findings}.
 */
export type SignalScoutRunDetailApiRunMetrics = { [key: string]: number }

/**
 * Run metadata snapshot (limits, skill id, allowed_tools resolution, plus `task_id` / `task_run_id` for the Tasks UI cross-link).
 */
export type SignalScoutRunDetailApiMetadata = { [key: string]: unknown }

/**
 * Full `SignalScoutRun` projection used by `get-run`. Includes structured payloads.
 */
export interface SignalScoutRunDetailApi {
    /** UUID of the run row. */
    run_id: string
    /** Canonical skill name the run executed. */
    skill_name: string
    /** Skill version snapshotted at run start. */
    skill_version: number
    /** Run status. */
    status: string
    /** ISO-8601 timestamp the run row was inserted. */
    started_at: string
    /**
     * ISO-8601 timestamp the run finalized.
     * @nullable
     */
    completed_at: string | null
    /** Prose summary of the run. */
    summary: string
    /** Findings persisted to the run row, including pre-emit attribution. */
    findings: SignalScoutRunDetailApiFindingsItem[]
    /** Hypotheses the run considered, including ones it explicitly skipped. */
    hypotheses_considered: SignalScoutRunDetailApiHypothesesConsideredItem[]
    /** Measured quantities about how the run went, e.g. {runtime_s, findings}. */
    run_metrics: SignalScoutRunDetailApiRunMetrics
    /** Run metadata snapshot (limits, skill id, allowed_tools resolution, plus `task_id` / `task_run_id` for the Tasks UI cross-link). */
    metadata: SignalScoutRunDetailApiMetadata
    /**
     * UUID of the Tasks `Task` the harness span ran inside. Null on aborted rows or rows older than the linkage capture.
     * @nullable
     */
    task_id?: string | null
    /**
     * UUID of the Tasks `TaskRun` (the specific execution of the task). Pairs with `task_id` to deep-link.
     * @nullable
     */
    task_run_id?: string | null
    /**
     * Relative deep-link to the Tasks UI for this run, e.g. `/project/{team_id}/tasks/{task_id}?runId={task_run_id}`. Null when either `task_id` or `task_run_id` is missing.
     * @nullable
     */
    task_url?: string | null
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
    /**
     * Optional severity tag (`P0`-`P4`) — informational only.
     * @nullable
     */
    severity?: string | null
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
     * `shadow_mode` | `already_emitted` | null when emitted normally.
     * @nullable
     */
    skipped_reason: string | null
}

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

/**
 * * `P0` - P0
 * `P1` - P1
 * `P2` - P2
 * `P3` - P3
 * `P4` - P4
 */
export type AutonomyPriorityEnumApi = (typeof AutonomyPriorityEnumApi)[keyof typeof AutonomyPriorityEnumApi]

export const AutonomyPriorityEnumApi = {
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
    autostart_priority?: AutonomyPriorityEnumApi | BlankEnumApi | null
    /**
     * ID of the Slack Integration to deliver inbox-item notifications through, or null when notifications are disabled.
     * @nullable
     */
    readonly slack_notification_integration_id: number | null
    /**
     * Slack channel target in the same `channel_id|#channel-name` shape PostHog uses elsewhere (only the channel id is required). Null disables Slack notifications.
     * @maxLength 255
     * @nullable
     */
    slack_notification_channel?: string | null
    /** Minimum report priority that triggers a Slack notification. P0 is highest. Null means notify on every priority (and reports without a priority judgment).

  * `P0` - P0
  * `P1` - P1
  * `P2` - P2
  * `P3` - P3
  * `P4` - P4 */
    slack_notification_min_priority?: AutonomyPriorityEnumApi | BlankEnumApi | null
    readonly created_at: string
    readonly updated_at: string
}

export type SignalsAgentMemoryListParams = {
    /**
     * Include expired `agent_inference` entries (default false). Use for audit/debug only.
     */
    include_expired?: boolean
    /**
     * Max rows to return (default 20, hard cap 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Tags filtered via Postgres array overlap. Pass repeated `tags=` query params to filter.
     */
    tags?: string[]
    /**
     * ILIKE substring match against `content`. Omit to return the most recent entries.
     */
    text?: string
}

export type SignalsAgentRunsListParams = {
    /**
     * Max rows to return (default 20, hard cap 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * ISO-8601 lower bound on `started_at`. Use to scope to a recent window.
     */
    since?: string
    /**
     * ILIKE substring match against `summary`. Omit to return the latest runs unfiltered.
     */
    text?: string
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
