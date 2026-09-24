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
 * The group's properties.
 */
export type GroupApiGroupProperties = { [key: string]: unknown }

export interface GroupApi {
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    group_type_index: number
    /** @maxLength 400 */
    group_key: string
    /** The group's properties. */
    group_properties: GroupApiGroupProperties
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

export interface GroupDeletePropertyApi {
    /** Name of the property to delete. */
    $unset: string
}

/**
 * The group's properties.
 */
export type FindGroupApiGroupProperties = { [key: string]: unknown }

export interface FindGroupApi {
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    group_type_index: number
    /** @maxLength 400 */
    group_key: string
    /** The group's properties. */
    group_properties: FindGroupApiGroupProperties
    readonly created_at: string
    /** @nullable */
    readonly notebook: string | null
}

/**
 * Marks this actor as a person.
 */
export type SerializedPersonActorApiType =
    (typeof SerializedPersonActorApiType)[keyof typeof SerializedPersonActorApiType]

export const SerializedPersonActorApiType = {
    Person: 'person',
} as const

/**
 * The actor's properties.
 */
export type SerializedPersonActorApiProperties = { [key: string]: unknown }

export type SerializedPersonActorApiMatchedRecordingsItem = { [key: string]: unknown }

export interface SerializedPersonActorApi {
    /** The person's UUID, or the group's key. */
    id: string
    /** The actor's properties. */
    properties: SerializedPersonActorApiProperties
    /**
     * When the actor was first seen.
     * @nullable
     */
    created_at: string | null
    /** Recordings that matched the query. Empty unless the endpoint asks for them. */
    matched_recordings: SerializedPersonActorApiMatchedRecordingsItem[]
    /**
     * The actor's value at the data point it was queried for. Null unless the query computes one.
     * @nullable
     */
    value_at_data_point: number | null
    /** Marks this actor as a person. */
    type: SerializedPersonActorApiType
    /** The person's UUID. Same value as `id`. */
    uuid: string
    /** Display name, resolved from the person's properties or distinct IDs. */
    name: string
    /** The person's distinct IDs, newest first. */
    distinct_ids: string[]
    /**
     * When the person was last seen.
     * @nullable
     */
    last_seen_at: string | null
    /**
     * Whether the person has been identified.
     * @nullable
     */
    is_identified: boolean | null
}

/**
 * Marks this actor as a group.
 */
export type SerializedGroupActorApiType = (typeof SerializedGroupActorApiType)[keyof typeof SerializedGroupActorApiType]

export const SerializedGroupActorApiType = {
    Group: 'group',
} as const

/**
 * The actor's properties.
 */
export type SerializedGroupActorApiProperties = { [key: string]: unknown }

export type SerializedGroupActorApiMatchedRecordingsItem = { [key: string]: unknown }

export interface SerializedGroupActorApi {
    /** The person's UUID, or the group's key. */
    id: string
    /** The actor's properties. */
    properties: SerializedGroupActorApiProperties
    /**
     * When the actor was first seen.
     * @nullable
     */
    created_at: string | null
    /** Recordings that matched the query. Empty unless the endpoint asks for them. */
    matched_recordings: SerializedGroupActorApiMatchedRecordingsItem[]
    /**
     * The actor's value at the data point it was queried for. Null unless the query computes one.
     * @nullable
     */
    value_at_data_point: number | null
    /** Marks this actor as a group. */
    type: SerializedGroupActorApiType
    /** Key identifying the group within its group type. */
    group_key: string
    /** Index of the group type this group belongs to. */
    group_type_index: number
}

export type RelatedActorApi = SerializedPersonActorApi | SerializedGroupActorApi

/**
 * Value to set. Any JSON value other than null.
 */
export type GroupUpdatePropertyRequestApiValue = string | number | boolean | { [key: string]: unknown } | unknown[]

export interface GroupUpdatePropertyRequestApi {
    /** Name of the property to set. */
    key: string
    /** Value to set. Any JSON value other than null. */
    value: GroupUpdatePropertyRequestApiValue
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

export type GroupsRelatedListParams = {
    /**
     * Group type of the actor to find related actors for. Omit when the actor is a person.
     */
    group_type_index?: number
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
