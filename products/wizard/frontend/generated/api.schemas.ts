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
 * @nullable
 */
export type UpsertWizardSessionRequestApiEventPlan = { [key: string]: unknown } | null

/**
 * @nullable
 */
export type UpsertWizardSessionRequestApiError = { [key: string]: unknown } | null

/**
 * Input: validates the JSON the wizard CLI posts. team_id is derived from URL.
 */
export interface UpsertWizardSessionRequestApi {
    session_id: string
    workflow_id: string
    skill_id: string
    started_at: string
    run_phase: RunPhaseEnumApi
    tasks: WizardTaskDTOApi[]
    /** @nullable */
    event_plan?: UpsertWizardSessionRequestApiEventPlan
    /** @nullable */
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
}
