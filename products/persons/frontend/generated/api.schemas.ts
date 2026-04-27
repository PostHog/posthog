/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type PropertyGroupOperatorApi = (typeof PropertyGroupOperatorApi)[keyof typeof PropertyGroupOperatorApi]

export const PropertyGroupOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `icontains` - icontains
 * `not_icontains` - not_icontains
 * `regex` - regex
 * `not_regex` - not_regex
 * `gt` - gt
 * `lt` - lt
 * `gte` - gte
 * `lte` - lte
 * `is_set` - is_set
 * `is_not_set` - is_not_set
 * `is_date_exact` - is_date_exact
 * `is_date_after` - is_date_after
 * `is_date_before` - is_date_before
 * `in` - in
 * `not_in` - not_in
 */
export type PropertyItemOperatorEnumApi = (typeof PropertyItemOperatorEnumApi)[keyof typeof PropertyItemOperatorEnumApi]

export const PropertyItemOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Lt: 'lt',
    Gte: 'gte',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateAfter: 'is_date_after',
    IsDateBefore: 'is_date_before',
    In: 'in',
    NotIn: 'not_in',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * * `event` - event
 * `event_metadata` - event_metadata
 * `feature` - feature
 * `person` - person
 * `cohort` - cohort
 * `element` - element
 * `static-cohort` - static-cohort
 * `dynamic-cohort` - dynamic-cohort
 * `precalculated-cohort` - precalculated-cohort
 * `group` - group
 * `recording` - recording
 * `log_entry` - log_entry
 * `behavioral` - behavioral
 * `session` - session
 * `hogql` - hogql
 * `data_warehouse` - data_warehouse
 * `data_warehouse_person_property` - data_warehouse_person_property
 * `error_tracking_issue` - error_tracking_issue
 * `log` - log
 * `log_attribute` - log_attribute
 * `log_resource_attribute` - log_resource_attribute
 * `span` - span
 * `span_attribute` - span_attribute
 * `span_resource_attribute` - span_resource_attribute
 * `revenue_analytics` - revenue_analytics
 * `flag` - flag
 * `workflow_variable` - workflow_variable
 */
export type PropertyFilterTypeEnumApi = (typeof PropertyFilterTypeEnumApi)[keyof typeof PropertyFilterTypeEnumApi]

export const PropertyFilterTypeEnumApi = {
    Event: 'event',
    EventMetadata: 'event_metadata',
    Feature: 'feature',
    Person: 'person',
    Cohort: 'cohort',
    Element: 'element',
    StaticCohort: 'static-cohort',
    DynamicCohort: 'dynamic-cohort',
    PrecalculatedCohort: 'precalculated-cohort',
    Group: 'group',
    Recording: 'recording',
    LogEntry: 'log_entry',
    Behavioral: 'behavioral',
    Session: 'session',
    Hogql: 'hogql',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
    ErrorTrackingIssue: 'error_tracking_issue',
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
    RevenueAnalytics: 'revenue_analytics',
    Flag: 'flag',
    WorkflowVariable: 'workflow_variable',
} as const

export interface PropertyItemApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url` */
    key: string
    /** Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]` */
    value: string | number | boolean | (string | number)[]
    operator?: PropertyItemOperatorEnumApi | BlankEnumApi | NullEnumApi | null
    type?: PropertyFilterTypeEnumApi | BlankEnumApi
}

export interface PropertyApi {
    /**
 You can use a simplified version:
```json
{
    "properties": [
        {
            "key": "email",
            "value": "x@y.com",
            "operator": "exact",
            "type": "event"
        }
    ]
}
```

Or you can create more complicated queries with AND and OR:
```json
{
    "properties": {
        "type": "AND",
        "values": [
            {
                "type": "OR",
                "values": [
                    {"key": "email", ...},
                    {"key": "email", ...}
                ]
            },
            {
                "type": "AND",
                "values": [
                    {"key": "email", ...},
                    {"key": "email", ...}
                ]
            }
        ]
    ]
}
```


* `AND` - AND
* `OR` - OR */
    type?: PropertyGroupOperatorApi
    values: PropertyItemApi[]
}

export interface PersonRecordApi {
    /** Numeric person ID. */
    readonly id: number
    /** Display name derived from person properties (email, name, or username). */
    readonly name: string
    readonly distinct_ids: readonly string[]
    /** Key-value map of person properties set via $set and $set_once operations. */
    properties?: unknown
    /** When this person was first seen (ISO 8601). */
    readonly created_at: string
    /** Unique identifier (UUID) for this person. */
    readonly uuid: string
    /**
     * Timestamp of the last event from this person, or null.
     * @nullable
     */
    readonly last_seen_at: string | null
}

export interface PaginatedPersonRecordListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    count?: number
    results?: PersonRecordApi[]
}

export interface PatchedPersonRecordApi {
    /** Numeric person ID. */
    readonly id?: number
    /** Display name derived from person properties (email, name, or username). */
    readonly name?: string
    readonly distinct_ids?: readonly string[]
    /** Key-value map of person properties set via $set and $set_once operations. */
    properties?: unknown
    /** When this person was first seen (ISO 8601). */
    readonly created_at?: string
    /** Unique identifier (UUID) for this person. */
    readonly uuid?: string
    /**
     * Timestamp of the last event from this person, or null.
     * @nullable
     */
    readonly last_seen_at?: string | null
}

export interface PersonDeletePropertyRequestApi {
    /** The property key to remove from this person. */
    $unset: string
}

export interface PersonUpdatePropertyRequestApi {
    /** The property key to set. */
    key: string
    /** The property value. Can be a string, number, boolean, or object. */
    value: unknown
}

export interface PersonBulkDeleteRequestApi {
    /** A list of PostHog person UUIDs to delete (max 1000). */
    ids?: string[]
    /** A list of distinct IDs whose associated persons will be deleted (max 1000). */
    distinct_ids?: string[]
    /** If true, queue deletion of all events associated with these persons. */
    delete_events?: boolean
    /** If true, queue deletion of all recordings associated with these persons. */
    delete_recordings?: boolean
    /** If true, keep the person records but delete their events and recordings. */
    keep_person?: boolean
}

export type PersonBulkDeleteResponseApiDeletionErrorsItem = { [key: string]: unknown }

export interface PersonBulkDeleteResponseApi {
    /** Number of persons matched by the provided IDs or distinct IDs. */
    persons_found: number
    /** Number of person records deleted from the database. 0 if keep_person was true. */
    persons_deleted: number
    /** Whether event deletion was requested for the matched persons. If a deletion was already queued for a person, it will not be duplicated. */
    events_queued_for_deletion: boolean
    /** Whether recording deletion was requested for the matched persons. If a deletion was already queued for a person, it will not be duplicated. */
    recordings_queued_for_deletion: boolean
    /** Persons that could not be deleted. Each entry contains 'person_uuid'. Contact support if this persists. */
    deletion_errors?: PersonBulkDeleteResponseApiDeletionErrorsItem[]
}

export interface AsyncDeletionStatusApi {
    /** The UUID of the person whose events are queued for deletion. */
    person_uuid: string
    /** When the deletion was requested. */
    created_at: string
    /** Current status: 'pending' or 'completed'. */
    readonly status: string
    /**
     * When the deletion was verified complete. Null if still pending.
     * @nullable
     */
    delete_verified_at: string | null
}

export interface PaginatedAsyncDeletionStatusListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    count?: number
    results?: AsyncDeletionStatusApi[]
}

/**
 * Person properties as they existed at the specified time
 */
export type PersonPropertiesAtTimeResponseApiProperties = { [key: string]: string | null }

/**
 * Serializer for the point-in-time query metadata.
 */
export interface PersonPropertiesAtTimeMetadataApi {
    /** The timestamp that was queried in ISO format */
    queried_timestamp: string
    /** Whether $set_once operations were included */
    include_set_once: boolean
    /**
     * The distinct_id parameter used in the request
     * @nullable
     */
    distinct_id_used: string | null
    /**
     * The person_id parameter used in the request
     * @nullable
     */
    person_id_used: string | null
    /** Whether the query used 'distinct_id' or 'person_id' mode */
    query_mode: string
    /** All distinct_ids that were queried for this person */
    distinct_ids_queried: string[]
    /** Number of distinct_ids associated with this person */
    distinct_ids_count: number
}

/**
 * Serializer for the point-in-time person properties response.
 */
export interface PersonPropertiesAtTimeResponseApi {
    /** The person ID */
    id: number
    /** The person's display name */
    name: string
    /** All distinct IDs associated with this person */
    distinct_ids: string[]
    /** Person properties as they existed at the specified time */
    properties: PersonPropertiesAtTimeResponseApiProperties
    /** When the person was first created */
    created_at: string
    /** The person's UUID */
    uuid: string
    /**
     * When the person was last seen
     * @nullable
     */
    last_seen_at: string | null
    /** Metadata about the point-in-time query */
    point_in_time_metadata: PersonPropertiesAtTimeMetadataApi
}

export type PersonsListParams = {
    /**
     * Filter list by distinct id.
     */
    distinct_id?: string
    /**
     * Filter persons by email (exact match)
     */
    email?: string
    format?: PersonsListFormat
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter Persons by person properties.
     */
    properties?: PropertyApi[]
    /**
     * Search persons, either by email (full text search) or distinct_id (exact match).
     */
    search?: string
}

export type PersonsListFormat = (typeof PersonsListFormat)[keyof typeof PersonsListFormat]

export const PersonsListFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsRetrieveParams = {
    format?: PersonsRetrieveFormat
}

export type PersonsRetrieveFormat = (typeof PersonsRetrieveFormat)[keyof typeof PersonsRetrieveFormat]

export const PersonsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsUpdateParams = {
    format?: PersonsUpdateFormat
}

export type PersonsUpdateFormat = (typeof PersonsUpdateFormat)[keyof typeof PersonsUpdateFormat]

export const PersonsUpdateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsPartialUpdateParams = {
    format?: PersonsPartialUpdateFormat
}

export type PersonsPartialUpdateFormat = (typeof PersonsPartialUpdateFormat)[keyof typeof PersonsPartialUpdateFormat]

export const PersonsPartialUpdateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsActivityRetrieveParams = {
    format?: PersonsActivityRetrieveFormat
}

export type PersonsActivityRetrieveFormat =
    (typeof PersonsActivityRetrieveFormat)[keyof typeof PersonsActivityRetrieveFormat]

export const PersonsActivityRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsDeletePropertyCreateParams = {
    format?: PersonsDeletePropertyCreateFormat
}

export type PersonsDeletePropertyCreateFormat =
    (typeof PersonsDeletePropertyCreateFormat)[keyof typeof PersonsDeletePropertyCreateFormat]

export const PersonsDeletePropertyCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsPropertiesTimelineRetrieveParams = {
    format?: PersonsPropertiesTimelineRetrieveFormat
}

export type PersonsPropertiesTimelineRetrieveFormat =
    (typeof PersonsPropertiesTimelineRetrieveFormat)[keyof typeof PersonsPropertiesTimelineRetrieveFormat]

export const PersonsPropertiesTimelineRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsSplitCreateParams = {
    format?: PersonsSplitCreateFormat
}

export type PersonsSplitCreateFormat = (typeof PersonsSplitCreateFormat)[keyof typeof PersonsSplitCreateFormat]

export const PersonsSplitCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsUpdatePropertyCreateParams = {
    format?: PersonsUpdatePropertyCreateFormat
}

export type PersonsUpdatePropertyCreateFormat =
    (typeof PersonsUpdatePropertyCreateFormat)[keyof typeof PersonsUpdatePropertyCreateFormat]

export const PersonsUpdatePropertyCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsAllActivityRetrieveParams = {
    format?: PersonsAllActivityRetrieveFormat
}

export type PersonsAllActivityRetrieveFormat =
    (typeof PersonsAllActivityRetrieveFormat)[keyof typeof PersonsAllActivityRetrieveFormat]

export const PersonsAllActivityRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsBatchByDistinctIdsCreateParams = {
    format?: PersonsBatchByDistinctIdsCreateFormat
}

export type PersonsBatchByDistinctIdsCreateFormat =
    (typeof PersonsBatchByDistinctIdsCreateFormat)[keyof typeof PersonsBatchByDistinctIdsCreateFormat]

export const PersonsBatchByDistinctIdsCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsBatchByUuidsCreateParams = {
    format?: PersonsBatchByUuidsCreateFormat
}

export type PersonsBatchByUuidsCreateFormat =
    (typeof PersonsBatchByUuidsCreateFormat)[keyof typeof PersonsBatchByUuidsCreateFormat]

export const PersonsBatchByUuidsCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsBulkDeleteCreateParams = {
    format?: PersonsBulkDeleteCreateFormat
}

export type PersonsBulkDeleteCreateFormat =
    (typeof PersonsBulkDeleteCreateFormat)[keyof typeof PersonsBulkDeleteCreateFormat]

export const PersonsBulkDeleteCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsCohortsRetrieveParams = {
    format?: PersonsCohortsRetrieveFormat
    /**
     * The person ID or UUID to get cohorts for.
     */
    person_id: string
}

export type PersonsCohortsRetrieveFormat =
    (typeof PersonsCohortsRetrieveFormat)[keyof typeof PersonsCohortsRetrieveFormat]

export const PersonsCohortsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsDeletionStatusListParams = {
    format?: PersonsDeletionStatusListFormat
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by a specific person UUID.
     */
    person_uuid?: string
    /**
     * Filter by deletion status: 'pending', 'completed', or 'all'.
     */
    status?: PersonsDeletionStatusListStatus
}

export type PersonsDeletionStatusListFormat =
    (typeof PersonsDeletionStatusListFormat)[keyof typeof PersonsDeletionStatusListFormat]

export const PersonsDeletionStatusListFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsDeletionStatusListStatus =
    (typeof PersonsDeletionStatusListStatus)[keyof typeof PersonsDeletionStatusListStatus]

export const PersonsDeletionStatusListStatus = {
    All: 'all',
    Completed: 'completed',
    Pending: 'pending',
} as const

export type PersonsFunnelRetrieveParams = {
    format?: PersonsFunnelRetrieveFormat
}

export type PersonsFunnelRetrieveFormat = (typeof PersonsFunnelRetrieveFormat)[keyof typeof PersonsFunnelRetrieveFormat]

export const PersonsFunnelRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsFunnelCreateParams = {
    format?: PersonsFunnelCreateFormat
}

export type PersonsFunnelCreateFormat = (typeof PersonsFunnelCreateFormat)[keyof typeof PersonsFunnelCreateFormat]

export const PersonsFunnelCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsFunnelCorrelationRetrieveParams = {
    format?: PersonsFunnelCorrelationRetrieveFormat
}

export type PersonsFunnelCorrelationRetrieveFormat =
    (typeof PersonsFunnelCorrelationRetrieveFormat)[keyof typeof PersonsFunnelCorrelationRetrieveFormat]

export const PersonsFunnelCorrelationRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsFunnelCorrelationCreateParams = {
    format?: PersonsFunnelCorrelationCreateFormat
}

export type PersonsFunnelCorrelationCreateFormat =
    (typeof PersonsFunnelCorrelationCreateFormat)[keyof typeof PersonsFunnelCorrelationCreateFormat]

export const PersonsFunnelCorrelationCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsLifecycleRetrieveParams = {
    format?: PersonsLifecycleRetrieveFormat
}

export type PersonsLifecycleRetrieveFormat =
    (typeof PersonsLifecycleRetrieveFormat)[keyof typeof PersonsLifecycleRetrieveFormat]

export const PersonsLifecycleRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsPropertiesAtTimeRetrieveParams = {
    /**
     * The distinct_id of the person (mutually exclusive with person_id)
     */
    distinct_id?: string
    format?: PersonsPropertiesAtTimeRetrieveFormat
    /**
     * Whether to handle $set_once operations (default: false)
     */
    include_set_once?: boolean
    /**
     * The person_id (UUID) to build properties for (mutually exclusive with distinct_id)
     */
    person_id?: string
    /**
     * ISO datetime string for the point in time (e.g., '2023-06-15T14:30:00Z')
     */
    timestamp: string
}

export type PersonsPropertiesAtTimeRetrieveFormat =
    (typeof PersonsPropertiesAtTimeRetrieveFormat)[keyof typeof PersonsPropertiesAtTimeRetrieveFormat]

export const PersonsPropertiesAtTimeRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsResetPersonDistinctIdCreateParams = {
    format?: PersonsResetPersonDistinctIdCreateFormat
}

export type PersonsResetPersonDistinctIdCreateFormat =
    (typeof PersonsResetPersonDistinctIdCreateFormat)[keyof typeof PersonsResetPersonDistinctIdCreateFormat]

export const PersonsResetPersonDistinctIdCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsTrendsRetrieveParams = {
    format?: PersonsTrendsRetrieveFormat
}

export type PersonsTrendsRetrieveFormat = (typeof PersonsTrendsRetrieveFormat)[keyof typeof PersonsTrendsRetrieveFormat]

export const PersonsTrendsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsValuesRetrieveParams = {
    format?: PersonsValuesRetrieveFormat
    /**
     * The person property key to get values for (e.g., 'email', 'plan', 'role').
     */
    key: string
    /**
     * Optional search string to filter values (case-insensitive substring match).
     */
    value?: string
}

export type PersonsValuesRetrieveFormat = (typeof PersonsValuesRetrieveFormat)[keyof typeof PersonsValuesRetrieveFormat]

export const PersonsValuesRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const
