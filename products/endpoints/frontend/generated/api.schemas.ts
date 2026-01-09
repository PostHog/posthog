/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface DateRangeApi {
    /** @nullable */
    date_from?: string | null
    /** @nullable */
    date_to?: string | null
    /**
     * Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.
     * @nullable
     */
    explicitDate?: boolean | null
}

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PropertyOperatorApi = {
    exact: 'exact',
    is_not: 'is_not',
    icontains: 'icontains',
    not_icontains: 'not_icontains',
    regex: 'regex',
    not_regex: 'not_regex',
    gt: 'gt',
    gte: 'gte',
    lt: 'lt',
    lte: 'lte',
    is_set: 'is_set',
    is_not_set: 'is_not_set',
    is_date_exact: 'is_date_exact',
    is_date_before: 'is_date_before',
    is_date_after: 'is_date_after',
    between: 'between',
    not_between: 'not_between',
    min: 'min',
    max: 'max',
    in: 'in',
    not_in: 'not_in',
    is_cleaned_path_exact: 'is_cleaned_path_exact',
    flag_evaluates_to: 'flag_evaluates_to',
} as const

/**
 * Event properties
 */
export type EventPropertyFilterApiType = (typeof EventPropertyFilterApiType)[keyof typeof EventPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EventPropertyFilterApiType = {
    event: 'event',
} as const

export type EventPropertyFilterApiValueAnyOfItem = string | number | boolean

export type EventPropertyFilterApiValue = EventPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface EventPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator?: PropertyOperatorApi
    /** Event properties */
    type?: EventPropertyFilterApiType
    value?: EventPropertyFilterApiValue
}

/**
 * Person properties
 */
export type PersonPropertyFilterApiType = (typeof PersonPropertyFilterApiType)[keyof typeof PersonPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonPropertyFilterApiType = {
    person: 'person',
} as const

export type PersonPropertyFilterApiValueAnyOfItem = string | number | boolean

export type PersonPropertyFilterApiValue = PersonPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface PersonPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: PersonPropertyFilterApiType
    value?: PersonPropertyFilterApiValue
}

export type KeyApi = (typeof KeyApi)[keyof typeof KeyApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const KeyApi = {
    tag_name: 'tag_name',
    text: 'text',
    href: 'href',
    selector: 'selector',
} as const

export type ElementPropertyFilterApiType =
    (typeof ElementPropertyFilterApiType)[keyof typeof ElementPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ElementPropertyFilterApiType = {
    element: 'element',
} as const

export type ElementPropertyFilterApiValueAnyOfItem = string | number | boolean

export type ElementPropertyFilterApiValue = ElementPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface ElementPropertyFilterApi {
    key: KeyApi
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: ElementPropertyFilterApiType
    value?: ElementPropertyFilterApiValue
}

export type EventMetadataPropertyFilterApiType =
    (typeof EventMetadataPropertyFilterApiType)[keyof typeof EventMetadataPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EventMetadataPropertyFilterApiType = {
    event_metadata: 'event_metadata',
} as const

export type EventMetadataPropertyFilterApiValueAnyOfItem = string | number | boolean

export type EventMetadataPropertyFilterApiValue =
    | EventMetadataPropertyFilterApiValueAnyOfItem[]
    | string
    | number
    | boolean

export interface EventMetadataPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: EventMetadataPropertyFilterApiType
    value?: EventMetadataPropertyFilterApiValue
}

export type SessionPropertyFilterApiType =
    (typeof SessionPropertyFilterApiType)[keyof typeof SessionPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SessionPropertyFilterApiType = {
    session: 'session',
} as const

export type SessionPropertyFilterApiValueAnyOfItem = string | number | boolean

export type SessionPropertyFilterApiValue = SessionPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface SessionPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: SessionPropertyFilterApiType
    value?: SessionPropertyFilterApiValue
}

export type CohortPropertyFilterApiKey = (typeof CohortPropertyFilterApiKey)[keyof typeof CohortPropertyFilterApiKey]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CohortPropertyFilterApiKey = {
    id: 'id',
} as const

export type CohortPropertyFilterApiType = (typeof CohortPropertyFilterApiType)[keyof typeof CohortPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CohortPropertyFilterApiType = {
    cohort: 'cohort',
} as const

export interface CohortPropertyFilterApi {
    /** @nullable */
    cohort_name?: string | null
    key?: CohortPropertyFilterApiKey
    /** @nullable */
    label?: string | null
    operator?: PropertyOperatorApi
    type?: CohortPropertyFilterApiType
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DurationTypeApi = {
    duration: 'duration',
    active_seconds: 'active_seconds',
    inactive_seconds: 'inactive_seconds',
} as const

export type RecordingPropertyFilterApiKey = DurationTypeApi | string

export type RecordingPropertyFilterApiType =
    (typeof RecordingPropertyFilterApiType)[keyof typeof RecordingPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RecordingPropertyFilterApiType = {
    recording: 'recording',
} as const

export type RecordingPropertyFilterApiValueAnyOfItem = string | number | boolean

export type RecordingPropertyFilterApiValue = RecordingPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface RecordingPropertyFilterApi {
    key: RecordingPropertyFilterApiKey
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: RecordingPropertyFilterApiType
    value?: RecordingPropertyFilterApiValue
}

export type LogEntryPropertyFilterApiType =
    (typeof LogEntryPropertyFilterApiType)[keyof typeof LogEntryPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const LogEntryPropertyFilterApiType = {
    log_entry: 'log_entry',
} as const

export type LogEntryPropertyFilterApiValueAnyOfItem = string | number | boolean

export type LogEntryPropertyFilterApiValue = LogEntryPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface LogEntryPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: LogEntryPropertyFilterApiType
    value?: LogEntryPropertyFilterApiValue
}

export type GroupPropertyFilterApiType = (typeof GroupPropertyFilterApiType)[keyof typeof GroupPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const GroupPropertyFilterApiType = {
    group: 'group',
} as const

export type GroupPropertyFilterApiValueAnyOfItem = string | number | boolean

export type GroupPropertyFilterApiValue = GroupPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface GroupPropertyFilterApi {
    /** @nullable */
    group_type_index?: number | null
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: GroupPropertyFilterApiType
    value?: GroupPropertyFilterApiValue
}

/**
 * Event property with "$feature/" prepended
 */
export type FeaturePropertyFilterApiType =
    (typeof FeaturePropertyFilterApiType)[keyof typeof FeaturePropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FeaturePropertyFilterApiType = {
    feature: 'feature',
} as const

export type FeaturePropertyFilterApiValueAnyOfItem = string | number | boolean

export type FeaturePropertyFilterApiValue = FeaturePropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface FeaturePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: FeaturePropertyFilterApiType
    value?: FeaturePropertyFilterApiValue
}

/**
 * Only flag_evaluates_to operator is allowed for flag dependencies
 */
export type FlagPropertyFilterApiOperator =
    (typeof FlagPropertyFilterApiOperator)[keyof typeof FlagPropertyFilterApiOperator]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FlagPropertyFilterApiOperator = {
    flag_evaluates_to: 'flag_evaluates_to',
} as const

/**
 * Feature flag dependency
 */
export type FlagPropertyFilterApiType = (typeof FlagPropertyFilterApiType)[keyof typeof FlagPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FlagPropertyFilterApiType = {
    flag: 'flag',
} as const

/**
 * The value can be true, false, or a variant name
 */
export type FlagPropertyFilterApiValue = boolean | string

export interface FlagPropertyFilterApi {
    /** The key should be the flag ID */
    key: string
    /** @nullable */
    label?: string | null
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator?: FlagPropertyFilterApiOperator
    /** Feature flag dependency */
    type?: FlagPropertyFilterApiType
    /** The value can be true, false, or a variant name */
    value: FlagPropertyFilterApiValue
}

export type HogQLPropertyFilterApiType = (typeof HogQLPropertyFilterApiType)[keyof typeof HogQLPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const HogQLPropertyFilterApiType = {
    hogql: 'hogql',
} as const

export type HogQLPropertyFilterApiValueAnyOfItem = string | number | boolean

export type HogQLPropertyFilterApiValue = HogQLPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface HogQLPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    type?: HogQLPropertyFilterApiType
    value?: HogQLPropertyFilterApiValue
}

export type EmptyPropertyFilterApiType = (typeof EmptyPropertyFilterApiType)[keyof typeof EmptyPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EmptyPropertyFilterApiType = {
    empty: 'empty',
} as const

export interface EmptyPropertyFilterApi {
    type?: EmptyPropertyFilterApiType
}

export type DataWarehousePropertyFilterApiType =
    (typeof DataWarehousePropertyFilterApiType)[keyof typeof DataWarehousePropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DataWarehousePropertyFilterApiType = {
    data_warehouse: 'data_warehouse',
} as const

export type DataWarehousePropertyFilterApiValueAnyOfItem = string | number | boolean

export type DataWarehousePropertyFilterApiValue =
    | DataWarehousePropertyFilterApiValueAnyOfItem[]
    | string
    | number
    | boolean

export interface DataWarehousePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: DataWarehousePropertyFilterApiType
    value?: DataWarehousePropertyFilterApiValue
}

export type DataWarehousePersonPropertyFilterApiType =
    (typeof DataWarehousePersonPropertyFilterApiType)[keyof typeof DataWarehousePersonPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DataWarehousePersonPropertyFilterApiType = {
    data_warehouse_person_property: 'data_warehouse_person_property',
} as const

export type DataWarehousePersonPropertyFilterApiValueAnyOfItem = string | number | boolean

export type DataWarehousePersonPropertyFilterApiValue =
    | DataWarehousePersonPropertyFilterApiValueAnyOfItem[]
    | string
    | number
    | boolean

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: DataWarehousePersonPropertyFilterApiType
    value?: DataWarehousePersonPropertyFilterApiValue
}

export type ErrorTrackingIssueFilterApiType =
    (typeof ErrorTrackingIssueFilterApiType)[keyof typeof ErrorTrackingIssueFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ErrorTrackingIssueFilterApiType = {
    error_tracking_issue: 'error_tracking_issue',
} as const

export type ErrorTrackingIssueFilterApiValueAnyOfItem = string | number | boolean

export type ErrorTrackingIssueFilterApiValue = ErrorTrackingIssueFilterApiValueAnyOfItem[] | string | number | boolean

export interface ErrorTrackingIssueFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: ErrorTrackingIssueFilterApiType
    value?: ErrorTrackingIssueFilterApiValue
}

export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const LogPropertyFilterTypeApi = {
    log: 'log',
    log_attribute: 'log_attribute',
    log_resource_attribute: 'log_resource_attribute',
} as const

export type LogPropertyFilterApiValueAnyOfItem = string | number | boolean

export type LogPropertyFilterApiValue = LogPropertyFilterApiValueAnyOfItem[] | string | number | boolean

export interface LogPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type: LogPropertyFilterTypeApi
    value?: LogPropertyFilterApiValue
}

export type RevenueAnalyticsPropertyFilterApiType =
    (typeof RevenueAnalyticsPropertyFilterApiType)[keyof typeof RevenueAnalyticsPropertyFilterApiType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RevenueAnalyticsPropertyFilterApiType = {
    revenue_analytics: 'revenue_analytics',
} as const

export type RevenueAnalyticsPropertyFilterApiValueAnyOfItem = string | number | boolean

export type RevenueAnalyticsPropertyFilterApiValue =
    | RevenueAnalyticsPropertyFilterApiValueAnyOfItem[]
    | string
    | number
    | boolean

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: RevenueAnalyticsPropertyFilterApiType
    value?: RevenueAnalyticsPropertyFilterApiValue
}

export type HogQLFiltersApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export interface HogQLFiltersApi {
    dateRange?: DateRangeApi
    /** @nullable */
    filterTestAccounts?: boolean | null
    /** @nullable */
    properties?: HogQLFiltersApiPropertiesItem[] | null
}

export type BounceRatePageViewModeApi = (typeof BounceRatePageViewModeApi)[keyof typeof BounceRatePageViewModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BounceRatePageViewModeApi = {
    count_pageviews: 'count_pageviews',
    uniq_urls: 'uniq_urls',
    uniq_page_screen_autocaptures: 'uniq_page_screen_autocaptures',
} as const

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FilterLogicalOperatorApi = {
    AND: 'AND',
    OR: 'OR',
} as const

export type CustomChannelFieldApi = (typeof CustomChannelFieldApi)[keyof typeof CustomChannelFieldApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CustomChannelFieldApi = {
    utm_source: 'utm_source',
    utm_medium: 'utm_medium',
    utm_campaign: 'utm_campaign',
    referring_domain: 'referring_domain',
    url: 'url',
    pathname: 'pathname',
    hostname: 'hostname',
} as const

export type CustomChannelOperatorApi = (typeof CustomChannelOperatorApi)[keyof typeof CustomChannelOperatorApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CustomChannelOperatorApi = {
    exact: 'exact',
    is_not: 'is_not',
    is_set: 'is_set',
    is_not_set: 'is_not_set',
    icontains: 'icontains',
    not_icontains: 'not_icontains',
    regex: 'regex',
    not_regex: 'not_regex',
} as const

export type CustomChannelConditionApiValue = string | string[]

export interface CustomChannelConditionApi {
    id: string
    key: CustomChannelFieldApi
    op: CustomChannelOperatorApi
    value?: CustomChannelConditionApiValue
}

export interface CustomChannelRuleApi {
    channel_type: string
    combiner: FilterLogicalOperatorApi
    id: string
    items: CustomChannelConditionApi[]
}

export interface DataWarehouseEventsModifierApi {
    distinct_id_field: string
    id_field: string
    table_name: string
    timestamp_field: string
}

export type InCohortViaApi = (typeof InCohortViaApi)[keyof typeof InCohortViaApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const InCohortViaApi = {
    auto: 'auto',
    leftjoin: 'leftjoin',
    subquery: 'subquery',
    leftjoin_conjoined: 'leftjoin_conjoined',
} as const

export type MaterializationModeApi = (typeof MaterializationModeApi)[keyof typeof MaterializationModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MaterializationModeApi = {
    auto: 'auto',
    legacy_null_as_string: 'legacy_null_as_string',
    legacy_null_as_null: 'legacy_null_as_null',
    disabled: 'disabled',
} as const

export type MaterializedColumnsOptimizationModeApi =
    (typeof MaterializedColumnsOptimizationModeApi)[keyof typeof MaterializedColumnsOptimizationModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MaterializedColumnsOptimizationModeApi = {
    disabled: 'disabled',
    optimized: 'optimized',
} as const

export type PersonsArgMaxVersionApi = (typeof PersonsArgMaxVersionApi)[keyof typeof PersonsArgMaxVersionApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsArgMaxVersionApi = {
    auto: 'auto',
    v1: 'v1',
    v2: 'v2',
} as const

export type PersonsJoinModeApi = (typeof PersonsJoinModeApi)[keyof typeof PersonsJoinModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsJoinModeApi = {
    inner: 'inner',
    left: 'left',
} as const

export type PersonsOnEventsModeApi = (typeof PersonsOnEventsModeApi)[keyof typeof PersonsOnEventsModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PersonsOnEventsModeApi = {
    disabled: 'disabled',
    person_id_no_override_properties_on_events: 'person_id_no_override_properties_on_events',
    person_id_override_properties_on_events: 'person_id_override_properties_on_events',
    person_id_override_properties_joined: 'person_id_override_properties_joined',
} as const

export type PropertyGroupsModeApi = (typeof PropertyGroupsModeApi)[keyof typeof PropertyGroupsModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PropertyGroupsModeApi = {
    enabled: 'enabled',
    disabled: 'disabled',
    optimized: 'optimized',
} as const

export type SessionTableVersionApi = (typeof SessionTableVersionApi)[keyof typeof SessionTableVersionApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SessionTableVersionApi = {
    auto: 'auto',
    v1: 'v1',
    v2: 'v2',
    v3: 'v3',
} as const

export type SessionsV2JoinModeApi = (typeof SessionsV2JoinModeApi)[keyof typeof SessionsV2JoinModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SessionsV2JoinModeApi = {
    string: 'string',
    uuid: 'uuid',
} as const

export interface HogQLQueryModifiersApi {
    /** @nullable */
    bounceRateDurationSeconds?: number | null
    bounceRatePageViewMode?: BounceRatePageViewModeApi
    /** @nullable */
    convertToProjectTimezone?: boolean | null
    /** @nullable */
    customChannelTypeRules?: CustomChannelRuleApi[] | null
    /** @nullable */
    dataWarehouseEventsModifiers?: DataWarehouseEventsModifierApi[] | null
    /** @nullable */
    debug?: boolean | null
    /** @nullable */
    formatCsvAllowDoubleQuotes?: boolean | null
    inCohortVia?: InCohortViaApi
    materializationMode?: MaterializationModeApi
    materializedColumnsOptimizationMode?: MaterializedColumnsOptimizationModeApi
    /** @nullable */
    optimizeJoinedFilters?: boolean | null
    /** @nullable */
    optimizeProjections?: boolean | null
    personsArgMaxVersion?: PersonsArgMaxVersionApi
    personsJoinMode?: PersonsJoinModeApi
    personsOnEventsMode?: PersonsOnEventsModeApi
    propertyGroupsMode?: PropertyGroupsModeApi
    /** @nullable */
    s3TableUseInvalidColumns?: boolean | null
    sessionTableVersion?: SessionTableVersionApi
    sessionsV2JoinMode?: SessionsV2JoinModeApi
    /** @nullable */
    timings?: boolean | null
    /** @nullable */
    useMaterializedViews?: boolean | null
    /** @nullable */
    usePreaggregatedIntermediateResults?: boolean | null
    /**
     * Try to automatically convert HogQL queries to use preaggregated tables at the AST level *
     * @nullable
     */
    usePreaggregatedTableTransforms?: boolean | null
    /** @nullable */
    usePresortedEventsTable?: boolean | null
    /** @nullable */
    useWebAnalyticsPreAggregatedTables?: boolean | null
}

export interface HogQLNoticeApi {
    /** @nullable */
    end?: number | null
    /** @nullable */
    fix?: string | null
    message: string
    /** @nullable */
    start?: number | null
}

export type QueryIndexUsageApi = (typeof QueryIndexUsageApi)[keyof typeof QueryIndexUsageApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const QueryIndexUsageApi = {
    undecisive: 'undecisive',
    no: 'no',
    partial: 'partial',
    yes: 'yes',
} as const

export interface HogQLMetadataResponseApi {
    /** @nullable */
    ch_table_names?: string[] | null
    errors: HogQLNoticeApi[]
    isUsingIndices?: QueryIndexUsageApi
    /** @nullable */
    isValid?: boolean | null
    notices: HogQLNoticeApi[]
    /** @nullable */
    query?: string | null
    /** @nullable */
    table_names?: string[] | null
    warnings: HogQLNoticeApi[]
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
    query_progress?: ClickhouseQueryProgressApi
    results?: unknown
    /**
     * When was query execution task enqueued.
     * @nullable
     */
    start_time?: string | null
    /** @nullable */
    task_id?: string | null
    team_id: number
}

export interface ResolvedDateRangeResponseApi {
    date_from: string
    date_to: string
}

export interface QueryTimingApi {
    /** Key. Shortened to 'k' to save on data. */
    k: string
    /** Time in seconds. Shortened to 't' to save on data. */
    t: number
}

export interface HogQLQueryResponseApi {
    /**
     * Executed ClickHouse query
     * @nullable
     */
    clickhouse?: string | null
    /**
     * Returned columns
     * @nullable
     */
    columns?: unknown[] | null
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Query explanation output
     * @nullable
     */
    explain?: string[] | null
    /** @nullable */
    hasMore?: boolean | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** @nullable */
    limit?: number | null
    /** Query metadata output */
    metadata?: HogQLMetadataResponseApi
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** @nullable */
    offset?: number | null
    /**
     * Input query string
     * @nullable
     */
    query?: string | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: unknown[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /**
     * Types of returned columns
     * @nullable
     */
    types?: unknown[] | null
}

export interface QueryLogTagsApi {
    /**
     * Name of the query, preferably unique. For example web_analytics_vitals
     * @nullable
     */
    name?: string | null
    /**
     * Product responsible for this query. Use string, there's no need to churn the Schema when we add a new product *
     * @nullable
     */
    productKey?: string | null
    /**
     * Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a new Scene *
     * @nullable
     */
    scene?: string | null
}

export interface HogQLVariableApi {
    code_name: string
    /** @nullable */
    isNull?: boolean | null
    value?: unknown
    variableId: string
}

export type HogQLQueryApiKind = (typeof HogQLQueryApiKind)[keyof typeof HogQLQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const HogQLQueryApiKind = {
    HogQLQuery: 'HogQLQuery',
} as const

/**
 * Constant values that can be referenced with the {placeholder} syntax in the query
 */
export type HogQLQueryApiValuesAnyOf = { [key: string]: unknown }

/**
 * Constant values that can be referenced with the {placeholder} syntax in the query
 * @nullable
 */
export type HogQLQueryApiValues = HogQLQueryApiValuesAnyOf | null | null

/**
 * Variables to be substituted into the query
 */
export type HogQLQueryApiVariablesAnyOf = { [key: string]: HogQLVariableApi }

/**
 * Variables to be substituted into the query
 * @nullable
 */
export type HogQLQueryApiVariables = HogQLQueryApiVariablesAnyOf | null | null

export interface HogQLQueryApi {
    /** @nullable */
    explain?: boolean | null
    filters?: HogQLFiltersApi
    kind?: HogQLQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /**
     * Client provided name of the query
     * @nullable
     */
    name?: string | null
    query: string
    response?: HogQLQueryResponseApi
    tags?: QueryLogTagsApi
    /**
     * Constant values that can be referenced with the {placeholder} syntax in the query
     * @nullable
     */
    values?: HogQLQueryApiValues
    /**
     * Variables to be substituted into the query
     * @nullable
     */
    variables?: HogQLQueryApiVariables
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type BreakdownTypeApi = (typeof BreakdownTypeApi)[keyof typeof BreakdownTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BreakdownTypeApi = {
    cohort: 'cohort',
    person: 'person',
    event: 'event',
    event_metadata: 'event_metadata',
    group: 'group',
    session: 'session',
    hogql: 'hogql',
    data_warehouse: 'data_warehouse',
    data_warehouse_person_property: 'data_warehouse_person_property',
    revenue_analytics: 'revenue_analytics',
} as const

export type MultipleBreakdownTypeApi = (typeof MultipleBreakdownTypeApi)[keyof typeof MultipleBreakdownTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MultipleBreakdownTypeApi = {
    cohort: 'cohort',
    person: 'person',
    event: 'event',
    event_metadata: 'event_metadata',
    group: 'group',
    session: 'session',
    hogql: 'hogql',
    revenue_analytics: 'revenue_analytics',
} as const

export type BreakdownApiProperty = string | number

export interface BreakdownApi {
    /** @nullable */
    group_type_index?: number | null
    /** @nullable */
    histogram_bin_count?: number | null
    /** @nullable */
    normalize_url?: boolean | null
    property: BreakdownApiProperty
    type?: MultipleBreakdownTypeApi
}

export type BreakdownFilterApiBreakdownAnyOfItem = string | number

export type BreakdownFilterApiBreakdown = string | BreakdownFilterApiBreakdownAnyOfItem[] | number

export interface BreakdownFilterApi {
    breakdown?: BreakdownFilterApiBreakdown
    /** @nullable */
    breakdown_group_type_index?: number | null
    /** @nullable */
    breakdown_hide_other_aggregation?: boolean | null
    /** @nullable */
    breakdown_histogram_bin_count?: number | null
    /** @nullable */
    breakdown_limit?: number | null
    /** @nullable */
    breakdown_normalize_url?: boolean | null
    /** @nullable */
    breakdown_path_cleaning?: boolean | null
    breakdown_type?: BreakdownTypeApi
    /**
     * @maxItems 3
     * @nullable
     */
    breakdowns?: BreakdownApi[] | null
}

export interface CompareFilterApi {
    /**
     * Whether to compare the current date range to a previous date range.
     * @nullable
     */
    compare?: boolean | null
    /**
     * The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago.
     * @nullable
     */
    compare_to?: string | null
}

export interface ActionConversionGoalApi {
    actionId: number
}

export interface CustomEventConversionGoalApi {
    customEventName: string
}

export type IntervalTypeApi = (typeof IntervalTypeApi)[keyof typeof IntervalTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const IntervalTypeApi = {
    second: 'second',
    minute: 'minute',
    hour: 'hour',
    day: 'day',
    week: 'week',
    month: 'month',
} as const

export type PropertyGroupFilterValueApiValuesItem =
    | PropertyGroupFilterValueApi
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export interface PropertyGroupFilterValueApi {
    type: FilterLogicalOperatorApi
    values: PropertyGroupFilterValueApiValuesItem[]
}

export interface PropertyGroupFilterApi {
    type: FilterLogicalOperatorApi
    values: PropertyGroupFilterValueApi[]
}

export type TrendsQueryResponseApiResultsItem = { [key: string]: unknown }

export interface TrendsQueryResponseApi {
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Wether more breakdown values are available.
     * @nullable
     */
    hasMore?: boolean | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: TrendsQueryResponseApiResultsItem[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type BaseMathTypeApi = (typeof BaseMathTypeApi)[keyof typeof BaseMathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BaseMathTypeApi = {
    total: 'total',
    dau: 'dau',
    weekly_active: 'weekly_active',
    monthly_active: 'monthly_active',
    unique_session: 'unique_session',
    first_time_for_user: 'first_time_for_user',
    first_matching_event_for_user: 'first_matching_event_for_user',
} as const

export type FunnelMathTypeApi = (typeof FunnelMathTypeApi)[keyof typeof FunnelMathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelMathTypeApi = {
    total: 'total',
    first_time_for_user: 'first_time_for_user',
    first_time_for_user_with_filters: 'first_time_for_user_with_filters',
} as const

export type PropertyMathTypeApi = (typeof PropertyMathTypeApi)[keyof typeof PropertyMathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PropertyMathTypeApi = {
    avg: 'avg',
    sum: 'sum',
    min: 'min',
    max: 'max',
    median: 'median',
    p75: 'p75',
    p90: 'p90',
    p95: 'p95',
    p99: 'p99',
} as const

export type CountPerActorMathTypeApi = (typeof CountPerActorMathTypeApi)[keyof typeof CountPerActorMathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CountPerActorMathTypeApi = {
    avg_count_per_actor: 'avg_count_per_actor',
    min_count_per_actor: 'min_count_per_actor',
    max_count_per_actor: 'max_count_per_actor',
    median_count_per_actor: 'median_count_per_actor',
    p75_count_per_actor: 'p75_count_per_actor',
    p90_count_per_actor: 'p90_count_per_actor',
    p95_count_per_actor: 'p95_count_per_actor',
    p99_count_per_actor: 'p99_count_per_actor',
} as const

export type ExperimentMetricMathTypeApi = (typeof ExperimentMetricMathTypeApi)[keyof typeof ExperimentMetricMathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ExperimentMetricMathTypeApi = {
    total: 'total',
    sum: 'sum',
    unique_session: 'unique_session',
    min: 'min',
    max: 'max',
    avg: 'avg',
    dau: 'dau',
    unique_group: 'unique_group',
    hogql: 'hogql',
} as const

export type CalendarHeatmapMathTypeApi = (typeof CalendarHeatmapMathTypeApi)[keyof typeof CalendarHeatmapMathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CalendarHeatmapMathTypeApi = {
    total: 'total',
    dau: 'dau',
} as const

export type MathGroupTypeIndexApi = (typeof MathGroupTypeIndexApi)[keyof typeof MathGroupTypeIndexApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MathGroupTypeIndexApi = {
    NUMBER_0: 0,
    NUMBER_1: 1,
    NUMBER_2: 2,
    NUMBER_3: 3,
    NUMBER_4: 4,
} as const

export type CurrencyCodeApi = (typeof CurrencyCodeApi)[keyof typeof CurrencyCodeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CurrencyCodeApi = {
    AED: 'AED',
    AFN: 'AFN',
    ALL: 'ALL',
    AMD: 'AMD',
    ANG: 'ANG',
    AOA: 'AOA',
    ARS: 'ARS',
    AUD: 'AUD',
    AWG: 'AWG',
    AZN: 'AZN',
    BAM: 'BAM',
    BBD: 'BBD',
    BDT: 'BDT',
    BGN: 'BGN',
    BHD: 'BHD',
    BIF: 'BIF',
    BMD: 'BMD',
    BND: 'BND',
    BOB: 'BOB',
    BRL: 'BRL',
    BSD: 'BSD',
    BTC: 'BTC',
    BTN: 'BTN',
    BWP: 'BWP',
    BYN: 'BYN',
    BZD: 'BZD',
    CAD: 'CAD',
    CDF: 'CDF',
    CHF: 'CHF',
    CLP: 'CLP',
    CNY: 'CNY',
    COP: 'COP',
    CRC: 'CRC',
    CVE: 'CVE',
    CZK: 'CZK',
    DJF: 'DJF',
    DKK: 'DKK',
    DOP: 'DOP',
    DZD: 'DZD',
    EGP: 'EGP',
    ERN: 'ERN',
    ETB: 'ETB',
    EUR: 'EUR',
    FJD: 'FJD',
    GBP: 'GBP',
    GEL: 'GEL',
    GHS: 'GHS',
    GIP: 'GIP',
    GMD: 'GMD',
    GNF: 'GNF',
    GTQ: 'GTQ',
    GYD: 'GYD',
    HKD: 'HKD',
    HNL: 'HNL',
    HRK: 'HRK',
    HTG: 'HTG',
    HUF: 'HUF',
    IDR: 'IDR',
    ILS: 'ILS',
    INR: 'INR',
    IQD: 'IQD',
    IRR: 'IRR',
    ISK: 'ISK',
    JMD: 'JMD',
    JOD: 'JOD',
    JPY: 'JPY',
    KES: 'KES',
    KGS: 'KGS',
    KHR: 'KHR',
    KMF: 'KMF',
    KRW: 'KRW',
    KWD: 'KWD',
    KYD: 'KYD',
    KZT: 'KZT',
    LAK: 'LAK',
    LBP: 'LBP',
    LKR: 'LKR',
    LRD: 'LRD',
    LTL: 'LTL',
    LVL: 'LVL',
    LSL: 'LSL',
    LYD: 'LYD',
    MAD: 'MAD',
    MDL: 'MDL',
    MGA: 'MGA',
    MKD: 'MKD',
    MMK: 'MMK',
    MNT: 'MNT',
    MOP: 'MOP',
    MRU: 'MRU',
    MTL: 'MTL',
    MUR: 'MUR',
    MVR: 'MVR',
    MWK: 'MWK',
    MXN: 'MXN',
    MYR: 'MYR',
    MZN: 'MZN',
    NAD: 'NAD',
    NGN: 'NGN',
    NIO: 'NIO',
    NOK: 'NOK',
    NPR: 'NPR',
    NZD: 'NZD',
    OMR: 'OMR',
    PAB: 'PAB',
    PEN: 'PEN',
    PGK: 'PGK',
    PHP: 'PHP',
    PKR: 'PKR',
    PLN: 'PLN',
    PYG: 'PYG',
    QAR: 'QAR',
    RON: 'RON',
    RSD: 'RSD',
    RUB: 'RUB',
    RWF: 'RWF',
    SAR: 'SAR',
    SBD: 'SBD',
    SCR: 'SCR',
    SDG: 'SDG',
    SEK: 'SEK',
    SGD: 'SGD',
    SRD: 'SRD',
    SSP: 'SSP',
    STN: 'STN',
    SYP: 'SYP',
    SZL: 'SZL',
    THB: 'THB',
    TJS: 'TJS',
    TMT: 'TMT',
    TND: 'TND',
    TOP: 'TOP',
    TRY: 'TRY',
    TTD: 'TTD',
    TWD: 'TWD',
    TZS: 'TZS',
    UAH: 'UAH',
    UGX: 'UGX',
    USD: 'USD',
    UYU: 'UYU',
    UZS: 'UZS',
    VES: 'VES',
    VND: 'VND',
    VUV: 'VUV',
    WST: 'WST',
    XAF: 'XAF',
    XCD: 'XCD',
    XOF: 'XOF',
    XPF: 'XPF',
    YER: 'YER',
    ZAR: 'ZAR',
    ZMW: 'ZMW',
} as const

export interface RevenueCurrencyPropertyConfigApi {
    /** @nullable */
    property?: string | null
    static?: CurrencyCodeApi
}

export type EventsNodeApiFixedPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type EventsNodeApiKind = (typeof EventsNodeApiKind)[keyof typeof EventsNodeApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EventsNodeApiKind = {
    EventsNode: 'EventsNode',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EventsNodeApiMath = {
    ...BaseMathTypeApi,
    ...FunnelMathTypeApi,
    ...PropertyMathTypeApi,
    ...CountPerActorMathTypeApi,
    ...ExperimentMetricMathTypeApi,
    ...CalendarHeatmapMathTypeApi,
    unique_group: 'unique_group',
    hogql: 'hogql',
} as const
export type EventsNodeApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type EventsNodeApiResponseAnyOf = { [key: string]: unknown }

/**
 * @nullable
 */
export type EventsNodeApiResponse = EventsNodeApiResponseAnyOf | null | null

export interface EventsNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * The event or `null` for all events.
     * @nullable
     */
    event?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?: EventsNodeApiFixedPropertiesItem[] | null
    kind?: EventsNodeApiKind
    /** @nullable */
    limit?: number | null
    math?: (typeof EventsNodeApiMath)[keyof typeof EventsNodeApiMath]
    math_group_type_index?: MathGroupTypeIndexApi
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi
    /** @nullable */
    math_property_type?: string | null
    /** @nullable */
    name?: string | null
    /** @nullable */
    optionalInFunnel?: boolean | null
    /**
     * Columns to order by
     * @nullable
     */
    orderBy?: string[] | null
    /**
     * Properties configurable in the interface
     * @nullable
     */
    properties?: EventsNodeApiPropertiesItem[] | null
    /** @nullable */
    response?: EventsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ActionsNodeApiFixedPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type ActionsNodeApiKind = (typeof ActionsNodeApiKind)[keyof typeof ActionsNodeApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsNodeApiKind = {
    ActionsNode: 'ActionsNode',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsNodeApiMath = {
    ...BaseMathTypeApi,
    ...FunnelMathTypeApi,
    ...PropertyMathTypeApi,
    ...CountPerActorMathTypeApi,
    ...ExperimentMetricMathTypeApi,
    ...CalendarHeatmapMathTypeApi,
    unique_group: 'unique_group',
    hogql: 'hogql',
} as const
export type ActionsNodeApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type ActionsNodeApiResponseAnyOf = { [key: string]: unknown }

/**
 * @nullable
 */
export type ActionsNodeApiResponse = ActionsNodeApiResponseAnyOf | null | null

export interface ActionsNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?: ActionsNodeApiFixedPropertiesItem[] | null
    id: number
    kind?: ActionsNodeApiKind
    math?: (typeof ActionsNodeApiMath)[keyof typeof ActionsNodeApiMath]
    math_group_type_index?: MathGroupTypeIndexApi
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi
    /** @nullable */
    math_property_type?: string | null
    /** @nullable */
    name?: string | null
    /** @nullable */
    optionalInFunnel?: boolean | null
    /**
     * Properties configurable in the interface
     * @nullable
     */
    properties?: ActionsNodeApiPropertiesItem[] | null
    /** @nullable */
    response?: ActionsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type DataWarehouseNodeApiFixedPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type DataWarehouseNodeApiKind = (typeof DataWarehouseNodeApiKind)[keyof typeof DataWarehouseNodeApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DataWarehouseNodeApiKind = {
    DataWarehouseNode: 'DataWarehouseNode',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DataWarehouseNodeApiMath = {
    ...BaseMathTypeApi,
    ...FunnelMathTypeApi,
    ...PropertyMathTypeApi,
    ...CountPerActorMathTypeApi,
    ...ExperimentMetricMathTypeApi,
    ...CalendarHeatmapMathTypeApi,
    unique_group: 'unique_group',
    hogql: 'hogql',
} as const
export type DataWarehouseNodeApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type DataWarehouseNodeApiResponseAnyOf = { [key: string]: unknown }

/**
 * @nullable
 */
export type DataWarehouseNodeApiResponse = DataWarehouseNodeApiResponseAnyOf | null | null

export interface DataWarehouseNodeApi {
    /** @nullable */
    custom_name?: string | null
    distinct_id_field: string
    /** @nullable */
    dw_source_type?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?: DataWarehouseNodeApiFixedPropertiesItem[] | null
    id: string
    id_field: string
    kind?: DataWarehouseNodeApiKind
    math?: (typeof DataWarehouseNodeApiMath)[keyof typeof DataWarehouseNodeApiMath]
    math_group_type_index?: MathGroupTypeIndexApi
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi
    /** @nullable */
    math_property_type?: string | null
    /** @nullable */
    name?: string | null
    /** @nullable */
    optionalInFunnel?: boolean | null
    /**
     * Properties configurable in the interface
     * @nullable
     */
    properties?: DataWarehouseNodeApiPropertiesItem[] | null
    /** @nullable */
    response?: DataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type GroupNodeApiFixedPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type GroupNodeApiKind = (typeof GroupNodeApiKind)[keyof typeof GroupNodeApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const GroupNodeApiKind = {
    GroupNode: 'GroupNode',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const GroupNodeApiMath = {
    ...BaseMathTypeApi,
    ...FunnelMathTypeApi,
    ...PropertyMathTypeApi,
    ...CountPerActorMathTypeApi,
    ...ExperimentMetricMathTypeApi,
    ...CalendarHeatmapMathTypeApi,
    unique_group: 'unique_group',
    hogql: 'hogql',
} as const
export type GroupNodeApiNodesItem = EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi

export type GroupNodeApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type GroupNodeApiResponseAnyOf = { [key: string]: unknown }

/**
 * @nullable
 */
export type GroupNodeApiResponse = GroupNodeApiResponseAnyOf | null | null

export interface GroupNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?: GroupNodeApiFixedPropertiesItem[] | null
    kind?: GroupNodeApiKind
    /** @nullable */
    limit?: number | null
    math?: (typeof GroupNodeApiMath)[keyof typeof GroupNodeApiMath]
    math_group_type_index?: MathGroupTypeIndexApi
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi
    /** @nullable */
    math_property_type?: string | null
    /** @nullable */
    name?: string | null
    /** Entities to combine in this group */
    nodes: GroupNodeApiNodesItem[]
    /** Group of entities combined with AND/OR operator */
    operator: FilterLogicalOperatorApi
    /** @nullable */
    optionalInFunnel?: boolean | null
    /**
     * Columns to order by
     * @nullable
     */
    orderBy?: string[] | null
    /**
     * Properties configurable in the interface
     * @nullable
     */
    properties?: GroupNodeApiPropertiesItem[] | null
    /** @nullable */
    response?: GroupNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type AggregationAxisFormatApi = (typeof AggregationAxisFormatApi)[keyof typeof AggregationAxisFormatApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const AggregationAxisFormatApi = {
    numeric: 'numeric',
    duration: 'duration',
    duration_ms: 'duration_ms',
    percentage: 'percentage',
    percentage_scaled: 'percentage_scaled',
    currency: 'currency',
} as const

export type DetailedResultsAggregationTypeApi =
    (typeof DetailedResultsAggregationTypeApi)[keyof typeof DetailedResultsAggregationTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DetailedResultsAggregationTypeApi = {
    total: 'total',
    average: 'average',
    median: 'median',
} as const

export type ChartDisplayTypeApi = (typeof ChartDisplayTypeApi)[keyof typeof ChartDisplayTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ChartDisplayTypeApi = {
    ActionsLineGraph: 'ActionsLineGraph',
    ActionsBar: 'ActionsBar',
    ActionsUnstackedBar: 'ActionsUnstackedBar',
    ActionsStackedBar: 'ActionsStackedBar',
    ActionsAreaGraph: 'ActionsAreaGraph',
    ActionsLineGraphCumulative: 'ActionsLineGraphCumulative',
    BoldNumber: 'BoldNumber',
    ActionsPie: 'ActionsPie',
    ActionsBarValue: 'ActionsBarValue',
    ActionsTable: 'ActionsTable',
    WorldMap: 'WorldMap',
    CalendarHeatmap: 'CalendarHeatmap',
} as const

export interface TrendsFormulaNodeApi {
    /**
     * Optional user-defined name for the formula
     * @nullable
     */
    custom_name?: string | null
    formula: string
}

export type PositionApi = (typeof PositionApi)[keyof typeof PositionApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PositionApi = {
    start: 'start',
    end: 'end',
} as const

export interface GoalLineApi {
    /** @nullable */
    borderColor?: string | null
    /** @nullable */
    displayIfCrossed?: boolean | null
    /** @nullable */
    displayLabel?: boolean | null
    label: string
    position?: PositionApi
    value: number
}

export type ResultCustomizationByApi = (typeof ResultCustomizationByApi)[keyof typeof ResultCustomizationByApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ResultCustomizationByApi = {
    value: 'value',
    position: 'position',
} as const

export type DataColorTokenApi = (typeof DataColorTokenApi)[keyof typeof DataColorTokenApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DataColorTokenApi = {
    'preset-1': 'preset-1',
    'preset-2': 'preset-2',
    'preset-3': 'preset-3',
    'preset-4': 'preset-4',
    'preset-5': 'preset-5',
    'preset-6': 'preset-6',
    'preset-7': 'preset-7',
    'preset-8': 'preset-8',
    'preset-9': 'preset-9',
    'preset-10': 'preset-10',
    'preset-11': 'preset-11',
    'preset-12': 'preset-12',
    'preset-13': 'preset-13',
    'preset-14': 'preset-14',
    'preset-15': 'preset-15',
} as const

export type ResultCustomizationByValueApiAssignmentBy =
    (typeof ResultCustomizationByValueApiAssignmentBy)[keyof typeof ResultCustomizationByValueApiAssignmentBy]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ResultCustomizationByValueApiAssignmentBy = {
    value: 'value',
} as const

export interface ResultCustomizationByValueApi {
    assignmentBy?: ResultCustomizationByValueApiAssignmentBy
    color?: DataColorTokenApi
    /** @nullable */
    hidden?: boolean | null
}

export type ResultCustomizationByPositionApiAssignmentBy =
    (typeof ResultCustomizationByPositionApiAssignmentBy)[keyof typeof ResultCustomizationByPositionApiAssignmentBy]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ResultCustomizationByPositionApiAssignmentBy = {
    position: 'position',
} as const

export interface ResultCustomizationByPositionApi {
    assignmentBy?: ResultCustomizationByPositionApiAssignmentBy
    color?: DataColorTokenApi
    /** @nullable */
    hidden?: boolean | null
}

export type YAxisScaleTypeApi = (typeof YAxisScaleTypeApi)[keyof typeof YAxisScaleTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const YAxisScaleTypeApi = {
    log10: 'log10',
    linear: 'linear',
} as const

export type TrendsFilterApiResultCustomizationsAnyOf = { [key: string]: ResultCustomizationByValueApi }

export type TrendsFilterApiResultCustomizationsAnyOfTwo = { [key: string]: ResultCustomizationByPositionApi }

/**
 * Customizations for the appearance of result datasets.
 */
export type TrendsFilterApiResultCustomizations =
    | TrendsFilterApiResultCustomizationsAnyOf
    | TrendsFilterApiResultCustomizationsAnyOfTwo

export interface TrendsFilterApi {
    aggregationAxisFormat?: AggregationAxisFormatApi
    /** @nullable */
    aggregationAxisPostfix?: string | null
    /** @nullable */
    aggregationAxisPrefix?: string | null
    /** @nullable */
    breakdown_histogram_bin_count?: number | null
    /** @nullable */
    confidenceLevel?: number | null
    /** @nullable */
    decimalPlaces?: number | null
    /** detailed results table */
    detailedResultsAggregationType?: DetailedResultsAggregationTypeApi
    display?: ChartDisplayTypeApi
    /** @nullable */
    formula?: string | null
    /**
     * List of formulas with optional custom names. Takes precedence over formula/formulas if set.
     * @nullable
     */
    formulaNodes?: TrendsFormulaNodeApi[] | null
    /** @nullable */
    formulas?: string[] | null
    /**
     * Goal Lines
     * @nullable
     */
    goalLines?: GoalLineApi[] | null
    /** @nullable */
    hiddenLegendIndexes?: number[] | null
    /** @nullable */
    minDecimalPlaces?: number | null
    /** @nullable */
    movingAverageIntervals?: number | null
    /** Wether result datasets are associated by their values or by their order. */
    resultCustomizationBy?: ResultCustomizationByApi
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: TrendsFilterApiResultCustomizations
    /** @nullable */
    showAlertThresholdLines?: boolean | null
    /** @nullable */
    showConfidenceIntervals?: boolean | null
    /** @nullable */
    showLabelsOnSeries?: boolean | null
    /** @nullable */
    showLegend?: boolean | null
    /** @nullable */
    showMovingAverage?: boolean | null
    /** @nullable */
    showMultipleYAxes?: boolean | null
    /** @nullable */
    showPercentStackView?: boolean | null
    /** @nullable */
    showTrendLines?: boolean | null
    /** @nullable */
    showValuesOnSeries?: boolean | null
    /** @nullable */
    smoothingIntervals?: number | null
    yAxisScaleType?: YAxisScaleTypeApi
}

/**
 * Whether we should be comparing against a specific conversion goal
 */
export type TrendsQueryApiConversionGoal = ActionConversionGoalApi | CustomEventConversionGoalApi

export type TrendsQueryApiKind = (typeof TrendsQueryApiKind)[keyof typeof TrendsQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const TrendsQueryApiKind = {
    TrendsQuery: 'TrendsQuery',
} as const

export type TrendsQueryApiPropertiesAnyOfItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

/**
 * Property filters for all series
 */
export type TrendsQueryApiProperties = TrendsQueryApiPropertiesAnyOfItem[] | PropertyGroupFilterApi

export type TrendsQueryApiSeriesItem = GroupNodeApi | EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi

export interface TrendsQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi
    /** Compare to date range */
    compareFilter?: CompareFilterApi
    /** Whether we should be comparing against a specific conversion goal */
    conversionGoal?: TrendsQueryApiConversionGoal
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi
    kind?: TrendsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Property filters for all series */
    properties?: TrendsQueryApiProperties
    response?: TrendsQueryResponseApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: TrendsQueryApiSeriesItem[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi
    /** Properties specific to the trends insight */
    trendsFilter?: TrendsFilterApi
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type BreakdownAttributionTypeApi = (typeof BreakdownAttributionTypeApi)[keyof typeof BreakdownAttributionTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BreakdownAttributionTypeApi = {
    first_touch: 'first_touch',
    last_touch: 'last_touch',
    all_events: 'all_events',
    step: 'step',
} as const

export type FunnelExclusionEventsNodeApiFixedPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type FunnelExclusionEventsNodeApiKind =
    (typeof FunnelExclusionEventsNodeApiKind)[keyof typeof FunnelExclusionEventsNodeApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelExclusionEventsNodeApiKind = {
    EventsNode: 'EventsNode',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelExclusionEventsNodeApiMath = {
    ...BaseMathTypeApi,
    ...FunnelMathTypeApi,
    ...PropertyMathTypeApi,
    ...CountPerActorMathTypeApi,
    ...ExperimentMetricMathTypeApi,
    ...CalendarHeatmapMathTypeApi,
    unique_group: 'unique_group',
    hogql: 'hogql',
} as const
export type FunnelExclusionEventsNodeApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type FunnelExclusionEventsNodeApiResponseAnyOf = { [key: string]: unknown }

/**
 * @nullable
 */
export type FunnelExclusionEventsNodeApiResponse = FunnelExclusionEventsNodeApiResponseAnyOf | null | null

export interface FunnelExclusionEventsNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * The event or `null` for all events.
     * @nullable
     */
    event?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?: FunnelExclusionEventsNodeApiFixedPropertiesItem[] | null
    funnelFromStep: number
    funnelToStep: number
    kind?: FunnelExclusionEventsNodeApiKind
    /** @nullable */
    limit?: number | null
    math?: (typeof FunnelExclusionEventsNodeApiMath)[keyof typeof FunnelExclusionEventsNodeApiMath]
    math_group_type_index?: MathGroupTypeIndexApi
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi
    /** @nullable */
    math_property_type?: string | null
    /** @nullable */
    name?: string | null
    /** @nullable */
    optionalInFunnel?: boolean | null
    /**
     * Columns to order by
     * @nullable
     */
    orderBy?: string[] | null
    /**
     * Properties configurable in the interface
     * @nullable
     */
    properties?: FunnelExclusionEventsNodeApiPropertiesItem[] | null
    /** @nullable */
    response?: FunnelExclusionEventsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type FunnelExclusionActionsNodeApiFixedPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type FunnelExclusionActionsNodeApiKind =
    (typeof FunnelExclusionActionsNodeApiKind)[keyof typeof FunnelExclusionActionsNodeApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelExclusionActionsNodeApiKind = {
    ActionsNode: 'ActionsNode',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelExclusionActionsNodeApiMath = {
    ...BaseMathTypeApi,
    ...FunnelMathTypeApi,
    ...PropertyMathTypeApi,
    ...CountPerActorMathTypeApi,
    ...ExperimentMetricMathTypeApi,
    ...CalendarHeatmapMathTypeApi,
    unique_group: 'unique_group',
    hogql: 'hogql',
} as const
export type FunnelExclusionActionsNodeApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export type FunnelExclusionActionsNodeApiResponseAnyOf = { [key: string]: unknown }

/**
 * @nullable
 */
export type FunnelExclusionActionsNodeApiResponse = FunnelExclusionActionsNodeApiResponseAnyOf | null | null

export interface FunnelExclusionActionsNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?: FunnelExclusionActionsNodeApiFixedPropertiesItem[] | null
    funnelFromStep: number
    funnelToStep: number
    id: number
    kind?: FunnelExclusionActionsNodeApiKind
    math?: (typeof FunnelExclusionActionsNodeApiMath)[keyof typeof FunnelExclusionActionsNodeApiMath]
    math_group_type_index?: MathGroupTypeIndexApi
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi
    /** @nullable */
    math_property_type?: string | null
    /** @nullable */
    name?: string | null
    /** @nullable */
    optionalInFunnel?: boolean | null
    /**
     * Properties configurable in the interface
     * @nullable
     */
    properties?: FunnelExclusionActionsNodeApiPropertiesItem[] | null
    /** @nullable */
    response?: FunnelExclusionActionsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type StepOrderValueApi = (typeof StepOrderValueApi)[keyof typeof StepOrderValueApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const StepOrderValueApi = {
    strict: 'strict',
    unordered: 'unordered',
    ordered: 'ordered',
} as const

export type FunnelStepReferenceApi = (typeof FunnelStepReferenceApi)[keyof typeof FunnelStepReferenceApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelStepReferenceApi = {
    total: 'total',
    previous: 'previous',
} as const

export type FunnelVizTypeApi = (typeof FunnelVizTypeApi)[keyof typeof FunnelVizTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelVizTypeApi = {
    steps: 'steps',
    time_to_convert: 'time_to_convert',
    trends: 'trends',
} as const

export type FunnelConversionWindowTimeUnitApi =
    (typeof FunnelConversionWindowTimeUnitApi)[keyof typeof FunnelConversionWindowTimeUnitApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelConversionWindowTimeUnitApi = {
    second: 'second',
    minute: 'minute',
    hour: 'hour',
    day: 'day',
    week: 'week',
    month: 'month',
} as const

export type FunnelLayoutApi = (typeof FunnelLayoutApi)[keyof typeof FunnelLayoutApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelLayoutApi = {
    horizontal: 'horizontal',
    vertical: 'vertical',
} as const

export type FunnelsFilterApiExclusionsItem = FunnelExclusionEventsNodeApi | FunnelExclusionActionsNodeApi

/**
 * Customizations for the appearance of result datasets.
 */
export type FunnelsFilterApiResultCustomizationsAnyOf = { [key: string]: ResultCustomizationByValueApi }

/**
 * Customizations for the appearance of result datasets.
 * @nullable
 */
export type FunnelsFilterApiResultCustomizations = FunnelsFilterApiResultCustomizationsAnyOf | null | null

export interface FunnelsFilterApi {
    /** @nullable */
    binCount?: number | null
    breakdownAttributionType?: BreakdownAttributionTypeApi
    /** @nullable */
    breakdownAttributionValue?: number | null
    /** @nullable */
    exclusions?: FunnelsFilterApiExclusionsItem[] | null
    /** @nullable */
    funnelAggregateByHogQL?: string | null
    /** @nullable */
    funnelFromStep?: number | null
    funnelOrderType?: StepOrderValueApi
    funnelStepReference?: FunnelStepReferenceApi
    /**
     * To select the range of steps for trends & time to convert funnels, 0-indexed
     * @nullable
     */
    funnelToStep?: number | null
    funnelVizType?: FunnelVizTypeApi
    /** @nullable */
    funnelWindowInterval?: number | null
    funnelWindowIntervalUnit?: FunnelConversionWindowTimeUnitApi
    /**
     * Goal Lines
     * @nullable
     */
    goalLines?: GoalLineApi[] | null
    /** @nullable */
    hiddenLegendBreakdowns?: string[] | null
    layout?: FunnelLayoutApi
    /**
     * Customizations for the appearance of result datasets.
     * @nullable
     */
    resultCustomizations?: FunnelsFilterApiResultCustomizations
    /** @nullable */
    showValuesOnSeries?: boolean | null
    /** @nullable */
    useUdf?: boolean | null
}

export interface FunnelsQueryResponseApi {
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** @nullable */
    isUdf?: boolean | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: unknown
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type FunnelsQueryApiKind = (typeof FunnelsQueryApiKind)[keyof typeof FunnelsQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelsQueryApiKind = {
    FunnelsQuery: 'FunnelsQuery',
} as const

export type FunnelsQueryApiPropertiesAnyOfItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

/**
 * Property filters for all series
 */
export type FunnelsQueryApiProperties = FunnelsQueryApiPropertiesAnyOfItem[] | PropertyGroupFilterApi

export type FunnelsQueryApiSeriesItem = EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi

export interface FunnelsQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Properties specific to the funnels insight */
    funnelsFilter?: FunnelsFilterApi
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi
    kind?: FunnelsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Property filters for all series */
    properties?: FunnelsQueryApiProperties
    response?: FunnelsQueryResponseApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: FunnelsQueryApiSeriesItem[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export interface RetentionValueApi {
    count: number
    /** @nullable */
    label?: string | null
}

/**
 * Optional breakdown value for retention cohorts
 */
export type RetentionResultApiBreakdownValue = string | number

export interface RetentionResultApi {
    /** Optional breakdown value for retention cohorts */
    breakdown_value?: RetentionResultApiBreakdownValue
    date: string
    label: string
    values: RetentionValueApi[]
}

export interface RetentionQueryResponseApi {
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: RetentionResultApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type RetentionDashboardDisplayTypeApi =
    (typeof RetentionDashboardDisplayTypeApi)[keyof typeof RetentionDashboardDisplayTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RetentionDashboardDisplayTypeApi = {
    table_only: 'table_only',
    graph_only: 'graph_only',
    all: 'all',
} as const

export type MeanRetentionCalculationApi = (typeof MeanRetentionCalculationApi)[keyof typeof MeanRetentionCalculationApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MeanRetentionCalculationApi = {
    simple: 'simple',
    weighted: 'weighted',
    none: 'none',
} as const

export type RetentionPeriodApi = (typeof RetentionPeriodApi)[keyof typeof RetentionPeriodApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RetentionPeriodApi = {
    Hour: 'Hour',
    Day: 'Day',
    Week: 'Week',
    Month: 'Month',
} as const

export type RetentionReferenceApi = (typeof RetentionReferenceApi)[keyof typeof RetentionReferenceApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RetentionReferenceApi = {
    total: 'total',
    previous: 'previous',
} as const

export type RetentionTypeApi = (typeof RetentionTypeApi)[keyof typeof RetentionTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RetentionTypeApi = {
    retention_recurring: 'retention_recurring',
    retention_first_time: 'retention_first_time',
    retention_first_ever_occurrence: 'retention_first_ever_occurrence',
} as const

export type RetentionEntityKindApi = (typeof RetentionEntityKindApi)[keyof typeof RetentionEntityKindApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RetentionEntityKindApi = {
    ActionsNode: 'ActionsNode',
    EventsNode: 'EventsNode',
} as const

export type EntityTypeApi = (typeof EntityTypeApi)[keyof typeof EntityTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EntityTypeApi = {
    actions: 'actions',
    events: 'events',
    data_warehouse: 'data_warehouse',
    new_entity: 'new_entity',
    groups: 'groups',
} as const

export type RetentionEntityApiId = string | number

export type RetentionEntityApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export interface RetentionEntityApi {
    /** @nullable */
    custom_name?: string | null
    id?: RetentionEntityApiId
    kind?: RetentionEntityKindApi
    /** @nullable */
    name?: string | null
    /** @nullable */
    order?: number | null
    /**
     * filters on the event
     * @nullable
     */
    properties?: RetentionEntityApiPropertiesItem[] | null
    type?: EntityTypeApi
    /** @nullable */
    uuid?: string | null
}

export type TimeWindowModeApi = (typeof TimeWindowModeApi)[keyof typeof TimeWindowModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const TimeWindowModeApi = {
    strict_calendar_dates: 'strict_calendar_dates',
    '24_hour_windows': '24_hour_windows',
} as const

export interface RetentionFilterApi {
    /** @nullable */
    cumulative?: boolean | null
    dashboardDisplay?: RetentionDashboardDisplayTypeApi
    /** controls the display of the retention graph */
    display?: ChartDisplayTypeApi
    /** @nullable */
    goalLines?: GoalLineApi[] | null
    meanRetentionCalculation?: MeanRetentionCalculationApi
    /** @nullable */
    minimumOccurrences?: number | null
    period?: RetentionPeriodApi
    /**
     * Custom brackets for retention calculations
     * @nullable
     */
    retentionCustomBrackets?: number[] | null
    /** Whether retention is with regard to initial cohort size, or that of the previous period. */
    retentionReference?: RetentionReferenceApi
    retentionType?: RetentionTypeApi
    returningEntity?: RetentionEntityApi
    /**
     * The selected interval to display across all cohorts (null = show all intervals for each cohort)
     * @nullable
     */
    selectedInterval?: number | null
    /** @nullable */
    showTrendLines?: boolean | null
    targetEntity?: RetentionEntityApi
    /** The time window mode to use for retention calculations */
    timeWindowMode?: TimeWindowModeApi
    /** @nullable */
    totalIntervals?: number | null
}

export type RetentionQueryApiKind = (typeof RetentionQueryApiKind)[keyof typeof RetentionQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RetentionQueryApiKind = {
    RetentionQuery: 'RetentionQuery',
} as const

export type RetentionQueryApiPropertiesAnyOfItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

/**
 * Property filters for all series
 */
export type RetentionQueryApiProperties = RetentionQueryApiPropertiesAnyOfItem[] | PropertyGroupFilterApi

export interface RetentionQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    kind?: RetentionQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Property filters for all series */
    properties?: RetentionQueryApiProperties
    response?: RetentionQueryResponseApi
    /** Properties specific to the retention insight */
    retentionFilter: RetentionFilterApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type FunnelPathTypeApi = (typeof FunnelPathTypeApi)[keyof typeof FunnelPathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FunnelPathTypeApi = {
    funnel_path_before_step: 'funnel_path_before_step',
    funnel_path_between_steps: 'funnel_path_between_steps',
    funnel_path_after_step: 'funnel_path_after_step',
} as const

export interface FunnelPathsFilterApi {
    funnelPathType?: FunnelPathTypeApi
    funnelSource: FunnelsQueryApi
    /** @nullable */
    funnelStep?: number | null
}

export type PathTypeApi = (typeof PathTypeApi)[keyof typeof PathTypeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PathTypeApi = {
    $pageview: '$pageview',
    $screen: '$screen',
    custom_event: 'custom_event',
    hogql: 'hogql',
} as const

export interface PathCleaningFilterApi {
    /** @nullable */
    alias?: string | null
    /** @nullable */
    order?: number | null
    /** @nullable */
    regex?: string | null
}

export interface PathsFilterApi {
    /** @nullable */
    edgeLimit?: number | null
    /** @nullable */
    endPoint?: string | null
    /** @nullable */
    excludeEvents?: string[] | null
    /** @nullable */
    includeEventTypes?: PathTypeApi[] | null
    /** @nullable */
    localPathCleaningFilters?: PathCleaningFilterApi[] | null
    /** @nullable */
    maxEdgeWeight?: number | null
    /** @nullable */
    minEdgeWeight?: number | null
    /**
     * Relevant only within actors query
     * @nullable
     */
    pathDropoffKey?: string | null
    /**
     * Relevant only within actors query
     * @nullable
     */
    pathEndKey?: string | null
    /** @nullable */
    pathGroupings?: string[] | null
    /** @nullable */
    pathReplacements?: boolean | null
    /**
     * Relevant only within actors query
     * @nullable
     */
    pathStartKey?: string | null
    /** @nullable */
    pathsHogQLExpression?: string | null
    /** @nullable */
    showFullUrls?: boolean | null
    /** @nullable */
    startPoint?: string | null
    /** @nullable */
    stepLimit?: number | null
}

export interface PathsLinkApi {
    average_conversion_time: number
    source: string
    target: string
    value: number
}

export interface PathsQueryResponseApi {
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: PathsLinkApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type PathsQueryApiKind = (typeof PathsQueryApiKind)[keyof typeof PathsQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PathsQueryApiKind = {
    PathsQuery: 'PathsQuery',
} as const

export type PathsQueryApiPropertiesAnyOfItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

/**
 * Property filters for all series
 */
export type PathsQueryApiProperties = PathsQueryApiPropertiesAnyOfItem[] | PropertyGroupFilterApi

export interface PathsQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Used for displaying paths in relation to funnel steps. */
    funnelPathsFilter?: FunnelPathsFilterApi
    kind?: PathsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Properties specific to the paths insight */
    pathsFilter: PathsFilterApi
    /** Property filters for all series */
    properties?: PathsQueryApiProperties
    response?: PathsQueryResponseApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type StickinessQueryResponseApiResultsItem = { [key: string]: unknown }

export interface StickinessQueryResponseApi {
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: StickinessQueryResponseApiResultsItem[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type StickinessComputationModeApi =
    (typeof StickinessComputationModeApi)[keyof typeof StickinessComputationModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const StickinessComputationModeApi = {
    non_cumulative: 'non_cumulative',
    cumulative: 'cumulative',
} as const

export type StickinessOperatorApi = (typeof StickinessOperatorApi)[keyof typeof StickinessOperatorApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const StickinessOperatorApi = {
    gte: 'gte',
    lte: 'lte',
    exact: 'exact',
} as const

export interface StickinessCriteriaApi {
    operator: StickinessOperatorApi
    value: number
}

export type StickinessFilterApiResultCustomizationsAnyOf = { [key: string]: ResultCustomizationByValueApi }

export type StickinessFilterApiResultCustomizationsAnyOfTwo = { [key: string]: ResultCustomizationByPositionApi }

/**
 * Customizations for the appearance of result datasets.
 */
export type StickinessFilterApiResultCustomizations =
    | StickinessFilterApiResultCustomizationsAnyOf
    | StickinessFilterApiResultCustomizationsAnyOfTwo

export interface StickinessFilterApi {
    computedAs?: StickinessComputationModeApi
    display?: ChartDisplayTypeApi
    /** @nullable */
    hiddenLegendIndexes?: number[] | null
    /** Whether result datasets are associated by their values or by their order. */
    resultCustomizationBy?: ResultCustomizationByApi
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: StickinessFilterApiResultCustomizations
    /** @nullable */
    showLegend?: boolean | null
    /** @nullable */
    showMultipleYAxes?: boolean | null
    /** @nullable */
    showValuesOnSeries?: boolean | null
    stickinessCriteria?: StickinessCriteriaApi
}

export type StickinessQueryApiKind = (typeof StickinessQueryApiKind)[keyof typeof StickinessQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const StickinessQueryApiKind = {
    StickinessQuery: 'StickinessQuery',
} as const

export type StickinessQueryApiPropertiesAnyOfItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

/**
 * Property filters for all series
 */
export type StickinessQueryApiProperties = StickinessQueryApiPropertiesAnyOfItem[] | PropertyGroupFilterApi

export type StickinessQueryApiSeriesItem = EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi

export interface StickinessQueryApi {
    /** Compare to date range */
    compareFilter?: CompareFilterApi
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi
    /**
     * How many intervals comprise a period. Only used for cohorts, otherwise default 1.
     * @nullable
     */
    intervalCount?: number | null
    kind?: StickinessQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Property filters for all series */
    properties?: StickinessQueryApiProperties
    response?: StickinessQueryResponseApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: StickinessQueryApiSeriesItem[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: StickinessFilterApi
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type LifecycleToggleApi = (typeof LifecycleToggleApi)[keyof typeof LifecycleToggleApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const LifecycleToggleApi = {
    new: 'new',
    resurrecting: 'resurrecting',
    returning: 'returning',
    dormant: 'dormant',
} as const

export interface LifecycleFilterApi {
    /** @nullable */
    showLegend?: boolean | null
    /** @nullable */
    showValuesOnSeries?: boolean | null
    /** @nullable */
    stacked?: boolean | null
    /** @nullable */
    toggledLifecycles?: LifecycleToggleApi[] | null
}

export type LifecycleQueryResponseApiResultsItem = { [key: string]: unknown }

export interface LifecycleQueryResponseApi {
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: LifecycleQueryResponseApiResultsItem[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type LifecycleQueryApiKind = (typeof LifecycleQueryApiKind)[keyof typeof LifecycleQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const LifecycleQueryApiKind = {
    LifecycleQuery: 'LifecycleQuery',
} as const

export type LifecycleQueryApiPropertiesAnyOfItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

/**
 * Property filters for all series
 */
export type LifecycleQueryApiProperties = LifecycleQueryApiPropertiesAnyOfItem[] | PropertyGroupFilterApi

export type LifecycleQueryApiSeriesItem = EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi

export interface LifecycleQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi
    kind?: LifecycleQueryApiKind
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: LifecycleFilterApi
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Property filters for all series */
    properties?: LifecycleQueryApiProperties
    response?: LifecycleQueryResponseApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: LifecycleQueryApiSeriesItem[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type WebStatsBreakdownApi = (typeof WebStatsBreakdownApi)[keyof typeof WebStatsBreakdownApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebStatsBreakdownApi = {
    Page: 'Page',
    InitialPage: 'InitialPage',
    ExitPage: 'ExitPage',
    ExitClick: 'ExitClick',
    PreviousPage: 'PreviousPage',
    ScreenName: 'ScreenName',
    InitialChannelType: 'InitialChannelType',
    InitialReferringDomain: 'InitialReferringDomain',
    InitialUTMSource: 'InitialUTMSource',
    InitialUTMCampaign: 'InitialUTMCampaign',
    InitialUTMMedium: 'InitialUTMMedium',
    InitialUTMTerm: 'InitialUTMTerm',
    InitialUTMContent: 'InitialUTMContent',
    InitialUTMSourceMediumCampaign: 'InitialUTMSourceMediumCampaign',
    Browser: 'Browser',
    OS: 'OS',
    Viewport: 'Viewport',
    DeviceType: 'DeviceType',
    Country: 'Country',
    Region: 'Region',
    City: 'City',
    Timezone: 'Timezone',
    Language: 'Language',
    FrustrationMetrics: 'FrustrationMetrics',
} as const

export type WebAnalyticsOrderByFieldsApi =
    (typeof WebAnalyticsOrderByFieldsApi)[keyof typeof WebAnalyticsOrderByFieldsApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebAnalyticsOrderByFieldsApi = {
    Visitors: 'Visitors',
    Views: 'Views',
    AvgTimeOnPage: 'AvgTimeOnPage',
    Clicks: 'Clicks',
    BounceRate: 'BounceRate',
    AverageScrollPercentage: 'AverageScrollPercentage',
    ScrollGt80Percentage: 'ScrollGt80Percentage',
    TotalConversions: 'TotalConversions',
    UniqueConversions: 'UniqueConversions',
    ConversionRate: 'ConversionRate',
    ConvertingUsers: 'ConvertingUsers',
    RageClicks: 'RageClicks',
    DeadClicks: 'DeadClicks',
    Errors: 'Errors',
} as const

export type WebAnalyticsOrderByDirectionApi =
    (typeof WebAnalyticsOrderByDirectionApi)[keyof typeof WebAnalyticsOrderByDirectionApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebAnalyticsOrderByDirectionApi = {
    ASC: 'ASC',
    DESC: 'DESC',
} as const

export interface SamplingRateApi {
    /** @nullable */
    denominator?: number | null
    numerator: number
}

export interface WebStatsTableQueryResponseApi {
    /** @nullable */
    columns?: unknown[] | null
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** @nullable */
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: unknown[]
    samplingRate?: SamplingRateApi
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
    /** @nullable */
    usedPreAggregatedTables?: boolean | null
}

export interface WebAnalyticsSamplingApi {
    /** @nullable */
    enabled?: boolean | null
    forceSamplingRate?: SamplingRateApi
}

export type WebStatsTableQueryApiConversionGoal = ActionConversionGoalApi | CustomEventConversionGoalApi

export type WebStatsTableQueryApiKind = (typeof WebStatsTableQueryApiKind)[keyof typeof WebStatsTableQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebStatsTableQueryApiKind = {
    WebStatsTableQuery: 'WebStatsTableQuery',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebStatsTableQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export type WebStatsTableQueryApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | SessionPropertyFilterApi

export interface WebStatsTableQueryApi {
    /**
     * Groups aggregation - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    aggregation_group_type_index?: number | null
    breakdownBy: WebStatsBreakdownApi
    compareFilter?: CompareFilterApi
    conversionGoal?: WebStatsTableQueryApiConversionGoal
    /**
     * Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi
    /** @nullable */
    doPathCleaning?: boolean | null
    /** @nullable */
    filterTestAccounts?: boolean | null
    /** @nullable */
    includeAvgTimeOnPage?: boolean | null
    /** @nullable */
    includeBounceRate?: boolean | null
    /** @nullable */
    includeRevenue?: boolean | null
    /** @nullable */
    includeScrollDepth?: boolean | null
    /** For Product Analytics UI compatibility only - not used in Web Analytics query execution */
    interval?: IntervalTypeApi
    kind?: WebStatsTableQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** @nullable */
    offset?: number | null
    /** @nullable */
    orderBy?: (typeof WebStatsTableQueryApiOrderByItem)[keyof typeof WebStatsTableQueryApiOrderByItem][] | null
    properties: WebStatsTableQueryApiPropertiesItem[]
    response?: WebStatsTableQueryResponseApi
    sampling?: WebAnalyticsSamplingApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type WebAnalyticsItemKindApi = (typeof WebAnalyticsItemKindApi)[keyof typeof WebAnalyticsItemKindApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebAnalyticsItemKindApi = {
    unit: 'unit',
    duration_s: 'duration_s',
    percentage: 'percentage',
    currency: 'currency',
} as const

export interface WebOverviewItemApi {
    /** @nullable */
    changeFromPreviousPct?: number | null
    /** @nullable */
    isIncreaseBad?: boolean | null
    key: string
    kind: WebAnalyticsItemKindApi
    /** @nullable */
    previous?: number | null
    /** @nullable */
    usedPreAggregatedTables?: boolean | null
    /** @nullable */
    value?: number | null
}

export interface WebOverviewQueryResponseApi {
    /** @nullable */
    dateFrom?: string | null
    /** @nullable */
    dateTo?: string | null
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /**
     * Generated HogQL query.
     * @nullable
     */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi
    results: WebOverviewItemApi[]
    samplingRate?: SamplingRateApi
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    usedPreAggregatedTables?: boolean | null
}

export type WebOverviewQueryApiConversionGoal = ActionConversionGoalApi | CustomEventConversionGoalApi

export type WebOverviewQueryApiKind = (typeof WebOverviewQueryApiKind)[keyof typeof WebOverviewQueryApiKind]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebOverviewQueryApiKind = {
    WebOverviewQuery: 'WebOverviewQuery',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WebOverviewQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export type WebOverviewQueryApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | SessionPropertyFilterApi

export interface WebOverviewQueryApi {
    /**
     * Groups aggregation - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi
    conversionGoal?: WebOverviewQueryApiConversionGoal
    /**
     * Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi
    /** @nullable */
    doPathCleaning?: boolean | null
    /** @nullable */
    filterTestAccounts?: boolean | null
    /** @nullable */
    includeRevenue?: boolean | null
    /** For Product Analytics UI compatibility only - not used in Web Analytics query execution */
    interval?: IntervalTypeApi
    kind?: WebOverviewQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi
    /** @nullable */
    orderBy?: (typeof WebOverviewQueryApiOrderByItem)[keyof typeof WebOverviewQueryApiOrderByItem][] | null
    properties: WebOverviewQueryApiPropertiesItem[]
    response?: WebOverviewQueryResponseApi
    sampling?: WebAnalyticsSamplingApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type EndpointRequestApiQuery =
    | HogQLQueryApi
    | TrendsQueryApi
    | FunnelsQueryApi
    | RetentionQueryApi
    | PathsQueryApi
    | StickinessQueryApi
    | LifecycleQueryApi
    | WebStatsTableQueryApi
    | WebOverviewQueryApi

export type DataWarehouseSyncIntervalApi =
    (typeof DataWarehouseSyncIntervalApi)[keyof typeof DataWarehouseSyncIntervalApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DataWarehouseSyncIntervalApi = {
    '5min': '5min',
    '30min': '30min',
    '1hour': '1hour',
    '6hour': '6hour',
    '12hour': '12hour',
    '24hour': '24hour',
    '7day': '7day',
    '30day': '30day',
} as const

export interface EndpointRequestApi {
    /** @nullable */
    cache_age_seconds?: number | null
    /** @nullable */
    derived_from_insight?: string | null
    /** @nullable */
    description?: string | null
    /** @nullable */
    is_active?: boolean | null
    /**
     * Whether this endpoint's query results are materialized to S3
     * @nullable
     */
    is_materialized?: boolean | null
    /** @nullable */
    name?: string | null
    query?: EndpointRequestApiQuery
    /** How frequently should the underlying materialized view be updated */
    sync_frequency?: DataWarehouseSyncIntervalApi
}

/**
 * Map of Insight query keys to be overridden at execution time. For example:   Assuming query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode","name": "$pageview","event": "$pageview","math": "total"}]}   If query_override = {"series": [{"kind": "EventsNode","name": "$identify","event": "$identify","math": "total"}]}   The query executed will return the count of $identify events, instead of $pageview's
 */
export type EndpointRunRequestApiQueryOverrideAnyOf = { [key: string]: unknown }

/**
 * Map of Insight query keys to be overridden at execution time. For example:   Assuming query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode","name": "$pageview","event": "$pageview","math": "total"}]}   If query_override = {"series": [{"kind": "EventsNode","name": "$identify","event": "$identify","math": "total"}]}   The query executed will return the count of $identify events, instead of $pageview's
 * @nullable
 */
export type EndpointRunRequestApiQueryOverride = EndpointRunRequestApiQueryOverrideAnyOf | null | null

/**
 * A map for overriding HogQL query variables, where the key is the variable name and the value is the variable value. Variable must be set on the endpoint's query between curly braces (i.e. {variable.from_date}) For example: {"from_date": "1970-01-01"}
 */
export type EndpointRunRequestApiVariablesAnyOf = { [key: string]: unknown }

/**
 * A map for overriding HogQL query variables, where the key is the variable name and the value is the variable value. Variable must be set on the endpoint's query between curly braces (i.e. {variable.from_date}) For example: {"from_date": "1970-01-01"}
 * @nullable
 */
export type EndpointRunRequestApiVariables = EndpointRunRequestApiVariablesAnyOf | null | null

export type DashboardFilterApiPropertiesItem =
    | EventPropertyFilterApi
    | PersonPropertyFilterApi
    | ElementPropertyFilterApi
    | EventMetadataPropertyFilterApi
    | SessionPropertyFilterApi
    | CohortPropertyFilterApi
    | RecordingPropertyFilterApi
    | LogEntryPropertyFilterApi
    | GroupPropertyFilterApi
    | FeaturePropertyFilterApi
    | FlagPropertyFilterApi
    | HogQLPropertyFilterApi
    | EmptyPropertyFilterApi
    | DataWarehousePropertyFilterApi
    | DataWarehousePersonPropertyFilterApi
    | ErrorTrackingIssueFilterApi
    | LogPropertyFilterApi
    | RevenueAnalyticsPropertyFilterApi

export interface DashboardFilterApi {
    breakdown_filter?: BreakdownFilterApi
    /** @nullable */
    date_from?: string | null
    /** @nullable */
    date_to?: string | null
    /** @nullable */
    explicitDate?: boolean | null
    /** @nullable */
    properties?: DashboardFilterApiPropertiesItem[] | null
}

export type EndpointRefreshModeApi = (typeof EndpointRefreshModeApi)[keyof typeof EndpointRefreshModeApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EndpointRefreshModeApi = {
    cache: 'cache',
    force: 'force',
    direct: 'direct',
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
    /** A map for overriding insight query filters.

Tip: Use to get data for a specific customer or user. */
    filters_override?: DashboardFilterApi
    /**
     * Map of Insight query keys to be overridden at execution time. For example:   Assuming query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode","name": "$pageview","event": "$pageview","math": "total"}]}   If query_override = {"series": [{"kind": "EventsNode","name": "$identify","event": "$identify","math": "total"}]}   The query executed will return the count of $identify events, instead of $pageview's
     * @nullable
     */
    query_override?: EndpointRunRequestApiQueryOverride
    refresh?: EndpointRefreshModeApi
    /**
     * A map for overriding HogQL query variables, where the key is the variable name and the value is the variable value. Variable must be set on the endpoint's query between curly braces (i.e. {variable.from_date}) For example: {"from_date": "1970-01-01"}
     * @nullable
     */
    variables?: EndpointRunRequestApiVariables
    /**
     * Specific endpoint version to execute. If not provided, the latest version is used.
     * @nullable
     */
    version?: number | null
}

export interface EndpointLastExecutionTimesRequestApi {
    names: string[]
}

export interface QueryStatusResponseApi {
    query_status: QueryStatusApi
}
