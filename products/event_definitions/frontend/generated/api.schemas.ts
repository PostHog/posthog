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
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * * `allow` - Allow
 * * `reject` - Reject
 */
export type EnforcementModeEnumApi = (typeof EnforcementModeEnumApi)[keyof typeof EnforcementModeEnumApi]

export const EnforcementModeEnumApi = {
    Allow: 'allow',
    Reject: 'reject',
} as const

/**
 * Serializer mixin that handles tags for objects.
 */
export interface EnterpriseEventDefinitionApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /** @nullable */
    owner?: number | null
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    /** @nullable */
    readonly created_at: string | null
    readonly updated_at: string
    readonly updated_by: UserBasicApi
    /** @nullable */
    readonly last_seen_at: string | null
    readonly last_updated_at: string
    verified?: boolean
    /** @nullable */
    readonly verified_at: string | null
    readonly verified_by: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
    enforcement_mode?: EnforcementModeEnumApi
    /**
     * Name of a single property on this event that PostHog UIs should display alongside the event (for example `$pathname` on `$pageview`). When set, surfaces like the session replay inspector show the property's value next to the event name without the user having to open the event.
     * @maxLength 400
     * @nullable
     */
    primary_property?: string | null
    readonly is_action: boolean
    readonly action_id: number
    readonly is_calculating: boolean
    readonly last_calculated_at: string
    readonly created_by: UserBasicApi
    post_to_slack?: boolean
    default_columns?: string[]
    readonly media_preview_urls: readonly string[]
}

export interface PaginatedEnterpriseEventDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EnterpriseEventDefinitionApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedEnterpriseEventDefinitionApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    /** @nullable */
    owner?: number | null
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    /** @nullable */
    readonly created_at?: string | null
    readonly updated_at?: string
    readonly updated_by?: UserBasicApi
    /** @nullable */
    readonly last_seen_at?: string | null
    readonly last_updated_at?: string
    verified?: boolean
    /** @nullable */
    readonly verified_at?: string | null
    readonly verified_by?: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
    enforcement_mode?: EnforcementModeEnumApi
    /**
     * Name of a single property on this event that PostHog UIs should display alongside the event (for example `$pathname` on `$pageview`). When set, surfaces like the session replay inspector show the property's value next to the event name without the user having to open the event.
     * @maxLength 400
     * @nullable
     */
    primary_property?: string | null
    readonly is_action?: boolean
    readonly action_id?: number
    readonly is_calculating?: boolean
    readonly last_calculated_at?: string
    readonly created_by?: UserBasicApi
    post_to_slack?: boolean
    default_columns?: string[]
    readonly media_preview_urls?: readonly string[]
}

/**
 * * `add` - add
 * * `remove` - remove
 * * `set` - set
 */
export type BulkUpdateTagsActionEnumApi = (typeof BulkUpdateTagsActionEnumApi)[keyof typeof BulkUpdateTagsActionEnumApi]

export const BulkUpdateTagsActionEnumApi = {
    Add: 'add',
    Remove: 'remove',
    Set: 'set',
} as const

/**
 * Variant of ``BulkUpdateTagsRequestSerializer`` for resources keyed by UUID (e.g. event definitions).
 */
export interface BulkUpdateTagsUUIDRequestApi {
    /**
     * List of object UUIDs to update tags on.
     * @maxItems 500
     */
    ids: string[]
    /** 'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.
     *
     * * `add` - add
     * * `remove` - remove
     * * `set` - set */
    action: BulkUpdateTagsActionEnumApi
    /** Tag names to add, remove, or set. */
    tags: string[]
}

export interface BulkUpdateTagsUUIDItemApi {
    /** UUID of the object whose tags were updated. */
    id: string
    /** The object's full tag list after the update. */
    tags: string[]
}

export interface BulkUpdateTagsUUIDErrorApi {
    /** UUID of the object that was skipped. */
    id: string
    /** Why the object was skipped, e.g. 'Not found'. */
    reason: string
}

export interface BulkUpdateTagsUUIDResponseApi {
    /** Objects whose tags were successfully updated. */
    updated: BulkUpdateTagsUUIDItemApi[]
    /** Objects that were skipped, with a reason each. */
    skipped: BulkUpdateTagsUUIDErrorApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface EventDefinitionRecordApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    last_seen_at?: string | null
    readonly last_updated_at: string
    tags?: unknown[]
    enforcement_mode?: EnforcementModeEnumApi
    /**
     * Name of a single property on this event that PostHog UIs should display alongside the event (for example `$pathname` on `$pageview`). When set, surfaces like the session replay inspector show the property's value next to the event name without the user having to open the event.
     * @maxLength 400
     * @nullable
     */
    primary_property?: string | null
    readonly is_action: boolean
    readonly action_id: number
    readonly is_calculating: boolean
    readonly last_calculated_at: string
    readonly created_by: UserBasicApi
    post_to_slack?: boolean
}

/**
 * Mapping from event name to the team-configured primary property for that event. Names without a configured primary property are omitted; callers should fall back to the core taxonomy defaults for those.
 */
export type PrimaryPropertiesResponseApiPrimaryProperties = { [key: string]: string }

export interface PrimaryPropertiesResponseApi {
    /** Mapping from event name to the team-configured primary property for that event. Names without a configured primary property are omitted; callers should fall back to the core taxonomy defaults for those. */
    primary_properties: PrimaryPropertiesResponseApiPrimaryProperties
}

export type EventDefinitionsListParams = {
    /**
     * When true, omit events that have been explicitly hidden by a team admin (Enterprise only).
     */
    exclude_hidden?: boolean
    /**
     * When true, omit events whose last ingested occurrence is older than 30 days. Events that have never been seen (`last_seen_at` is null) are kept so newly-defined events remain discoverable. Default false. If a search returns zero results with this filter on, retry with `exclude_stale=false` and tell the user the matches are stale.
     */
    exclude_stale?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EventDefinitionsByNameRetrieveParams = {
    /**
     * The exact event name to look up
     */
    name: string
}

export type EventDefinitionsPrimaryPropertiesRetrieveParams = {
    /**
     * Optional: restrict the response to these event names. Repeat the parameter for multiple names (e.g. `?names=a&names=b`). When omitted, returns every team-configured primary property.
     */
    names?: string[]
}
