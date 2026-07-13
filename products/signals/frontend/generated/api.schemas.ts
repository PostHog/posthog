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
 * * `candidate` - Candidate
 * * `in_progress` - In Progress
 * * `pending_input` - Pending Input
 * * `ready` - Ready
 * * `resolved` - Resolved
 * * `failed` - Failed
 * * `deleted` - Deleted
 * * `suppressed` - Suppressed
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
    /**
     * Reason code from the latest dismissal artefact, set when the report was suppressed (when present).
     * @nullable
     */
    readonly dismissal_reason: string | null
    /**
     * Free-form note captured alongside the dismissal reason (when present).
     * @nullable
     */
    readonly dismissal_note: string | null
    readonly is_suggested_reviewer: boolean
    /** Distinct source products contributing signals to this report (from ClickHouse). */
    readonly source_products: readonly string[]
    /**
     * skill_name slug of the scout that authored this report, when scout-authored (from ClickHouse); null otherwise.
     * @nullable
     */
    readonly scout_name: string | null
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
 * Editable human-facing fields on a signal report (PATCH).
 *
 * Both fields are optional so a caller can change either independently, but at least one
 * must be supplied. Every other report field — status, weights, judgments — is owned by the
 * signals pipeline and is deliberately not writable here.
 */
export interface PatchedSignalReportContentUpdateApi {
    /**
     * New human-facing title for the report. Omit to leave the title unchanged.
     * @minLength 1
     * @maxLength 300
     */
    title?: string
    /**
     * New summary (the report's description) explaining what the report is about. Omit to leave the summary unchanged.
     * @minLength 1
     * @maxLength 10000
     */
    summary?: string
}

/**
 * * `session_replay` - session_replay
 * * `llm_analytics` - llm_analytics
 * * `github` - github
 * * `linear` - linear
 * * `jira` - jira
 * * `zendesk` - zendesk
 * * `conversations` - conversations
 * * `error_tracking` - error_tracking
 * * `endpoints` - endpoints
 * * `pganalyze` - pganalyze
 * * `signals_scout` - signals_scout
 * * `logs` - logs
 * * `health_checks` - health_checks
 * * `replay_vision` - replay_vision
 */
export type SignalSourceProductApi = (typeof SignalSourceProductApi)[keyof typeof SignalSourceProductApi]

export const SignalSourceProductApi = {
    SessionReplay: 'session_replay',
    LlmAnalytics: 'llm_analytics',
    Github: 'github',
    Linear: 'linear',
    Jira: 'jira',
    Zendesk: 'zendesk',
    Conversations: 'conversations',
    ErrorTracking: 'error_tracking',
    Endpoints: 'endpoints',
    Pganalyze: 'pganalyze',
    SignalsScout: 'signals_scout',
    Logs: 'logs',
    HealthChecks: 'health_checks',
    ReplayVision: 'replay_vision',
} as const

/**
 * * `session_analysis_cluster` - session_analysis_cluster
 * * `session_problem` - session_problem
 * * `evaluation` - evaluation
 * * `evaluation_report` - evaluation_report
 * * `issue` - issue
 * * `ticket` - ticket
 * * `issue_created` - issue_created
 * * `issue_reopened` - issue_reopened
 * * `issue_spiking` - issue_spiking
 * * `endpoint_execution_failed` - endpoint_execution_failed
 * * `endpoint_breakdown_limit_exceeded` - endpoint_breakdown_limit_exceeded
 * * `cross_source_issue` - cross_source_issue
 * * `alert_state_change` - alert_state_change
 * * `health_issue` - health_issue
 * * `scanner_finding` - scanner_finding
 */
export type SignalSourceTypeApi = (typeof SignalSourceTypeApi)[keyof typeof SignalSourceTypeApi]

export const SignalSourceTypeApi = {
    SessionAnalysisCluster: 'session_analysis_cluster',
    SessionProblem: 'session_problem',
    Evaluation: 'evaluation',
    EvaluationReport: 'evaluation_report',
    Issue: 'issue',
    Ticket: 'ticket',
    IssueCreated: 'issue_created',
    IssueReopened: 'issue_reopened',
    IssueSpiking: 'issue_spiking',
    EndpointExecutionFailed: 'endpoint_execution_failed',
    EndpointBreakdownLimitExceeded: 'endpoint_breakdown_limit_exceeded',
    CrossSourceIssue: 'cross_source_issue',
    AlertStateChange: 'alert_state_change',
    HealthIssue: 'health_issue',
    ScannerFinding: 'scanner_finding',
} as const

export type ProblemTypeEnumApi = (typeof ProblemTypeEnumApi)[keyof typeof ProblemTypeEnumApi]

export const ProblemTypeEnumApi = {
    Confusion: 'confusion',
    Abandonment: 'abandonment',
    BlockingException: 'blocking_exception',
    NonBlockingException: 'non_blocking_exception',
    Failure: 'failure',
} as const

export interface SessionProblemEventEntryApi {
    event: string
    timestamp: string
    current_url?: string | null
    event_type?: string | null
    interaction_text?: string | null
}

export interface SessionProblemSignalExtraApi {
    session_id: string
    segment_title: string
    start_time: string
    end_time: string
    problem_type: ProblemTypeEnumApi
    distinct_id: string
    session_start_time?: string | null
    session_end_time?: string | null
    session_duration?: number | null
    session_active_seconds?: number | null
    exported_asset_id?: number | null
    event_history?: SessionProblemEventEntryApi[] | null
}

export interface LlmEvalSignalExtraApi {
    evaluation_id: string
    target_event_id?: string | null
    target_event_type?: string | null
    trace_id: string
    model?: string | null
    provider?: string | null
}

export interface LlmEvalReportSignalExtraApi {
    evaluation_id: string
    evaluation_name: string
    evaluation_description: string
    report_id: string
    report_run_id: string
    period_start: string
    period_end: string
}

export interface ZendeskTicketSignalExtraApi {
    url: string
    type: string | null
    tags: string[]
    created_at: string
    priority: string | null
    status: string
}

export interface GithubIssueSignalExtraApi {
    html_url: string
    number: number
    labels: string[]
    created_at: string
    updated_at: string
    locked: boolean
    state: string
}

export interface LinearIssueSignalExtraApi {
    url: string
    identifier: string
    number: number
    priority: number
    priority_label: string
    labels: string[]
    state_name: string | null
    state_type: string | null
    team_name: string | null
    created_at: string
    updated_at: string
}

export interface JiraIssueSignalExtraApi {
    key: string
    url: string | null
    status: string | null
    priority: string | null
    assignee: string | null
    labels: string[]
    created: string | null
    updated: string | null
}

export interface ConversationsTicketSignalExtraApi {
    ticket_number: number
    channel_source: string
    channel_detail: string | null
    status: string
    priority: string | null
    created_at: string
    email_subject: string | null
}

export interface ErrorTrackingSignalExtraApi {
    fingerprint: string
}

export interface PgAnalyzeIssueReferenceApi {
    kind?: string | null
    name?: string | null
    url?: string | null
    queryText?: string | null
}

export interface PgAnalyzeIssueSignalExtraApi {
    severity: string | null
    references: PgAnalyzeIssueReferenceApi[]
    database_id: string | null
    server_human_id: string | null
    server_name: string | null
    synced_at: string
}

export interface EndpointExecutionFailedSignalExtraApi {
    endpoint_name: string
    endpoint_version: number | null
    materialized: boolean
    saved_query_id: string | null
    error_class: string
    error_message: string
}

export interface EndpointBreakdownLimitExceededSignalExtraApi {
    endpoint_name: string
    breakdown_limit: number
}

export type ReportPriorityApi = (typeof ReportPriorityApi)[keyof typeof ReportPriorityApi]

export const ReportPriorityApi = {
    P0: 'P0',
    P1: 'P1',
    P2: 'P2',
    P3: 'P3',
    P4: 'P4',
} as const

export interface SignalsScoutEvidenceEntryApi {
    source_product: string
    entity_id?: string | null
    summary: string
}

export interface SignalsScoutTimeRangeApi {
    date_from: string
    date_to: string
}

export interface SignalsScoutSignalExtraApi {
    scout_run_id: string
    task_run_id: string
    task_id?: string | null
    finding_id: string
    skill_name: string
    skill_version: number
    confidence: number
    severity?: ReportPriorityApi | null
    hypothesis?: string | null
    evidence: SignalsScoutEvidenceEntryApi[]
    dedupe_keys?: string[] | null
    tags?: string[] | null
    time_range?: SignalsScoutTimeRangeApi | null
    mcp_trace_id?: string | null
}

export type LogsAlertStateChangeSignalExtraActionEnumApi =
    (typeof LogsAlertStateChangeSignalExtraActionEnumApi)[keyof typeof LogsAlertStateChangeSignalExtraActionEnumApi]

export const LogsAlertStateChangeSignalExtraActionEnumApi = {
    Firing: 'firing',
    Broken: 'broken',
} as const

export type LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi =
    (typeof LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi)[keyof typeof LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi]

export const LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi = {
    Above: 'above',
    Below: 'below',
} as const

export type LogsAlertStateChangeSignalExtraApiFilters = { [key: string]: unknown }

export interface LogsAlertStateChangeSignalExtraApi {
    alert_id: string
    alert_name: string
    action: LogsAlertStateChangeSignalExtraActionEnumApi
    threshold_count: number
    threshold_operator: LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi
    window_minutes: number
    result_count: number | null
    consecutive_failures: number
    filters: LogsAlertStateChangeSignalExtraApiFilters
    url: string
}

export interface ReplayVisionScannerFindingSignalExtraApi {
    scanner_id: string
    scanner_name: string
    scanner_type: string
    observation_id: string
    session_id: string
    confidence: number
    problem_type: string
    start_time: number
    end_time: number
    url: string
    exported_asset_id: number
    distinct_id?: string | null
    recording_start_time?: string | null
    recording_end_time?: string | null
    recording_duration?: number | null
    recording_active_seconds?: number | null
}

export type HealthCheckSignalExtraSeverityEnumApi =
    (typeof HealthCheckSignalExtraSeverityEnumApi)[keyof typeof HealthCheckSignalExtraSeverityEnumApi]

export const HealthCheckSignalExtraSeverityEnumApi = {
    Critical: 'critical',
    Warning: 'warning',
    Info: 'info',
} as const

export type HealthCheckSignalExtraApiPayload = { [key: string]: unknown }

export interface HealthCheckSignalExtraApi {
    kind: string
    severity: HealthCheckSignalExtraSeverityEnumApi
    issue_id: string
    title: string
    summary: string
    link: string
    url: string
    payload: HealthCheckSignalExtraApiPayload
}

export type SignalExtraApi =
    | SessionProblemSignalExtraApi
    | LlmEvalSignalExtraApi
    | LlmEvalReportSignalExtraApi
    | ZendeskTicketSignalExtraApi
    | GithubIssueSignalExtraApi
    | LinearIssueSignalExtraApi
    | JiraIssueSignalExtraApi
    | ConversationsTicketSignalExtraApi
    | ErrorTrackingSignalExtraApi
    | PgAnalyzeIssueSignalExtraApi
    | EndpointExecutionFailedSignalExtraApi
    | EndpointBreakdownLimitExceededSignalExtraApi
    | SignalsScoutSignalExtraApi
    | LogsAlertStateChangeSignalExtraApi
    | ReplayVisionScannerFindingSignalExtraApi
    | HealthCheckSignalExtraApi

export interface SpecificityMetadataApi {
    /** Title of the PR the specificity gate evaluated. */
    pr_title: string
    /** Whether the report passed the PR-specificity gate. */
    specific_enough: boolean
    /** The gate's reasoning. */
    reason: string
}

export interface MatchedMetadataApi {
    /** Signal already in the report that this one matched. */
    parent_signal_id: string
    /** Query used to find the parent signal. */
    match_query: string
    /** Why the signals were judged to describe the same issue. */
    reason: string
    /** PR-specificity gate result, when the gate ran. */
    specificity?: SpecificityMetadataApi | null
}

export interface NoMatchMetadataApi {
    /** Why no existing report matched. */
    reason: string
    /** Candidate signals that were considered and rejected. */
    rejected_signal_ids: string[]
    /** PR-specificity gate result that caused a rejection, when present. */
    specificity_rejection?: SpecificityMetadataApi | null
}

export type SignalMatchMetadataApi = MatchedMetadataApi | NoMatchMetadataApi

export interface SignalNodeApi {
    /** ClickHouse document id of the signal. */
    signal_id: string
    /** The signal's human-readable description. */
    content: string
    /** Product that emitted the signal.
     *
     * * `session_replay` - session_replay
     * * `llm_analytics` - llm_analytics
     * * `github` - github
     * * `linear` - linear
     * * `jira` - jira
     * * `zendesk` - zendesk
     * * `conversations` - conversations
     * * `error_tracking` - error_tracking
     * * `endpoints` - endpoints
     * * `pganalyze` - pganalyze
     * * `signals_scout` - signals_scout
     * * `logs` - logs
     * * `health_checks` - health_checks
     * * `replay_vision` - replay_vision */
    source_product: SignalSourceProductApi
    /** Signal type within the source product.
     *
     * * `session_analysis_cluster` - session_analysis_cluster
     * * `session_problem` - session_problem
     * * `evaluation` - evaluation
     * * `evaluation_report` - evaluation_report
     * * `issue` - issue
     * * `ticket` - ticket
     * * `issue_created` - issue_created
     * * `issue_reopened` - issue_reopened
     * * `issue_spiking` - issue_spiking
     * * `endpoint_execution_failed` - endpoint_execution_failed
     * * `endpoint_breakdown_limit_exceeded` - endpoint_breakdown_limit_exceeded
     * * `cross_source_issue` - cross_source_issue
     * * `alert_state_change` - alert_state_change
     * * `health_issue` - health_issue
     * * `scanner_finding` - scanner_finding */
    source_type: SignalSourceTypeApi
    /** Emitter-scoped id of the underlying object (issue, ticket, ...). */
    source_id: string
    /** Signal weight in [0, 1]; drives report ranking. */
    weight: number
    /** Emission timestamp. */
    timestamp: string
    /** Product-specific payload; shape depends on (source_product, source_type). */
    extra: SignalExtraApi
    /** Clustering match/no-match metadata, when present. */
    match_metadata?: SignalMatchMetadataApi | null
}

/**
 * Response body for GET /api/projects/:id/signals/reports/:id/signals/.
 */
export interface ReportSignalsResponseApi {
    /** The report these signals were clustered into. */
    report: SignalReportApi
    /** All signals contributing to the report. */
    signals: SignalNodeApi[]
}

/**
 * * `suppressed` - suppressed
 * * `potential` - potential
 */
export type SignalReportStateEnumApi = (typeof SignalReportStateEnumApi)[keyof typeof SignalReportStateEnumApi]

export const SignalReportStateEnumApi = {
    Suppressed: 'suppressed',
    Potential: 'potential',
} as const

/**
 * * `already_fixed` - Already fixed
 * * `report_unclear` - Report is unclear to me
 * * `analysis_wrong` - Agent's analysis is wrong
 * * `wontfix_intentional` - Won't fix - intentional behavior
 * * `wontfix_irrelevant` - Won't fix - issue is real but insignificant
 * * `other` - Something else…
 */
export type DismissalReasonEnumApi = (typeof DismissalReasonEnumApi)[keyof typeof DismissalReasonEnumApi]

export const DismissalReasonEnumApi = {
    AlreadyFixed: 'already_fixed',
    ReportUnclear: 'report_unclear',
    AnalysisWrong: 'analysis_wrong',
    WontfixIntentional: 'wontfix_intentional',
    WontfixIrrelevant: 'wontfix_irrelevant',
    Other: 'other',
} as const

export interface SignalReportStateRequestApi {
    /** Target state for the report. Use 'suppressed' to dismiss the report from the inbox, or 'potential' to snooze/reopen it for later review.
     *
     * * `suppressed` - suppressed
     * * `potential` - potential */
    state: SignalReportStateEnumApi
    /** Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. 'already_fixed' is a snooze, not a dismissal: pair it with state='potential' (restore) so the report reappears if the issue recurs. Use 'other' together with a dismissal_note for anything that doesn't fit a code.
     *
     * * `already_fixed` - Already fixed
     * * `report_unclear` - Report is unclear to me
     * * `analysis_wrong` - Agent's analysis is wrong
     * * `wontfix_intentional` - Won't fix - intentional behavior
     * * `wontfix_irrelevant` - Won't fix - issue is real but insignificant
     * * `other` - Something else… */
    dismissal_reason?: DismissalReasonEnumApi
    /**
     * Optional free-form note explaining the dismissal. Capped at 4000 characters.
     * @maxLength 4000
     */
    dismissal_note?: string
    /**
     * Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal.
     * @minimum 1
     * @maximum 100000
     */
    snooze_for?: number
}

/**
 * * `video_segment` - Video Segment
 * * `safety_judgment` - Safety Judgment
 * * `actionability_judgment` - Actionability Judgment
 * * `priority_judgment` - Priority Judgment
 * * `signal_finding` - Signal Finding
 * * `repo_selection` - Repo Selection
 * * `suggested_reviewers` - Suggested Reviewers
 * * `dismissal` - Dismissal
 * * `code_reference` - Code Reference
 * * `commit` - Commit
 * * `task_run` - Task Run
 * * `note` - Note
 * * `title_change` - Title Change
 * * `summary_change` - Summary Change
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
    CodeReference: 'code_reference',
    Commit: 'commit',
    TaskRun: 'task_run',
    Note: 'note',
    TitleChange: 'title_change',
    SummaryChange: 'summary_change',
} as const

export interface _UserApi {
    readonly id: number
    readonly uuid: string
    readonly first_name: string
    readonly last_name: string
    readonly email: string
}

export type SignalReportArtefactApiContent = { [key: string]: unknown } | unknown[]

export interface SignalReportArtefactApi {
    readonly id: string
    readonly type: SignalReportArtefactTypeEnumApi
    readonly content: SignalReportArtefactApiContent
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** User the artefact is attributed to, when a user produced it. Null for task/system writes. */
    readonly created_by: _UserApi | null
    /**
     * Task the artefact is attributed to, when an agent produced it. Null for user/system writes.
     * @nullable
     */
    readonly task_id: string | null
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
 * Body for appending an artefact to a report.
 *
 * Everything is append-only: log artefacts accumulate, status artefacts supersede the previous
 * version (latest-wins). The `content` shape depends on `artefact_type` and is validated
 * against the type's schema (see `products/signals/backend/artefact_schemas.py`).
 */
export interface SignalReportArtefactLogCreateApi {
    /** The artefact type. One of: actionability_judgment, code_reference, commit, dismissal, note, priority_judgment, repo_selection, safety_judgment, signal_finding, suggested_reviewers, task_run. Log types accumulate; status types (safety_judgment, actionability_judgment, priority_judgment, repo_selection, suggested_reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status. */
    artefact_type: string
    /** The artefact payload as a JSON object or array; shape depends on artefact_type and is validated against its schema. */
    content: unknown
}

/**
 * Response shape for the log-artefact create/update endpoints — echoes the stored row.
 */
export interface SignalReportArtefactWriteResponseApi {
    /** The artefact's unique id. */
    readonly id: string
    /** The id of the report this artefact belongs to. */
    readonly report_id: string
    /** The artefact type. */
    readonly type: string
    /** The artefact payload, parsed from storage. */
    readonly content: unknown
    /** When the artefact was created. */
    readonly created_at: string
    /**
     * When the artefact was last written — set on creation and refreshed on each edit. Null only for rows created before this field existed.
     * @nullable
     */
    readonly updated_at: string | null
    /**
     * Task the artefact is attributed to, when an agent produced it. Null for user writes.
     * @nullable
     */
    readonly task_id: string | null
}

/**
 * Body for replacing the content of an existing artefact (addressed by id).
 *
 * Per-type schema validation happens in the view, which knows the artefact's type.
 */
export interface PatchedSignalReportArtefactLogUpdateApi {
    /** The new artefact payload as a JSON object or array, matching the artefact type's schema. */
    content?: unknown
}

/**
 * Response for the `commit` artefact diff endpoint — the commit's branch rendered against the
 * repository default branch.
 */
export interface CommitDiffResponseApi {
    /** Unified diff (patch) text of the branch against the repository default branch, from the GitHub compare API. */
    readonly diff: string
    /** True when the diff was too large to return in full and has been truncated. */
    readonly truncated: boolean
}

export interface SignalReportBulkStateRequestApi {
    /** Target state for the report. Use 'suppressed' to dismiss the report from the inbox, or 'potential' to snooze/reopen it for later review.
     *
     * * `suppressed` - suppressed
     * * `potential` - potential */
    state: SignalReportStateEnumApi
    /** Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. 'already_fixed' is a snooze, not a dismissal: pair it with state='potential' (restore) so the report reappears if the issue recurs. Use 'other' together with a dismissal_note for anything that doesn't fit a code.
     *
     * * `already_fixed` - Already fixed
     * * `report_unclear` - Report is unclear to me
     * * `analysis_wrong` - Agent's analysis is wrong
     * * `wontfix_intentional` - Won't fix - intentional behavior
     * * `wontfix_irrelevant` - Won't fix - issue is real but insignificant
     * * `other` - Something else… */
    dismissal_reason?: DismissalReasonEnumApi
    /**
     * Optional free-form note explaining the dismissal. Capped at 4000 characters.
     * @maxLength 4000
     */
    dismissal_note?: string
    /**
     * Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal.
     * @minimum 1
     * @maximum 100000
     */
    snooze_for?: number
    /**
     * Report ids to transition to `state` in one call (1–100). Duplicates are de-duplicated; each id is processed independently so one disallowed transition does not block the rest. `dismissal_reason`, `dismissal_note` and `snooze_for` apply to every id.
     * @maxItems 100
     */
    ids: string[]
}

export interface SignalReportBulkStateResultApi {
    /** The report id this result refers to. */
    id: string
    /** One of: transitioned, skipped, failed, not_found. transitioned: the state change was applied. skipped: the transition was not allowed from the report's current status (a 409 on the single-report endpoint). failed: the request data was invalid for this report. not_found: no report with this id is visible to you. */
    outcome: string
    /**
     * The report's status after the transition. Present only when outcome is 'transitioned'.
     * @nullable
     */
    status?: string | null
    /**
     * Human-readable explanation for non-transitioned outcomes (skipped / failed / not_found).
     * @nullable
     */
    detail?: string | null
}

export interface SignalReportBulkStateResponseApi {
    /** One result per requested id, in request order (after de-duplication). */
    results: SignalReportBulkStateResultApi[]
    /** Number of reports whose state was changed. */
    transitioned_count: number
    /** Number of reports whose transition was not allowed. */
    skipped_count: number
    /** Number of reports that failed on invalid request data. */
    failed_count: number
    /** Number of requested ids not visible to the caller. */
    not_found_count: number
}

export type ScoutOriginEnumApi = (typeof ScoutOriginEnumApi)[keyof typeof ScoutOriginEnumApi]

export const ScoutOriginEnumApi = {
    Canonical: 'canonical',
    Custom: 'custom',
} as const

/**
 * Per-(team, skill) scout config: schedule, enablement, and emit posture.
 *
 * One row per `signals-scout-*` skill on the team. The coordinator auto-creates a row
 * when it discovers a scout skill; this serializer lets agents tune the row.
 */
export interface SignalScoutConfigApi {
    readonly id: string
    /** The `signals-scout-*` skill this config controls. Set at creation, not editable. */
    readonly skill_name: string
    /** Human-readable summary of what this scout investigates, sourced from the scout skill's `description` metadata. Use it for a quick steer on the scout's focus without loading the full skill body. Empty if the skill is not currently present on the team or carries no description. */
    readonly description: string
    /** Where this scout came from: `canonical` for a scout PostHog ships and maintains (seeded from `products/signals/skills/`), or `custom` for one a team hand-authored on this project. Use it to badge built-in vs custom scouts instead of a hardcoded name list. Defaults to `custom` if the skill is not currently present on the team. */
    readonly scout_origin: ScoutOriginEnumApi
    /** Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator. */
    enabled?: boolean
    /** Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. */
    emit?: boolean
    /**
     * Minutes between runs (30–43200). The scout runs once this interval has elapsed since its last run.
     * @minimum 30
     * @maximum 43200
     */
    run_interval_minutes?: number
    /**
     * When the coordinator last dispatched this scout. Null if it has never run.
     * @nullable
     */
    readonly last_run_at: string | null
    readonly created_at: string
}

/**
 * Request body for registering a scout config without waiting for the coordinator tick.
 *
 * Upsert keyed on `skill_name`: if the coordinator (or a concurrent caller) already
 * registered the row, the provided tunables are applied to it instead.
 */
export interface SignalScoutConfigCreateApi {
    /**
     * The `signals-scout-*` skill to register a config for. The skill must already exist on this project — author it via the skills store first.
     * @maxLength 200
     */
    skill_name: string
    /** Whether this scout runs on its schedule. Defaults to true. */
    enabled?: boolean
    /** Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true. */
    emit?: boolean
    /**
     * Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).
     * @minimum 30
     * @maximum 43200
     */
    run_interval_minutes?: number
}

/**
 * Per-(team, skill) scout config: schedule, enablement, and emit posture.
 *
 * One row per `signals-scout-*` skill on the team. The coordinator auto-creates a row
 * when it discovers a scout skill; this serializer lets agents tune the row.
 */
export interface PatchedSignalScoutConfigApi {
    readonly id?: string
    /** The `signals-scout-*` skill this config controls. Set at creation, not editable. */
    readonly skill_name?: string
    /** Human-readable summary of what this scout investigates, sourced from the scout skill's `description` metadata. Use it for a quick steer on the scout's focus without loading the full skill body. Empty if the skill is not currently present on the team or carries no description. */
    readonly description?: string
    /** Where this scout came from: `canonical` for a scout PostHog ships and maintains (seeded from `products/signals/skills/`), or `custom` for one a team hand-authored on this project. Use it to badge built-in vs custom scouts instead of a hardcoded name list. Defaults to `custom` if the skill is not currently present on the team. */
    readonly scout_origin?: ScoutOriginEnumApi
    /** Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator. */
    enabled?: boolean
    /** Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. */
    emit?: boolean
    /**
     * Minutes between runs (30–43200). The scout runs once this interval has elapsed since its last run.
     * @minimum 30
     * @maximum 43200
     */
    run_interval_minutes?: number
    /**
     * When the coordinator last dispatched this scout. Null if it has never run.
     * @nullable
     */
    readonly last_run_at?: string | null
    readonly created_at?: string
}

/**
 * Response for an on-demand (`run now`) scout dispatch.
 *
 * The run executes asynchronously on the Temporal worker, so there is no `SignalScoutRun`
 * row yet at response time — the bridge row is created once the run's first turn starts.
 * Poll the scout's runs (`signals-scout-runs-list`) to see the resulting run and its findings.
 */
export interface SignalScoutManualRunApi {
    /** The `signals-scout-*` skill that was dispatched. */
    skill_name: string
    /** Temporal workflow id for the dispatched run. The run executes asynchronously; poll the scout's runs to see the resulting run row, its status, and any emitted findings. */
    workflow_id: string
    /** True when a new run was dispatched. The endpoint returns 409 instead when a run for this scout is already in progress. */
    started: boolean
}

/**
 * One project member's routing identity, for picking a `suggested_reviewers` entry on a report.
 */
export interface ScoutMemberApi {
    /** The member's stable PostHog user UUID — the same id that appears as `created_by.uuid` on entities they own. A durable handle for this person across runs. */
    user_uuid: string
    /** The member's email — use to match a finding's owner by name/email. */
    email: string
    /** The member's first name (may be empty). */
    first_name: string
    /** The member's last name (may be empty). */
    last_name: string
    /**
     * The member's resolved GitHub login (lowercased), already resolved server-side — put this value in a report's `suggested_reviewers` once you've matched the finding's owner to this row. Null when the member has no linked GitHub identity: a null-login member can't be routed to at all (neither a login nor a uuid resolves), so pick a different owner or leave `suggested_reviewers` empty.
     * @nullable
     */
    github_login: string | null
}

/**
 * A team's enforced scout run caps and current usage.
 *
 * These are the values the coordinator actually applies at dispatch (resolved per-team override →
 * fleet-wide default → code constant), so the UI can show the real throttle rather than what a
 * user thinks they configured.
 */
export interface ScoutLimitsApi {
    /** Most scout runs the team can start in a single 30-minute coordinator tick. */
    max_runs_per_tick: number
    /**
     * Most scout runs the team can start per rolling 24 hours, or null when uncapped.
     * @nullable
     */
    max_runs_per_day: number | null
    /** Scout runs the team has started in the trailing 24 hours. */
    runs_today: number
    /**
     * Runs still allowed in the trailing 24h window (max_runs_per_day − runs_today), or null when uncapped.
     * @nullable
     */
    runs_remaining_today: number | null
}

/**
 * Team-scoped scout metadata for the inbox / Code-app UIs: enrollment, the alpha banner, and
 * the enforced limits. Sourced from the `signals-scout` flag payload so the banner and caps can
 * change without a deploy to either app.
 */
export interface ScoutMetadataApi {
    /** Whether this project runs scouts. True when the project is in the signals-scout flag's enrollment set — either listed explicitly in guaranteed_team_ids or covered by the "*" wildcard (every project that turns scouts on) — and not in skip_team_ids. */
    enrolled: boolean
    /**
     * Free-form announcement banner to show above the scout UI (e.g. alpha run-limit notice), or null when unset.
     * @nullable
     */
    banner_message: string | null
    /** The team's enforced scout run caps and current usage. */
    limits: ScoutLimitsApi
}

/**
 * `inventory.project_context` — free-form orientation about the project's product.
 */
export interface ProjectContextApi {
    /**
     * Human-set product description on the project (max 1000 chars). When present, the most direct "what does this team's product do" answer. `null` when unset.
     * @nullable
     */
    product_description: string | null
    /** Registered app URLs for this team (toolbar / replay). The team's actual product surface; complements `$pageview.$host` discovery via `read-data-schema`. */
    app_urls: string[]
}

/**
 * One row in `inventory.product_intents`.
 */
export interface ProductIntentEntryApi {
    /** Product key the team signaled intent to use. */
    product_type: string
    /**
     * ISO-8601 timestamp the team activated the product, or null if intent only.
     * @nullable
     */
    activated_at: string | null
    /**
     * ISO-8601 timestamp the intent was first recorded.
     * @nullable
     */
    created_at: string | null
}

/**
 * One row in `inventory.integrations`. Sensitive config is intentionally excluded.
 */
export interface IntegrationEntryApi {
    /** Integration kind (e.g. `slack`, `github`, `linear`). */
    kind: string
    /**
     * ISO-8601 timestamp the integration was connected.
     * @nullable
     */
    created_at: string | null
}

/**
 * One row in `inventory.external_data_sources`.
 */
export interface ExternalDataSourceEntryApi {
    /** Warehouse source type (e.g. `Stripe`, `Postgres`, `BigQuery`). */
    source_type: string
    /** Current sync status (`Running`, `Failed`, `Paused`, etc.). */
    status: string
    /** Schema prefix used by this source, if any. */
    prefix: string
    /**
     * ISO-8601 timestamp the source was connected.
     * @nullable
     */
    created_at: string | null
    /**
     * ISO-8601 timestamp of the most recent completed sync job, or null if this source has never completed a sync. Use this to tell a healthy source apart from one stuck in `Running` that has imported zero rows — `status` alone conflates the two.
     * @nullable
     */
    last_run_at: string | null
    /**
     * Newest schema-level sync error for this source, or null if no schema is erroring.
     * @nullable
     */
    latest_error: string | null
}

/**
 * One row in either bucket of `inventory.signal_source_configs`.
 */
export interface SignalSourceConfigEntryApi {
    /** Source product the config applies to. */
    source_product: string
    /** Source type within the product. */
    source_type: string
}

/**
 * `inventory.signal_source_configs` split into enabled and disabled buckets.
 */
export interface SignalSourceConfigsBucketsApi {
    /** Source configs the team has explicitly enabled. */
    enabled: SignalSourceConfigEntryApi[]
    /** Source configs the team has explicitly disabled (different from never wired up). */
    disabled: SignalSourceConfigEntryApi[]
}

/**
 * `inventory.emit_eligibility` — whether scout findings can reach the inbox for this team.
 */
export interface EmitEligibilityApi {
    /** Whether the organization has approved AI data processing (an org-level gate on all scout emits). */
    ai_processing_approved: boolean
    /** Whether the `signals_scout` signal source is enabled for this team. */
    source_enabled: boolean
    /** True only when both team/org-level gates pass, so scout findings (signal and report channels alike) actually reach the inbox. When False, every emit is silently dropped — quick-close instead of doing throwaway investigation. Does not account for a scout's own dry-run `emit` toggle, which is per-config, not team-wide. */
    can_emit: boolean
    /**
     * One-line next step to unblock emits when `can_emit` is False; null when emits can flow.
     * @nullable
     */
    remediation: string | null
}

/**
 * One bucket in `inventory.existing_inbox_reports.by_status`.
 */
export interface InboxReportStatusBucketApi {
    /** Report status (e.g. `potential`, `candidate`, `ready`). */
    status: string
    /** Number of reports in this status (excludes deleted/suppressed). */
    count: number
}

/**
 * `inventory.existing_inbox_reports` — what's already been surfaced to the inbox.
 */
export interface ExistingInboxReportsApi {
    /** Total non-deleted, non-suppressed reports for this team. */
    total: number
    /** Per-status breakdown of inbox reports. */
    by_status: InboxReportStatusBucketApi[]
}

/**
 * One row in `inventory.recent_activity.by_scope`.
 */
export interface ScopeActivityEntryApi {
    /** Activity-log scope (entity type), e.g. `FeatureFlag`, `Dashboard`, `Survey`. */
    scope: string
    /** Total activity-log entries for this scope in the window (write velocity). */
    edits: number
    /** Distinct users who edited this scope in the window. */
    users: number
    /**
     * ISO-8601 timestamp of the most recent edit in the window.
     * @nullable
     */
    last_edit: string | null
}

/**
 * `inventory.recent_activity` — per-scope counts off the activity log.
 */
export interface RecentActivityApi {
    /** Lookback window in days the per-scope counts cover. */
    window_days: number
    /** Per-scope activity rows, busiest scope first. Triage which entity type the team has worked in lately. */
    by_scope: ScopeActivityEntryApi[]
}

/**
 * One row in `inventory.recent_reviewer_corrections.corrections`.
 */
export interface ReviewerCorrectionEntryApi {
    /** UUID of the report whose reviewers a human edited. */
    report_id: string
    /**
     * Report title at the time of the edit.
     * @nullable
     */
    report_title: string | null
    /** GitHub logins on the report before the human edit (lowercased). */
    before: string[]
    /** GitHub logins on the report after the human edit (lowercased). */
    after: string[]
    /**
     * ISO-8601 timestamp of the edit.
     * @nullable
     */
    at: string | null
}

/**
 * `inventory.recent_reviewer_corrections` — human edits to report reviewer lists.
 */
export interface RecentReviewerCorrectionsApi {
    /** Lookback window in days the corrections cover. */
    window_days: number
    /** Human reviewer edits, newest first. A human swapping a report's suggested reviewers is authoritative ownership precedent — route to who they chose. */
    corrections: ReviewerCorrectionEntryApi[]
}

/**
 * One row in `inventory.recent_dashboards`.
 */
export interface RecentDashboardEntryApi {
    /** Dashboard ID — pass to `dashboard-get` to pull the full payload. */
    id: number
    /** Dashboard name (may be blank if unnamed). */
    name: string
    /**
     * ISO-8601 timestamp of the most recent view in the PostHog UI.
     * @nullable
     */
    last_accessed_at: string | null
    /**
     * ISO-8601 timestamp of the most recent data refresh. Distinct from access — a dashboard can be refreshed without anyone viewing it.
     * @nullable
     */
    last_refresh: string | null
    /**
     * ISO-8601 timestamp the dashboard was created.
     * @nullable
     */
    created_at: string | null
}

/**
 * One row in `inventory.recent_surveys.recent`.
 */
export interface RecentSurveyEntryApi {
    /** Survey UUID — pass to `survey-get` for full question shape. */
    id: string
    /** Survey name (may be blank if unnamed). */
    name: string
    /** Survey mode: `popover`, `widget`, `external_survey`, or `api`. */
    type: string
    /** Derived status: `draft`, `running`, `stopped`, or `archived`. */
    status: string
    /**
     * ISO-8601 last-modified timestamp.
     * @nullable
     */
    updated_at: string | null
}

/**
 * `inventory.recent_surveys` — total + active count, plus the 5 most recently modified.
 */
export interface RecentSurveysApi {
    /** Total surveys on the team. */
    total_count: number
    /** Surveys that are live (not archived, started, and not yet ended). */
    active_count: number
    /** The 5 most recently updated surveys. */
    recent: RecentSurveyEntryApi[]
}

/**
 * One row in `inventory.recent_feature_flags.recent`.
 */
export interface RecentFeatureFlagEntryApi {
    /** Feature flag ID. */
    id: number
    /** Flag key used in code (`posthog.isFeatureEnabled('<key>')`). */
    key: string
    /** Human-set description; falls back to the key when blank. */
    name: string
    /** Whether the flag is currently evaluating (a user could be hitting it). */
    active: boolean
    /**
     * ISO-8601 last-modified timestamp.
     * @nullable
     */
    updated_at: string | null
}

/**
 * `inventory.recent_feature_flags` — total + active count, plus the 5 most recently modified.
 */
export interface RecentFeatureFlagsApi {
    /** Total non-deleted feature flags on the team. */
    total_count: number
    /** Flags currently evaluating (`active=true`). */
    active_count: number
    /** The 5 most recently updated non-deleted flags. */
    recent: RecentFeatureFlagEntryApi[]
}

/**
 * One row in `inventory.recent_experiments.recent`.
 */
export interface RecentExperimentEntryApi {
    /** Experiment ID. */
    id: number
    /** Experiment name. */
    name: string
    /** Derived status: `draft`, `running`, `stopped`, or `archived`. */
    status: string
    /**
     * Key of the experiment's feature flag — cross-ref into `recent_feature_flags`. Null if unlinked.
     * @nullable
     */
    feature_flag_key: string | null
    /**
     * ISO-8601 last-modified timestamp.
     * @nullable
     */
    updated_at: string | null
}

/**
 * `inventory.recent_experiments` — total + currently-running count, plus the 5 most recently modified.
 */
export interface RecentExperimentsApi {
    /** Total experiments on the team. */
    total_count: number
    /** Experiments currently running (started, not ended, not archived). */
    running_count: number
    /** The 5 most recently updated experiments. */
    recent: RecentExperimentEntryApi[]
}

/**
 * One row in `inventory.recent_alerts.recent`.
 */
export interface RecentAlertEntryApi {
    /** Alert configuration UUID. */
    id: string
    /** Alert name. */
    name: string
    /** Whether the alert is currently armed. */
    enabled: boolean
    /** Alert state (e.g. `not_firing`, `firing`). */
    state: string
    /**
     * How often the alert is evaluated (e.g. `daily`, `hourly`); null if unset.
     * @nullable
     */
    calculation_interval: string | null
    /**
     * ID of the insight the alert watches; null if none.
     * @nullable
     */
    insight_id: number | null
    /**
     * ISO-8601 creation timestamp.
     * @nullable
     */
    created_at: string | null
}

/**
 * `inventory.recent_alerts` — total + currently-enabled count, plus the 5 most recently created.
 */
export interface RecentAlertsApi {
    /** Total insight alerts on the team. */
    total_count: number
    /** Alerts currently armed (`enabled=true`). */
    enabled_count: number
    /** The 5 most recently created alerts. */
    recent: RecentAlertEntryApi[]
}

/**
 * One row in `inventory.recent_hog_functions.recent`.
 */
export interface RecentHogFunctionEntryApi {
    /** Hog function UUID. */
    id: string
    /** Hog function name. */
    name: string
    /**
     * Function type: `destination`, `transformation`, `site_app`, etc. Null if unset.
     * @nullable
     */
    type: string | null
    /**
     * Function kind sub-classifier; null if unset.
     * @nullable
     */
    kind: string | null
    /** Whether the function is currently enabled. */
    enabled: boolean
    /**
     * ISO-8601 last-modified timestamp.
     * @nullable
     */
    updated_at: string | null
}

/**
 * `inventory.recent_hog_functions` — total + enabled count, plus the 5 most recently modified.
 */
export interface RecentHogFunctionsApi {
    /** Total non-deleted hog functions on the team. */
    total_count: number
    /** Hog functions currently enabled (`enabled=true`). */
    enabled_count: number
    /** The 5 most recently updated hog functions. */
    recent: RecentHogFunctionEntryApi[]
}

/**
 * One row in `inventory.recent_hog_flows.recent`.
 */
export interface RecentHogFlowEntryApi {
    /** Hog flow UUID. */
    id: string
    /** Hog flow name. */
    name: string
    /** Flow lifecycle state (e.g. `draft`, `active`, `archived`). */
    status: string
    /**
     * ISO-8601 last-modified timestamp.
     * @nullable
     */
    updated_at: string | null
}

/**
 * `inventory.recent_hog_flows` — total + non-archived count, plus the 5 most recently modified.
 */
export interface RecentHogFlowsApi {
    /** Total hog flows on the team. */
    total_count: number
    /** Hog flows that are not archived. */
    active_count: number
    /** The 5 most recently updated hog flows. */
    recent: RecentHogFlowEntryApi[]
}

/**
 * One row in `inventory.recent_notebooks.recent`.
 */
export interface RecentNotebookEntryApi {
    /** Notebook short ID — pass to the notebooks API to open it. */
    short_id: string
    /** Notebook title (may be blank if untitled). */
    title: string
    /**
     * ISO-8601 last-modified timestamp.
     * @nullable
     */
    last_modified_at: string | null
}

/**
 * `inventory.recent_notebooks` — total + the 5 most recently modified.
 */
export interface RecentNotebooksApi {
    /** Total non-deleted notebooks on the team. */
    total_count: number
    /** The 5 most recently modified notebooks. */
    recent: RecentNotebookEntryApi[]
}

/**
 * One row in `inventory.recent_cohorts.recent`.
 */
export interface RecentCohortEntryApi {
    /** Cohort ID. */
    id: number
    /** Cohort name. */
    name: string
    /** True for a one-shot snapshot cohort; false for a dynamic-filter cohort. */
    is_static: boolean
    /**
     * Membership size when last calculated; null if never calculated.
     * @nullable
     */
    count: number | null
    /**
     * ISO-8601 creation timestamp.
     * @nullable
     */
    created_at: string | null
}

/**
 * `inventory.recent_cohorts` — total + the 5 most recently created.
 */
export interface RecentCohortsApi {
    /** Total non-deleted cohorts on the team. */
    total_count: number
    /** The 5 most recently created cohorts. */
    recent: RecentCohortEntryApi[]
}

/**
 * One row in `inventory.recent_actions.recent`.
 */
export interface RecentActionEntryApi {
    /** Action ID. */
    id: number
    /** Action name. */
    name: string
    /**
     * ISO-8601 last-modified timestamp.
     * @nullable
     */
    updated_at: string | null
}

/**
 * `inventory.recent_actions` — total + the 5 most recently modified.
 */
export interface RecentActionsApi {
    /** Total non-deleted actions on the team. */
    total_count: number
    /** The 5 most recently updated actions. */
    recent: RecentActionEntryApi[]
}

/**
 * One row in `inventory.top_events`.
 */
export interface TopEventEntryApi {
    /** Rolling lookback window (in days) that every count and timestamp on this row is measured over — these are windowed figures, NOT lifetime totals. A capture gap can collapse a real, high-volume project's in-window counts to near-zero, so a thin `count` here does not by itself mean the project is low-volume: rule out an ingestion gap (compare against a trailing baseline via a direct `execute-sql`) before closing out a surface as unused. */
    window_days: number
    /** Event name as captured. */
    event: string
    /** Number of occurrences within the last `window_days` (windowed, not lifetime). */
    count: number
    /** `uniq(person_id)` over the window — reach. Distinguishes a high-count event firing on one power user from one firing on many users. */
    distinct_users: number
    /** Count in just the last 24 hours. Compare to `count / window_days` to spot bursts: a ratio well above `1 / window_days` means the event is concentrated in the last day. */
    recent_24h_count: number
    /** `uniq(person_id)` over just the last 24 hours. A burst across many users is qualitatively different from one user in a loop. */
    recent_24h_users: number
    /**
     * ISO-8601 timestamp of the earliest occurrence within the `window_days` window. Compare to the window start to spot new event types: close to `now` ⇒ likely new or recently bursting; close to the window edge ⇒ has been around at least that long (the window can't tell you when the event *truly* first appeared).
     * @nullable
     */
    first_seen_in_window: string | null
    /**
     * ISO-8601 timestamp of the most recent occurrence within the `window_days` window.
     * @nullable
     */
    last_seen_in_window: string | null
}

/**
 * The deterministic inventory layer of a project profile.
 *
 * Read this to orient on the team's product mix, integrations, warehouse sources, signal
 * coverage, and existing inbox surface in one tool call. Distinct from `SignalScratchpad`:
 * profile is ground truth from authoritative tables; memory is agent inference.
 */
export interface ProjectProfileInventoryApi {
    /** Free-form orientation: human-set product description + registered app URLs. */
    project_context: ProjectContextApi
    /** Product keys this team has completed onboarding for, sorted alphabetically. */
    products_in_use: string[]
    /** Products the team signaled intent to use; useful for spotting stuck onboardings. */
    product_intents: ProductIntentEntryApi[]
    /** Connected integrations (kind + connection time only — config never surfaced). */
    integrations: IntegrationEntryApi[]
    /** Connected warehouse sources (excludes soft-deleted). */
    external_data_sources: ExternalDataSourceEntryApi[]
    /** Signal source configs split into enabled / disabled buckets. */
    signal_source_configs: SignalSourceConfigsBucketsApi
    /** Whether scout findings can actually reach the inbox for this team — the org-level AI data-processing consent gate and the `signals_scout` source toggle, plus a one-line remediation pointer. Read at cold start to quick-close before doing throwaway work. */
    emit_eligibility: EmitEligibilityApi
    /** Counts of reports already in the inbox, grouped by status. */
    existing_inbox_reports: ExistingInboxReportsApi
    /** Per-scope counts off the activity log over the recent-activity window — cross-cutting orientation across every entity type (surveys, feature flags, experiments, dashboards, insights, cohorts, notebooks, actions, etc.). Each scope reports `edits` (total log entries), `users` (distinct user count), and `last_edit` (ISO-8601). Use to triage which scope a team has been working in lately before drilling down via the per-entity readers or `advanced-activity-logs-list`. */
    recent_activity: RecentActivityApi
    /** Recent human edits to report reviewer lists (before/after GitHub logins). The strongest ownership precedent available — check it before setting `suggested_reviewers` and fold what it shows into `reviewer:` memory keys. */
    recent_reviewer_corrections: RecentReviewerCorrectionsApi
    /** Up to 20 dashboards on this team sorted by `last_accessed_at` desc — what the team is currently looking at, not necessarily the most-trafficked. We don't have per-dashboard view counts in Postgres, only the timestamp of the most recent access. */
    recent_dashboards: RecentDashboardEntryApi[]
    /** Surveys orientation: total + active count, plus the 5 most recently updated surveys with id, name, type, status (draft / running / stopped / archived), and updated_at. */
    recent_surveys: RecentSurveysApi
    /** Feature flag orientation: total + active count, plus the 5 most recently updated non-deleted flags with id, key, name, active, and updated_at. */
    recent_feature_flags: RecentFeatureFlagsApi
    /** Experiment orientation: total + running count, plus the 5 most recently updated experiments. The feature_flag_key on each row lets the scout correlate experiments with the `recent_feature_flags` section. */
    recent_experiments: RecentExperimentsApi
    /** Alert orientation: total + enabled count, plus the 5 most recently created alerts with their state and threshold metadata. */
    recent_alerts: RecentAlertsApi
    /** Hog function orientation: total + enabled count, plus the 5 most recently updated destinations / transformations the team has wired up via the CDP pipelines. */
    recent_hog_functions: RecentHogFunctionsApi
    /** Hog flow orientation: total + non-archived count, plus the 5 most recently updated automation flows. */
    recent_hog_flows: RecentHogFlowsApi
    /** Notebook orientation: total + the 5 most recently modified notebooks — useful signal for what the team has been investigating. */
    recent_notebooks: RecentNotebooksApi
    /** Cohort orientation: total + the 5 most recently created cohorts on the team. */
    recent_cohorts: RecentCohortsApi
    /** Action orientation: total + the 5 most recently updated actions — useful to anchor agent reasoning about what the team treats as a meaningful interaction. */
    recent_actions: RecentActionsApi
    /**
     * Top ~50 events by count over a recent rolling window (each row carries `window_days`), with first/last seen timestamps within that window. These are WINDOWED counts, not lifetime totals: a capture gap can collapse a real, high-volume project's counts to near-zero here, so rule out an ingestion gap (compare against a trailing baseline via a direct `execute-sql`) before reading thinness as a genuinely low-volume project. `null` if the underlying ClickHouse query failed or timed out (distinct from `[]`, which means the team has no captures in the window). Use the gap between `first_seen_in_window` and `now` to spot new event types or recent bursts.
     * @nullable
     */
    top_events: TopEventEntryApi[] | null
}

/**
 * Top-level `payload` shape on a `SignalProjectProfile` row.
 *
 * v1 carries `inventory` only. Phase 7 will add `deltas`, `activity_notes`, and
 * `narrative` slots — they're absent (not null) in v1 responses.
 */
export interface ProjectProfilePayloadApi {
    /** Deterministic snapshot of what's true about the project. */
    inventory: ProjectProfileInventoryApi
}

/**
 * Wire shape for the project profile returned by `signals-scout-harness-project-profile-list`.
 *
 * Read this once at the start of a run (after `skill-get`) to orient on the team. Cache
 * is per-team with a soft TTL (`PROFILE_TTL`); the response always reflects either the
 * latest cached profile or a freshly-built one if the cache was stale or the caller passed
 * `force_refresh=true`.
 */
export interface ProjectProfileApi {
    /** UUID of the `SignalProjectProfile` row. */
    profile_id: string
    /** ISO-8601 timestamp the profile was built. */
    computed_at: string
    /** ISO-8601 timestamp after which the profile is considered stale. */
    expires_at: string
    /** Schema version of the inventory builder. Bumps invalidate older cached rows. */
    source_version: string
    /** Structured profile content. v1 has `inventory` only. */
    payload: ProjectProfilePayloadApi
}

/**
 * Lightweight projection of a `SignalScoutRun` row used by `search-recent-runs`.
 *
 * Status and timestamps flow from the linked `tasks.TaskRun`.
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
    /** ISO-8601 timestamp the bridge row was created — the field `date_from` / `date_to` filter and order on. Use this (not `started_at`) as the `date_to` cursor when walking past the 100-row cap, so runs created in the gap between a boundary run's TaskRun and its bridge row aren't skipped. */
    created_at: string
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
    /**
     * Full `error_message` from the linked TaskRun, surfaced only for failed/cancelled runs (null otherwise, including on success). Use `failure_reason` for a concise scan-friendly summary.
     * @nullable
     */
    error?: string | null
    /**
     * Concise derived reason the run didn't complete cleanly — the first line of `error` (bounded), or a status-derived fallback. Null unless the run terminated failed/cancelled. Read this to see at a glance *why* a run emitted nothing without pulling full stack traces.
     * @nullable
     */
    failure_reason?: string | null
    /** Number of findings this run actually emitted to the inbox. 0 for runs that investigated but surfaced nothing, or ran dry-run / before AI approval. `> 0` means the run produced at least one `Signal`. */
    emitted_count: number
    /** The `finding_id`s behind `emitted_count`, in emit order. Each maps to a `Signal` with `source_id = run:<run_id>:finding:<finding_id>`. Empty for non-emitting runs. */
    emitted_finding_ids: string[]
    /** The `SignalReport` ids this run authored directly via the `emit_report` channel, in emit order. Separate from `emitted_finding_ids` (weak `emit_signal` findings) — a report-authoring scout writes a full report here instead. Empty for runs that authored no report. */
    emitted_report_ids: string[]
    /** The `SignalReport` ids this run mutated via the `edit_report` channel (rewrote title/summary and/or appended a note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are generally not reports the run authored. Empty for runs that edited no report. */
    edited_report_ids: string[]
}

/**
 * Full `SignalScoutRun` projection used by `get-run`. Same shape as the summary
 * today; kept distinct so future detail-only extensions (linked Signal rows,
 * LLMA token-cost join) can land here without bloating the list response.
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
    /** ISO-8601 timestamp the bridge row was created — the field `date_from` / `date_to` filter and order on. Use this (not `started_at`) as the `date_to` cursor when walking past the 100-row cap, so runs created in the gap between a boundary run's TaskRun and its bridge row aren't skipped. */
    created_at: string
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
    /**
     * Full `error_message` from the linked TaskRun, surfaced only for failed/cancelled runs (null otherwise, including on success). Use `failure_reason` for a concise scan-friendly summary.
     * @nullable
     */
    error?: string | null
    /**
     * Concise derived reason the run didn't complete cleanly — the first line of `error` (bounded), or a status-derived fallback. Null unless the run terminated failed/cancelled. Read this to see at a glance *why* a run emitted nothing without pulling full stack traces.
     * @nullable
     */
    failure_reason?: string | null
    /** Number of findings this run actually emitted to the inbox. 0 for runs that investigated but surfaced nothing, or ran dry-run / before AI approval. `> 0` means the run produced at least one `Signal`. */
    emitted_count: number
    /** The `finding_id`s behind `emitted_count`, in emit order. Each maps to a `Signal` with `source_id = run:<run_id>:finding:<finding_id>`. Empty for non-emitting runs. */
    emitted_finding_ids: string[]
    /** The `SignalReport` ids this run authored directly via the `emit_report` channel, in emit order. Separate from `emitted_finding_ids` (weak `emit_signal` findings) — a report-authoring scout writes a full report here instead. Empty for runs that authored no report. */
    emitted_report_ids: string[]
    /** The `SignalReport` ids this run mutated via the `edit_report` channel (rewrote title/summary and/or appended a note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are generally not reports the run authored. Empty for runs that edited no report. */
    edited_report_ids: string[]
}

/**
 * One suggested reviewer — identified by `github_login`, `user_uuid`, or both.
 *
 * The server canonicalizes each entry to a lowercased GitHub login: a `user_uuid` is resolved to the
 * org member's linked GitHub login (and wins over a supplied `github_login` when both are given). A
 * `user_uuid` that isn't an org member of this team with a linked GitHub identity is rejected — so a
 * reviewer is never silently dropped.
 */
export interface SuggestedReviewerApi {
    /**
     * GitHub login (case-insensitive, stored lowercased) — e.g. `octocat`, no `@`, no display name. Resolve one via `signals-scout-members-list` (each member row carries a resolved `github_login`) or git history when you only have a name.
     * @maxLength 200
     */
    github_login?: string
    /** PostHog user UUID (e.g. from `signals-scout-members-list`, or an entity's `created_by`). Resolved server-side to the member's linked GitHub login — use this when you know the PostHog user but not their GitHub handle. Must be a concrete UUID; the `@me` alias is not valid here. */
    user_uuid?: string
}

/**
 * Request body for `edit-report`. Can target ANY of the team's inbox reports, not just scout-authored ones.
 */
export interface EditReportRequestApi {
    /** Id of the report to edit (must belong to this project). */
    report_id: string
    /**
     * Optional new title. Conventional-commit style (`type(scope): description`) renders with type/scope styling. The pipeline may later re-research and overwrite it.
     * @maxLength 300
     * @nullable
     */
    title?: string | null
    /**
     * Optional new summary. Markdown is supported (headings, lists, code, links; images are not rendered); lead with one plain declarative sentence — it becomes the inbox card headline. The pipeline may later re-research and overwrite it.
     * @nullable
     */
    summary?: string | null
    /**
     * Optional free-form note to append to the report's work log (attributed to this scout).
     * @nullable
     */
    append_note?: string | null
    /**
     * Optional reviewers to set on the report (each a `github_login` and/or `user_uuid`), replacing any existing list. Use this to route a report that surfaced with no reviewer — it re-runs autostart, so a report that was missing a qualifying reviewer can now open a draft PR. An empty list is a no-op (existing reviewers are left untouched, never cleared).
     * @maxItems 10
     */
    suggested_reviewers?: SuggestedReviewerApi[]
}

export interface EditReportResponseApi {
    /** Id of the edited report. */
    report_id: string
    /** Which presentation fields changed (e.g. `title`, `summary`); empty if only a note was appended. */
    updated_fields: string[]
    /** Whether a note artefact was appended. */
    note_appended: boolean
    /** Whether the report's suggested reviewers were replaced. */
    reviewers_set: boolean
}

/**
 * * `P0` - P0
 * * `P1` - P1
 * * `P2` - P2
 * * `P3` - P3
 * * `P4` - P4
 */
export type AutonomyPriorityEnumApi = (typeof AutonomyPriorityEnumApi)[keyof typeof AutonomyPriorityEnumApi]

export const AutonomyPriorityEnumApi = {
    P0: 'P0',
    P1: 'P1',
    P2: 'P2',
    P3: 'P3',
    P4: 'P4',
} as const

/**
 * One finding a scout run emitted to the inbox — the persisted, queryable record of
 * *what* the run surfaced, returned by `signals-scout-runs-emissions-list`. The emitted text
 * lives in `description`; `source_id` is the join key (`run:<run_id>:finding:<finding_id>`)
 * back into the underlying signal store.
 */
export interface SignalScoutEmissionApi {
    readonly id: string
    /** UUID of the `SignalScoutRun` that emitted this finding. */
    run_id: string
    /** Stable id the finding was emitted under; matches an entry in the run's `emitted_finding_ids`. */
    finding_id: string
    /** The emitted finding prose — the signal's `description` as surfaced to the inbox. */
    description: string
    /**
     * Agent's weight for the signal in [0, 1]. Drives ranking in the inbox.
     * @minimum 0
     * @maximum 1
     */
    weight: number
    /**
     * Agent's confidence the finding is real in [0, 1].
     * @minimum 0
     * @maximum 1
     */
    confidence: number
    /** Optional severity tag — one of P0, P1, P2, P3, P4 — or null if the run didn't set one.
     *
     * * `P0` - P0
     * * `P1` - P1
     * * `P2` - P2
     * * `P3` - P3
     * * `P4` - P4 */
    severity: AutonomyPriorityEnumApi | null
    /** Slug tags the scout attached to this finding (lowercase kebab-case, e.g. `cost-spike`). Empty list when the run set none. */
    tags: string[]
    /** Deterministic `run:<run_id>:finding:<finding_id>` — the join key into the underlying signal store. */
    source_id: string
    /** ISO-8601 timestamp the finding was emitted. */
    emitted_at: string
}

/**
 * Minimal inbox `SignalReport` projection for the scout reverse lookup — just enough
 * for the scout UI to render a clickable chip and deep-link into the inbox, which loads
 * the full report itself.
 */
export interface LinkedSignalReportApi {
    /** UUID of the linked `SignalReport`. */
    id: string
    /**
     * LLM-generated report title, or null if the report hasn't been summarised yet.
     * @nullable
     */
    title: string | null
    /** Current report status (e.g. `potential`, `ready`, `resolved`). */
    status: string
}

/**
 * One finding the run emitted, paired with the inbox report (if any) its signal grouped into.
 *
 * Best-effort reverse of the report -> signals link: `report` is null when the finding hasn't
 * grouped into a report yet, was de-duplicated away, or its signal was deleted.
 */
export interface ScoutEmissionReportLinkApi {
    /** Stable id the finding was emitted under. */
    finding_id: string
    /** Deterministic `run:<run_id>:finding:<finding_id>` join key into the signal store. */
    source_id: string
    /** The inbox report this finding linked to, or null if none could be resolved. */
    report: LinkedSignalReportApi | null
}

/**
 * One observation backing an authored report — becomes a bound signal row on the report.
 */
export interface ReportEvidenceApi {
    /** Prose for this observation. Embedded and rendered to the safety/research surfaces. */
    description: string
    /** Stable id for this observation within the report (lets a later edit address it). */
    source_id: string
    /**
     * Optional per-signal weight (defaults to 1.0). Scouts rarely need to set this.
     * @minimum 0
     */
    weight?: number
}

/**
 * * `immediately_actionable` - immediately_actionable
 * * `requires_human_input` - requires_human_input
 * * `not_actionable` - not_actionable
 */
export type ActionabilityEnumApi = (typeof ActionabilityEnumApi)[keyof typeof ActionabilityEnumApi]

export const ActionabilityEnumApi = {
    ImmediatelyActionable: 'immediately_actionable',
    RequiresHumanInput: 'requires_human_input',
    NotActionable: 'not_actionable',
} as const

/**
 * Request body for `emit-report`. Run attribution is taken from the URL path.
 */
export interface EmitReportRequestApi {
    /**
     * One-line report title the inbox shows. Conventional-commit style (`type(scope): description`, e.g. `fix(insights): missing series color`) renders with type/scope styling.
     * @maxLength 300
     */
    title: string
    /** The report body the inbox shows. Markdown is supported (headings, lists, code, links; images are not rendered). Lead with one plain declarative sentence — the inbox card uses your first line verbatim as the headline (~140 chars, emphasis stripped), then renders the full markdown in the detail view. */
    summary: string
    /**
     * The observations backing the report — each becomes a bound signal. At least one.
     * @minItems 1
     */
    evidence: ReportEvidenceApi[]
    /** 2-3 sentence evidence-grounded justification for the actionability call below. */
    actionability_explanation: string
    /** The scout's actionability call: `immediately_actionable` -> the report surfaces READY; `requires_human_input` -> PENDING_INPUT; `not_actionable` -> suppressed. A safety-judge failure suppresses the report regardless.
     *
     * * `immediately_actionable` - immediately_actionable
     * * `requires_human_input` - requires_human_input
     * * `not_actionable` - not_actionable */
    actionability: ActionabilityEnumApi
    /** Whether the issue already appears fixed in recent changes (tracked separately). */
    already_addressed?: boolean
    /**
     * Optional repo for autostart (opening a draft PR): `owner/repo` targets that repo, the `NO_REPO` sentinel opts out (report lands without a PR), and omitting it triggers free-form selection across the team's repos — the slow path on a many-repo team, so pass `owner/repo` when you know it.
     * @nullable
     */
    repository?: string | null
    /** Optional priority (`P0`-`P4`). Required for autostart; pair with `priority_explanation`.
     *
     * * `P0` - P0
     * * `P1` - P1
     * * `P2` - P2
     * * `P3` - P3
     * * `P4` - P4 */
    priority?: AutonomyPriorityEnumApi | null
    /**
     * 2-3 sentence justification for `priority`. Required when `priority` is set.
     * @nullable
     */
    priority_explanation?: string | null
    /**
     * Optional reviewers to route the report to (each a `github_login` and/or `user_uuid`). This is the primary way a report reaches a human — the inbox floats a reviewer's own reports to the top of their inbox even when no PR is involved — so set it whenever you can name a plausible owner. It also gates autostart: a PR opens only if at least one reviewer clears their autonomy threshold.
     * @maxItems 10
     */
    suggested_reviewers?: SuggestedReviewerApi[]
}

export interface EmitReportResponseApi {
    /**
     * The authored report's id (null only when a preflight gate skipped the call). Returned even when suppressed, so you can edit/dedup against it.
     * @nullable
     */
    report_id: string | null
    /**
     * Birth status: `ready` | `pending_input` | `suppressed`, or null when gate-skipped.
     * @nullable
     */
    report_status: string | null
    /** True when the report actually surfaced in the inbox (READY or PENDING_INPUT). */
    emitted: boolean
    /**
     * `scout_config_missing` | `scout_emit_disabled` | `ai_processing_not_approved` | `source_disabled` | null when not gate-skipped.
     * @nullable
     */
    skipped_reason: string | null
    /**
     * When the safety judge suppressed the report, why; null when safe.
     * @nullable
     */
    safety_explanation: string | null
    /**
     * One-line, actionable next step when `skipped_reason` is set and the block is fixable (e.g. an org admin must approve AI data processing). Null when the report was authored or the skip isn't something the scout can act on.
     * @nullable
     */
    remediation: string | null
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
    /**
     * Canonical evidence-bundle prose. Becomes the signal's `description`.
     * @maxLength 50000
     */
    description: string
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
     *
     * * `P0` - P0
     * * `P1` - P1
     * * `P2` - P2
     * * `P3` - P3
     * * `P4` - P4 */
    severity?: AutonomyPriorityEnumApi | null
    /** Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`). */
    dedupe_keys?: string[]
    /**
     * Optional category tags as lowercase kebab-case slugs (e.g. `cost-spike`, `silent-failure`), max 10. Reuse the vocabulary in your `tags:<domain>:taxonomy` scratchpad entry when a tag fits; coin a new slug when a genuinely new category emerges. Near-miss formats are normalized to slugs; persisted in the signal's `extra.tags` and on the emission row.
     * @maxItems 10
     * @items.maxLength 50
     */
    tags?: string[]
    /** Optional time window the finding refers to. */
    time_range?: TimeRangeApi | null
    /**
     * Optional MCP trace id for cross-system debugging.
     * @nullable
     */
    mcp_trace_id?: string | null
    /**
     * Stable id for this finding, baked into the signal's source_id for traceability. NOT a dedupe key — re-emitting the same id creates another signal.
     * @maxLength 100
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
    /**
     * One-line, actionable next step when `skipped_reason` is set and the block is fixable (e.g. an org admin must approve AI data processing). Null when emitted normally or the skip isn't something the scout can act on.
     * @nullable
     */
    remediation: string | null
}

/**
 * Request body for the batched emissions / emission-reports lookups: the set of run UUIDs to
 * resolve in one call. Collapses the findings UI's old per-run fan-out (one request — and for the
 * reports lookup, one ClickHouse round-trip — per emitted run) into a single request.
 */
export interface ScoutRunIdsBatchRequestApi {
    /**
     * UUIDs of the `SignalScoutRun` rows to resolve in one batch. Run ids belonging to another team are silently ignored (they contribute no rows) rather than failing the whole request. Capped at 200 ids per call.
     * @maxItems 200
     */
    run_ids: string[]
}

/**
 * Fleet-wide tally of recently emitted findings — backs the "Scout findings" callout so it
 * renders from one cheap query instead of the client walking the whole paginated runs window.
 */
export interface FleetFindingsSummaryApi {
    /** Total findings the fleet emitted in the window — the sum of each emitted run's `emitted_count`, over the most recent 120 emitted runs. */
    count: number
    /** Number of distinct scouts (skills) that emitted at least one finding in the window. */
    scout_count: number
    /**
     * ISO-8601 timestamp of the most recently emitted finding's run (TaskRun completion, falling back to run creation), or null when nothing was emitted in the window.
     * @nullable
     */
    latest_at: string | null
}

/**
 * `SignalScratchpad` projection used by `search-memory` and `remember`.
 */
export interface ScratchpadEntryApi {
    /** Agent-chosen semantic key, unique per team. */
    key: string
    /** Prose content for prompt injection. Blank when the search projected it out (`keys_only=true`); truncated to a preview when `content_max_chars` was set. */
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
    /**
     * Canonical skill name of the scout that created this entry (e.g. `signals-scout-apm`), or null if human-authored.
     * @nullable
     */
    created_by_skill?: string | null
    /**
     * Relative Tasks UI deep-link to the run that created this entry, or null if the run linkage isn't captured.
     * @nullable
     */
    created_by_run_url?: string | null
}

/**
 * Request body for `remember`.
 */
export interface RememberRequestApi {
    /**
     * Agent-chosen semantic key, unique per team; re-using a key overwrites the entry in place. Key off the *stable identity* of what you're tracking — never embed a date, timestamp, or run id (that mints a new row every run and breaks dedupe). For run state/cursors, use one fixed key and keep the timestamp in `content`.
     * @maxLength 300
     */
    key: string
    /**
     * Prose to write. Read verbatim into future prompts.
     * @maxLength 50000
     */
    content: string
    /**
     * Run that authored this memory; persisted as `created_by_run_id` for lineage. Best-effort — a `run_id` that isn't a run on this project is dropped (lineage left null), not rejected, so the memory write is never lost.
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
 * * `llm_analytics` - LLM analytics
 * * `github` - GitHub
 * * `linear` - Linear
 * * `jira` - Jira
 * * `zendesk` - Zendesk
 * * `conversations` - Conversations
 * * `error_tracking` - Error tracking
 * * `pganalyze` - pganalyze
 * * `signals_scout` - Signals scout
 * * `logs` - Logs
 * * `health_checks` - Health checks
 * * `endpoints` - Endpoints
 * * `replay_vision` - Replay Vision
 */
export type SignalSourceConfigSourceProductEnumApi =
    (typeof SignalSourceConfigSourceProductEnumApi)[keyof typeof SignalSourceConfigSourceProductEnumApi]

export const SignalSourceConfigSourceProductEnumApi = {
    SessionReplay: 'session_replay',
    LlmAnalytics: 'llm_analytics',
    Github: 'github',
    Linear: 'linear',
    Jira: 'jira',
    Zendesk: 'zendesk',
    Conversations: 'conversations',
    ErrorTracking: 'error_tracking',
    Pganalyze: 'pganalyze',
    SignalsScout: 'signals_scout',
    Logs: 'logs',
    HealthChecks: 'health_checks',
    Endpoints: 'endpoints',
    ReplayVision: 'replay_vision',
} as const

/**
 * * `session_analysis_cluster` - Session analysis cluster
 * * `evaluation` - Evaluation
 * * `evaluation_report` - Evaluation report
 * * `issue` - Issue
 * * `ticket` - Ticket
 * * `issue_created` - Issue created
 * * `issue_reopened` - Issue reopened
 * * `issue_spiking` - Issue spiking
 * * `cross_source_issue` - Cross source issue
 * * `alert_state_change` - Alert state change
 * * `health_issue` - Health issue
 * * `endpoint_execution_failed` - Endpoint execution failed
 * * `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded
 * * `scanner_finding` - Scanner finding
 */
export type SignalSourceConfigSourceTypeEnumApi =
    (typeof SignalSourceConfigSourceTypeEnumApi)[keyof typeof SignalSourceConfigSourceTypeEnumApi]

export const SignalSourceConfigSourceTypeEnumApi = {
    SessionAnalysisCluster: 'session_analysis_cluster',
    Evaluation: 'evaluation',
    EvaluationReport: 'evaluation_report',
    Issue: 'issue',
    Ticket: 'ticket',
    IssueCreated: 'issue_created',
    IssueReopened: 'issue_reopened',
    IssueSpiking: 'issue_spiking',
    CrossSourceIssue: 'cross_source_issue',
    AlertStateChange: 'alert_state_change',
    HealthIssue: 'health_issue',
    EndpointExecutionFailed: 'endpoint_execution_failed',
    EndpointBreakdownLimitExceeded: 'endpoint_breakdown_limit_exceeded',
    ScannerFinding: 'scanner_finding',
} as const

export interface SignalSourceConfigApi {
    readonly id: string
    source_product: SignalSourceConfigSourceProductEnumApi
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
    source_product?: SignalSourceConfigSourceProductEnumApi
    source_type?: SignalSourceConfigSourceTypeEnumApi
    enabled?: boolean
    config?: unknown
    readonly created_at?: string
    readonly updated_at?: string
    /** @nullable */
    readonly status?: string | null
}

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
     *
     * * `P0` - P0
     * * `P1` - P1
     * * `P2` - P2
     * * `P3` - P3
     * * `P4` - P4 */
    slack_notification_min_priority?: AutonomyPriorityEnumApi | BlankEnumApi | null
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
     * Filter reports by whether a shipped implementation pull request exists. 'true' keeps only reports with a PR; 'false' keeps only those without. Pair with limit=1 to count PR reports cheaply.
     */
    has_implementation_pr?: boolean
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
     * Comma-separated list of priorities to include. Valid values: P0, P1, P2, P3, P4. Reports without a priority assignment are excluded when this filter is set.
     */
    priority?: string
    /**
     * Case-insensitive substring match against report title and summary.
     */
    search?: string
    /**
     * Comma-separated list of source products to include. Reports are kept if at least one of their contributing signals comes from one of these products (e.g. error_tracking, session_replay).
     */
    source_product?: string
    /**
     * Comma-separated list of statuses to include. Valid values: potential, candidate, in_progress, pending_input, ready, resolved, failed, suppressed. Defaults to all statuses except suppressed.
     */
    status?: string
    /**
     * Comma-separated list of PostHog user UUIDs. Reports are kept if their suggested reviewers include any of the given users.
     */
    suggested_reviewers?: string
    /**
     * Only reports associated with this task (via the report's task associations).
     */
    task_id?: string
}

export type SignalsReportArtefactsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SignalsScoutMembersListParams = {
    /**
     * Case-insensitive substring filter over member email and first/last name. Use it to narrow a large project's roster to the owner you're trying to match instead of pulling every member.
     * @minLength 1
     */
    search?: string
}

export type SignalsScoutProjectProfileGetParams = {
    /**
     * When true, skip the cache and rebuild the profile from authoritative sources before responding. Use after seeding events, importing data, or any other change the caller knows just landed but hasn't surfaced through natural cache expiry yet. Honored only for the internal scout token — public read callers get the cached profile regardless. Concurrent forced rebuilds are serialized by the team-keyed advisory lock — at most one extra `build_inventory` per simultaneous request.
     */
    force_refresh?: boolean
}

export type SignalsScoutRunsListParams = {
    /**
     * ISO-8601 inclusive lower bound on `created_at`. Omit to skip the lower bound.
     */
    date_from?: string
    /**
     * ISO-8601 exclusive upper bound on `created_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `created_at` of the oldest run from the prior page).
     */
    date_to?: string
    /**
     * Filter by emit outcome. `true` returns only runs that emitted at least one finding (`emitted_count > 0`); `false` returns only runs that emitted nothing. Omit for both.
     * @nullable
     */
    emitted?: boolean | null
    /**
     * Max rows to return (default 20, hard cap 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Exact-match filter on the scout skill (e.g. `signals-scout-errors`). Narrows the run dump to a single scout — the primary scoping path when a specialist dedupes against its own past runs. Omit to span every scout on the team.
     * @minLength 1
     */
    skill_name?: string
    /**
     * Exact-match filter on the skill version. Pair with `skill_name` to pin one version; omit for all.
     * @minimum 1
     */
    skill_version?: number
    /**
     * Case-insensitive substring match on the scout's end-of-run `summary`. Omit to skip the filter.
     * @minLength 1
     */
    text?: string
}

export type SignalsScoutRunsRecentEmissionsParams = {
    /**
     * ISO-8601 inclusive lower bound on `emitted_at`. Omit to skip the lower bound.
     */
    date_from?: string
    /**
     * ISO-8601 exclusive upper bound on `emitted_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `emitted_at` of the oldest emission from the prior page).
     */
    date_to?: string
    /**
     * Max rows to return (default 50, hard cap 200).
     * @minimum 1
     * @maximum 200
     */
    limit?: number
    /**
     * Exact-match filter on the emitting scout's skill (e.g. `signals-scout-errors`). Narrows to findings one specialist surfaced; omit to span every scout on the team.
     * @minLength 1
     */
    skill_name?: string
}

export type SignalsScoutRunsFindingsSummaryParams = {
    /**
     * Lookback window in hours over runs' `created_at` (default 72, hard cap 168).
     * @minimum 1
     * @maximum 168
     */
    window_hours?: number
}

export type SignalsScoutScratchpadSearchParams = {
    /**
     * Truncate each entry's `content` to the first N characters (a preview). Omit for the full body. Ignored when `keys_only=true`.
     * @minimum 0
     */
    content_max_chars?: number
    /**
     * ISO-8601 inclusive lower bound on `updated_at`. Omit to skip the lower bound.
     */
    date_from?: string
    /**
     * ISO-8601 exclusive upper bound on `updated_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `updated_at` of the oldest entry from the prior page).
     */
    date_to?: string
    /**
     * When true, blank each entry's `content` and return only keys + metadata. Use to scan which memories exist without pulling their (potentially large) bodies, then re-query the ones worth a full read. Takes precedence over `content_max_chars`.
     */
    keys_only?: boolean
    /**
     * Max rows to return (default 20, hard cap 500).
     * @minimum 1
     * @maximum 500
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
