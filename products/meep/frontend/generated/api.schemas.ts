/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface MeepTopicApi {
    readonly id: string
    /** @maxLength 255 */
    title: string
    mission: string
    /** @nullable */
    readonly conversation_id: string | null
    readonly created_at: string
}

export interface PaginatedMeepTopicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MeepTopicApi[]
}

export type MeepTopicDetailsApiContext = { [key: string]: unknown }

export interface MeepTopicDetailsApi {
    readonly id: string
    /** @maxLength 255 */
    title: string
    mission: string
    /** @nullable */
    readonly conversation_id: string | null
    readonly created_at: string
    readonly context: MeepTopicDetailsApiContext
}

export interface MeepConversationBindingApi {
    task_id: string
}

export interface MeepScoutStatusApi {
    scout_id: string
    enabled: boolean
}

export interface MeepScoutApi {
    id: string
    name: string
    skill_name: string
    enabled: boolean
}

export interface MeepScoutCreateApi {
    /** @maxLength 100 */
    name: string
    /** @maxLength 16000 */
    instructions: string
    /**
     * Optional five-field schedule in the project's timezone. Defaults to the native scout cadence.
     * @maxLength 100
     */
    cron?: string
}

export interface MeepTaskAnswerApi {
    /** A stable ID for this answer, reused when retrying. */
    request_id: string
    /** The board item asking for input. */
    item_id: string
    /** The run ID that asked the question. */
    question_run_id: string
    /**
     * The person's answer to the child task.
     * @maxLength 16000
     */
    answer: string
}

export interface MeepTaskStartResultApi {
    /** The created board item ID. */
    item_id: string
    /** The child task ID. */
    task_id: string
    /** The child run ID. */
    run_id: string
}

export interface MeepTaskStartApi {
    /** A stable ID for this request, reused when retrying. */
    request_id: string
    /**
     * A short title for the board task.
     * @maxLength 255
     */
    title: string
    /**
     * The independent work and expected result.
     * @maxLength 16000
     */
    brief: string
}

export interface MeepTaskWaitApi {
    /** A stable ID for this wait, reused when retrying. */
    request_id: string
    /**
     * Up to 20 board item IDs to wait for.
     * @maxItems 20
     */
    item_ids: string[]
}

export interface MeepTaskWaitResultApi {
    /** The wait status. */
    status: string
    /** The selected board item IDs. */
    item_ids: string[]
}

export type MeepTopicsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
