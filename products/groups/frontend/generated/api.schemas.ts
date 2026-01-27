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

export interface PaginatedGroupListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: GroupApi[]
}

export interface CreateGroupApi {
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    group_type_index: number
    /** @maxLength 400 */
    group_key: string
    group_properties?: unknown | null
}

export type GroupsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Specify the group type to list
     */
    group_type_index: number
    /**
     * Search the group name
     */
    search: string
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

export type GroupsList2Params = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Specify the group type to list
     */
    group_type_index: number
    /**
     * Search the group name
     */
    search: string
}

export type GroupsActivityRetrieve2Params = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type GroupsDeletePropertyCreate2Params = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type GroupsFindRetrieve2Params = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type GroupsRelatedRetrieve2Params = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type GroupsUpdatePropertyCreate2Params = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}
