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
