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
 * Team-defined tags layered on top of the fixed taxonomy, as a {name: description} map. Names must be lowercase snake_case (max 60 chars), descriptions max 200 chars, max 15 entries.
 */
export type SessionSummariesConfigApiCustomTags = { [key: string]: string }

export interface SessionSummariesConfigApi {
    /**
     * Free-form description of the team's product, used to tailor AI-generated single-session replay summaries. Injected into the system prompt of every summary generated for this team via the replay page.
     * @maxLength 10000
     */
    product_context?: string
    /** Team-defined tags layered on top of the fixed taxonomy, as a {name: description} map. Names must be lowercase snake_case (max 60 chars), descriptions max 200 chars, max 15 entries. */
    custom_tags?: SessionSummariesConfigApiCustomTags
}

/**
 * Team-defined tags layered on top of the fixed taxonomy, as a {name: description} map. Names must be lowercase snake_case (max 60 chars), descriptions max 200 chars, max 15 entries.
 */
export type PatchedSessionSummariesConfigApiCustomTags = { [key: string]: string }

export interface PatchedSessionSummariesConfigApi {
    /**
     * Free-form description of the team's product, used to tailor AI-generated single-session replay summaries. Injected into the system prompt of every summary generated for this team via the replay page.
     * @maxLength 10000
     */
    product_context?: string
    /** Team-defined tags layered on top of the fixed taxonomy, as a {name: description} map. Names must be lowercase snake_case (max 60 chars), descriptions max 200 chars, max 15 entries. */
    custom_tags?: PatchedSessionSummariesConfigApiCustomTags
}

export interface SessionSummariesApi {
    /**
     * List of session IDs to summarize (max 300)
     * @minItems 1
     * @maxItems 300
     */
    session_ids: string[]
    /**
     * Optional focus area for the summarization
     * @maxLength 500
     */
    focus_area?: string
}
