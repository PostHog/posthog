/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface GroupApi {
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    group_type_index: number
    /** @maxLength 400 */
    group_key: string
    group_properties?: unknown
    readonly created_at: string
}

export interface CreateGroupApi {
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    group_type_index: number
    /** @maxLength 400 */
    group_key: string
    group_properties?: unknown
}

export type GroupsListParams = {
    /**
     * Pagination cursor returned in the `next` URL of a previous response
     */
    cursor?: string
    /**
     * Filter groups whose key contains this string (case-insensitive)
     */
    group_key?: string
    /**
     * Specify the group type to list
     */
    group_type_index: number
    /**
     * Search the group name
     */
    search?: string
}

export type GroupsActivityRetrieveParams = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type GroupsDeletePropertyCreateParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type GroupsFindRetrieveParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * When true, do not lazily create the group's CRM notebook. Use for read-only lookups (e.g. resolving a group's display name) that should not have side effects.
     */
    skip_create_notebook?: boolean
}

export type GroupsRelatedRetrieveParams = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type GroupsUpdatePropertyCreateParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}
