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

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

export type PropertyItemApiOperator = OperatorEnumApi | BlankEnumApi | NullEnumApi

export type PropertyItemApiType = PropertyItemTypeEnumApi | BlankEnumApi

export interface PropertyItemApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url` */
    key: string
    /** Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]` */
    value: string
    operator?: PropertyItemApiOperator
    type?: PropertyItemApiType
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

export type EnvironmentsPersonsListParams = {
    /**
     * Filter list by distinct id.
     */
    distinct_id?: string
    /**
     * Filter persons by email (exact match)
     */
    email?: string
    format?: EnvironmentsPersonsListFormat
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

export type EnvironmentsPersonsListFormat =
    (typeof EnvironmentsPersonsListFormat)[keyof typeof EnvironmentsPersonsListFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsListFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsRetrieveParams = {
    format?: EnvironmentsPersonsRetrieveFormat
}

export type EnvironmentsPersonsRetrieveFormat =
    (typeof EnvironmentsPersonsRetrieveFormat)[keyof typeof EnvironmentsPersonsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsUpdateParams = {
    format?: EnvironmentsPersonsUpdateFormat
}

export type EnvironmentsPersonsUpdateFormat =
    (typeof EnvironmentsPersonsUpdateFormat)[keyof typeof EnvironmentsPersonsUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsPartialUpdateParams = {
    format?: EnvironmentsPersonsPartialUpdateFormat
}

export type EnvironmentsPersonsPartialUpdateFormat =
    (typeof EnvironmentsPersonsPartialUpdateFormat)[keyof typeof EnvironmentsPersonsPartialUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsPartialUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsActivityRetrieve2Params = {
    format?: EnvironmentsPersonsActivityRetrieve2Format
}

export type EnvironmentsPersonsActivityRetrieve2Format =
    (typeof EnvironmentsPersonsActivityRetrieve2Format)[keyof typeof EnvironmentsPersonsActivityRetrieve2Format]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsActivityRetrieve2Format = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsDeletePropertyCreateParams = {
    /**
     * Specify the property key to delete
     */
    $unset: string
    format?: EnvironmentsPersonsDeletePropertyCreateFormat
}

export type EnvironmentsPersonsDeletePropertyCreateFormat =
    (typeof EnvironmentsPersonsDeletePropertyCreateFormat)[keyof typeof EnvironmentsPersonsDeletePropertyCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsDeletePropertyCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsPropertiesTimelineRetrieveParams = {
    format?: EnvironmentsPersonsPropertiesTimelineRetrieveFormat
}

export type EnvironmentsPersonsPropertiesTimelineRetrieveFormat =
    (typeof EnvironmentsPersonsPropertiesTimelineRetrieveFormat)[keyof typeof EnvironmentsPersonsPropertiesTimelineRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsPropertiesTimelineRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsSplitCreateParams = {
    format?: EnvironmentsPersonsSplitCreateFormat
}

export type EnvironmentsPersonsSplitCreateFormat =
    (typeof EnvironmentsPersonsSplitCreateFormat)[keyof typeof EnvironmentsPersonsSplitCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsSplitCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsUpdatePropertyCreateParams = {
    format?: EnvironmentsPersonsUpdatePropertyCreateFormat
    /**
     * Specify the property key
     */
    key: string
    /**
     * Specify the property value
     */
    value: unknown
}

export type EnvironmentsPersonsUpdatePropertyCreateFormat =
    (typeof EnvironmentsPersonsUpdatePropertyCreateFormat)[keyof typeof EnvironmentsPersonsUpdatePropertyCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsUpdatePropertyCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsActivityRetrieveParams = {
    format?: EnvironmentsPersonsActivityRetrieveFormat
}

export type EnvironmentsPersonsActivityRetrieveFormat =
    (typeof EnvironmentsPersonsActivityRetrieveFormat)[keyof typeof EnvironmentsPersonsActivityRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsActivityRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsBulkDeleteCreateParams = {
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
    format?: EnvironmentsPersonsBulkDeleteCreateFormat
    /**
     * A list of PostHog person IDs, up to 1000 of them. We'll delete all the persons listed.
     */
    ids?: { [key: string]: unknown }
    /**
     * If true, the person record itself will not be deleted. This is useful if you want to keep the person record for auditing purposes but remove events and recordings associated with them
     */
    keep_person?: boolean
}

export type EnvironmentsPersonsBulkDeleteCreateFormat =
    (typeof EnvironmentsPersonsBulkDeleteCreateFormat)[keyof typeof EnvironmentsPersonsBulkDeleteCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsBulkDeleteCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsCohortsRetrieveParams = {
    format?: EnvironmentsPersonsCohortsRetrieveFormat
}

export type EnvironmentsPersonsCohortsRetrieveFormat =
    (typeof EnvironmentsPersonsCohortsRetrieveFormat)[keyof typeof EnvironmentsPersonsCohortsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsCohortsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsFunnelRetrieveParams = {
    format?: EnvironmentsPersonsFunnelRetrieveFormat
}

export type EnvironmentsPersonsFunnelRetrieveFormat =
    (typeof EnvironmentsPersonsFunnelRetrieveFormat)[keyof typeof EnvironmentsPersonsFunnelRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsFunnelRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsFunnelCreateParams = {
    format?: EnvironmentsPersonsFunnelCreateFormat
}

export type EnvironmentsPersonsFunnelCreateFormat =
    (typeof EnvironmentsPersonsFunnelCreateFormat)[keyof typeof EnvironmentsPersonsFunnelCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsFunnelCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsFunnelCorrelationRetrieveParams = {
    format?: EnvironmentsPersonsFunnelCorrelationRetrieveFormat
}

export type EnvironmentsPersonsFunnelCorrelationRetrieveFormat =
    (typeof EnvironmentsPersonsFunnelCorrelationRetrieveFormat)[keyof typeof EnvironmentsPersonsFunnelCorrelationRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsFunnelCorrelationRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsFunnelCorrelationCreateParams = {
    format?: EnvironmentsPersonsFunnelCorrelationCreateFormat
}

export type EnvironmentsPersonsFunnelCorrelationCreateFormat =
    (typeof EnvironmentsPersonsFunnelCorrelationCreateFormat)[keyof typeof EnvironmentsPersonsFunnelCorrelationCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsFunnelCorrelationCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsLifecycleRetrieveParams = {
    format?: EnvironmentsPersonsLifecycleRetrieveFormat
}

export type EnvironmentsPersonsLifecycleRetrieveFormat =
    (typeof EnvironmentsPersonsLifecycleRetrieveFormat)[keyof typeof EnvironmentsPersonsLifecycleRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsLifecycleRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsResetPersonDistinctIdCreateParams = {
    format?: EnvironmentsPersonsResetPersonDistinctIdCreateFormat
}

export type EnvironmentsPersonsResetPersonDistinctIdCreateFormat =
    (typeof EnvironmentsPersonsResetPersonDistinctIdCreateFormat)[keyof typeof EnvironmentsPersonsResetPersonDistinctIdCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsResetPersonDistinctIdCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsStickinessRetrieveParams = {
    format?: EnvironmentsPersonsStickinessRetrieveFormat
}

export type EnvironmentsPersonsStickinessRetrieveFormat =
    (typeof EnvironmentsPersonsStickinessRetrieveFormat)[keyof typeof EnvironmentsPersonsStickinessRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsStickinessRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsTrendsRetrieveParams = {
    format?: EnvironmentsPersonsTrendsRetrieveFormat
}

export type EnvironmentsPersonsTrendsRetrieveFormat =
    (typeof EnvironmentsPersonsTrendsRetrieveFormat)[keyof typeof EnvironmentsPersonsTrendsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsTrendsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type EnvironmentsPersonsValuesRetrieveParams = {
    format?: EnvironmentsPersonsValuesRetrieveFormat
}

export type EnvironmentsPersonsValuesRetrieveFormat =
    (typeof EnvironmentsPersonsValuesRetrieveFormat)[keyof typeof EnvironmentsPersonsValuesRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsPersonsValuesRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsListFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsRetrieveParams = {
    format?: PersonsRetrieveFormat
}

export type PersonsRetrieveFormat = (typeof PersonsRetrieveFormat)[keyof typeof PersonsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsUpdateParams = {
    format?: PersonsUpdateFormat
}

export type PersonsUpdateFormat = (typeof PersonsUpdateFormat)[keyof typeof PersonsUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsPartialUpdateParams = {
    format?: PersonsPartialUpdateFormat
}

export type PersonsPartialUpdateFormat = (typeof PersonsPartialUpdateFormat)[keyof typeof PersonsPartialUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsPartialUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsActivityRetrieve2Params = {
    format?: PersonsActivityRetrieve2Format
}

export type PersonsActivityRetrieve2Format =
    (typeof PersonsActivityRetrieve2Format)[keyof typeof PersonsActivityRetrieve2Format]

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsDeletePropertyCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsPropertiesTimelineRetrieveParams = {
    format?: PersonsPropertiesTimelineRetrieveFormat
}

export type PersonsPropertiesTimelineRetrieveFormat =
    (typeof PersonsPropertiesTimelineRetrieveFormat)[keyof typeof PersonsPropertiesTimelineRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsPropertiesTimelineRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsSplitCreateParams = {
    format?: PersonsSplitCreateFormat
}

export type PersonsSplitCreateFormat = (typeof PersonsSplitCreateFormat)[keyof typeof PersonsSplitCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsUpdatePropertyCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsActivityRetrieveParams = {
    format?: PersonsActivityRetrieveFormat
}

export type PersonsActivityRetrieveFormat =
    (typeof PersonsActivityRetrieveFormat)[keyof typeof PersonsActivityRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsBulkDeleteCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsCohortsRetrieveParams = {
    format?: PersonsCohortsRetrieveFormat
}

export type PersonsCohortsRetrieveFormat =
    (typeof PersonsCohortsRetrieveFormat)[keyof typeof PersonsCohortsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsCohortsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelRetrieveParams = {
    format?: PersonsFunnelRetrieveFormat
}

export type PersonsFunnelRetrieveFormat = (typeof PersonsFunnelRetrieveFormat)[keyof typeof PersonsFunnelRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsFunnelRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCreateParams = {
    format?: PersonsFunnelCreateFormat
}

export type PersonsFunnelCreateFormat = (typeof PersonsFunnelCreateFormat)[keyof typeof PersonsFunnelCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsFunnelCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCorrelationRetrieveParams = {
    format?: PersonsFunnelCorrelationRetrieveFormat
}

export type PersonsFunnelCorrelationRetrieveFormat =
    (typeof PersonsFunnelCorrelationRetrieveFormat)[keyof typeof PersonsFunnelCorrelationRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsFunnelCorrelationRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsFunnelCorrelationCreateParams = {
    format?: PersonsFunnelCorrelationCreateFormat
}

export type PersonsFunnelCorrelationCreateFormat =
    (typeof PersonsFunnelCorrelationCreateFormat)[keyof typeof PersonsFunnelCorrelationCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsFunnelCorrelationCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsLifecycleRetrieveParams = {
    format?: PersonsLifecycleRetrieveFormat
}

export type PersonsLifecycleRetrieveFormat =
    (typeof PersonsLifecycleRetrieveFormat)[keyof typeof PersonsLifecycleRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsLifecycleRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsResetPersonDistinctIdCreateParams = {
    format?: PersonsResetPersonDistinctIdCreateFormat
}

export type PersonsResetPersonDistinctIdCreateFormat =
    (typeof PersonsResetPersonDistinctIdCreateFormat)[keyof typeof PersonsResetPersonDistinctIdCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsResetPersonDistinctIdCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsStickinessRetrieveParams = {
    format?: PersonsStickinessRetrieveFormat
}

export type PersonsStickinessRetrieveFormat =
    (typeof PersonsStickinessRetrieveFormat)[keyof typeof PersonsStickinessRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsStickinessRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsTrendsRetrieveParams = {
    format?: PersonsTrendsRetrieveFormat
}

export type PersonsTrendsRetrieveFormat = (typeof PersonsTrendsRetrieveFormat)[keyof typeof PersonsTrendsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsTrendsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type PersonsValuesRetrieveParams = {
    format?: PersonsValuesRetrieveFormat
}

export type PersonsValuesRetrieveFormat = (typeof PersonsValuesRetrieveFormat)[keyof typeof PersonsValuesRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsValuesRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const
