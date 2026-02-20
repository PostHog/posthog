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
 * * `AND` - AND
 * `OR` - OR
 */
export type PropertyTypeEnumApi = (typeof PropertyTypeEnumApi)[keyof typeof PropertyTypeEnumApi]

export const PropertyTypeEnumApi = {
    AND: 'AND',
    OR: 'OR',
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
export type OperatorEnumApi = (typeof OperatorEnumApi)[keyof typeof OperatorEnumApi]

export const OperatorEnumApi = {
    exact: 'exact',
    is_not: 'is_not',
    icontains: 'icontains',
    not_icontains: 'not_icontains',
    regex: 'regex',
    not_regex: 'not_regex',
    gt: 'gt',
    lt: 'lt',
    gte: 'gte',
    lte: 'lte',
    is_set: 'is_set',
    is_not_set: 'is_not_set',
    is_date_exact: 'is_date_exact',
    is_date_after: 'is_date_after',
    is_date_before: 'is_date_before',
    in: 'in',
    not_in: 'not_in',
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
 * `revenue_analytics` - revenue_analytics
 * `flag` - flag
 * `workflow_variable` - workflow_variable
 */
export type PropertyItemTypeEnumApi = (typeof PropertyItemTypeEnumApi)[keyof typeof PropertyItemTypeEnumApi]

export const PropertyItemTypeEnumApi = {
    event: 'event',
    event_metadata: 'event_metadata',
    feature: 'feature',
    person: 'person',
    cohort: 'cohort',
    element: 'element',
    'static-cohort': 'static-cohort',
    'dynamic-cohort': 'dynamic-cohort',
    'precalculated-cohort': 'precalculated-cohort',
    group: 'group',
    recording: 'recording',
    log_entry: 'log_entry',
    behavioral: 'behavioral',
    session: 'session',
    hogql: 'hogql',
    data_warehouse: 'data_warehouse',
    data_warehouse_person_property: 'data_warehouse_person_property',
    error_tracking_issue: 'error_tracking_issue',
    log: 'log',
    log_attribute: 'log_attribute',
    log_resource_attribute: 'log_resource_attribute',
    revenue_analytics: 'revenue_analytics',
    flag: 'flag',
    workflow_variable: 'workflow_variable',
} as const

export interface PropertyItemApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url` */
    key: string
    /** Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]` */
    value: string
    operator?: OperatorEnumApi | BlankEnumApi | NullEnumApi | null
    type?: PropertyItemTypeEnumApi | BlankEnumApi
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
    type?: PropertyTypeEnumApi
    values: PropertyItemApi[]
}

export interface PersonApi {
    readonly id: number
    readonly name: string
    readonly distinct_ids: readonly string[]
    properties?: unknown
    readonly created_at: string
    readonly uuid: string
    /** @nullable */
    readonly last_seen_at: string | null
}

export interface PaginatedPersonListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    count?: number
    results?: PersonApi[]
}

export interface PatchedPersonApi {
    readonly id?: number
    readonly name?: string
    readonly distinct_ids?: readonly string[]
    properties?: unknown
    readonly created_at?: string
    readonly uuid?: string
    /** @nullable */
    readonly last_seen_at?: string | null
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
    csv: 'csv',
    json: 'json',
} as const

export type PersonsRetrieveParams = {
    format?: PersonsRetrieveFormat
}

export type PersonsRetrieveFormat = (typeof PersonsRetrieveFormat)[keyof typeof PersonsRetrieveFormat]

export const PersonsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsUpdateParams = {
    format?: PersonsUpdateFormat
}

export type PersonsUpdateFormat = (typeof PersonsUpdateFormat)[keyof typeof PersonsUpdateFormat]

export const PersonsUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsPartialUpdateParams = {
    format?: PersonsPartialUpdateFormat
}

export type PersonsPartialUpdateFormat = (typeof PersonsPartialUpdateFormat)[keyof typeof PersonsPartialUpdateFormat]

export const PersonsPartialUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsActivityRetrieve2Params = {
    format?: PersonsActivityRetrieve2Format
}

export type PersonsActivityRetrieve2Format =
    (typeof PersonsActivityRetrieve2Format)[keyof typeof PersonsActivityRetrieve2Format]

export const PersonsActivityRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsDeletePropertyCreateParams = {
    /**
     * Specify the property key to delete
     */
    $unset: string
    format?: PersonsDeletePropertyCreateFormat
}

export type PersonsDeletePropertyCreateFormat =
    (typeof PersonsDeletePropertyCreateFormat)[keyof typeof PersonsDeletePropertyCreateFormat]

export const PersonsDeletePropertyCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsPropertiesTimelineRetrieveParams = {
    format?: PersonsPropertiesTimelineRetrieveFormat
}

export type PersonsPropertiesTimelineRetrieveFormat =
    (typeof PersonsPropertiesTimelineRetrieveFormat)[keyof typeof PersonsPropertiesTimelineRetrieveFormat]

export const PersonsPropertiesTimelineRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsSplitCreateParams = {
    format?: PersonsSplitCreateFormat
}

export type PersonsSplitCreateFormat = (typeof PersonsSplitCreateFormat)[keyof typeof PersonsSplitCreateFormat]

export const PersonsSplitCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsUpdatePropertyCreateParams = {
    format?: PersonsUpdatePropertyCreateFormat
    /**
     * Specify the property key
     */
    key: string
    /**
     * Specify the property value
     */
    value: unknown
}

export type PersonsUpdatePropertyCreateFormat =
    (typeof PersonsUpdatePropertyCreateFormat)[keyof typeof PersonsUpdatePropertyCreateFormat]

export const PersonsUpdatePropertyCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsActivityRetrieveParams = {
    format?: PersonsActivityRetrieveFormat
}

export type PersonsActivityRetrieveFormat =
    (typeof PersonsActivityRetrieveFormat)[keyof typeof PersonsActivityRetrieveFormat]

export const PersonsActivityRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsBatchByDistinctIdsCreateParams = {
    format?: PersonsBatchByDistinctIdsCreateFormat
}

export type PersonsBatchByDistinctIdsCreateFormat =
    (typeof PersonsBatchByDistinctIdsCreateFormat)[keyof typeof PersonsBatchByDistinctIdsCreateFormat]

export const PersonsBatchByDistinctIdsCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsBulkDeleteCreateParams = {
    /**
     * If true, a task to delete all events associated with this person will be created and queued. The task does not run immediately and instead is batched together and at 5AM UTC every Sunday
     */
    delete_events?: boolean
    /**
     * If true, a task to delete all recordings associated with this person will be created and queued. The task does not run immediately and instead is batched together and at 5AM UTC every Sunday
     */
    delete_recordings?: boolean
    /**
     * A list of distinct IDs, up to 1000 of them. We'll delete all persons associated with those distinct IDs.
     */
    distinct_ids?: { [key: string]: unknown }
    format?: PersonsBulkDeleteCreateFormat
    /**
     * A list of PostHog person IDs, up to 1000 of them. We'll delete all the persons listed.
     */
    ids?: { [key: string]: unknown }
    /**
     * If true, the person record itself will not be deleted. This is useful if you want to keep the person record for auditing purposes but remove events and recordings associated with them
     */
    keep_person?: boolean
}

export type PersonsBulkDeleteCreateFormat =
    (typeof PersonsBulkDeleteCreateFormat)[keyof typeof PersonsBulkDeleteCreateFormat]

export const PersonsBulkDeleteCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsCohortsRetrieveParams = {
    format?: PersonsCohortsRetrieveFormat
}

export type PersonsCohortsRetrieveFormat =
    (typeof PersonsCohortsRetrieveFormat)[keyof typeof PersonsCohortsRetrieveFormat]

export const PersonsCohortsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelRetrieveParams = {
    format?: PersonsFunnelRetrieveFormat
}

export type PersonsFunnelRetrieveFormat = (typeof PersonsFunnelRetrieveFormat)[keyof typeof PersonsFunnelRetrieveFormat]

export const PersonsFunnelRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCreateParams = {
    format?: PersonsFunnelCreateFormat
}

export type PersonsFunnelCreateFormat = (typeof PersonsFunnelCreateFormat)[keyof typeof PersonsFunnelCreateFormat]

export const PersonsFunnelCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCorrelationRetrieveParams = {
    format?: PersonsFunnelCorrelationRetrieveFormat
}

export type PersonsFunnelCorrelationRetrieveFormat =
    (typeof PersonsFunnelCorrelationRetrieveFormat)[keyof typeof PersonsFunnelCorrelationRetrieveFormat]

export const PersonsFunnelCorrelationRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCorrelationCreateParams = {
    format?: PersonsFunnelCorrelationCreateFormat
}

export type PersonsFunnelCorrelationCreateFormat =
    (typeof PersonsFunnelCorrelationCreateFormat)[keyof typeof PersonsFunnelCorrelationCreateFormat]

export const PersonsFunnelCorrelationCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsLifecycleRetrieveParams = {
    format?: PersonsLifecycleRetrieveFormat
}

export type PersonsLifecycleRetrieveFormat =
    (typeof PersonsLifecycleRetrieveFormat)[keyof typeof PersonsLifecycleRetrieveFormat]

export const PersonsLifecycleRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsResetPersonDistinctIdCreateParams = {
    format?: PersonsResetPersonDistinctIdCreateFormat
}

export type PersonsResetPersonDistinctIdCreateFormat =
    (typeof PersonsResetPersonDistinctIdCreateFormat)[keyof typeof PersonsResetPersonDistinctIdCreateFormat]

export const PersonsResetPersonDistinctIdCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsStickinessRetrieveParams = {
    format?: PersonsStickinessRetrieveFormat
}

export type PersonsStickinessRetrieveFormat =
    (typeof PersonsStickinessRetrieveFormat)[keyof typeof PersonsStickinessRetrieveFormat]

export const PersonsStickinessRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsTrendsRetrieveParams = {
    format?: PersonsTrendsRetrieveFormat
}

export type PersonsTrendsRetrieveFormat = (typeof PersonsTrendsRetrieveFormat)[keyof typeof PersonsTrendsRetrieveFormat]

export const PersonsTrendsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsValuesRetrieveParams = {
    format?: PersonsValuesRetrieveFormat
}

export type PersonsValuesRetrieveFormat = (typeof PersonsValuesRetrieveFormat)[keyof typeof PersonsValuesRetrieveFormat]

export const PersonsValuesRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const
