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

export interface ErrorResponseApi {
    /** Error message */
    error: string
}

/**
 * * `trusted` - Trusted
 * `full` - Full
 * `custom` - Custom
 */
export type NetworkAccessLevelEnumApi = (typeof NetworkAccessLevelEnumApi)[keyof typeof NetworkAccessLevelEnumApi]

export const NetworkAccessLevelEnumApi = {
    Trusted: 'trusted',
    Full: 'full',
    Custom: 'custom',
} as const

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

export interface SandboxEnvironmentListApi {
    readonly id: string
    /** @maxLength 255 */
    name: string
    network_access_level?: NetworkAccessLevelEnumApi
    /** List of allowed domains for custom network access */
    allowed_domains?: string[]
    /** List of repositories this environment applies to (format: org/repo) */
    repositories?: string[]
    /** If true, only the creator can see this environment. Otherwise visible to whole team. */
    private?: boolean
    /** If true, this environment is for internal use (e.g. signals pipeline) and should not be exposed to end users. */
    internal?: boolean
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedSandboxEnvironmentListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SandboxEnvironmentListApi[]
}

export interface SandboxEnvironmentApi {
    readonly id: string
    /** @maxLength 255 */
    name: string
    network_access_level?: NetworkAccessLevelEnumApi
    /** List of allowed domains for custom network access */
    allowed_domains?: string[]
    /** Whether to include default trusted domains (GitHub, npm, PyPI) */
    include_default_domains?: boolean
    /** List of repositories this environment applies to (format: org/repo) */
    repositories?: string[]
    /** Encrypted environment variables (write-only, never returned in responses) */
    environment_variables?: unknown
    /** Whether this environment has any environment variables set */
    readonly has_environment_variables: boolean
    /** If true, only the creator can see this environment. Otherwise visible to whole team. */
    private?: boolean
    /** If true, this environment is for internal use (e.g. signals pipeline) and should not be exposed to end users. */
    readonly internal: boolean
    /** Computed domain allowlist based on network_access_level and allowed_domains */
    readonly effective_domains: readonly string[]
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
}

/**
 * Serializer for extracted tasks
 */
export interface TaskApi {
    title: string
    description?: string
    /** @nullable */
    assignee?: string | null
}

export interface PaginatedTaskListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskApi[]
}

/**
 * Latest run details for this task
 * @nullable
 */
export type PatchedTaskApiLatestRun = { [key: string]: unknown } | null | null

/**
 * * `error_tracking` - Error Tracking
 * `eval_clusters` - Eval Clusters
 * `user_created` - User Created
 * `slack` - Slack
 * `support_queue` - Support Queue
 * `session_summaries` - Session Summaries
 * `signal_report` - Signal Report
 */
export type OriginProductEnumApi = (typeof OriginProductEnumApi)[keyof typeof OriginProductEnumApi]

export const OriginProductEnumApi = {
    ErrorTracking: 'error_tracking',
    EvalClusters: 'eval_clusters',
    UserCreated: 'user_created',
    Slack: 'slack',
    SupportQueue: 'support_queue',
    SessionSummaries: 'session_summaries',
    SignalReport: 'signal_report',
} as const

export interface PatchedTaskApi {
    readonly id?: string
    /** @nullable */
    readonly task_number?: number | null
    readonly slug?: string
    /** @maxLength 255 */
    title?: string
    title_manually_set?: boolean
    description?: string
    origin_product?: OriginProductEnumApi
    /**
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub integration for this task
     * @nullable
     */
    github_integration?: number | null
    /** @nullable */
    signal_report?: string | null
    /** JSON schema for the task. This is used to validate the output of the task. */
    json_schema?: unknown | null
    /** If true, this task is for internal use and should not be exposed to end users. */
    internal?: boolean
    /**
     * Latest run details for this task
     * @nullable
     */
    readonly latest_run?: PatchedTaskApiLatestRun
    readonly created_at?: string
    readonly updated_at?: string
    readonly created_by?: UserBasicApi
}

/**
 * * `interactive` - interactive
 * `background` - background
 */
export type TaskRunCreateRequestModeEnumApi =
    (typeof TaskRunCreateRequestModeEnumApi)[keyof typeof TaskRunCreateRequestModeEnumApi]

export const TaskRunCreateRequestModeEnumApi = {
    Interactive: 'interactive',
    Background: 'background',
} as const

/**
 * * `user` - user
 * `bot` - bot
 */
export type PrAuthorshipModeEnumApi = (typeof PrAuthorshipModeEnumApi)[keyof typeof PrAuthorshipModeEnumApi]

export const PrAuthorshipModeEnumApi = {
    User: 'user',
    Bot: 'bot',
} as const

/**
 * * `manual` - manual
 * `signal_report` - signal_report
 */
export type RunSourceEnumApi = (typeof RunSourceEnumApi)[keyof typeof RunSourceEnumApi]

export const RunSourceEnumApi = {
    Manual: 'manual',
    SignalReport: 'signal_report',
} as const

/**
 * Request body for creating a new task run
 */
export interface TaskRunCreateRequestApi {
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs

* `interactive` - interactive
* `background` - background */
    mode?: TaskRunCreateRequestModeEnumApi
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

* `user` - user
* `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.

* `manual` - manual
* `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Ephemeral GitHub user token from PostHog Code for user-authored cloud pull requests. */
    github_user_token?: string
}

/**
 * * `not_started` - Not Started
 * `queued` - Queued
 * `in_progress` - In Progress
 * `completed` - Completed
 * `failed` - Failed
 * `cancelled` - Cancelled
 */
export type TaskRunDetailStatusEnumApi = (typeof TaskRunDetailStatusEnumApi)[keyof typeof TaskRunDetailStatusEnumApi]

export const TaskRunDetailStatusEnumApi = {
    NotStarted: 'not_started',
    Queued: 'queued',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

/**
 * * `local` - Local
 * `cloud` - Cloud
 */
export type EnvironmentEnumApi = (typeof EnvironmentEnumApi)[keyof typeof EnvironmentEnumApi]

export const EnvironmentEnumApi = {
    Local: 'local',
    Cloud: 'cloud',
} as const

export interface TaskRunArtifactResponseApi {
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Artifact size in bytes */
    size?: number
    /** Optional MIME type */
    content_type?: string
    /** S3 object key for the artifact */
    storage_path: string
    /** Timestamp when the artifact was uploaded */
    uploaded_at: string
}

export interface TaskRunDetailApi {
    readonly id: string
    readonly task: string
    /**
     * Current stage for this run (e.g., 'research', 'plan', 'build')
     * @maxLength 100
     * @nullable
     */
    stage?: string | null
    /**
     * Branch name for the run
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    status?: TaskRunDetailStatusEnumApi
    /** Execution environment

* `local` - Local
* `cloud` - Cloud */
    environment?: EnvironmentEnumApi
    /**
     * Presigned S3 URL for log access (valid for 1 hour).
     * @nullable
     */
    readonly log_url: string | null
    /**
     * Error message if execution failed
     * @nullable
     */
    error_message?: string | null
    /** Run output data (e.g., PR URL, commit SHA, etc.) */
    output?: unknown | null
    /** Run state data for resuming or tracking execution state */
    state?: unknown
    readonly artifacts: readonly TaskRunArtifactResponseApi[]
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly completed_at: string | null
}

export interface PaginatedTaskRunDetailListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskRunDetailApi[]
}

/**
 * * `not_started` - not_started
 * `queued` - queued
 * `in_progress` - in_progress
 * `completed` - completed
 * `failed` - failed
 * `cancelled` - cancelled
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

export interface PatchedTaskRunUpdateApi {
    /** Current execution status

* `not_started` - not_started
* `queued` - queued
* `in_progress` - in_progress
* `completed` - completed
* `failed` - failed
* `cancelled` - cancelled */
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
    output?: unknown | null
    /** State of the run */
    state?: unknown
    /**
     * Error message if execution failed
     * @nullable
     */
    error_message?: string | null
}

export type TaskRunAppendLogRequestApiEntriesItem = { [key: string]: unknown }

export interface TaskRunAppendLogRequestApi {
    /** Array of log entry dictionaries to append */
    entries: TaskRunAppendLogRequestApiEntriesItem[]
}

/**
 * * `plan` - plan
 * `context` - context
 * `reference` - reference
 * `output` - output
 * `artifact` - artifact
 * `tree_snapshot` - tree_snapshot
 */
export type TaskRunArtifactUploadTypeEnumApi =
    (typeof TaskRunArtifactUploadTypeEnumApi)[keyof typeof TaskRunArtifactUploadTypeEnumApi]

export const TaskRunArtifactUploadTypeEnumApi = {
    Plan: 'plan',
    Context: 'context',
    Reference: 'reference',
    Output: 'output',
    Artifact: 'artifact',
    TreeSnapshot: 'tree_snapshot',
} as const

export interface TaskRunArtifactUploadApi {
    /**
     * File name to associate with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact

* `plan` - plan
* `context` - context
* `reference` - reference
* `output` - output
* `artifact` - artifact
* `tree_snapshot` - tree_snapshot */
    type: TaskRunArtifactUploadTypeEnumApi
    /** Raw file contents (UTF-8 string or base64 data) */
    content: string
    /**
     * Optional MIME type for the artifact
     * @maxLength 255
     */
    content_type?: string
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
 * `cancel` - cancel
 * `close` - close
 */
export type MethodEnumApi = (typeof MethodEnumApi)[keyof typeof MethodEnumApi]

export const MethodEnumApi = {
    UserMessage: 'user_message',
    Cancel: 'cancel',
    Close: 'close',
} as const

/**
 * JSON-RPC request to send a command to the agent server in the sandbox.
 */
export interface TaskRunCommandRequestApi {
    /** JSON-RPC version, must be '2.0'

* `2.0` - 2.0 */
    jsonrpc: JsonrpcEnumApi
    /** Command method to execute on the agent server

* `user_message` - user_message
* `cancel` - cancel
* `close` - close */
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
    /** @maxLength 10000 */
    text: string
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

/**
 * * `needs_setup` - needs_setup
 * `detected` - detected
 * `waiting_for_data` - waiting_for_data
 * `ready` - ready
 * `not_applicable` - not_applicable
 * `unknown` - unknown
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

* `needs_setup` - needs_setup
* `detected` - detected
* `waiting_for_data` - waiting_for_data
* `ready` - ready
* `not_applicable` - not_applicable
* `unknown` - unknown */
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

export type TasksListParams = {
    /**
     * Filter by creator user ID
     */
    created_by?: number
    /**
     * Filter by internal flag. Defaults to excluding internal tasks when not specified.
     */
    internal?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
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
     * Filter by task run stage
     * @minLength 1
     */
    stage?: string
}

export type TasksRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
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
