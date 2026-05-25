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
 * * `idle` - IDLE
 * `running` - RUNNING
 * `completed` - COMPLETED
 * `error` - ERROR
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
 * `in_progress` - IN_PROGRESS
 * `completed` - COMPLETED
 * `failed` - FAILED
 * `canceled` - CANCELED
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

  * `idle` - IDLE
  * `running` - RUNNING
  * `completed` - COMPLETED
  * `error` - ERROR */
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
