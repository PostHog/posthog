/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface WebMCPExecRequestApi {
    /**
     * The exec command to run, for example `search insights` or `call insight-get {...}`.
     * @maxLength 100000
     */
    command: string
}

export type WebMCPExecResultApiContentItem = {
    type: string
    [key: string]: unknown
}

export interface WebMCPExecResultApi {
    /** MCP content blocks the tool returned, such as `{type: 'text', text: '...'}`. */
    content: WebMCPExecResultApiContentItem[]
    /** True when the tool ran and reported a failure. */
    is_error: boolean
}
