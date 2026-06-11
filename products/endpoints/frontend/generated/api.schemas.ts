// Kernel types below are authored in frontend/src/queries/schema (x-schema-source:
// posthog.schema.*) — aliased instead of re-emitting a lossy generated copy.
import type {
    Breakdown,
    BreakdownFilter,
    ClickhouseQueryProgress,
    DashboardFilter,
    EndpointLastExecutionTimesRequest,
    EndpointRunRequest,
    QueryStatus,
    QueryStatusResponse,
} from '~/queries/schema/schema-general'
import type {
    CohortPropertyFilter,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    ErrorTrackingIssueFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    LogEntryPropertyFilter,
    LogPropertyFilter,
    PersonPropertyFilter,
    RecordingPropertyFilter,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
    SpanPropertyFilter,
    WorkflowVariablePropertyFilter,
} from '~/types'

export type BreakdownApi = Breakdown
export type BreakdownFilterApi = BreakdownFilter
export type ClickhouseQueryProgressApi = ClickhouseQueryProgress
export type CohortPropertyFilterApi = CohortPropertyFilter
export type DashboardFilterApi = DashboardFilter
export type DataWarehousePersonPropertyFilterApi = DataWarehousePersonPropertyFilter
export type DataWarehousePropertyFilterApi = DataWarehousePropertyFilter
export type ElementPropertyFilterApi = ElementPropertyFilter
export type EmptyPropertyFilterApi = EmptyPropertyFilter
export type EndpointLastExecutionTimesRequestApi = EndpointLastExecutionTimesRequest
export type EndpointRunRequestApi = EndpointRunRequest
export type ErrorTrackingIssueFilterApi = ErrorTrackingIssueFilter
export type EventMetadataPropertyFilterApi = EventMetadataPropertyFilter
export type EventPropertyFilterApi = EventPropertyFilter
export type FeaturePropertyFilterApi = FeaturePropertyFilter
export type FlagPropertyFilterApi = FlagPropertyFilter
export type GroupPropertyFilterApi = GroupPropertyFilter
export type HogQLPropertyFilterApi = HogQLPropertyFilter
export type LogEntryPropertyFilterApi = LogEntryPropertyFilter
export type LogPropertyFilterApi = LogPropertyFilter
export type PersonPropertyFilterApi = PersonPropertyFilter
export type QueryStatusApi = QueryStatus
export type QueryStatusResponseApi = QueryStatusResponse
export type RecordingPropertyFilterApi = RecordingPropertyFilter
export type RevenueAnalyticsPropertyFilterApi = RevenueAnalyticsPropertyFilter
export type SessionPropertyFilterApi = SessionPropertyFilter
export type SpanPropertyFilterApi = SpanPropertyFilter
export type WorkflowVariablePropertyFilterApi = WorkflowVariablePropertyFilter

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
     * UUID of the underlying saved query backing this materialization. Only populated when the version is materialized.
     * @nullable
     */
    saved_query_id?: string | null
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
export type EndpointResponseApiBucketOverrides = { [key: string]: unknown } | null

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
    /** How fresh the data is, in seconds. One of: 900, 1800, 3600, 21600, 43200, 86400, 604800. */
    data_freshness_seconds: number
    /** Relative API path to execute this endpoint (e.g. /api/projects/{team_id}/endpoints/{name}/run). */
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
    /**
     * UUID of the current EndpointVersion row.
     * @nullable
     */
    current_version_id?: string | null
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
    /** Tag names associated with this endpoint. */
    tags: string[]
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
export type EndpointRequestApiBucketOverrides = { [key: string]: unknown } | null

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
    query?: unknown
    /**
     * Human-readable description of what this endpoint returns.
     * @nullable
     */
    description?: string | null
    /**
     * How fresh the data should be, in seconds. Must be one of: 900 (15 min), 1800 (30 min), 3600 (1 h), 21600 (6 h), 43200 (12 h), 86400 (24 h, default), 604800 (7 d). Controls cache TTL and materialization sync frequency.
     * @nullable
     */
    data_freshness_seconds?: number | null
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
    /**
     * List of tag names to associate with this endpoint. Replaces any existing tags.
     * @nullable
     */
    tags?: string[] | null
}

/**
 * Per-column bucket overrides for range variable materialization.
 * @nullable
 */
export type EndpointVersionResponseApiBucketOverrides = { [key: string]: unknown } | null

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
    /** How fresh the data is, in seconds. One of: 900, 1800, 3600, 21600, 43200, 86400, 604800. */
    data_freshness_seconds: number
    /** Relative API path to execute this endpoint (e.g. /api/projects/{team_id}/endpoints/{name}/run). */
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
    /**
     * UUID of the current EndpointVersion row.
     * @nullable
     */
    current_version_id?: string | null
    /** Total number of versions for this endpoint. */
    versions_count: number
    /**
     * Short ID of the source insight, if derived from one.
     * @nullable
     */
    derived_from_insight: string | null
    /**
     * When this specific version was last executed via the API (ISO 8601), or null if it hasn't been executed. Per-version tracking is recent, so versions that predate it read null until their next run.
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
    /** Tag names associated with this endpoint. */
    tags: string[]
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
export type PatchedEndpointRequestApiBucketOverrides = { [key: string]: unknown } | null

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
    query?: unknown
    /**
     * Human-readable description of what this endpoint returns.
     * @nullable
     */
    description?: string | null
    /**
     * How fresh the data should be, in seconds. Must be one of: 900 (15 min), 1800 (30 min), 3600 (1 h), 21600 (6 h), 43200 (12 h), 86400 (24 h, default), 604800 (7 d). Controls cache TTL and materialization sync frequency.
     * @nullable
     */
    data_freshness_seconds?: number | null
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
    /**
     * List of tag names to associate with this endpoint. Replaces any existing tags.
     * @nullable
     */
    tags?: string[] | null
}

/**
 * Per-column bucket function overrides, e.g. {"timestamp": "hour"}
 * @nullable
 */
export type MaterializationPreviewRequestApiBucketOverrides = { [key: string]: string } | null

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
    /** Unique identifier for this execution. Use it to find the matching entry in the endpoint's logs. */
    execution_id?: string
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
 *
 * For HogQL endpoints:   Keys must match a variable `code_name` defined in the query (referenced as `{variables.code_name}`).   Example: `{"event_name": "$pageview"}`
 *
 * For non-materialized insight endpoints (e.g. TrendsQuery):   - `date_from` and `date_to` are built-in variables that filter the date range.     Example: `{"date_from": "2024-01-01", "date_to": "2024-01-31"}`
 *
 * For materialized insight endpoints:   - Use the breakdown property name as the key to filter by breakdown value.     Example: `{"$browser": "Chrome"}`   - `date_from`/`date_to` are not supported on materialized insight endpoints.
 *
 * Unknown variable names will return a 400 error.
 */
export type EndpointRunRequestApiVariables = { [key: string]: unknown } | null

export type BreakdownTypeApi = (typeof BreakdownTypeApi)[keyof typeof BreakdownTypeApi]

export const BreakdownTypeApi = {
    Cohort: 'cohort',
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Group: 'group',
    Session: 'session',
    Hogql: 'hogql',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
    RevenueAnalytics: 'revenue_analytics',
} as const

export type MultipleBreakdownTypeApi = (typeof MultipleBreakdownTypeApi)[keyof typeof MultipleBreakdownTypeApi]

export const MultipleBreakdownTypeApi = {
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Group: 'group',
    Session: 'session',
    Hogql: 'hogql',
    Cohort: 'cohort',
    RevenueAnalytics: 'revenue_analytics',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
} as const

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

export const PropertyOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Gte: 'gte',
    Lt: 'lt',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
    Between: 'between',
    NotBetween: 'not_between',
    Min: 'min',
    Max: 'max',
    In: 'in',
    NotIn: 'not_in',
    IsCleanedPathExact: 'is_cleaned_path_exact',
    FlagEvaluatesTo: 'flag_evaluates_to',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null

export const EmptyPropertyFilterApiValue = {
    type: 'empty',
} as const
export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

export const LogPropertyFilterTypeApi = {
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
} as const

export type SpanPropertyFilterTypeApi = (typeof SpanPropertyFilterTypeApi)[keyof typeof SpanPropertyFilterTypeApi]

export const SpanPropertyFilterTypeApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export type EndpointRefreshModeApi = (typeof EndpointRefreshModeApi)[keyof typeof EndpointRefreshModeApi]

export const EndpointRefreshModeApi = {
    Cache: 'cache',
    Force: 'force',
    Direct: 'direct',
} as const

export interface PaginatedEndpointVersionResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EndpointVersionResponseApi[]
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

export type EndpointsLogsRetrieveParams = {
    /**
     * Only return entries after this ISO 8601 timestamp.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}

export type EndpointsOpenapiSpecRetrieveParams = {
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
