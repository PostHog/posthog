/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface FileSystemApi {
    readonly id: string
    path: string
    /** @nullable */
    readonly depth: number | null
    /** @maxLength 100 */
    type?: string
    /**
     * @maxLength 100
     * @nullable
     */
    ref?: string | null
    /** @nullable */
    href?: string | null
    meta?: unknown | null
    /** @nullable */
    shortcut?: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly last_viewed_at: string | null
}
