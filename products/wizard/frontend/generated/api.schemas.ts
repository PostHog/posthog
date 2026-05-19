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
    /** Stable identifier the wizard assigns to a run, formatted '{workflow_id}-{skill_id}-{started_at_iso}'. Re-posting with the same session_id upserts the existing row. */
    session_id: string
    readonly team_id: number
    /** High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'. */
    workflow_id: string
    /** Specific skill within the workflow, e.g. 'posthog_integration', 'revenue_analytics_setup'. */
    skill_id: string
    /** UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id. */
    started_at: string
    /** Lifecycle stage of the wizard run.

  * `idle` - idle
  * `running` - running
  * `completed` - completed
  * `error` - error */
    run_phase: RunPhaseEnumApi
    /** Full snapshot of the wizard's current task list. Each push overwrites the previous list; tasks may be added, removed, or re-ordered between pushes. */
    tasks: WizardTaskApi[]
    /** Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific. */
    event_plan?: unknown
    /** Populated when run_phase='error'. Shape: { type: string, message: string }. */
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
