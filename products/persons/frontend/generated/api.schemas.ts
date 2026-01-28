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

export type PersonsList2Params = {
    /**
     * Filter list by distinct id.
     */
    distinct_id?: string
    /**
     * Filter persons by email (exact match)
     */
    email?: string
    format?: PersonsList2Format
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

export type PersonsList2Format = (typeof PersonsList2Format)[keyof typeof PersonsList2Format]

export const PersonsList2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsRetrieve2Params = {
    format?: PersonsRetrieve2Format
}

export type PersonsRetrieve2Format = (typeof PersonsRetrieve2Format)[keyof typeof PersonsRetrieve2Format]

export const PersonsRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsUpdate2Params = {
    format?: PersonsUpdate2Format
}

export type PersonsUpdate2Format = (typeof PersonsUpdate2Format)[keyof typeof PersonsUpdate2Format]

export const PersonsUpdate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsPartialUpdate2Params = {
    format?: PersonsPartialUpdate2Format
}

export type PersonsPartialUpdate2Format = (typeof PersonsPartialUpdate2Format)[keyof typeof PersonsPartialUpdate2Format]

export const PersonsPartialUpdate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsActivityRetrieve4Params = {
    format?: PersonsActivityRetrieve4Format
}

export type PersonsActivityRetrieve4Format =
    (typeof PersonsActivityRetrieve4Format)[keyof typeof PersonsActivityRetrieve4Format]

export const PersonsActivityRetrieve4Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsDeletePropertyCreate2Params = {
    /**
     * Specify the property key to delete
     */
    $unset: string
    format?: PersonsDeletePropertyCreate2Format
}

export type PersonsDeletePropertyCreate2Format =
    (typeof PersonsDeletePropertyCreate2Format)[keyof typeof PersonsDeletePropertyCreate2Format]

export const PersonsDeletePropertyCreate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsPropertiesTimelineRetrieve2Params = {
    format?: PersonsPropertiesTimelineRetrieve2Format
}

export type PersonsPropertiesTimelineRetrieve2Format =
    (typeof PersonsPropertiesTimelineRetrieve2Format)[keyof typeof PersonsPropertiesTimelineRetrieve2Format]

export const PersonsPropertiesTimelineRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsSplitCreate2Params = {
    format?: PersonsSplitCreate2Format
}

export type PersonsSplitCreate2Format = (typeof PersonsSplitCreate2Format)[keyof typeof PersonsSplitCreate2Format]

export const PersonsSplitCreate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsUpdatePropertyCreate2Params = {
    format?: PersonsUpdatePropertyCreate2Format
    /**
     * Specify the property key
     */
    key: string
    /**
     * Specify the property value
     */
    value: unknown
}

export type PersonsUpdatePropertyCreate2Format =
    (typeof PersonsUpdatePropertyCreate2Format)[keyof typeof PersonsUpdatePropertyCreate2Format]

export const PersonsUpdatePropertyCreate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsActivityRetrieve3Params = {
    format?: PersonsActivityRetrieve3Format
}

export type PersonsActivityRetrieve3Format =
    (typeof PersonsActivityRetrieve3Format)[keyof typeof PersonsActivityRetrieve3Format]

export const PersonsActivityRetrieve3Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsBulkDeleteCreate2Params = {
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
    format?: PersonsBulkDeleteCreate2Format
    /**
     * A list of PostHog person IDs, up to 1000 of them. We'll delete all the persons listed.
     */
    ids?: { [key: string]: unknown }
    /**
     * If true, the person record itself will not be deleted. This is useful if you want to keep the person record for auditing purposes but remove events and recordings associated with them
     */
    keep_person?: boolean
}

export type PersonsBulkDeleteCreate2Format =
    (typeof PersonsBulkDeleteCreate2Format)[keyof typeof PersonsBulkDeleteCreate2Format]

export const PersonsBulkDeleteCreate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsCohortsRetrieve2Params = {
    format?: PersonsCohortsRetrieve2Format
}

export type PersonsCohortsRetrieve2Format =
    (typeof PersonsCohortsRetrieve2Format)[keyof typeof PersonsCohortsRetrieve2Format]

export const PersonsCohortsRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelRetrieve2Params = {
    format?: PersonsFunnelRetrieve2Format
}

export type PersonsFunnelRetrieve2Format =
    (typeof PersonsFunnelRetrieve2Format)[keyof typeof PersonsFunnelRetrieve2Format]

export const PersonsFunnelRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCreate2Params = {
    format?: PersonsFunnelCreate2Format
}

export type PersonsFunnelCreate2Format = (typeof PersonsFunnelCreate2Format)[keyof typeof PersonsFunnelCreate2Format]

export const PersonsFunnelCreate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCorrelationRetrieve2Params = {
    format?: PersonsFunnelCorrelationRetrieve2Format
}

export type PersonsFunnelCorrelationRetrieve2Format =
    (typeof PersonsFunnelCorrelationRetrieve2Format)[keyof typeof PersonsFunnelCorrelationRetrieve2Format]

export const PersonsFunnelCorrelationRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCorrelationCreate2Params = {
    format?: PersonsFunnelCorrelationCreate2Format
}

export type PersonsFunnelCorrelationCreate2Format =
    (typeof PersonsFunnelCorrelationCreate2Format)[keyof typeof PersonsFunnelCorrelationCreate2Format]

export const PersonsFunnelCorrelationCreate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsLifecycleRetrieve2Params = {
    format?: PersonsLifecycleRetrieve2Format
}

export type PersonsLifecycleRetrieve2Format =
    (typeof PersonsLifecycleRetrieve2Format)[keyof typeof PersonsLifecycleRetrieve2Format]

export const PersonsLifecycleRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsResetPersonDistinctIdCreate2Params = {
    format?: PersonsResetPersonDistinctIdCreate2Format
}

export type PersonsResetPersonDistinctIdCreate2Format =
    (typeof PersonsResetPersonDistinctIdCreate2Format)[keyof typeof PersonsResetPersonDistinctIdCreate2Format]

export const PersonsResetPersonDistinctIdCreate2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsStickinessRetrieve2Params = {
    format?: PersonsStickinessRetrieve2Format
}

export type PersonsStickinessRetrieve2Format =
    (typeof PersonsStickinessRetrieve2Format)[keyof typeof PersonsStickinessRetrieve2Format]

export const PersonsStickinessRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsTrendsRetrieve2Params = {
    format?: PersonsTrendsRetrieve2Format
}

export type PersonsTrendsRetrieve2Format =
    (typeof PersonsTrendsRetrieve2Format)[keyof typeof PersonsTrendsRetrieve2Format]

export const PersonsTrendsRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsValuesRetrieve2Params = {
    format?: PersonsValuesRetrieve2Format
}

export type PersonsValuesRetrieve2Format =
    (typeof PersonsValuesRetrieve2Format)[keyof typeof PersonsValuesRetrieve2Format]

export const PersonsValuesRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const
