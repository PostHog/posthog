/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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
