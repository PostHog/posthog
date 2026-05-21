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
 * * `idle` - idle
 * `running` - running
 * `completed` - completed
 * `error` - error
 */
export type RunPhaseEnumApi = (typeof RunPhaseEnumApi)[keyof typeof RunPhaseEnumApi]

export const RunPhaseEnumApi = {
    Idle: 'idle',
    Running: 'running',
    Completed: 'completed',
    Error: 'error',
} as const

/**
 * * `pending` - pending
 * `in_progress` - in_progress
 * `completed` - completed
 * `failed` - failed
 * `canceled` - canceled
 */
export type WizardTaskStatusEnumApi = (typeof WizardTaskStatusEnumApi)[keyof typeof WizardTaskStatusEnumApi]

export const WizardTaskStatusEnumApi = {
    Pending: 'pending',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Canceled: 'canceled',
} as const

export interface WizardTaskApi {
    /** Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes. */
    id: string
    /** Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes. */
    title: string
    /** Current lifecycle stage of the task.

  * `pending` - pending
  * `in_progress` - in_progress
  * `completed` - completed
  * `failed` - failed
  * `canceled` - canceled */
    status: WizardTaskStatusEnumApi
}

export interface WizardSessionApi {
    /** @maxLength 255 */
    session_id: string
    readonly team_id: number
    /** @maxLength 255 */
    workflow_id: string
    /** @maxLength 255 */
    skill_id: string
    started_at: string
    run_phase: RunPhaseEnumApi
    tasks: WizardTaskApi[]
    event_plan?: unknown
    error?: unknown
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedWizardSessionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WizardSessionApi[]
}

export interface PatchedWizardSessionApi {
    /** @maxLength 255 */
    session_id?: string
    readonly team_id?: number
    /** @maxLength 255 */
    workflow_id?: string
    /** @maxLength 255 */
    skill_id?: string
    started_at?: string
    run_phase?: RunPhaseEnumApi
    tasks?: WizardTaskApi[]
    event_plan?: unknown
    error?: unknown
    readonly created_at?: string
    readonly updated_at?: string
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

export type WizardListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
