/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface CodeInviteRedeemRequestApi {
    /** @maxLength 50 */
    code: string
}

/**
 * * `burst` - burst
 * * `sustained` - sustained
 */
export type LimitTypeEnumApi = (typeof LimitTypeEnumApi)[keyof typeof LimitTypeEnumApi]

export const LimitTypeEnumApi = {
    Burst: 'burst',
    Sustained: 'sustained',
} as const

export interface TaskRunErrorResponseApi {
    /** Human-readable validation error */
    detail?: string
    /** Human-readable error message */
    error?: string
    /** Machine-readable error type */
    type?: string
    /** Machine-readable error code */
    code?: string
    /** Request field associated with the error */
    attr?: string
    /** Artifact ids that could not be resolved for the run */
    missing_artifact_ids?: string[]
    /** Which usage limit was hit on a rate_limited error: 'burst' (daily) or 'sustained' (monthly)
     *
     * * `burst` - burst
     * * `sustained` - sustained */
    limit_type?: LimitTypeEnumApi
    /** ISO 8601 timestamp when the hit usage limit resets, when known */
    reset_at?: string
    /** Whether the team is on a Pro plan (drives the upgrade-prompt copy) */
    is_pro?: boolean
}

/**
 * @nullable
 */
export type TaskUserBasicInfoApiHedgehogConfig = { [key: string]: unknown } | null

/**
 * Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.
 */
export interface TaskUserBasicInfoApi {
    id: number
    uuid: string
    distinct_id: string
    first_name: string
    last_name: string
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    hedgehog_config?: TaskUserBasicInfoApiHedgehogConfig
    /** @nullable */
    role_at_organization?: string | null
}

/**
 * List response for sandbox environments (subset of fields).
 */
export interface SandboxEnvironmentDTOApi {
    id: string
    name: string
    network_access_level: string
    allowed_domains?: string[]
    repositories?: string[]
    private: boolean
    internal: boolean
    created_by?: TaskUserBasicInfoApi | null
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
}

export interface PaginatedSandboxEnvironmentDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SandboxEnvironmentDTOApi[]
}

/**
 * * `trusted` - Trusted
 * * `full` - Full
 * * `custom` - Custom
 */
export type NetworkAccessLevelEnumApi = (typeof NetworkAccessLevelEnumApi)[keyof typeof NetworkAccessLevelEnumApi]

export const NetworkAccessLevelEnumApi = {
    Trusted: 'trusted',
    Full: 'full',
    Custom: 'custom',
} as const

/**
 * Request body for creating or updating a sandbox environment.
 */
export interface SandboxEnvironmentWriteApi {
    /**
     * Display name for the environment.
     * @maxLength 255
     */
    name: string
    /** Network access policy: trusted (default allowlist), full (unrestricted), or custom.
     *
     * * `trusted` - Trusted
     * * `full` - Full
     * * `custom` - Custom */
    network_access_level?: NetworkAccessLevelEnumApi
    /**
     * Allowed domains for custom network access.
     * @items.maxLength 255
     */
    allowed_domains?: string[]
    /** Whether to include default trusted domains (GitHub, npm, PyPI). */
    include_default_domains?: boolean
    /**
     * Repositories this environment applies to (format: org/repo).
     * @items.maxLength 255
     */
    repositories?: string[]
    /** Encrypted environment variables (write-only, never returned in responses). */
    environment_variables?: unknown
    /** If true, only the creator can see this environment; otherwise the whole team can. */
    private?: boolean
}

/**
 * Request body for creating or updating a sandbox environment.
 */
export interface PatchedSandboxEnvironmentWriteApi {
    /**
     * Display name for the environment.
     * @maxLength 255
     */
    name?: string
    /** Network access policy: trusted (default allowlist), full (unrestricted), or custom.
     *
     * * `trusted` - Trusted
     * * `full` - Full
     * * `custom` - Custom */
    network_access_level?: NetworkAccessLevelEnumApi
    /**
     * Allowed domains for custom network access.
     * @items.maxLength 255
     */
    allowed_domains?: string[]
    /** Whether to include default trusted domains (GitHub, npm, PyPI). */
    include_default_domains?: boolean
    /**
     * Repositories this environment applies to (format: org/repo).
     * @items.maxLength 255
     */
    repositories?: string[]
    /** Encrypted environment variables (write-only, never returned in responses). */
    environment_variables?: unknown
    /** If true, only the creator can see this environment; otherwise the whole team can. */
    private?: boolean
}

/**
 * Detail/create/update/run response for a task automation.
 */
export interface TaskAutomationDTOApi {
    id: string
    name: string
    prompt: string
    /** @nullable */
    repository: string | null
    /** @nullable */
    github_integration: number | null
    cron_expression: string
    timezone: string
    /** @nullable */
    template_id: string | null
    enabled: boolean
    /** @nullable */
    last_run_at: string | null
    /** @nullable */
    last_run_status: string | null
    last_task_id: string
    /** @nullable */
    last_task_run_id: string | null
    /** @nullable */
    last_error: string | null
    created_at: string
    updated_at: string
}

export interface PaginatedTaskAutomationDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskAutomationDTOApi[]
}

/**
 * Request body for creating or updating a task automation.
 */
export interface TaskAutomationWriteApi {
    /**
     * Display name (stored as the backing task's title).
     * @maxLength 255
     */
    name: string
    /** The automation prompt (stored as the backing task's description). */
    prompt: string
    /**
     * Target repository in the format organization/repository.
     * @maxLength 255
     */
    repository: string
    /**
     * GitHub integration to run as. Defaults to the team's GitHub integration when omitted.
     * @nullable
     */
    github_integration?: number | null
    /**
     * Standard 5-field cron expression (minute hour day month weekday).
     * @maxLength 100
     */
    cron_expression: string
    /**
     * IANA timezone the schedule runs in.
     * @maxLength 128
     */
    timezone?: string
    /**
     * Optional template identifier this automation was created from.
     * @maxLength 255
     * @nullable
     */
    template_id?: string | null
    /** Whether the schedule is active; paused when false. */
    enabled?: boolean
}

/**
 * Request body for creating or updating a task automation.
 */
export interface PatchedTaskAutomationWriteApi {
    /**
     * Display name (stored as the backing task's title).
     * @maxLength 255
     */
    name?: string
    /** The automation prompt (stored as the backing task's description). */
    prompt?: string
    /**
     * Target repository in the format organization/repository.
     * @maxLength 255
     */
    repository?: string
    /**
     * GitHub integration to run as. Defaults to the team's GitHub integration when omitted.
     * @nullable
     */
    github_integration?: number | null
    /**
     * Standard 5-field cron expression (minute hour day month weekday).
     * @maxLength 100
     */
    cron_expression?: string
    /**
     * IANA timezone the schedule runs in.
     * @maxLength 128
     */
    timezone?: string
    /**
     * Optional template identifier this automation was created from.
     * @maxLength 255
     * @nullable
     */
    template_id?: string | null
    /** Whether the schedule is active; paused when false. */
    enabled?: boolean
}

/**
 * @nullable
 */
export type TaskDetailDTOApiJsonSchema = { [key: string]: unknown } | null

/**
 * Conversation envelope variant: ``latest_run`` is just the latest run's id, not the nested
 * run detail. The frontend only needs the id to reconnect to sandbox logs, and emitting the id
 * avoids presigning a log URL per conversation.
 *
 * Read access here follows the conversation (the share-by-link unit), not per-creator task
 * visibility — write/send stays creator-gated. See ``tasks_facade.get_conversation_task_dtos``.
 */
export interface TaskDetailDTOApi {
    id: string
    /** @nullable */
    task_number: number | null
    slug: string
    title: string
    title_manually_set: boolean
    description: string
    origin_product: string
    /** @nullable */
    repository: string | null
    /** @nullable */
    github_integration: number | null
    /** @nullable */
    github_user_integration: string | null
    /** @nullable */
    signal_report: string | null
    /** @nullable */
    json_schema: TaskDetailDTOApiJsonSchema
    internal: boolean
    archived: boolean
    /** @nullable */
    archived_at: string | null
    /**
     * Id of the latest TaskRun; null when the task has no runs.
     * @nullable
     */
    readonly latest_run: string | null
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
    created_by?: TaskUserBasicInfoApi | null
    /** @nullable */
    ci_prompt: string | null
}

export interface PaginatedTaskDetailDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskDetailDTOApi[]
}

/**
 * * `onboarding` - Onboarding
 * * `error_tracking` - Error Tracking
 * * `eval_clusters` - Eval Clusters
 * * `user_created` - User Created
 * * `automation` - Automation
 * * `slack` - Slack
 * * `support_queue` - Support Queue
 * * `session_summaries` - Session Summaries
 * * `posthog_ai` - PostHog AI
 * * `signal_report` - Signal Report
 * * `signals_scout` - Signals Scout
 * * `support_reply` - Support Reply
 * * `hogdesk` - HogDesk
 */
export type OriginProductEnumApi = (typeof OriginProductEnumApi)[keyof typeof OriginProductEnumApi]

export const OriginProductEnumApi = {
    Onboarding: 'onboarding',
    ErrorTracking: 'error_tracking',
    EvalClusters: 'eval_clusters',
    UserCreated: 'user_created',
    Automation: 'automation',
    Slack: 'slack',
    SupportQueue: 'support_queue',
    SessionSummaries: 'session_summaries',
    PosthogAi: 'posthog_ai',
    SignalReport: 'signal_report',
    SignalsScout: 'signals_scout',
    SupportReply: 'support_reply',
    Hogdesk: 'hogdesk',
} as const

/**
 * * `implementation` - Implementation
 */
export type SignalReportTaskRelationshipEnumApi =
    (typeof SignalReportTaskRelationshipEnumApi)[keyof typeof SignalReportTaskRelationshipEnumApi]

export const SignalReportTaskRelationshipEnumApi = {
    Implementation: 'implementation',
} as const

/**
 * * `claude` - claude
 * * `codex` - codex
 */
export type RuntimeAdapterEnumApi = (typeof RuntimeAdapterEnumApi)[keyof typeof RuntimeAdapterEnumApi]

export const RuntimeAdapterEnumApi = {
    Claude: 'claude',
    Codex: 'codex',
} as const

/**
 * * `low` - low
 * * `medium` - medium
 * * `high` - high
 * * `xhigh` - xhigh
 * * `max` - max
 */
export type ReasoningEffortEnumApi = (typeof ReasoningEffortEnumApi)[keyof typeof ReasoningEffortEnumApi]

export const ReasoningEffortEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Xhigh: 'xhigh',
    Max: 'max',
} as const

/**
 * Request body for creating or updating a task.
 *
 * Field required/default semantics match the ``Task`` model. The view passes
 * ``validated_data`` (integration/report PK fields already resolved to instances) to the
 * facade ``create_task`` / ``update_task`` functions.
 */
export interface TaskWriteApi {
    /**
     * Short human-readable title. Auto-generated from `description` when omitted.
     * @maxLength 255
     */
    title?: string
    /** Whether the title was set by a human (vs auto-generated from the description). */
    title_manually_set?: boolean
    /** Free-form description of the work to be done. Used as the prompt passed to the agent. */
    description?: string
    /** PostHog product or surface that created this task (e.g. error_tracking, slack, user_created).
     *
     * * `onboarding` - Onboarding
     * * `error_tracking` - Error Tracking
     * * `eval_clusters` - Eval Clusters
     * * `user_created` - User Created
     * * `automation` - Automation
     * * `slack` - Slack
     * * `support_queue` - Support Queue
     * * `session_summaries` - Session Summaries
     * * `posthog_ai` - PostHog AI
     * * `signal_report` - Signal Report
     * * `signals_scout` - Signals Scout
     * * `support_reply` - Support Reply
     * * `hogdesk` - HogDesk */
    origin_product?: OriginProductEnumApi
    /**
     * Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub integration for this task.
     * @nullable
     */
    github_integration?: number | null
    /**
     * User-scoped GitHub integration to use for user-authored cloud runs.
     * @nullable
     */
    github_user_integration?: string | null
    /**
     * Signal report this task implements, when created from a report.
     * @nullable
     */
    signal_report?: string | null
    signal_report_task_relationship?: SignalReportTaskRelationshipEnumApi
    /** JSON schema used to validate the output of the task. */
    json_schema?: unknown
    /** If true, this task is for internal use and should not be exposed to end users. */
    internal?: boolean
    /** If true, the task is hidden from default list responses. */
    archived?: boolean
    /**
     * Custom prompt for CI fixes. If blank, a default prompt will be used.
     * @nullable
     */
    ci_prompt?: string | null
    /**
     * Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /**
     * Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.
     * @nullable
     */
    model?: string | null
    /** Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max */
    reasoning_effort?: ReasoningEffortEnumApi | null
}

/**
 * Request body for creating or updating a task.
 *
 * Field required/default semantics match the ``Task`` model. The view passes
 * ``validated_data`` (integration/report PK fields already resolved to instances) to the
 * facade ``create_task`` / ``update_task`` functions.
 */
export interface PatchedTaskWriteApi {
    /**
     * Short human-readable title. Auto-generated from `description` when omitted.
     * @maxLength 255
     */
    title?: string
    /** Whether the title was set by a human (vs auto-generated from the description). */
    title_manually_set?: boolean
    /** Free-form description of the work to be done. Used as the prompt passed to the agent. */
    description?: string
    /** PostHog product or surface that created this task (e.g. error_tracking, slack, user_created).
     *
     * * `onboarding` - Onboarding
     * * `error_tracking` - Error Tracking
     * * `eval_clusters` - Eval Clusters
     * * `user_created` - User Created
     * * `automation` - Automation
     * * `slack` - Slack
     * * `support_queue` - Support Queue
     * * `session_summaries` - Session Summaries
     * * `posthog_ai` - PostHog AI
     * * `signal_report` - Signal Report
     * * `signals_scout` - Signals Scout
     * * `support_reply` - Support Reply
     * * `hogdesk` - HogDesk */
    origin_product?: OriginProductEnumApi
    /**
     * Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub integration for this task.
     * @nullable
     */
    github_integration?: number | null
    /**
     * User-scoped GitHub integration to use for user-authored cloud runs.
     * @nullable
     */
    github_user_integration?: string | null
    /**
     * Signal report this task implements, when created from a report.
     * @nullable
     */
    signal_report?: string | null
    signal_report_task_relationship?: SignalReportTaskRelationshipEnumApi
    /** JSON schema used to validate the output of the task. */
    json_schema?: unknown
    /** If true, this task is for internal use and should not be exposed to end users. */
    internal?: boolean
    /** If true, the task is hidden from default list responses. */
    archived?: boolean
    /**
     * Custom prompt for CI fixes. If blank, a default prompt will be used.
     * @nullable
     */
    ci_prompt?: string | null
    /**
     * Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /**
     * Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.
     * @nullable
     */
    model?: string | null
    /** Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max */
    reasoning_effort?: ReasoningEffortEnumApi | null
}

/**
 * Request body for the presence beacon and beacon-leave endpoints.
 *
 * `device_id` is the UUID of the caller's `UserPushToken` row, which the
 * client received when it registered for push via `/api/users/@me/push_tokens/`.
 * The client is expected to use the same identifier on the beacon and leave
 * calls; if the user has unregistered the underlying push token, the value
 * won't resolve and the call returns 404 — at which point pushes were
 * already not going there anyway.
 */
export interface TaskPresenceBeaconRequestApi {
    /** UUID of the caller's UserPushToken (returned by `/api/users/@me/push_tokens/` on register). */
    device_id: string
}

/**
 * * `interactive` - interactive
 * * `background` - background
 */
export type TaskExecutionModeEnumApi = (typeof TaskExecutionModeEnumApi)[keyof typeof TaskExecutionModeEnumApi]

export const TaskExecutionModeEnumApi = {
    Interactive: 'interactive',
    Background: 'background',
} as const

/**
 * * `user` - user
 * * `bot` - bot
 */
export type PrAuthorshipModeEnumApi = (typeof PrAuthorshipModeEnumApi)[keyof typeof PrAuthorshipModeEnumApi]

export const PrAuthorshipModeEnumApi = {
    User: 'user',
    Bot: 'bot',
} as const

/**
 * * `manual` - manual
 * * `signal_report` - signal_report
 */
export type RunSourceEnumApi = (typeof RunSourceEnumApi)[keyof typeof RunSourceEnumApi]

export const RunSourceEnumApi = {
    Manual: 'manual',
    SignalReport: 'signal_report',
} as const

/**
 * * `claude` - claude
 */
export type ClaudeRuntimeAdapterEnumApi = (typeof ClaudeRuntimeAdapterEnumApi)[keyof typeof ClaudeRuntimeAdapterEnumApi]

export const ClaudeRuntimeAdapterEnumApi = {
    Claude: 'claude',
} as const

/**
 * * `default` - default
 * * `acceptEdits` - acceptEdits
 * * `plan` - plan
 * * `bypassPermissions` - bypassPermissions
 * * `auto` - auto
 */
export type InitialPermissionModeEnumApi =
    (typeof InitialPermissionModeEnumApi)[keyof typeof InitialPermissionModeEnumApi]

export const InitialPermissionModeEnumApi = {
    Default: 'default',
    AcceptEdits: 'acceptEdits',
    Plan: 'plan',
    BypassPermissions: 'bypassPermissions',
    Auto: 'auto',
} as const

/**
 * Request body for creating a new task run
 */
export interface ClaudeTaskRunCreateSchemaApi {
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** ID of a previous run to resume from. Must belong to the same task. */
    resume_from_run_id?: string
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /**
     * Identifiers for staged task artifacts that should be attached to the initial run prompt.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Agent runtime adapter to launch for this run. Must be 'claude' for Claude runtimes.
     *
     * * `claude` - claude */
    runtime_adapter: ClaudeRuntimeAdapterEnumApi
    /** LLM model identifier to run in the Claude runtime. */
    model: string
    /** Reasoning effort to request for models that expose an effort control.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max */
    reasoning_effort?: ReasoningEffortEnumApi
    /** Optional GitHub user token from PostHog Code for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens. */
    github_user_token?: string
    /** Initial permission mode for Claude runtimes.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto */
    initial_permission_mode?: InitialPermissionModeEnumApi
}

/**
 * * `codex` - codex
 */
export type CodexRuntimeAdapterEnumApi = (typeof CodexRuntimeAdapterEnumApi)[keyof typeof CodexRuntimeAdapterEnumApi]

export const CodexRuntimeAdapterEnumApi = {
    Codex: 'codex',
} as const

/**
 * * `auto` - auto
 * * `read-only` - read-only
 * * `full-access` - full-access
 */
export type CodexTaskRunCreateSchemaInitialPermissionModeEnumApi =
    (typeof CodexTaskRunCreateSchemaInitialPermissionModeEnumApi)[keyof typeof CodexTaskRunCreateSchemaInitialPermissionModeEnumApi]

export const CodexTaskRunCreateSchemaInitialPermissionModeEnumApi = {
    Auto: 'auto',
    ReadOnly: 'read-only',
    FullAccess: 'full-access',
} as const

/**
 * Request body for creating a new task run
 */
export interface CodexTaskRunCreateSchemaApi {
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** ID of a previous run to resume from. Must belong to the same task. */
    resume_from_run_id?: string
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /**
     * Identifiers for staged task artifacts that should be attached to the initial run prompt.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Agent runtime adapter to launch for this run. Must be 'codex' for Codex runtimes.
     *
     * * `codex` - codex */
    runtime_adapter: CodexRuntimeAdapterEnumApi
    /** LLM model identifier to run in the Codex runtime. */
    model: string
    /** Reasoning effort to request for models that expose an effort control.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max */
    reasoning_effort?: ReasoningEffortEnumApi
    /** Optional GitHub user token from PostHog Code for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens. */
    github_user_token?: string
    /** Initial permission mode for Codex runtimes.
     *
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi
}

export interface TaskRunResumeRequestSchemaApi {
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** ID of a previous run to resume from. Must belong to the same task. */
    resume_from_run_id?: string
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Optional GitHub user token from PostHog Code for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens. */
    github_user_token?: string
}

export type TaskRunCreateRequestSchemaApi =
    | ClaudeTaskRunCreateSchemaApi
    | CodexTaskRunCreateSchemaApi
    | TaskRunResumeRequestSchemaApi

/**
 * * `plan` - plan
 * * `context` - context
 * * `reference` - reference
 * * `output` - output
 * * `artifact` - artifact
 * * `tree_snapshot` - tree_snapshot
 * * `user_attachment` - user_attachment
 * * `skill_bundle` - skill_bundle
 */
export type TaskRunArtifactTypeEnumApi = (typeof TaskRunArtifactTypeEnumApi)[keyof typeof TaskRunArtifactTypeEnumApi]

export const TaskRunArtifactTypeEnumApi = {
    Plan: 'plan',
    Context: 'context',
    Reference: 'reference',
    Output: 'output',
    Artifact: 'artifact',
    TreeSnapshot: 'tree_snapshot',
    UserAttachment: 'user_attachment',
    SkillBundle: 'skill_bundle',
} as const

/**
 * * `user` - user
 * * `repo` - repo
 * * `marketplace` - marketplace
 * * `codex` - codex
 */
export type SkillSourceEnumApi = (typeof SkillSourceEnumApi)[keyof typeof SkillSourceEnumApi]

export const SkillSourceEnumApi = {
    User: 'user',
    Repo: 'repo',
    Marketplace: 'marketplace',
    Codex: 'codex',
} as const

/**
 * * `zip` - zip
 */
export type BundleFormatEnumApi = (typeof BundleFormatEnumApi)[keyof typeof BundleFormatEnumApi]

export const BundleFormatEnumApi = {
    Zip: 'zip',
} as const

export interface TaskRunArtifactMetadataApi {
    /**
     * Name of the local skill included in a skill_bundle artifact.
     * @maxLength 255
     */
    skill_name: string
    /** Local source for the uploaded skill bundle, such as user or repo.
     *
     * * `user` - user
     * * `repo` - repo
     * * `marketplace` - marketplace
     * * `codex` - codex */
    skill_source: SkillSourceEnumApi
    /**
     * SHA-256 hex digest of the uploaded skill bundle bytes.
     * @pattern ^[a-f0-9]{64}$
     */
    content_sha256: string
    /** Archive format used for the local skill bundle.
     *
     * * `zip` - zip */
    bundle_format: BundleFormatEnumApi
    /**
     * Version of the local skill bundle metadata schema.
     * @minimum 1
     */
    schema_version: number
}

export interface TaskStagedArtifactFinalizeUploadApi {
    /** Stable identifier returned by the staged prepare upload endpoint */
    id: string
    /**
     * File name associated with the staged artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * S3 object key returned by the prepare step
     * @maxLength 500
     */
    storage_path: string
    /**
     * Optional MIME type recorded for the artifact
     * @maxLength 255
     */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
}

export interface TaskStagedArtifactsFinalizeUploadRequestApi {
    /** Array of staged artifacts to finalize after upload */
    artifacts: TaskStagedArtifactFinalizeUploadApi[]
}

export interface TaskRunArtifactResponseApi {
    /** Stable identifier for the artifact within this run */
    id?: string
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Source of the artifact, such as agent_output or user_attachment */
    source?: string
    /** Artifact size in bytes */
    size?: number
    /** Optional MIME type */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
    /** S3 object key for the artifact */
    storage_path: string
    /** Timestamp when the artifact was uploaded */
    uploaded_at: string
}

export interface TaskStagedArtifactsFinalizeUploadResponseApi {
    /** Finalized staged artifacts available for attachment to a new run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskStagedArtifactPrepareUploadApi {
    /**
     * File name to associate with the staged artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * Expected upload size in bytes (max 31457280 bytes)
     * @minimum 1
     * @maximum 31457280
     */
    size: number
    /**
     * Optional MIME type for the artifact upload
     * @maxLength 255
     */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
}

export interface TaskStagedArtifactsPrepareUploadRequestApi {
    /** Array of staged artifacts to prepare before creating a run */
    artifacts: TaskStagedArtifactPrepareUploadApi[]
}

/**
 * Form fields that must be submitted verbatim with the file upload
 */
export type S3PresignedPostApiFields = { [key: string]: string }

export interface S3PresignedPostApi {
    /** Presigned S3 POST URL */
    url: string
    /** Form fields that must be submitted verbatim with the file upload */
    fields: S3PresignedPostApiFields
}

export interface TaskStagedArtifactPrepareUploadResponseApi {
    /** Stable identifier for the prepared staged artifact within this task */
    id: string
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Source of the artifact, such as agent_output or user_attachment */
    source?: string
    /** Expected upload size in bytes */
    size: number
    /** Optional MIME type */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
    /** S3 object key reserved for the staged artifact */
    storage_path: string
    /** Presigned POST expiry in seconds */
    expires_in: number
    /** Presigned S3 POST configuration for uploading the file */
    presigned_post: S3PresignedPostApi
}

export interface TaskStagedArtifactsPrepareUploadResponseApi {
    /** Prepared staged uploads for the requested artifacts */
    artifacts: TaskStagedArtifactPrepareUploadResponseApi[]
}

/**
 * * `anthropic` - anthropic
 * * `openai` - openai
 */
export type TaskRunDetailDTOProviderEnumApi =
    (typeof TaskRunDetailDTOProviderEnumApi)[keyof typeof TaskRunDetailDTOProviderEnumApi]

export const TaskRunDetailDTOProviderEnumApi = {
    Anthropic: 'anthropic',
    Openai: 'openai',
} as const

/**
 * @nullable
 */
export type TaskRunDetailDTOApiOutput = { [key: string]: unknown } | null

export type TaskRunDetailDTOApiState = { [key: string]: unknown }

/**
 * Detail response for a task run.
 *
 * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
 * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
 * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
 * ``latest_run`` shape by the task detail response.
 */
export interface TaskRunDetailDTOApi {
    id: string
    /** Parent task id this run belongs to. */
    task: string
    /** @nullable */
    stage: string | null
    /** @nullable */
    branch: string | null
    status: string
    environment: string
    /** Configured runtime adapter for this run, such as 'claude' or 'codex'.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /** Configured LLM provider for this run, such as 'anthropic' or 'openai'.
     *
     * * `anthropic` - anthropic
     * * `openai` - openai */
    provider?: TaskRunDetailDTOProviderEnumApi | null
    /**
     * Configured LLM model identifier for this run.
     * @nullable
     */
    model?: string | null
    /** Configured reasoning effort for this run when the selected model supports it.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max */
    reasoning_effort?: ReasoningEffortEnumApi | null
    /**
     * Presigned S3 URL for log access (valid for 1 hour).
     * @nullable
     */
    log_url?: string | null
    /** @nullable */
    error_message: string | null
    /** @nullable */
    output: TaskRunDetailDTOApiOutput
    state: TaskRunDetailDTOApiState
    readonly artifacts: readonly TaskRunArtifactResponseApi[]
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
    /** @nullable */
    completed_at?: string | null
}

export interface PaginatedTaskRunDetailDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskRunDetailDTOApi[]
}

/**
 * * `local` - local
 * * `cloud` - cloud
 */
export type TaskRunBootstrapCreateRequestEnvironmentEnumApi =
    (typeof TaskRunBootstrapCreateRequestEnvironmentEnumApi)[keyof typeof TaskRunBootstrapCreateRequestEnvironmentEnumApi]

export const TaskRunBootstrapCreateRequestEnvironmentEnumApi = {
    Local: 'local',
    Cloud: 'cloud',
} as const

/**
 * * `default` - default
 * * `acceptEdits` - acceptEdits
 * * `plan` - plan
 * * `bypassPermissions` - bypassPermissions
 * * `auto` - auto
 * * `read-only` - read-only
 * * `full-access` - full-access
 */
export type TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi =
    (typeof TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi)[keyof typeof TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi]

export const TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi = {
    Default: 'default',
    AcceptEdits: 'acceptEdits',
    Plan: 'plan',
    BypassPermissions: 'bypassPermissions',
    Auto: 'auto',
    ReadOnly: 'read-only',
    FullAccess: 'full-access',
} as const

/**
 * Request body for creating a task run without starting execution yet.
 */
export interface TaskRunBootstrapCreateRequestApi {
    /** Execution environment for the new run. Use 'cloud' for remote sandbox runs and 'local' for desktop sessions.
     *
     * * `local` - local
     * * `cloud` - cloud */
    environment?: TaskRunBootstrapCreateRequestEnvironmentEnumApi
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Agent runtime adapter to launch for this run. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi
    /** LLM model identifier to run in the selected runtime. */
    model?: string
    /** Reasoning effort to request for models that expose an effort control.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max */
    reasoning_effort?: ReasoningEffortEnumApi
    /** Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests. */
    github_user_token?: string
    /** Initial permission mode for the agent session. Claude runtimes accept PostHog permission presets like 'plan'. Codex runtimes accept native Codex modes like 'auto' and 'read-only'.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi
    /**
     * Label of the Home-tab quick action that started this run (e.g. 'Fix CI'), surfaced on the workstream.
     * @maxLength 120
     */
    home_quick_action?: string
}

/**
 * * `not_started` - not_started
 * * `queued` - queued
 * * `in_progress` - in_progress
 * * `completed` - completed
 * * `failed` - failed
 * * `cancelled` - cancelled
 */
export type TaskRunUpdateStatusEnumApi = (typeof TaskRunUpdateStatusEnumApi)[keyof typeof TaskRunUpdateStatusEnumApi]

export const TaskRunUpdateStatusEnumApi = {
    NotStarted: 'not_started',
    Queued: 'queued',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

/**
 * * `local` - local
 */
export type TaskRunUpdateEnvironmentEnumApi =
    (typeof TaskRunUpdateEnvironmentEnumApi)[keyof typeof TaskRunUpdateEnvironmentEnumApi]

export const TaskRunUpdateEnvironmentEnumApi = {
    Local: 'local',
} as const

export interface PatchedTaskRunUpdateApi {
    /** Current execution status
     *
     * * `not_started` - not_started
     * * `queued` - queued
     * * `in_progress` - in_progress
     * * `completed` - completed
     * * `failed` - failed
     * * `cancelled` - cancelled */
    status?: TaskRunUpdateStatusEnumApi
    /**
     * Git branch name to associate with the task
     * @nullable
     */
    branch?: string | null
    /**
     * Current stage of the run (e.g. research, plan, build)
     * @nullable
     */
    stage?: string | null
    /** Output from the run */
    output?: unknown
    /** State of the run */
    state?: unknown
    /** State keys to remove atomically before applying any state updates. */
    state_remove_keys?: string[]
    /**
     * Error message if execution failed
     * @nullable
     */
    error_message?: string | null
    /** Transition a cloud run to local. Use the resume_in_cloud action to move a run into cloud.
     *
     * * `local` - local */
    environment?: TaskRunUpdateEnvironmentEnumApi
}

export type TaskRunAppendLogRequestApiEntriesItem = { [key: string]: unknown }

export interface TaskRunAppendLogRequestApi {
    /** Array of log entry dictionaries to append */
    entries: TaskRunAppendLogRequestApiEntriesItem[]
}

/**
 * * `utf-8` - utf-8
 * * `base64` - base64
 */
export type ContentEncodingEnumApi = (typeof ContentEncodingEnumApi)[keyof typeof ContentEncodingEnumApi]

export const ContentEncodingEnumApi = {
    Utf8: 'utf-8',
    Base64: 'base64',
} as const

export interface TaskRunArtifactUploadApi {
    /**
     * File name to associate with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /** Artifact contents encoded according to content_encoding */
    content: string
    /** Encoding used for content. Use base64 for binary files and utf-8 for text payloads.
     *
     * * `utf-8` - utf-8
     * * `base64` - base64 */
    content_encoding?: ContentEncodingEnumApi
    /**
     * Optional MIME type for the artifact
     * @maxLength 255
     */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
}

export interface TaskRunArtifactsUploadRequestApi {
    /** Array of artifacts to upload */
    artifacts: TaskRunArtifactUploadApi[]
}

export interface TaskRunArtifactsUploadResponseApi {
    /** Updated list of artifacts on the run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskRunArtifactPresignRequestApi {
    /**
     * S3 storage path returned in the artifact manifest
     * @maxLength 500
     */
    storage_path: string
}

export interface TaskRunArtifactFinalizeUploadApi {
    /** Stable identifier returned by the prepare upload endpoint */
    id: string
    /**
     * File name associated with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * S3 object key returned by the prepare step
     * @maxLength 500
     */
    storage_path: string
    /**
     * Optional MIME type recorded for the artifact
     * @maxLength 255
     */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
}

export interface TaskRunArtifactsFinalizeUploadRequestApi {
    /** Array of uploaded artifacts to finalize */
    artifacts: TaskRunArtifactFinalizeUploadApi[]
}

export interface TaskRunArtifactsFinalizeUploadResponseApi {
    /** Updated list of artifacts on the run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskRunArtifactPrepareUploadApi {
    /**
     * File name to associate with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * Expected upload size in bytes (max 31457280 bytes)
     * @minimum 1
     * @maximum 31457280
     */
    size: number
    /**
     * Optional MIME type for the artifact upload
     * @maxLength 255
     */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
}

export interface TaskRunArtifactsPrepareUploadRequestApi {
    /** Array of artifacts to prepare */
    artifacts: TaskRunArtifactPrepareUploadApi[]
}

export interface TaskRunArtifactPrepareUploadResponseApi {
    /** Stable identifier for the prepared artifact within this run */
    id: string
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Source of the artifact, such as agent_output or user_attachment */
    source?: string
    /** Expected upload size in bytes */
    size: number
    /** Optional MIME type */
    content_type?: string
    /** Optional structured metadata for special artifact types, such as skill bundles. */
    metadata?: TaskRunArtifactMetadataApi
    /** S3 object key reserved for the artifact */
    storage_path: string
    /** Presigned POST expiry in seconds */
    expires_in: number
    /** Presigned S3 POST configuration for uploading the file */
    presigned_post: S3PresignedPostApi
}

export interface TaskRunArtifactsPrepareUploadResponseApi {
    /** Prepared uploads for the requested artifacts */
    artifacts: TaskRunArtifactPrepareUploadResponseApi[]
}

export interface TaskRunArtifactPresignResponseApi {
    /** Presigned URL for downloading the artifact */
    url: string
    /** URL expiry in seconds */
    expires_in: number
}

/**
 * Parameters for the command
 */
export type TaskRunCommandRequestApiParams = { [key: string]: unknown }

/**
 * * `2.0` - 2.0
 */
export type JsonrpcEnumApi = (typeof JsonrpcEnumApi)[keyof typeof JsonrpcEnumApi]

export const JsonrpcEnumApi = {
    '20': '2.0',
} as const

/**
 * * `user_message` - user_message
 * * `cancel` - cancel
 * * `close` - close
 * * `permission_response` - permission_response
 * * `set_config_option` - set_config_option
 */
export type MethodEnumApi = (typeof MethodEnumApi)[keyof typeof MethodEnumApi]

export const MethodEnumApi = {
    UserMessage: 'user_message',
    Cancel: 'cancel',
    Close: 'close',
    PermissionResponse: 'permission_response',
    SetConfigOption: 'set_config_option',
} as const

/**
 * JSON-RPC request to send a command to the agent server in the sandbox.
 */
export interface TaskRunCommandRequestApi {
    /** JSON-RPC version, must be '2.0'
     *
     * * `2.0` - 2.0 */
    jsonrpc: JsonrpcEnumApi
    /** Command method to execute on the agent server
     *
     * * `user_message` - user_message
     * * `cancel` - cancel
     * * `close` - close
     * * `permission_response` - permission_response
     * * `set_config_option` - set_config_option */
    method: MethodEnumApi
    /** Parameters for the command */
    params?: TaskRunCommandRequestApiParams
    /** Optional JSON-RPC request ID (string or number) */
    id?: unknown
}

/**
 * Command result on success
 */
export type TaskRunCommandResponseApiResult = { [key: string]: unknown }

/**
 * Error details on failure
 */
export type TaskRunCommandResponseApiError = { [key: string]: unknown }

/**
 * Response from the agent server command endpoint.
 */
export interface TaskRunCommandResponseApi {
    /** JSON-RPC version */
    jsonrpc: string
    /** Request ID echoed back (string or number) */
    id?: unknown
    /** Command result on success */
    result?: TaskRunCommandResponseApiResult
    /** Error details on failure */
    error?: TaskRunCommandResponseApiError
}

/**
 * Response containing a JWT token for direct sandbox connection
 */
export interface ConnectionTokenResponseApi {
    /** JWT token for authenticating with the sandbox */
    token: string
}

export interface TaskRunRelayMessageRequestApi {
    /**
     * Joined message body. Used when text_parts is absent.
     * @maxLength 10000
     */
    text: string
    /**
     * Ordered assistant text blocks. When present, the last non-empty entry is posted instead of text.
     * @items.maxLength 10000
     */
    text_parts?: string[]
}

export interface TaskRunRelayMessageResponseApi {
    /** Relay status: 'accepted' or 'skipped' */
    status: string
    /** Relay workflow ID when accepted */
    relay_id?: string
}

export interface PatchedTaskRunSetOutputRequestApi {
    /** Output data from the run. Validated against the task's json_schema if one is set. */
    output?: unknown
}

export interface TaskRunStartRequestApi {
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /**
     * Identifiers for run artifacts that should be attached to the next user message delivered to the sandbox.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
}

/**
 * Response containing a JWT token (and resolved base URL) for reading a task run's live event stream
 */
export interface StreamReadTokenResponseApi {
    /** Run-scoped JWT the browser presents to the agent-proxy to read this run's live event stream */
    token: string
    /**
     * Base URL of the agent-proxy to read the stream from when routing via the proxy is enabled for this user. Null means read from the Django endpoint directly (same-origin). The client appends the run's stream path and sends the token as a Bearer header when this is set.
     * @nullable
     */
    stream_base_url: string | null
}

/**
 * * `slack_message` - slack_message
 * * `slack_canvas` - slack_canvas
 * * `document` - document
 * * `spreadsheet` - spreadsheet
 * * `dashboard` - dashboard
 * * `file` - file
 * * `github_pr` - github_pr
 */
export type ArtifactTypeEnumApi = (typeof ArtifactTypeEnumApi)[keyof typeof ArtifactTypeEnumApi]

export const ArtifactTypeEnumApi = {
    SlackMessage: 'slack_message',
    SlackCanvas: 'slack_canvas',
    Document: 'document',
    Spreadsheet: 'spreadsheet',
    Dashboard: 'dashboard',
    File: 'file',
    GithubPr: 'github_pr',
} as const

/**
 * * `slack_message` - slack_message
 * * `slack_canvas` - slack_canvas
 * * `slack_file` - slack_file
 * * `document_connector` - document_connector
 * * `github_pr` - github_pr
 */
export type AdapterEnumApi = (typeof AdapterEnumApi)[keyof typeof AdapterEnumApi]

export const AdapterEnumApi = {
    SlackMessage: 'slack_message',
    SlackCanvas: 'slack_canvas',
    SlackFile: 'slack_file',
    DocumentConnector: 'document_connector',
    GithubPr: 'github_pr',
} as const

/**
 * * `active` - active
 * * `failed` - failed
 */
export type TaskArtifactStatusEnumApi = (typeof TaskArtifactStatusEnumApi)[keyof typeof TaskArtifactStatusEnumApi]

export const TaskArtifactStatusEnumApi = {
    Active: 'active',
    Failed: 'failed',
} as const

export type TaskRunLivingArtifactResponseApiVersionsItem = { [key: string]: unknown }

export interface TaskRunLivingArtifactResponseApi {
    /** Stable living artifact id. Use this id when editing the artifact. */
    id: string
    /** Task id this living artifact belongs to. */
    task_id: string
    /** Task run id that created or currently owns this artifact. */
    run_id: string
    /** Project id that owns this artifact. */
    team_id: number
    /** Human-readable artifact name. */
    name: string
    /** Artifact format or delivery surface, such as document, spreadsheet, slack_canvas, file, or slack_message.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `document` - document
     * * `spreadsheet` - spreadsheet
     * * `dashboard` - dashboard
     * * `file` - file
     * * `github_pr` - github_pr */
    artifact_type: ArtifactTypeEnumApi
    /** Adapter that currently stores or edits the artifact.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `slack_file` - slack_file
     * * `document_connector` - document_connector
     * * `github_pr` - github_pr */
    adapter: AdapterEnumApi
    /** Current registry status for the artifact.
     *
     * * `active` - active
     * * `failed` - failed */
    status: TaskArtifactStatusEnumApi
    /** Adapter-specific location, such as S3 key or Slack canvas id. */
    location: unknown
    /** Adapter-specific metadata for external storage and source tracking. */
    metadata: unknown
    /** Current version number for the artifact. */
    current_version: number
    /** Chronological version records for this artifact. */
    versions: TaskRunLivingArtifactResponseApiVersionsItem[]
    /**
     * ISO timestamp when created.
     * @nullable
     */
    created_at?: string | null
    /**
     * ISO timestamp when last updated.
     * @nullable
     */
    updated_at?: string | null
}

export interface TaskRunLivingArtifactsResponseApi {
    /** Living artifacts for this task run. */
    artifacts: TaskRunLivingArtifactResponseApi[]
}

/**
 * Optional metadata to persist with the living artifact.
 */
export type TaskRunLivingArtifactCreateRequestApiMetadata = { [key: string]: unknown }

export interface TaskRunLivingArtifactCreateRequestApi {
    /**
     * Human-readable artifact name, used as the title.
     * @maxLength 255
     */
    name: string
    /** Artifact format or delivery surface to create, such as document, spreadsheet, slack_canvas, or file.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `document` - document
     * * `spreadsheet` - spreadsheet
     * * `dashboard` - dashboard
     * * `file` - file
     * * `github_pr` - github_pr */
    artifact_type?: ArtifactTypeEnumApi
    /** Optional preferred external storage or delivery adapter. Slack adapters deliver into the mapped Slack thread; omitted Slack-run documents use Slack canvas, omitted Slack-run files and spreadsheets use Slack file upload, and document_connector uses a connected external document provider.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `slack_file` - slack_file
     * * `document_connector` - document_connector
     * * `github_pr` - github_pr */
    adapter?: AdapterEnumApi
    /**
     * Markdown or text content for the initial artifact version.
     * @maxLength 500000
     */
    content?: string
    /** Base64-encoded binary content for Slack file uploads or other external adapters. Prefer source_artifact_id or source_storage_path for large files that were already uploaded as run artifacts. */
    content_base64?: string
    /**
     * MIME type for content_base64 or source-backed artifacts, such as application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.
     * @maxLength 255
     */
    content_type?: string
    /** Existing run artifact id to use as the initial content source. */
    source_artifact_id?: string
    /** Existing run artifact storage_path to use as the initial content source. */
    source_storage_path?: string
    /** Optional metadata to persist with the living artifact. */
    metadata?: TaskRunLivingArtifactCreateRequestApiMetadata
}

export type TaskRunLivingArtifactOpenResponseApiVersionsItem = { [key: string]: unknown }

export interface TaskRunLivingArtifactOpenResponseApi {
    /** Stable living artifact id. Use this id when editing the artifact. */
    id: string
    /** Task id this living artifact belongs to. */
    task_id: string
    /** Task run id that created or currently owns this artifact. */
    run_id: string
    /** Project id that owns this artifact. */
    team_id: number
    /** Human-readable artifact name. */
    name: string
    /** Artifact format or delivery surface, such as document, spreadsheet, slack_canvas, file, or slack_message.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `document` - document
     * * `spreadsheet` - spreadsheet
     * * `dashboard` - dashboard
     * * `file` - file
     * * `github_pr` - github_pr */
    artifact_type: ArtifactTypeEnumApi
    /** Adapter that currently stores or edits the artifact.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `slack_file` - slack_file
     * * `document_connector` - document_connector
     * * `github_pr` - github_pr */
    adapter: AdapterEnumApi
    /** Current registry status for the artifact.
     *
     * * `active` - active
     * * `failed` - failed */
    status: TaskArtifactStatusEnumApi
    /** Adapter-specific location, such as S3 key or Slack canvas id. */
    location: unknown
    /** Adapter-specific metadata for external storage and source tracking. */
    metadata: unknown
    /** Current version number for the artifact. */
    current_version: number
    /** Chronological version records for this artifact. */
    versions: TaskRunLivingArtifactOpenResponseApiVersionsItem[]
    /**
     * ISO timestamp when created.
     * @nullable
     */
    created_at?: string | null
    /**
     * ISO timestamp when last updated.
     * @nullable
     */
    updated_at?: string | null
    /**
     * Current artifact content when the adapter can read it directly.
     * @nullable
     */
    content?: string | null
}

/**
 * Optional metadata to merge into the artifact registry record.
 */
export type TaskRunLivingArtifactEditRequestApiMetadata = { [key: string]: unknown }

export interface TaskRunLivingArtifactEditRequestApi {
    /**
     * Optional new human-readable artifact name.
     * @maxLength 255
     */
    name?: string
    /**
     * Markdown or text content for the next version.
     * @maxLength 500000
     */
    content?: string
    /** Base64-encoded binary content for the next version, used by adapters such as slack_file. */
    content_base64?: string
    /**
     * MIME type for content_base64 or source-backed edits.
     * @maxLength 255
     */
    content_type?: string
    /** Existing run artifact id to use as the next version content source. */
    source_artifact_id?: string
    /** Existing run artifact storage_path to use as the next version content source. */
    source_storage_path?: string
    /** Optional metadata to merge into the artifact registry record. */
    metadata?: TaskRunLivingArtifactEditRequestApiMetadata
}

export interface TaskRepositoriesResponseApi {
    /** Distinct repositories in use by non-deleted, non-internal tasks for the current team. */
    repositories: string[]
}

/**
 * * `needs_setup` - needs_setup
 * * `detected` - detected
 * * `waiting_for_data` - waiting_for_data
 * * `ready` - ready
 * * `not_applicable` - not_applicable
 * * `unknown` - unknown
 */
export type CapabilityStateStateEnumApi = (typeof CapabilityStateStateEnumApi)[keyof typeof CapabilityStateStateEnumApi]

export const CapabilityStateStateEnumApi = {
    NeedsSetup: 'needs_setup',
    Detected: 'detected',
    WaitingForData: 'waiting_for_data',
    Ready: 'ready',
    NotApplicable: 'not_applicable',
    Unknown: 'unknown',
} as const

/**
 * Supporting evidence
 */
export type CapabilityStateApiEvidence = { [key: string]: unknown }

export interface CapabilityStateApi {
    /** Current state of the capability
     *
     * * `needs_setup` - needs_setup
     * * `detected` - detected
     * * `waiting_for_data` - waiting_for_data
     * * `ready` - ready
     * * `not_applicable` - not_applicable
     * * `unknown` - unknown */
    state: CapabilityStateStateEnumApi
    /** Whether the state is estimated from static analysis */
    estimated: boolean
    /** Human-readable explanation */
    reason: string
    /** Supporting evidence */
    evidence?: CapabilityStateApiEvidence
}

export interface ScanEvidenceApi {
    /** Number of files scanned */
    filesScanned: number
    /** Total candidate files detected */
    detectedFilesCount: number
    /** Number of distinct event names found */
    eventNameCount: number
    /** Whether posthog.init() was found in scanned files */
    foundPosthogInit: boolean
    /** Whether posthog.capture() was found in scanned files */
    foundPosthogCapture: boolean
    /** Whether error tracking signals were found in scanned files */
    foundErrorSignal: boolean
}

export interface RepositoryReadinessResponseApi {
    /** Normalized repository identifier */
    repository: string
    /** Repository classification */
    classification: string
    /** Whether the repository is excluded from readiness checks */
    excluded: boolean
    /** Tracking capability state */
    coreSuggestions: CapabilityStateApi
    /** Computer vision capability state */
    replayInsights: CapabilityStateApi
    /** Error tracking capability state */
    errorInsights: CapabilityStateApi
    /** Overall readiness state */
    overall: string
    /** Count of replay-derived evidence tasks */
    evidenceTaskCount: number
    /** Lookback window in days */
    windowDays: number
    /** ISO timestamp when the response was generated */
    generatedAt: string
    /** Age of cached response in seconds */
    cacheAgeSeconds: number
    /** Scan evidence details */
    scan?: ScanEvidenceApi
}

/**
 * Slack-side identifiers and the mapping metadata for a thread → task lookup.
 */
export interface SlackThreadContextThreadApi {
    /** Echoed input URL. */
    url: string
    /** Slack channel id parsed from the URL (e.g. C0ACRAMJUAG). */
    channel: string
    /** Slack thread_ts (e.g. 1779956938.619299). */
    thread_ts: string
    /**
     * Slack workspace id (e.g. T…). Null when no mapping exists yet.
     * @nullable
     */
    slack_workspace_id: string | null
    /**
     * The Slack user who triggered the task. Null when no mapping exists yet.
     * @nullable
     */
    mentioning_slack_user_id: string | null
}

/**
 * The PostHog Task linked to the Slack thread.
 */
export interface SlackThreadContextTaskApi {
    /** UUID of the Task row. */
    id: string
    /** Team that owns the task. */
    team_id: number
    /** Task title (typically the first ~255 chars of the Slack ask). */
    title: string
    /**
     * Resolved repository in `org/repo` form, or null if the run started without a repo.
     * @nullable
     */
    repository: string | null
    /** `Task.OriginProduct` (`slack` for slack-originated tasks). */
    origin_product: string
    /** When the task was created (server-side timestamp). */
    created_at: string
    /** Absolute URL to the task detail page in the PostHog app. */
    url: string
}

/**
 * The internal sandbox run the discovery agent used to pick this run's repo.
 *
 * Only present when the originating mention was ambiguous (multiple candidate
 * repos, no explicit mention) — that's the only path that spins up a research
 * sandbox. Null otherwise.
 */
export interface SlackThreadContextRepoResearchApi {
    /** UUID of the internal repo-research Task. */
    task_id: string
    /** UUID of the internal repo-research TaskRun. */
    run_id: string
    /**
     * Research run status, or null if the run row could not be loaded.
     * @nullable
     */
    status: string | null
    /** Temporal workflow id for the research sandbox run (`task-processing-<task_id>-<run_id>`). */
    task_processing_workflow_id: string
    /**
     * Full Temporal Web UI URL for the research workflow; null when `TEMPORAL_UI_HOST` is unset.
     * @nullable
     */
    task_processing_workflow_url: string | null
    /**
     * Live sandbox tunnel URL for the research run, when one was attached.
     * @nullable
     */
    sandbox_url: string | null
    /** Absolute URL to the research task detail page (carries `?ph_debug=true`). */
    task_view_url: string
    /**
     * Presigned S3 URL for the research run's JSONL log transcript (valid ~1 hour).
     * @nullable
     */
    log_url: string | null
}

/**
 * One TaskRun and its associated Temporal workflow handles.
 */
export interface SlackThreadContextRunApi {
    /** UUID of the TaskRun row. */
    id: string
    /** Run status (queued/in_progress/completed/failed/…). */
    status: string
    /** When the run was created. */
    created_at: string
    /**
     * When the run reached a terminal state, or null while still running.
     * @nullable
     */
    completed_at: string | null
    /**
     * Live sandbox tunnel URL, when one was attached.
     * @nullable
     */
    sandbox_url: string | null
    /**
     * PR URL produced by the run, when one was opened.
     * @nullable
     */
    pr_url: string | null
    /**
     * Error captured on terminal failure, or null on success.
     * @nullable
     */
    error_message: string | null
    /** Temporal workflow id for the sandbox/agent run (`task-processing-<task_id>-<run_id>`). */
    task_processing_workflow_id: string
    /**
     * Full Temporal Web UI URL for the task-processing workflow; null when `TEMPORAL_UI_HOST` is unset.
     * @nullable
     */
    task_processing_workflow_url: string | null
    /**
     * Temporal workflow id of the Slack mention that dispatched this run (`posthog-code-mention-<workspace>:<event_id_or_channel:ts>`). Null for runs created before this field was persisted.
     * @nullable
     */
    mention_workflow_id: string | null
    /**
     * Full Temporal Web UI URL for the mention dispatch workflow; null when unavailable.
     * @nullable
     */
    mention_workflow_url: string | null
    /** Absolute URL to the task detail page focused on this run. */
    task_view_url: string
    /**
     * Presigned S3 URL for the run's full JSONL log transcript (valid ~1 hour).
     * @nullable
     */
    log_url: string | null
    /** The discovery-agent sandbox that picked this run's repo, when the mention was ambiguous. */
    repo_research: SlackThreadContextRepoResearchApi | null
}

/**
 * Top-level response for the slack-thread debug endpoint.
 */
export interface SlackThreadContextResponseApi {
    /** Slack-side identifiers and the mapping metadata. */
    thread: SlackThreadContextThreadApi
    /** Linked PostHog Task. Null when no mapping was found for the thread. */
    task: SlackThreadContextTaskApi | null
    /** All runs on the task, oldest first. Empty when no mapping was found. */
    runs: SlackThreadContextRunApi[]
}

export interface TaskSummariesRequestApi {
    /**
     * Task IDs to fetch summaries for (max 5000). Response is paginated; follow the `next` cursor to retrieve all results.
     * @maxItems 5000
     */
    ids: string[]
}

/**
 * * `not_started` - Not Started
 * * `queued` - Queued
 * * `in_progress` - In Progress
 * * `completed` - Completed
 * * `failed` - Failed
 * * `cancelled` - Cancelled
 */
export type TaskRunStatusEnumApi = (typeof TaskRunStatusEnumApi)[keyof typeof TaskRunStatusEnumApi]

export const TaskRunStatusEnumApi = {
    NotStarted: 'not_started',
    Queued: 'queued',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

/**
 * * `local` - Local
 * * `cloud` - Cloud
 */
export type TaskRunEnvironmentEnumApi = (typeof TaskRunEnvironmentEnumApi)[keyof typeof TaskRunEnvironmentEnumApi]

export const TaskRunEnvironmentEnumApi = {
    Local: 'local',
    Cloud: 'cloud',
} as const

export interface TaskRunSummaryApi {
    status: TaskRunStatusEnumApi | null
    environment: TaskRunEnvironmentEnumApi | null
}

/**
 * Summary response for a task — reads from a frozen ``TaskSummaryDTO``.
 */
export interface TaskSummaryDTOApi {
    id: string
    title: string
    /** @nullable */
    repository: string | null
    created_at: string
    updated_at: string
    latest_run?: TaskRunSummaryApi | null
}

export interface PaginatedTaskSummaryDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskSummaryDTOApi[]
}

/**
 * Request body for warming a full idling Run while composing a Code-app cloud task.
 *
 * Collection-level: no task exists yet at typing time. The warmer births a draft Task and an
 * interactive Run that boots, clones, checks out `branch`, and starts the agent, then idles awaiting
 * the first message. `github_integration` is a plain integration PK (an integer); the view re-scopes
 * it to the caller's team before use.
 */
export interface WarmTaskRequestApi {
    /**
     * Target GitHub repository to clone, in `organization/repo` format (e.g. `posthog/posthog`).
     * @maxLength 255
     */
    repository: string
    /** Primary key of the team's GitHub integration to clone with. */
    github_integration: number
    /**
     * Branch to check out in the warm sandbox. Defaults to the repository's default branch when omitted.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Agent runtime adapter to warm the sandbox on ('claude' or 'codex'). The warm Run starts the agent on this runtime so a matching submit reuses it; a submit selecting a different runtime falls through to a cold Run instead of reusing a mismatched warm session.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /**
     * LLM model identifier to warm the sandbox on. A submit selecting a different model won't reuse this warm Run.
     * @nullable
     */
    model?: string | null
    /** Reasoning effort to warm the sandbox on for models that expose an effort control.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max */
    reasoning_effort?: ReasoningEffortEnumApi | null
}

/**
 * Response for a successful warm request — the draft Task + idling warm Run reused on submit.
 */
export interface WarmTaskResponseApi {
    /** Id of the draft Task birthed for the warm Run. */
    task_id: string
    /** Id of the idling warm Run. The normal create+run path reuses and activates it on submit. */
    run_id: string
}

export type SandboxListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type TaskAutomationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type TasksListParams = {
    /**
     * Filter by archived state. Defaults to excluding archived tasks. Use 'true' to list only archived tasks, 'false' for the default, or 'all' to include both.
     *
     * * `true` - true
     * * `false` - false
     * * `all` - all
     * @minLength 1
     */
    archived?: TasksListArchived
    /**
     * Filter by creator user ID
     */
    created_by?: number
    /**
     * Filter by the internal flag, which controls whether a task is shown by default, not whether it is accessible. Defaults to excluding internal tasks. Use 'all' to include both internal and user-facing tasks, or 'true' to list only internal tasks. All values are available to any team member; access stays governed by task visibility.
     *
     * * `true` - true
     * * `false` - false
     * * `all` - all
     * @minLength 1
     */
    internal?: TasksListInternal
    /**
     * Number of results to return per page.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     * @minimum 0
     */
    offset?: number
    /**
     * Filter by repository organization
     * @minLength 1
     */
    organization?: string
    /**
     * Filter by origin product
     * @minLength 1
     */
    origin_product?: string
    /**
     * Filter by repository name (can include org/repo format)
     * @minLength 1
     */
    repository?: string
    /**
     * Case-insensitive substring search over task title and description. A numeric value also matches the task number. An empty value disables the filter.
     */
    search?: string
    /**
     * Filter by task run stage
     * @minLength 1
     */
    stage?: string
    /**
     * Filter tasks by the status of their most recent run.
     *
     * * `not_started` - not_started
     * * `queued` - queued
     * * `in_progress` - in_progress
     * * `completed` - completed
     * * `failed` - failed
     * * `cancelled` - cancelled
     * @minLength 1
     */
    status?: TasksListStatus
}

export type TasksListArchived = (typeof TasksListArchived)[keyof typeof TasksListArchived]

export const TasksListArchived = {
    True: 'true',
    False: 'false',
    All: 'all',
} as const

export type TasksListInternal = (typeof TasksListInternal)[keyof typeof TasksListInternal]

export const TasksListInternal = {
    True: 'true',
    False: 'false',
    All: 'all',
} as const

export type TasksListStatus = (typeof TasksListStatus)[keyof typeof TasksListStatus]

export const TasksListStatus = {
    NotStarted: 'not_started',
    Queued: 'queued',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

export type TasksRunsListParams = {
    /**
     * Number of results to return per page.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     * @minimum 0
     */
    offset?: number
}

export type TasksRunsSessionLogsRetrieveParams = {
    /**
     * Only return events after this ISO8601 timestamp
     */
    after?: string
    /**
     * Comma-separated list of event types to include
     * @minLength 1
     */
    event_types?: string
    /**
     * Comma-separated list of event types to exclude
     * @minLength 1
     */
    exclude_types?: string
    /**
     * Maximum number of entries to return (default 1000, max 5000)
     * @minimum 1
     * @maximum 5000
     */
    limit?: number
    /**
     * Zero-based offset into the filtered log entries
     * @minimum 0
     */
    offset?: number
}

export type TasksRunsStreamRetrieveParams = {
    /**
     * Set to `latest` to skip the event backlog and only receive events published after connecting.
     */
    start?: string
}

export type TasksRepositoryReadinessRetrieveParams = {
    refresh?: boolean
    /**
     * Repository in org/repo format
     * @minLength 1
     */
    repository: string
    /**
     * @minimum 1
     * @maximum 30
     */
    window_days?: number
}

export type TasksSlackThreadContextRetrieveParams = {
    /**
     * Full Slack permalink to any message in the thread (e.g. https://posthog.slack.com/archives/C…/p1779956938619299). Replies inside the thread are accepted too — the `thread_ts` query param (when present) takes precedence over the in-path message ts.
     * @minLength 1
     */
    url: string
}

export type TasksSummariesCreateParams = {
    /**
     * Page size for the paginated response.
     */
    limit?: number
    /**
     * Offset into the result set for pagination.
     */
    offset?: number
}
