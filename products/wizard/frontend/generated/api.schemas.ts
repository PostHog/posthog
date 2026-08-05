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
 * * `monorepo` - monorepo
 * * `single` - single
 */
export type RepoTypeEnumApi = (typeof RepoTypeEnumApi)[keyof typeof RepoTypeEnumApi]

export const RepoTypeEnumApi = {
    Monorepo: 'monorepo',
    Single: 'single',
} as const

/**
 * One project the detection agent found in the repository.
 */
export interface DetectedProjectApi {
    /**
     * Repo-relative path of the project ('.' for the repository root).
     * @maxLength 512
     */
    path: string
    /**
     * Human-readable framework name the agent classified, e.g. 'Next.js'.
     * @maxLength 100
     */
    framework: string
    /**
     * Detection-kind-specific target the project matched (e.g. the source-map skill variant 'nextjs'), or null when the stack isn't supported.
     * @maxLength 64
     * @nullable
     */
    variant?: string | null
    /** Whether a PostHog SDK is already installed in this project. */
    has_posthog: boolean
    /** Whether the detection kind can act on this project (supported variant + SDK present). */
    instrumentable: boolean
    /**
     * Why the project is not instrumentable, when it isn't. Human-readable.
     * @maxLength 300
     * @nullable
     */
    reason?: string | null
}

/**
 * The structured result of one detection run. Typed rather than a free-form dict so the
 * shape the app renders is enforced at the edge instead of trusted from the producer.
 */
export interface DetectionReportApi {
    /** Whether the repository is a multi-project workspace or a single project.
     *
     * * `monorepo` - monorepo
     * * `single` - single */
    repo_type: RepoTypeEnumApi
    /** Projects found in the repository, one entry per project manifest. */
    projects: DetectedProjectApi[]
}

/**
 * Why a detection run failed. Populated instead of `report`.
 */
export interface DetectionErrorApi {
    /**
     * Machine-readable failure category, e.g. 'no-manifests', 'agent-error'.
     * @maxLength 100
     * @nullable
     */
    type?: string | null
    /**
     * Human-readable failure description.
     * @maxLength 2000
     */
    message: string
}

/**
 * Input: validates the JSON a detection agent posts. team_id is derived from URL.
 */
export interface UpsertWizardRepositoryDetectionRequestApi {
    /** The detection result. Exactly one of `report` / `error` must be set. */
    report?: DetectionReportApi | null
    /** Why the run failed. Exactly one of `report` / `error` must be set. */
    error?: DetectionErrorApi | null
    /**
     * TaskRun UUID of the cloud run producing this result. Omit for local runs.
     * @nullable
     */
    task_run_id?: string | null
    /**
     * Repository the detection ran against, in 'org/repo' form. Together with `kind` this is the idempotency anchor — reposting the same pair replaces the existing row.
     * @maxLength 255
     */
    repository: string
    /**
     * Detection flavor, e.g. 'error-tracking-source-maps'.
     * @maxLength 64
     */
    kind: string
}

/**
 * Output: serialises a WizardRepositoryDetectionDTO returned by the facade.
 */
export interface WizardRepositoryDetectionDTOApi {
    /** The detection result, or null when the run failed (see `error`). */
    report: DetectionReportApi | null
    /** Why the run failed, or null when it succeeded (see `report`). */
    error: DetectionErrorApi | null
    id: string
    team_id: number
    /** Repository the detection ran against, in 'org/repo' form. */
    repository: string
    /** Detection flavor, e.g. 'error-tracking-source-maps'. */
    kind: string
    /**
     * TaskRun UUID of the cloud run that produced this result, when it ran in the cloud.
     * @nullable
     */
    task_run_id: string | null
    created_at: string
    updated_at: string
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
