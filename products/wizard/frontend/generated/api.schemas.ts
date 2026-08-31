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
 * * `local` - local
 * * `cloud` - cloud
 */
export type RunEnvironmentEnumApi = (typeof RunEnvironmentEnumApi)[keyof typeof RunEnvironmentEnumApi]

export const RunEnvironmentEnumApi = {
    Local: 'local',
    Cloud: 'cloud',
} as const

export interface WizardProgramApi {
    /** Stable identifier used to select the program. */
    readonly id: string
    /** Display name of the program. */
    readonly name: string
    /** What the program does. */
    readonly description: string
    /** Exact Wizard package version used by the program. */
    readonly wizard_version: string
    /** Wizard CLI arguments used to start the program. */
    readonly command: readonly string[]
    /** Labels that categorize the program. */
    readonly tags: readonly string[]
    /** Programs that should run before this program. */
    readonly required_programs: readonly string[]
    /** Environments where the program can run. */
    readonly supported_environments: readonly RunEnvironmentEnumApi[]
}

export interface PaginatedWizardProgramListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WizardProgramApi[]
}

/**
 * Selects a folder on the user's machine as the workspace.
 */
export type LocalFolderWorkspaceApiType = (typeof LocalFolderWorkspaceApiType)[keyof typeof LocalFolderWorkspaceApiType]

export const LocalFolderWorkspaceApiType = {
    LocalFolder: 'local_folder',
} as const

export interface LocalFolderWorkspaceApi {
    /** Selects a folder on the user's machine as the workspace. */
    type: LocalFolderWorkspaceApiType
    /**
     * Name of the project in the local folder.
     * @maxLength 255
     */
    project_name: string
}

/**
 * Selects a GitHub repository as the workspace.
 */
export type GitRepositoryWorkspaceApiType =
    (typeof GitRepositoryWorkspaceApiType)[keyof typeof GitRepositoryWorkspaceApiType]

export const GitRepositoryWorkspaceApiType = {
    GitRepository: 'git_repository',
} as const

export interface GitRepositoryWorkspaceApi {
    /** Selects a GitHub repository as the workspace. */
    type: GitRepositoryWorkspaceApiType
    /**
     * GitHub repository in owner/name format.
     * @maxLength 255
     */
    repository: string
}

export type WizardWorkspaceApi = LocalFolderWorkspaceApi | GitRepositoryWorkspaceApi

/**
 * * `created` - created
 * * `running` - running
 * * `completed` - completed
 * * `failed` - failed
 * * `cancelled` - cancelled
 */
export type WizardRunStatusEnumApi = (typeof WizardRunStatusEnumApi)[keyof typeof WizardRunStatusEnumApi]

export const WizardRunStatusEnumApi = {
    Created: 'created',
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

/**
 * * `dispatching` - dispatching
 * * `provisioning` - provisioning
 * * `preparing_workspace` - preparing_workspace
 * * `executing_wizard` - executing_wizard
 * * `creating_artifacts` - creating_artifacts
 */
export type WizardRunStageEnumApi = (typeof WizardRunStageEnumApi)[keyof typeof WizardRunStageEnumApi]

export const WizardRunStageEnumApi = {
    Dispatching: 'dispatching',
    Provisioning: 'provisioning',
    PreparingWorkspace: 'preparing_workspace',
    ExecutingWizard: 'executing_wizard',
    CreatingArtifacts: 'creating_artifacts',
} as const

export interface WizardRunApi {
    /** Unique ID of the Wizard run. */
    readonly id: string
    /** Project that owns the Wizard run. */
    readonly team_id: number
    /**
     * User who created the Wizard run, or null if that user no longer exists.
     * @nullable
     */
    readonly created_by_id: number | null
    /** Where the setup agent runs.
     *
     * * `local` - local
     * * `cloud` - cloud */
    readonly environment: RunEnvironmentEnumApi
    /** Project that the setup agent works on. */
    readonly workspace: WizardWorkspaceApi
    /** Registry program selected for this run. */
    readonly program: WizardProgramApi
    /** Current lifecycle status of the Wizard run.
     *
     * * `created` - created
     * * `running` - running
     * * `completed` - completed
     * * `failed` - failed
     * * `cancelled` - cancelled */
    readonly status: WizardRunStatusEnumApi
    /**
     * Machine-readable failure reason, or null if the run has not failed.
     * @nullable
     */
    readonly error_code: string | null
    /**
     * Safe failure explanation, or null if the run has not failed.
     * @nullable
     */
    readonly error_message: string | null
    /** Current cloud worker stage, or null outside active cloud execution.
     *
     * * `dispatching` - dispatching
     * * `provisioning` - provisioning
     * * `preparing_workspace` - preparing_workspace
     * * `executing_wizard` - executing_wizard
     * * `creating_artifacts` - creating_artifacts */
    readonly stage: WizardRunStageEnumApi | null
    /** When the Wizard run was created. */
    readonly created_at: string
    /**
     * When the run last changed.
     * @nullable
     */
    readonly updated_at: string | null
    /**
     * When execution started, or null while queued.
     * @nullable
     */
    readonly started_at: string | null
    /**
     * When execution reached a terminal status, or null while active.
     * @nullable
     */
    readonly finished_at: string | null
    /**
     * Cloud execution deadline, or null for local runs.
     * @nullable
     */
    readonly deadline_at: string | null
}

export interface PaginatedWizardRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WizardRunApi[]
}

export interface WizardRunCreateRequestApi {
    /**
     * Registry program to run.
     * @pattern ^[a-z0-9]+(?:-[a-z0-9]+)*$
     */
    program_id: string
    /** Where the setup agent runs.
     *
     * * `local` - local
     * * `cloud` - cloud */
    environment: RunEnvironmentEnumApi
    /** Project that the setup agent works on. */
    workspace: WizardWorkspaceApi
    /**
     * Unique key that makes cloud run creation safe to retry.
     * @maxLength 255
     */
    idempotency_key?: string
    /** Wizard package version to run. Defaults to the backend pin and accepts latest explicitly. */
    wizard_version?: string
}

export interface WizardRunErrorApi {
    /** Error category. */
    readonly type: string
    /** Machine-readable error code. */
    readonly code: string
    /** What happened and how to continue. */
    readonly detail: string
    /**
     * Request field associated with the error, when available.
     * @nullable
     */
    readonly attr: string | null
}

/**
 * * `completed` - completed
 * * `failed` - failed
 * * `cancelled` - cancelled
 */
export type WizardRunStatusUpdateRequestStatusEnumApi =
    (typeof WizardRunStatusUpdateRequestStatusEnumApi)[keyof typeof WizardRunStatusUpdateRequestStatusEnumApi]

export const WizardRunStatusUpdateRequestStatusEnumApi = {
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

export interface PatchedWizardRunStatusUpdateRequestApi {
    /** New terminal status for the Wizard run.
     *
     * * `completed` - completed
     * * `failed` - failed
     * * `cancelled` - cancelled */
    status?: WizardRunStatusUpdateRequestStatusEnumApi
    /**
     * Machine-readable reason the Wizard run failed.
     * @maxLength 50
     * @nullable
     */
    error_code?: string | null
}

/**
 * Format of the changes produced by the run.
 *
 * * `git_diff` - git_diff
 */
export type WizardRunGitDiffArtifactApiArtifactType =
    (typeof WizardRunGitDiffArtifactApiArtifactType)[keyof typeof WizardRunGitDiffArtifactApiArtifactType]

export const WizardRunGitDiffArtifactApiArtifactType = {
    GitDiff: 'git_diff',
} as const

export interface WizardRunGitDiffArtifactApi {
    /** Unique ID of the run artifact. */
    readonly id: string
    /** Project that owns the run artifact. */
    readonly team_id: number
    /** Wizard run that produced the artifact. */
    readonly run_id: string
    /** Format of the changes produced by the run.
     *
     * * `git_diff` - git_diff */
    readonly artifact_type: WizardRunGitDiffArtifactApiArtifactType
    /** Stored artifact size in bytes. */
    readonly size_bytes: number
    /** SHA-256 hash of the stored artifact content. */
    readonly content_hash: string
    /**
     * Number of added lines in the diff.
     * @nullable
     */
    readonly additions: number | null
    /**
     * Number of removed lines in the diff.
     * @nullable
     */
    readonly removals: number | null
    /** Time when the artifact was stored. */
    readonly created_at: string
}

/**
 * Format of the changes produced by the run.
 *
 * * `pull_request` - pull_request
 */
export type WizardRunPullRequestArtifactApiArtifactType =
    (typeof WizardRunPullRequestArtifactApiArtifactType)[keyof typeof WizardRunPullRequestArtifactApiArtifactType]

export const WizardRunPullRequestArtifactApiArtifactType = {
    PullRequest: 'pull_request',
} as const

export interface WizardRunPullRequestArtifactApi {
    /** Unique ID of the run artifact. */
    readonly id: string
    /** Project that owns the run artifact. */
    readonly team_id: number
    /** Wizard run that produced the artifact. */
    readonly run_id: string
    /** Format of the changes produced by the run.
     *
     * * `pull_request` - pull_request */
    readonly artifact_type: WizardRunPullRequestArtifactApiArtifactType
    /** GitHub URL of the pull request. */
    readonly url: string
    /** Repository-local pull request number. */
    readonly number: number
    /** GitHub repository in owner/name format. */
    readonly repository: string
    /** Branch containing the setup agent's changes. */
    readonly head_branch: string
    /** Branch that the pull request targets. */
    readonly base_branch: string
    /** Time when the artifact was stored. */
    readonly created_at: string
}

export type WizardRunArtifactApi = WizardRunGitDiffArtifactApi | WizardRunPullRequestArtifactApi

export interface PaginatedWizardRunArtifactListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WizardRunArtifactApi[]
}

/**
 * The in-flight `wizard_ask` question. Typed rather than a free-form dict so the shape the
 * widget renders is enforced at the edge instead of trusted from the producer.
 */
export interface PendingInputApi {
    /**
     * Identifier the wizard mints for this question. Changes when a new question is asked.
     * @maxLength 255
     */
    id: string
    /** UTC timestamp when the wizard asked. Defaults to the session's update time when absent. */
    asked_at?: string
    /**
     * How many questions this single ask covers.
     * @minimum 1
     * @maximum 100
     */
    question_count?: number
    /** Whether the answer is a secret. Sensitive questions never carry prompt text. */
    sensitive?: boolean
    /**
     * The question text shown to the user. Always empty for sensitive questions.
     * @maxItems 10
     * @items.maxLength 2000
     */
    prompts?: string[]
}

/**
 * * `idle` - IDLE
 * * `running` - RUNNING
 * * `completed` - COMPLETED
 * * `error` - ERROR
 */
export type RunPhaseEnumApi = (typeof RunPhaseEnumApi)[keyof typeof RunPhaseEnumApi]

export const RunPhaseEnumApi = {
    Idle: 'idle',
    Running: 'running',
    Completed: 'completed',
    Error: 'error',
} as const

/**
 * * `pending` - PENDING
 * * `in_progress` - IN_PROGRESS
 * * `completed` - COMPLETED
 * * `failed` - FAILED
 * * `canceled` - CANCELED
 */
export type WizardTaskDTOStatusEnumApi = (typeof WizardTaskDTOStatusEnumApi)[keyof typeof WizardTaskDTOStatusEnumApi]

export const WizardTaskDTOStatusEnumApi = {
    Pending: 'pending',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Canceled: 'canceled',
} as const

export interface WizardTaskDTOApi {
    id: string
    title: string
    status: WizardTaskDTOStatusEnumApi
}

export interface WizardSessionUserDTOApi {
    id: number
    first_name: string
    email: string
}

/**
 * @nullable
 */
export type WizardSessionDTOApiEventPlan = { [key: string]: unknown } | null

/**
 * @nullable
 */
export type WizardSessionDTOApiError = { [key: string]: unknown } | null

/**
 * Output: serialises a WizardSessionDTO returned by the facade.
 */
export interface WizardSessionDTOApi {
    /** The question the wizard is currently blocked on, or null when nothing is pending. */
    pending_input: PendingInputApi | null
    session_id: string
    team_id: number
    workflow_id: string
    skill_id: string
    started_at: string
    run_phase: RunPhaseEnumApi
    tasks: WizardTaskDTOApi[]
    /** @nullable */
    event_plan: WizardSessionDTOApiEventPlan
    /** @nullable */
    error: WizardSessionDTOApiError
    /**
     * Markdown handoff doc the wizard produced for this run (its setup report), or null while the run hasn't written one. Sticky once set.
     * @nullable
     */
    handoff_text: string | null
    /** The user who initiated this wizard run (null for runs created before attribution existed). Lets the UI name whose run it is. */
    created_by: WizardSessionUserDTOApi | null
    created_at: string
    updated_at: string
    is_stale: boolean
}

export interface PaginatedWizardSessionDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WizardSessionDTOApi[]
}

/**
 * Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific.
 * @nullable
 */
export type UpsertWizardSessionRequestApiEventPlan = { [key: string]: unknown } | null

/**
 * Populated when run_phase='error'. Shape: { type: string, message: string }.
 * @nullable
 */
export type UpsertWizardSessionRequestApiError = { [key: string]: unknown } | null

/**
 * Input: validates the JSON the wizard CLI posts. team_id is derived from URL.
 */
export interface UpsertWizardSessionRequestApi {
    /** Populated while the wizard is blocked on a question in the terminal. Null/absent means no input is pending; a push without it clears the previous prompt. */
    pending_input?: PendingInputApi | null
    /**
     * Markdown handoff doc for the run (the wizard's setup report). Send it once the run has produced one; omitting it on later pushes keeps the stored value.
     * @maxLength 65536
     * @nullable
     */
    handoff_text?: string | null
    /**
     * Stable identifier the wizard mints for this run (format: '{workflow_id}-{skill_id}-{started_at_iso}'). Reposting with the same session_id upserts the existing row.
     * @maxLength 255
     */
    session_id: string
    /**
     * High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'.
     * @maxLength 255
     */
    workflow_id: string
    /**
     * Specific skill within the workflow, e.g. 'nextjs', 'django', 'laravel'.
     * @maxLength 255
     */
    skill_id: string
    /** UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id. */
    started_at: string
    /** Lifecycle stage of the wizard run.
     *
     * * `idle` - IDLE
     * * `running` - RUNNING
     * * `completed` - COMPLETED
     * * `error` - ERROR */
    run_phase: RunPhaseEnumApi
    tasks: WizardTaskDTOApi[]
    /**
     * Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific.
     * @nullable
     */
    event_plan?: UpsertWizardSessionRequestApiEventPlan
    /**
     * Populated when run_phase='error'. Shape: { type: string, message: string }.
     * @nullable
     */
    error?: UpsertWizardSessionRequestApiError
}

/**
 * * `git_diff` - git_diff
 */
export type WizardRunArtifactTypeEnumApi =
    (typeof WizardRunArtifactTypeEnumApi)[keyof typeof WizardRunArtifactTypeEnumApi]

export const WizardRunArtifactTypeEnumApi = {
    GitDiff: 'git_diff',
} as const

/**
 * * `pull_request` - pull_request
 */
export type WizardRunPullRequestArtifactArtifactTypeEnumApi =
    (typeof WizardRunPullRequestArtifactArtifactTypeEnumApi)[keyof typeof WizardRunPullRequestArtifactArtifactTypeEnumApi]

export const WizardRunPullRequestArtifactArtifactTypeEnumApi = {
    PullRequest: 'pull_request',
} as const

export type WizardRegistryListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type WizardRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type WizardRunsArtifactsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type WizardSessionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter to a single skill within the workflow (e.g. 'nextjs').
     */
    skill_id?: string
    /**
     * Filter to a single workflow (e.g. 'onboarding').
     */
    workflow_id?: string
}

export type WizardSessionsLatestRetrieveParams = {
    /**
     * Filter to a single skill within the workflow (e.g. 'nextjs').
     */
    skill_id?: string
    /**
     * Filter to a single workflow (e.g. 'posthog-integration').
     */
    workflow_id: string
}

export type WizardSessionsStreamRetrieveParams = {
    skill_id?: string
    workflow_id: string
}
