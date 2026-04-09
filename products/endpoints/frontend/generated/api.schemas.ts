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
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

/**
 * Materialization status for an endpoint version.
 */
export interface EndpointMaterializationApi {
    /** URL-safe endpoint name. */
    name: string
    /** Current materialization status (e.g. 'Completed', 'Running'). */
    status?: string
    /** Whether this endpoint query can be materialized. */
    can_materialize: boolean
    /**
     * Reason why materialization is not possible (only when can_materialize is false).
     * @nullable
     */
    reason?: string | null
    /**
     * ISO 8601 timestamp of the last successful materialization.
     * @nullable
     */
    last_materialized_at?: string | null
    /** Last materialization error message, if any. */
    error?: string
    /**
     * How often the materialization refreshes (e.g. 'every_hour').
     * @nullable
     */
    sync_frequency?: string | null
}

/**
 * A column in the endpoint's query result.
 */
export interface EndpointColumnApi {
    /** Column name from the query SELECT clause. */
    name: string
    /** Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown. */
    type: string
}

/**
 * Per-column bucket overrides for range variable materialization.
 * @nullable
 */
export type EndpointResponseApiBucketOverrides = { [key: string]: unknown } | null | null

/**
 * Full endpoint representation returned by list/retrieve/create/update.
 */
export interface EndpointResponseApi {
    /** Unique endpoint identifier (UUID). */
    id: string
    /** URL-safe endpoint name, unique per team. */
    name: string
    /**
     * Human-readable description of the endpoint.
     * @nullable
     */
    description: string | null
    /** The HogQL or insight query definition (JSON object with 'kind' key). */
    query: unknown
    /** Whether the endpoint can be executed via the API. */
    is_active: boolean
    /**
     * Cache TTL in seconds, or null for default interval-based caching.
     * @nullable
     */
    cache_age_seconds: number | null
    /** Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run). */
    endpoint_path: string
    /**
     * Absolute URL to execute this endpoint.
     * @nullable
     */
    url: string | null
    /**
     * Absolute URL to view this endpoint in the PostHog UI.
     * @nullable
     */
    ui_url: string | null
    /** When the endpoint was created (ISO 8601). */
    created_at: string
    /** When the endpoint was last updated (ISO 8601). */
    updated_at: string
    /** User who created the endpoint. */
    readonly created_by: UserBasicApi
    /** Whether the current version's results are pre-computed to S3. */
    is_materialized: boolean
    /** Latest version number. */
    current_version: number
    /** Total number of versions for this endpoint. */
    versions_count: number
    /**
     * Short ID of the source insight, if derived from one.
     * @nullable
     */
    derived_from_insight: string | null
    /**
     * When this endpoint was last executed via the API (ISO 8601), or null if never executed.
     * @nullable
     */
    last_executed_at: string | null
    /** Materialization status and configuration for the current version. */
    materialization: EndpointMaterializationApi
    /**
     * Per-column bucket overrides for range variable materialization.
     * @nullable
     */
    bucket_overrides: EndpointResponseApiBucketOverrides
    /** Column names and types from the query's SELECT clause. */
    columns: EndpointColumnApi[]
}

export interface PaginatedEndpointResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EndpointResponseApi[]
}

/**
 * Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.
 * @nullable
 */
export type EndpointRequestApiBucketOverrides = { [key: string]: unknown } | null | null

/**
 * Schema for creating/updating endpoints. OpenAPI docs only — validation uses Pydantic.
 */
export interface EndpointRequestApi {
    /**
     * Unique URL-safe name. Must start with a letter, only letters/numbers/hyphens/underscores, max 128 chars.
     * @nullable
     */
    name?: string | null
    /** HogQL or insight query this endpoint executes. Changing this auto-creates a new version. */
    query?: unknown | null
    /**
     * Human-readable description of what this endpoint returns.
     * @nullable
     */
    description?: string | null
    /**
     * Cache TTL in seconds (60–86400).
     * @nullable
     */
    cache_age_seconds?: number | null
    /**
     * Whether this endpoint is available for execution via the API.
     * @nullable
     */
    is_active?: boolean | null
    /**
     * Whether query results are materialized to S3.
     * @nullable
     */
    is_materialized?: boolean | null
    /**
     * Materialization refresh frequency (e.g. 'every_hour', 'every_day').
     * @nullable
     */
    sync_frequency?: string | null
    /**
     * Short ID of the insight this endpoint was derived from.
     * @nullable
     */
    derived_from_insight?: string | null
    /**
     * Target a specific version for updates (defaults to current version).
     * @nullable
     */
    version?: number | null
    /**
     * Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.
     * @nullable
     */
    bucket_overrides?: EndpointRequestApiBucketOverrides
    /**
     * Set to true to soft-delete this endpoint.
     * @nullable
     */
    deleted?: boolean | null
}

/**
 * Per-column bucket overrides for range variable materialization.
 * @nullable
 */
export type EndpointVersionResponseApiBucketOverrides = { [key: string]: unknown } | null | null

/**
 * Extended endpoint representation when viewing a specific version.
 */
export interface EndpointVersionResponseApi {
    /** Unique endpoint identifier (UUID). */
    id: string
    /** URL-safe endpoint name, unique per team. */
    name: string
    /**
     * Human-readable description of the endpoint.
     * @nullable
     */
    description: string | null
    /** The HogQL or insight query definition (JSON object with 'kind' key). */
    query: unknown
    /** Whether the endpoint can be executed via the API. */
    is_active: boolean
    /**
     * Cache TTL in seconds, or null for default interval-based caching.
     * @nullable
     */
    cache_age_seconds: number | null
    /** Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run). */
    endpoint_path: string
    /**
     * Absolute URL to execute this endpoint.
     * @nullable
     */
    url: string | null
    /**
     * Absolute URL to view this endpoint in the PostHog UI.
     * @nullable
     */
    ui_url: string | null
    /** When the endpoint was created (ISO 8601). */
    created_at: string
    /** When the endpoint was last updated (ISO 8601). */
    updated_at: string
    /** User who created the endpoint. */
    readonly created_by: UserBasicApi
    /** Whether the current version's results are pre-computed to S3. */
    is_materialized: boolean
    /** Latest version number. */
    current_version: number
    /** Total number of versions for this endpoint. */
    versions_count: number
    /**
     * Short ID of the source insight, if derived from one.
     * @nullable
     */
    derived_from_insight: string | null
    /**
     * When this endpoint was last executed via the API (ISO 8601), or null if never executed.
     * @nullable
     */
    last_executed_at: string | null
    /** Materialization status and configuration for the current version. */
    materialization: EndpointMaterializationApi
    /**
     * Per-column bucket overrides for range variable materialization.
     * @nullable
     */
    bucket_overrides: EndpointVersionResponseApiBucketOverrides
    /** Column names and types from the query's SELECT clause. */
    columns: EndpointColumnApi[]
    /** Version number. */
    version: number
    /** Version unique identifier (UUID). */
    version_id: string
    /** Whether the parent endpoint is active (distinct from version.is_active). */
    endpoint_is_active: boolean
    /** ISO 8601 timestamp when this version was created. */
    version_created_at: string
    /**
     * ISO 8601 timestamp when this version was last updated.
     * @nullable
     */
    version_updated_at: string | null
    /** User who created this version. */
    readonly version_created_by: UserBasicApi | null
}

/**
 * Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.
 * @nullable
 */
export type PatchedEndpointRequestApiBucketOverrides = { [key: string]: unknown } | null | null

/**
 * Schema for creating/updating endpoints. OpenAPI docs only — validation uses Pydantic.
 */
export interface PatchedEndpointRequestApi {
    /**
     * Unique URL-safe name. Must start with a letter, only letters/numbers/hyphens/underscores, max 128 chars.
     * @nullable
     */
    name?: string | null
    /** HogQL or insight query this endpoint executes. Changing this auto-creates a new version. */
    query?: unknown | null
    /**
     * Human-readable description of what this endpoint returns.
     * @nullable
     */
    description?: string | null
    /**
     * Cache TTL in seconds (60–86400).
     * @nullable
     */
    cache_age_seconds?: number | null
    /**
     * Whether this endpoint is available for execution via the API.
     * @nullable
     */
    is_active?: boolean | null
    /**
     * Whether query results are materialized to S3.
     * @nullable
     */
    is_materialized?: boolean | null
    /**
     * Materialization refresh frequency (e.g. 'every_hour', 'every_day').
     * @nullable
     */
    sync_frequency?: string | null
    /**
     * Short ID of the insight this endpoint was derived from.
     * @nullable
     */
    derived_from_insight?: string | null
    /**
     * Target a specific version for updates (defaults to current version).
     * @nullable
     */
    version?: number | null
    /**
     * Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.
     * @nullable
     */
    bucket_overrides?: PatchedEndpointRequestApiBucketOverrides
    /**
     * Set to true to soft-delete this endpoint.
     * @nullable
     */
    deleted?: boolean | null
}

/**
 * Per-column bucket function overrides, e.g. {"timestamp": "hour"}
 * @nullable
 */
export type MaterializationPreviewRequestApiBucketOverrides = { [key: string]: string } | null | null

export interface MaterializationPreviewRequestApi {
    version?: number
    /**
     * Per-column bucket function overrides, e.g. {"timestamp": "hour"}
     * @nullable
     */
    bucket_overrides?: MaterializationPreviewRequestApiBucketOverrides
}

/**
 * Response from executing an endpoint query.
 */
export interface EndpointRunResponseApi {
    /** URL-safe endpoint name that was executed. */
    name: string
    /** Query result rows. Each row is a list of values matching the columns order. */
    results?: unknown[]
    /** Column names from the query SELECT clause. */
    columns?: string[]
    /** Whether more results are available beyond the limit. */
    hasMore?: boolean
    /** Version number of the endpoint that was executed. */
    endpoint_version?: number
}

/**
 * Variables to parameterize the endpoint query. The key is the variable name and the value is the variable value.

For HogQL endpoints:   Keys must match a variable `code_name` defined in the query (referenced as `{variables.code_name}`).   Example: `{"event_name": "$pageview"}`

For non-materialized insight endpoints (e.g. TrendsQuery):   - `date_from` and `date_to` are built-in variables that filter the date range.     Example: `{"date_from": "2024-01-01", "date_to": "2024-01-31"}`

For materialized insight endpoints:   - Use the breakdown property name as the key to filter by breakdown value.     Example: `{"$browser": "Chrome"}`   - `date_from`/`date_to` are not supported on materialized insight endpoints.

Unknown variable names will return a 400 error.
 * @nullable
 */
export type EndpointRunRequestApiVariables = { [key: string]: unknown } | null | null

export type EndpointRefreshModeApi = (typeof EndpointRefreshModeApi)[keyof typeof EndpointRefreshModeApi]

export const EndpointRefreshModeApi = {
    Cache: 'cache',
    Force: 'force',
    Direct: 'direct',
} as const

export interface EndpointRunRequestApi {
    /**
     * Client provided query ID. Can be used to retrieve the status or cancel the query.
     * @nullable
     */
    client_query_id?: string | null
    /**
     * Whether to include debug information (such as the executed HogQL) in the response.
     * @nullable
     */
    debug?: boolean | null
    /**
     * Maximum number of results to return. If not provided, returns all results.
     * @nullable
     */
    limit?: number | null
    /**
     * Number of results to skip. Must be used together with limit. Only supported for HogQL endpoints.
     * @nullable
     */
    offset?: number | null
    refresh?: EndpointRefreshModeApi | null
    /**
   * Variables to parameterize the endpoint query. The key is the variable name and the value is the variable value.

For HogQL endpoints:   Keys must match a variable `code_name` defined in the query (referenced as `{variables.code_name}`).   Example: `{"event_name": "$pageview"}`

For non-materialized insight endpoints (e.g. TrendsQuery):   - `date_from` and `date_to` are built-in variables that filter the date range.     Example: `{"date_from": "2024-01-01", "date_to": "2024-01-31"}`

For materialized insight endpoints:   - Use the breakdown property name as the key to filter by breakdown value.     Example: `{"$browser": "Chrome"}`   - `date_from`/`date_to` are not supported on materialized insight endpoints.

Unknown variable names will return a 400 error.
   * @nullable
   */
    variables?: EndpointRunRequestApiVariables
    /**
     * Specific endpoint version to execute. If not provided, the latest version is used.
     * @nullable
     */
    version?: number | null
}

export interface PaginatedEndpointVersionResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EndpointVersionResponseApi[]
}

export interface EndpointLastExecutionTimesRequestApi {
    names: string[]
}

export interface ClickhouseQueryProgressApi {
    active_cpu_time: number
    bytes_read: number
    estimated_rows_total: number
    rows_read: number
    time_elapsed: number
}

export interface QueryStatusApi {
    /**
     * Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set.
     * @nullable
     */
    complete?: boolean | null
    /** @nullable */
    dashboard_id?: number | null
    /**
     * When did the query execution task finish (whether successfully or not).
     * @nullable
     */
    end_time?: string | null
    /**
     * If the query failed, this will be set to true. More information can be found in the error_message field.
     * @nullable
     */
    error?: boolean | null
    /** @nullable */
    error_message?: string | null
    /** @nullable */
    expiration_time?: string | null
    id: string
    /** @nullable */
    insight_id?: number | null
    /** @nullable */
    labels?: string[] | null
    /**
     * When was the query execution task picked up by a worker.
     * @nullable
     */
    pickup_time?: string | null
    /** ONLY async queries use QueryStatus. */
    query_async?: boolean
    query_progress?: ClickhouseQueryProgressApi | null
    results?: unknown | null
    /**
     * When was query execution task enqueued.
     * @nullable
     */
    start_time?: string | null
    /** @nullable */
    task_id?: string | null
    team_id: number
}

export interface QueryStatusResponseApi {
    query_status: QueryStatusApi
}

export type EndpointsListParams = {
    created_by?: number
    is_active?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EndpointsOpenapiJsonRetrieveParams = {
    /**
     * Specific endpoint version to generate the spec for. Defaults to latest.
     */
    version?: number
}

export type EndpointsVersionsListParams = {
    created_by?: number
    is_active?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
