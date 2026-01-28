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
    semver_eq: 'semver_eq',
    semver_neq: 'semver_neq',
    semver_gt: 'semver_gt',
    semver_gte: 'semver_gte',
    semver_lt: 'semver_lt',
    semver_lte: 'semver_lte',
    semver_tilde: 'semver_tilde',
    semver_caret: 'semver_caret',
    semver_wildcard: 'semver_wildcard',
} as const

/**
 * Event properties
 */
export type EventPropertyFilterApiType = (typeof EventPropertyFilterApiType)[keyof typeof EventPropertyFilterApiType]

export const EventPropertyFilterApiType = {
    event: 'event',
} as const

export interface EventPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator?: PropertyOperatorApi | null
    /** Event properties */
    type?: EventPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

/**
 * Person properties
 */
export type PersonPropertyFilterApiType = (typeof PersonPropertyFilterApiType)[keyof typeof PersonPropertyFilterApiType]

export const PersonPropertyFilterApiType = {
    person: 'person',
} as const

export interface PersonPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: PersonPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type KeyApi = (typeof KeyApi)[keyof typeof KeyApi]

export const KeyApi = {
    tag_name: 'tag_name',
    text: 'text',
    href: 'href',
    selector: 'selector',
} as const

export type ElementPropertyFilterApiType =
    (typeof ElementPropertyFilterApiType)[keyof typeof ElementPropertyFilterApiType]

export const ElementPropertyFilterApiType = {
    element: 'element',
} as const

export interface ElementPropertyFilterApi {
    key: KeyApi
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: ElementPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type EventMetadataPropertyFilterApiType =
    (typeof EventMetadataPropertyFilterApiType)[keyof typeof EventMetadataPropertyFilterApiType]

export const EventMetadataPropertyFilterApiType = {
    event_metadata: 'event_metadata',
} as const

export interface EventMetadataPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: EventMetadataPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type SessionPropertyFilterApiType =
    (typeof SessionPropertyFilterApiType)[keyof typeof SessionPropertyFilterApiType]

export const SessionPropertyFilterApiType = {
    session: 'session',
} as const

export interface SessionPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: SessionPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type CohortPropertyFilterApiKey = (typeof CohortPropertyFilterApiKey)[keyof typeof CohortPropertyFilterApiKey]

export const CohortPropertyFilterApiKey = {
    id: 'id',
} as const

export type CohortPropertyFilterApiType = (typeof CohortPropertyFilterApiType)[keyof typeof CohortPropertyFilterApiType]

export const CohortPropertyFilterApiType = {
    cohort: 'cohort',
} as const

export interface CohortPropertyFilterApi {
    /** @nullable */
    cohort_name?: string | null
    key?: CohortPropertyFilterApiKey
    /** @nullable */
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: CohortPropertyFilterApiType
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    duration: 'duration',
    active_seconds: 'active_seconds',
    inactive_seconds: 'inactive_seconds',
} as const

export type RecordingPropertyFilterApiType =
    (typeof RecordingPropertyFilterApiType)[keyof typeof RecordingPropertyFilterApiType]

export const RecordingPropertyFilterApiType = {
    recording: 'recording',
} as const

export interface RecordingPropertyFilterApi {
    key: DurationTypeApi | string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: RecordingPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type LogEntryPropertyFilterApiType =
    (typeof LogEntryPropertyFilterApiType)[keyof typeof LogEntryPropertyFilterApiType]

export const LogEntryPropertyFilterApiType = {
    log_entry: 'log_entry',
} as const

export interface LogEntryPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: LogEntryPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type GroupPropertyFilterApiType = (typeof GroupPropertyFilterApiType)[keyof typeof GroupPropertyFilterApiType]

export const GroupPropertyFilterApiType = {
    group: 'group',
} as const

export interface GroupPropertyFilterApi {
    /** @nullable */
    group_type_index?: number | null
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: GroupPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

/**
 * Event property with "$feature/" prepended
 */
export type FeaturePropertyFilterApiType =
    (typeof FeaturePropertyFilterApiType)[keyof typeof FeaturePropertyFilterApiType]

export const FeaturePropertyFilterApiType = {
    feature: 'feature',
} as const

export interface FeaturePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: FeaturePropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

/**
 * Only flag_evaluates_to operator is allowed for flag dependencies
 */
export type FlagPropertyFilterApiOperator =
    (typeof FlagPropertyFilterApiOperator)[keyof typeof FlagPropertyFilterApiOperator]

export const FlagPropertyFilterApiOperator = {
    flag_evaluates_to: 'flag_evaluates_to',
} as const

/**
 * Feature flag dependency
 */
export type FlagPropertyFilterApiType = (typeof FlagPropertyFilterApiType)[keyof typeof FlagPropertyFilterApiType]

export const FlagPropertyFilterApiType = {
    flag: 'flag',
} as const

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
    value: boolean | string
}

export type HogQLPropertyFilterApiType = (typeof HogQLPropertyFilterApiType)[keyof typeof HogQLPropertyFilterApiType]

export const HogQLPropertyFilterApiType = {
    hogql: 'hogql',
} as const

export interface HogQLPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    type?: HogQLPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type EmptyPropertyFilterApiType = (typeof EmptyPropertyFilterApiType)[keyof typeof EmptyPropertyFilterApiType]

export const EmptyPropertyFilterApiType = {
    empty: 'empty',
} as const

export interface EmptyPropertyFilterApi {
    type?: EmptyPropertyFilterApiType
}

export type DataWarehousePropertyFilterApiType =
    (typeof DataWarehousePropertyFilterApiType)[keyof typeof DataWarehousePropertyFilterApiType]

export const DataWarehousePropertyFilterApiType = {
    data_warehouse: 'data_warehouse',
} as const

export interface DataWarehousePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: DataWarehousePropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type DataWarehousePersonPropertyFilterApiType =
    (typeof DataWarehousePersonPropertyFilterApiType)[keyof typeof DataWarehousePersonPropertyFilterApiType]

export const DataWarehousePersonPropertyFilterApiType = {
    data_warehouse_person_property: 'data_warehouse_person_property',
} as const

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: DataWarehousePersonPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type ErrorTrackingIssueFilterApiType =
    (typeof ErrorTrackingIssueFilterApiType)[keyof typeof ErrorTrackingIssueFilterApiType]

export const ErrorTrackingIssueFilterApiType = {
    error_tracking_issue: 'error_tracking_issue',
} as const

export interface ErrorTrackingIssueFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: ErrorTrackingIssueFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

export const LogPropertyFilterTypeApi = {
    log: 'log',
    log_attribute: 'log_attribute',
    log_resource_attribute: 'log_resource_attribute',
} as const

export interface LogPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type: LogPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type RevenueAnalyticsPropertyFilterApiType =
    (typeof RevenueAnalyticsPropertyFilterApiType)[keyof typeof RevenueAnalyticsPropertyFilterApiType]

export const RevenueAnalyticsPropertyFilterApiType = {
    revenue_analytics: 'revenue_analytics',
} as const

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: RevenueAnalyticsPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface HogQLFiltersApi {
    dateRange?: DateRangeApi | null
    /** @nullable */
    filterTestAccounts?: boolean | null
    /** @nullable */
    properties?:
        | (
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
          )[]
        | null
}

export type HogQLQueryApiKind = (typeof HogQLQueryApiKind)[keyof typeof HogQLQueryApiKind]

export const HogQLQueryApiKind = {
    HogQLQuery: 'HogQLQuery',
} as const

export type BounceRatePageViewModeApi = (typeof BounceRatePageViewModeApi)[keyof typeof BounceRatePageViewModeApi]

export const BounceRatePageViewModeApi = {
    count_pageviews: 'count_pageviews',
    uniq_urls: 'uniq_urls',
    uniq_page_screen_autocaptures: 'uniq_page_screen_autocaptures',
} as const

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    AND: 'AND',
    OR: 'OR',
} as const

export type CustomChannelFieldApi = (typeof CustomChannelFieldApi)[keyof typeof CustomChannelFieldApi]

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

export interface CustomChannelConditionApi {
    id: string
    key: CustomChannelFieldApi
    op: CustomChannelOperatorApi
    value?: string | string[] | null
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

export const InCohortViaApi = {
    auto: 'auto',
    leftjoin: 'leftjoin',
    subquery: 'subquery',
    leftjoin_conjoined: 'leftjoin_conjoined',
} as const

export type MaterializationModeApi = (typeof MaterializationModeApi)[keyof typeof MaterializationModeApi]

export const MaterializationModeApi = {
    auto: 'auto',
    legacy_null_as_string: 'legacy_null_as_string',
    legacy_null_as_null: 'legacy_null_as_null',
    disabled: 'disabled',
} as const

export type MaterializedColumnsOptimizationModeApi =
    (typeof MaterializedColumnsOptimizationModeApi)[keyof typeof MaterializedColumnsOptimizationModeApi]

export const MaterializedColumnsOptimizationModeApi = {
    disabled: 'disabled',
    optimized: 'optimized',
} as const

export type PersonsArgMaxVersionApi = (typeof PersonsArgMaxVersionApi)[keyof typeof PersonsArgMaxVersionApi]

export const PersonsArgMaxVersionApi = {
    auto: 'auto',
    v1: 'v1',
    v2: 'v2',
} as const

export type PersonsJoinModeApi = (typeof PersonsJoinModeApi)[keyof typeof PersonsJoinModeApi]

export const PersonsJoinModeApi = {
    inner: 'inner',
    left: 'left',
} as const

export type PersonsOnEventsModeApi = (typeof PersonsOnEventsModeApi)[keyof typeof PersonsOnEventsModeApi]

export const PersonsOnEventsModeApi = {
    disabled: 'disabled',
    person_id_no_override_properties_on_events: 'person_id_no_override_properties_on_events',
    person_id_override_properties_on_events: 'person_id_override_properties_on_events',
    person_id_override_properties_joined: 'person_id_override_properties_joined',
} as const

export type PropertyGroupsModeApi = (typeof PropertyGroupsModeApi)[keyof typeof PropertyGroupsModeApi]

export const PropertyGroupsModeApi = {
    enabled: 'enabled',
    disabled: 'disabled',
    optimized: 'optimized',
} as const

export type SessionTableVersionApi = (typeof SessionTableVersionApi)[keyof typeof SessionTableVersionApi]

export const SessionTableVersionApi = {
    auto: 'auto',
    v1: 'v1',
    v2: 'v2',
    v3: 'v3',
} as const

export type SessionsV2JoinModeApi = (typeof SessionsV2JoinModeApi)[keyof typeof SessionsV2JoinModeApi]

export const SessionsV2JoinModeApi = {
    string: 'string',
    uuid: 'uuid',
} as const

export interface HogQLQueryModifiersApi {
    /** @nullable */
    bounceRateDurationSeconds?: number | null
    bounceRatePageViewMode?: BounceRatePageViewModeApi | null
    /** @nullable */
    convertToProjectTimezone?: boolean | null
    /** @nullable */
    customChannelTypeRules?: CustomChannelRuleApi[] | null
    /** @nullable */
    dataWarehouseEventsModifiers?: DataWarehouseEventsModifierApi[] | null
    /** @nullable */
    debug?: boolean | null
    /**
     * If these are provided, the query will fail if these skip indexes are not used
     * @nullable
     */
    forceClickhouseDataSkippingIndexes?: string[] | null
    /** @nullable */
    formatCsvAllowDoubleQuotes?: boolean | null
    inCohortVia?: InCohortViaApi | null
    materializationMode?: MaterializationModeApi | null
    materializedColumnsOptimizationMode?: MaterializedColumnsOptimizationModeApi | null
    /** @nullable */
    optimizeJoinedFilters?: boolean | null
    /** @nullable */
    optimizeProjections?: boolean | null
    personsArgMaxVersion?: PersonsArgMaxVersionApi | null
    personsJoinMode?: PersonsJoinModeApi | null
    personsOnEventsMode?: PersonsOnEventsModeApi | null
    propertyGroupsMode?: PropertyGroupsModeApi | null
    /** @nullable */
    s3TableUseInvalidColumns?: boolean | null
    sessionTableVersion?: SessionTableVersionApi | null
    sessionsV2JoinMode?: SessionsV2JoinModeApi | null
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
    isUsingIndices?: QueryIndexUsageApi | null
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
    metadata?: HogQLMetadataResponseApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /**
     * Input query string
     * @nullable
     */
    query?: string | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
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
    value?: unknown | null
    variableId: string
}

/**
 * Constant values that can be referenced with the {placeholder} syntax in the query
 * @nullable
 */
export type HogQLQueryApiValues = { [key: string]: unknown } | null | null

/**
 * Variables to be substituted into the query
 * @nullable
 */
export type HogQLQueryApiVariables = { [key: string]: HogQLVariableApi } | null | null

export interface HogQLQueryApi {
    /** @nullable */
    explain?: boolean | null
    filters?: HogQLFiltersApi | null
    kind?: HogQLQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /**
     * Client provided name of the query
     * @nullable
     */
    name?: string | null
    query: string
    response?: HogQLQueryResponseApi | null
    tags?: QueryLogTagsApi | null
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

export interface BreakdownApi {
    /** @nullable */
    group_type_index?: number | null
    /** @nullable */
    histogram_bin_count?: number | null
    /** @nullable */
    normalize_url?: boolean | null
    property: string | number
    type?: MultipleBreakdownTypeApi | null
}

export interface BreakdownFilterApi {
    breakdown?: string | (string | number)[] | number | null
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
    breakdown_type?: BreakdownTypeApi | null
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

export const IntervalTypeApi = {
    second: 'second',
    minute: 'minute',
    hour: 'hour',
    day: 'day',
    week: 'week',
    month: 'month',
} as const

export type TrendsQueryApiKind = (typeof TrendsQueryApiKind)[keyof typeof TrendsQueryApiKind]

export const TrendsQueryApiKind = {
    TrendsQuery: 'TrendsQuery',
} as const

export interface PropertyGroupFilterValueApi {
    type: FilterLogicalOperatorApi
    values: (
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
    )[]
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
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: TrendsQueryResponseApiResultsItem[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type GroupNodeApiKind = (typeof GroupNodeApiKind)[keyof typeof GroupNodeApiKind]

export const GroupNodeApiKind = {
    GroupNode: 'GroupNode',
} as const

export type BaseMathTypeApi = (typeof BaseMathTypeApi)[keyof typeof BaseMathTypeApi]

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

export const FunnelMathTypeApi = {
    total: 'total',
    first_time_for_user: 'first_time_for_user',
    first_time_for_user_with_filters: 'first_time_for_user_with_filters',
} as const

export type PropertyMathTypeApi = (typeof PropertyMathTypeApi)[keyof typeof PropertyMathTypeApi]

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

export const CalendarHeatmapMathTypeApi = {
    total: 'total',
    dau: 'dau',
} as const

export type MathGroupTypeIndexApi = (typeof MathGroupTypeIndexApi)[keyof typeof MathGroupTypeIndexApi]

export const MathGroupTypeIndexApi = {
    NUMBER_0: 0,
    NUMBER_1: 1,
    NUMBER_2: 2,
    NUMBER_3: 3,
    NUMBER_4: 4,
} as const

export type CurrencyCodeApi = (typeof CurrencyCodeApi)[keyof typeof CurrencyCodeApi]

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
    static?: CurrencyCodeApi | null
}

export type EventsNodeApiKind = (typeof EventsNodeApiKind)[keyof typeof EventsNodeApiKind]

export const EventsNodeApiKind = {
    EventsNode: 'EventsNode',
} as const

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
/**
 * @nullable
 */
export type EventsNodeApiResponse = { [key: string]: unknown } | null | null

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
    fixedProperties?:
        | (
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
          )[]
        | null
    kind?: EventsNodeApiKind
    /** @nullable */
    limit?: number | null
    math?: (typeof EventsNodeApiMath)[keyof typeof EventsNodeApiMath] | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
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
    properties?:
        | (
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
          )[]
        | null
    /** @nullable */
    response?: EventsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ActionsNodeApiKind = (typeof ActionsNodeApiKind)[keyof typeof ActionsNodeApiKind]

export const ActionsNodeApiKind = {
    ActionsNode: 'ActionsNode',
} as const

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
/**
 * @nullable
 */
export type ActionsNodeApiResponse = { [key: string]: unknown } | null | null

export interface ActionsNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?:
        | (
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
          )[]
        | null
    id: number
    kind?: ActionsNodeApiKind
    math?: (typeof ActionsNodeApiMath)[keyof typeof ActionsNodeApiMath] | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
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
    properties?:
        | (
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
          )[]
        | null
    /** @nullable */
    response?: ActionsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type DataWarehouseNodeApiKind = (typeof DataWarehouseNodeApiKind)[keyof typeof DataWarehouseNodeApiKind]

export const DataWarehouseNodeApiKind = {
    DataWarehouseNode: 'DataWarehouseNode',
} as const

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
/**
 * @nullable
 */
export type DataWarehouseNodeApiResponse = { [key: string]: unknown } | null | null

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
    fixedProperties?:
        | (
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
          )[]
        | null
    id: string
    id_field: string
    kind?: DataWarehouseNodeApiKind
    math?: (typeof DataWarehouseNodeApiMath)[keyof typeof DataWarehouseNodeApiMath] | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
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
    properties?:
        | (
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
          )[]
        | null
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
/**
 * @nullable
 */
export type GroupNodeApiResponse = { [key: string]: unknown } | null | null

export interface GroupNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?:
        | (
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
          )[]
        | null
    kind?: GroupNodeApiKind
    /** @nullable */
    limit?: number | null
    math?: (typeof GroupNodeApiMath)[keyof typeof GroupNodeApiMath] | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    /** @nullable */
    math_property_type?: string | null
    /** @nullable */
    name?: string | null
    /** Entities to combine in this group */
    nodes: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
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
    properties?:
        | (
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
          )[]
        | null
    /** @nullable */
    response?: GroupNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type AggregationAxisFormatApi = (typeof AggregationAxisFormatApi)[keyof typeof AggregationAxisFormatApi]

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

export const DetailedResultsAggregationTypeApi = {
    total: 'total',
    average: 'average',
    median: 'median',
} as const

export type ChartDisplayTypeApi = (typeof ChartDisplayTypeApi)[keyof typeof ChartDisplayTypeApi]

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
    TwoDimensionalHeatmap: 'TwoDimensionalHeatmap',
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
    position?: PositionApi | null
    value: number
}

export type ResultCustomizationByApi = (typeof ResultCustomizationByApi)[keyof typeof ResultCustomizationByApi]

export const ResultCustomizationByApi = {
    value: 'value',
    position: 'position',
} as const

export type ResultCustomizationByValueApiAssignmentBy =
    (typeof ResultCustomizationByValueApiAssignmentBy)[keyof typeof ResultCustomizationByValueApiAssignmentBy]

export const ResultCustomizationByValueApiAssignmentBy = {
    value: 'value',
} as const

export type DataColorTokenApi = (typeof DataColorTokenApi)[keyof typeof DataColorTokenApi]

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

export interface ResultCustomizationByValueApi {
    assignmentBy?: ResultCustomizationByValueApiAssignmentBy
    color?: DataColorTokenApi | null
    /** @nullable */
    hidden?: boolean | null
}

export type ResultCustomizationByPositionApiAssignmentBy =
    (typeof ResultCustomizationByPositionApiAssignmentBy)[keyof typeof ResultCustomizationByPositionApiAssignmentBy]

export const ResultCustomizationByPositionApiAssignmentBy = {
    position: 'position',
} as const

export interface ResultCustomizationByPositionApi {
    assignmentBy?: ResultCustomizationByPositionApiAssignmentBy
    color?: DataColorTokenApi | null
    /** @nullable */
    hidden?: boolean | null
}

export type YAxisScaleTypeApi = (typeof YAxisScaleTypeApi)[keyof typeof YAxisScaleTypeApi]

export const YAxisScaleTypeApi = {
    log10: 'log10',
    linear: 'linear',
} as const

/**
 * Customizations for the appearance of result datasets.
 */
export type TrendsFilterApiResultCustomizations =
    | { [key: string]: ResultCustomizationByValueApi }
    | { [key: string]: ResultCustomizationByPositionApi }
    | null

export interface TrendsFilterApi {
    aggregationAxisFormat?: AggregationAxisFormatApi | null
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
    detailedResultsAggregationType?: DetailedResultsAggregationTypeApi | null
    display?: ChartDisplayTypeApi | null
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
    resultCustomizationBy?: ResultCustomizationByApi | null
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
    yAxisScaleType?: YAxisScaleTypeApi | null
}

export interface TrendsQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi | null
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    /** Whether we should be comparing against a specific conversion goal */
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    kind?: TrendsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
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
          )[]
        | PropertyGroupFilterApi
        | null
    response?: TrendsQueryResponseApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (GroupNodeApi | EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** Properties specific to the trends insight */
    trendsFilter?: TrendsFilterApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type BreakdownAttributionTypeApi = (typeof BreakdownAttributionTypeApi)[keyof typeof BreakdownAttributionTypeApi]

export const BreakdownAttributionTypeApi = {
    first_touch: 'first_touch',
    last_touch: 'last_touch',
    all_events: 'all_events',
    step: 'step',
} as const

export type FunnelExclusionEventsNodeApiKind =
    (typeof FunnelExclusionEventsNodeApiKind)[keyof typeof FunnelExclusionEventsNodeApiKind]

export const FunnelExclusionEventsNodeApiKind = {
    EventsNode: 'EventsNode',
} as const

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
/**
 * @nullable
 */
export type FunnelExclusionEventsNodeApiResponse = { [key: string]: unknown } | null | null

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
    fixedProperties?:
        | (
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
          )[]
        | null
    funnelFromStep: number
    funnelToStep: number
    kind?: FunnelExclusionEventsNodeApiKind
    /** @nullable */
    limit?: number | null
    math?: (typeof FunnelExclusionEventsNodeApiMath)[keyof typeof FunnelExclusionEventsNodeApiMath] | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
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
    properties?:
        | (
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
          )[]
        | null
    /** @nullable */
    response?: FunnelExclusionEventsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type FunnelExclusionActionsNodeApiKind =
    (typeof FunnelExclusionActionsNodeApiKind)[keyof typeof FunnelExclusionActionsNodeApiKind]

export const FunnelExclusionActionsNodeApiKind = {
    ActionsNode: 'ActionsNode',
} as const

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
/**
 * @nullable
 */
export type FunnelExclusionActionsNodeApiResponse = { [key: string]: unknown } | null | null

export interface FunnelExclusionActionsNodeApi {
    /** @nullable */
    custom_name?: string | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?:
        | (
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
          )[]
        | null
    funnelFromStep: number
    funnelToStep: number
    id: number
    kind?: FunnelExclusionActionsNodeApiKind
    math?: (typeof FunnelExclusionActionsNodeApiMath)[keyof typeof FunnelExclusionActionsNodeApiMath] | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    /** @nullable */
    math_hogql?: string | null
    /** @nullable */
    math_multiplier?: number | null
    /** @nullable */
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
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
    properties?:
        | (
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
          )[]
        | null
    /** @nullable */
    response?: FunnelExclusionActionsNodeApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type StepOrderValueApi = (typeof StepOrderValueApi)[keyof typeof StepOrderValueApi]

export const StepOrderValueApi = {
    strict: 'strict',
    unordered: 'unordered',
    ordered: 'ordered',
} as const

export type FunnelStepReferenceApi = (typeof FunnelStepReferenceApi)[keyof typeof FunnelStepReferenceApi]

export const FunnelStepReferenceApi = {
    total: 'total',
    previous: 'previous',
} as const

export type FunnelVizTypeApi = (typeof FunnelVizTypeApi)[keyof typeof FunnelVizTypeApi]

export const FunnelVizTypeApi = {
    steps: 'steps',
    time_to_convert: 'time_to_convert',
    trends: 'trends',
} as const

export type FunnelConversionWindowTimeUnitApi =
    (typeof FunnelConversionWindowTimeUnitApi)[keyof typeof FunnelConversionWindowTimeUnitApi]

export const FunnelConversionWindowTimeUnitApi = {
    second: 'second',
    minute: 'minute',
    hour: 'hour',
    day: 'day',
    week: 'week',
    month: 'month',
} as const

export type FunnelLayoutApi = (typeof FunnelLayoutApi)[keyof typeof FunnelLayoutApi]

export const FunnelLayoutApi = {
    horizontal: 'horizontal',
    vertical: 'vertical',
} as const

/**
 * Customizations for the appearance of result datasets.
 * @nullable
 */
export type FunnelsFilterApiResultCustomizations = { [key: string]: ResultCustomizationByValueApi } | null | null

export interface FunnelsFilterApi {
    /** @nullable */
    binCount?: number | null
    breakdownAttributionType?: BreakdownAttributionTypeApi | null
    /** @nullable */
    breakdownAttributionValue?: number | null
    /** @nullable */
    exclusions?: (FunnelExclusionEventsNodeApi | FunnelExclusionActionsNodeApi)[] | null
    /** @nullable */
    funnelAggregateByHogQL?: string | null
    /** @nullable */
    funnelFromStep?: number | null
    funnelOrderType?: StepOrderValueApi | null
    funnelStepReference?: FunnelStepReferenceApi | null
    /**
     * To select the range of steps for trends & time to convert funnels, 0-indexed
     * @nullable
     */
    funnelToStep?: number | null
    funnelVizType?: FunnelVizTypeApi | null
    /** @nullable */
    funnelWindowInterval?: number | null
    funnelWindowIntervalUnit?: FunnelConversionWindowTimeUnitApi | null
    /**
     * Goal Lines
     * @nullable
     */
    goalLines?: GoalLineApi[] | null
    /** @nullable */
    hiddenLegendBreakdowns?: string[] | null
    layout?: FunnelLayoutApi | null
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

export type FunnelsQueryApiKind = (typeof FunnelsQueryApiKind)[keyof typeof FunnelsQueryApiKind]

export const FunnelsQueryApiKind = {
    FunnelsQuery: 'FunnelsQuery',
} as const

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
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface FunnelsQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi | null
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Properties specific to the funnels insight */
    funnelsFilter?: FunnelsFilterApi | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    kind?: FunnelsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
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
          )[]
        | PropertyGroupFilterApi
        | null
    response?: FunnelsQueryResponseApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type RetentionQueryApiKind = (typeof RetentionQueryApiKind)[keyof typeof RetentionQueryApiKind]

export const RetentionQueryApiKind = {
    RetentionQuery: 'RetentionQuery',
} as const

export interface RetentionValueApi {
    count: number
    /** @nullable */
    label?: string | null
}

export interface RetentionResultApi {
    /** Optional breakdown value for retention cohorts */
    breakdown_value?: string | number | null
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
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RetentionResultApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type RetentionDashboardDisplayTypeApi =
    (typeof RetentionDashboardDisplayTypeApi)[keyof typeof RetentionDashboardDisplayTypeApi]

export const RetentionDashboardDisplayTypeApi = {
    table_only: 'table_only',
    graph_only: 'graph_only',
    all: 'all',
} as const

export type MeanRetentionCalculationApi = (typeof MeanRetentionCalculationApi)[keyof typeof MeanRetentionCalculationApi]

export const MeanRetentionCalculationApi = {
    simple: 'simple',
    weighted: 'weighted',
    none: 'none',
} as const

export type RetentionPeriodApi = (typeof RetentionPeriodApi)[keyof typeof RetentionPeriodApi]

export const RetentionPeriodApi = {
    Hour: 'Hour',
    Day: 'Day',
    Week: 'Week',
    Month: 'Month',
} as const

export type RetentionReferenceApi = (typeof RetentionReferenceApi)[keyof typeof RetentionReferenceApi]

export const RetentionReferenceApi = {
    total: 'total',
    previous: 'previous',
} as const

export type RetentionTypeApi = (typeof RetentionTypeApi)[keyof typeof RetentionTypeApi]

export const RetentionTypeApi = {
    retention_recurring: 'retention_recurring',
    retention_first_time: 'retention_first_time',
    retention_first_ever_occurrence: 'retention_first_ever_occurrence',
} as const

export type RetentionEntityKindApi = (typeof RetentionEntityKindApi)[keyof typeof RetentionEntityKindApi]

export const RetentionEntityKindApi = {
    ActionsNode: 'ActionsNode',
    EventsNode: 'EventsNode',
} as const

export type EntityTypeApi = (typeof EntityTypeApi)[keyof typeof EntityTypeApi]

export const EntityTypeApi = {
    actions: 'actions',
    events: 'events',
    data_warehouse: 'data_warehouse',
    new_entity: 'new_entity',
    groups: 'groups',
} as const

export interface RetentionEntityApi {
    /** @nullable */
    custom_name?: string | null
    id?: string | number | null
    kind?: RetentionEntityKindApi | null
    /** @nullable */
    name?: string | null
    /** @nullable */
    order?: number | null
    /**
     * filters on the event
     * @nullable
     */
    properties?:
        | (
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
          )[]
        | null
    type?: EntityTypeApi | null
    /** @nullable */
    uuid?: string | null
}

export type TimeWindowModeApi = (typeof TimeWindowModeApi)[keyof typeof TimeWindowModeApi]

export const TimeWindowModeApi = {
    strict_calendar_dates: 'strict_calendar_dates',
    '24_hour_windows': '24_hour_windows',
} as const

export interface RetentionFilterApi {
    /** @nullable */
    cumulative?: boolean | null
    dashboardDisplay?: RetentionDashboardDisplayTypeApi | null
    /** controls the display of the retention graph */
    display?: ChartDisplayTypeApi | null
    /** @nullable */
    goalLines?: GoalLineApi[] | null
    meanRetentionCalculation?: MeanRetentionCalculationApi | null
    /** @nullable */
    minimumOccurrences?: number | null
    period?: RetentionPeriodApi | null
    /**
     * Custom brackets for retention calculations
     * @nullable
     */
    retentionCustomBrackets?: number[] | null
    /** Whether retention is with regard to initial cohort size, or that of the previous period. */
    retentionReference?: RetentionReferenceApi | null
    retentionType?: RetentionTypeApi | null
    returningEntity?: RetentionEntityApi | null
    /**
     * The selected interval to display across all cohorts (null = show all intervals for each cohort)
     * @nullable
     */
    selectedInterval?: number | null
    /** @nullable */
    showTrendLines?: boolean | null
    targetEntity?: RetentionEntityApi | null
    /** The time window mode to use for retention calculations */
    timeWindowMode?: TimeWindowModeApi | null
    /** @nullable */
    totalIntervals?: number | null
}

export interface RetentionQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi | null
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    kind?: RetentionQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
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
          )[]
        | PropertyGroupFilterApi
        | null
    response?: RetentionQueryResponseApi | null
    /** Properties specific to the retention insight */
    retentionFilter: RetentionFilterApi
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type FunnelPathTypeApi = (typeof FunnelPathTypeApi)[keyof typeof FunnelPathTypeApi]

export const FunnelPathTypeApi = {
    funnel_path_before_step: 'funnel_path_before_step',
    funnel_path_between_steps: 'funnel_path_between_steps',
    funnel_path_after_step: 'funnel_path_after_step',
} as const

export interface FunnelPathsFilterApi {
    funnelPathType?: FunnelPathTypeApi | null
    funnelSource: FunnelsQueryApi
    /** @nullable */
    funnelStep?: number | null
}

export type PathsQueryApiKind = (typeof PathsQueryApiKind)[keyof typeof PathsQueryApiKind]

export const PathsQueryApiKind = {
    PathsQuery: 'PathsQuery',
} as const

export type PathTypeApi = (typeof PathTypeApi)[keyof typeof PathTypeApi]

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
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: PathsLinkApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

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
    dateRange?: DateRangeApi | null
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Used for displaying paths in relation to funnel steps. */
    funnelPathsFilter?: FunnelPathsFilterApi | null
    kind?: PathsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Properties specific to the paths insight */
    pathsFilter: PathsFilterApi
    /** Property filters for all series */
    properties?:
        | (
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
          )[]
        | PropertyGroupFilterApi
        | null
    response?: PathsQueryResponseApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type StickinessQueryApiKind = (typeof StickinessQueryApiKind)[keyof typeof StickinessQueryApiKind]

export const StickinessQueryApiKind = {
    StickinessQuery: 'StickinessQuery',
} as const

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
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: StickinessQueryResponseApiResultsItem[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type StickinessComputationModeApi =
    (typeof StickinessComputationModeApi)[keyof typeof StickinessComputationModeApi]

export const StickinessComputationModeApi = {
    non_cumulative: 'non_cumulative',
    cumulative: 'cumulative',
} as const

export type StickinessOperatorApi = (typeof StickinessOperatorApi)[keyof typeof StickinessOperatorApi]

export const StickinessOperatorApi = {
    gte: 'gte',
    lte: 'lte',
    exact: 'exact',
} as const

export interface StickinessCriteriaApi {
    operator: StickinessOperatorApi
    value: number
}

/**
 * Customizations for the appearance of result datasets.
 */
export type StickinessFilterApiResultCustomizations =
    | { [key: string]: ResultCustomizationByValueApi }
    | { [key: string]: ResultCustomizationByPositionApi }
    | null

export interface StickinessFilterApi {
    computedAs?: StickinessComputationModeApi | null
    display?: ChartDisplayTypeApi | null
    /** @nullable */
    hiddenLegendIndexes?: number[] | null
    /** Whether result datasets are associated by their values or by their order. */
    resultCustomizationBy?: ResultCustomizationByApi | null
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: StickinessFilterApiResultCustomizations
    /** @nullable */
    showLegend?: boolean | null
    /** @nullable */
    showMultipleYAxes?: boolean | null
    /** @nullable */
    showValuesOnSeries?: boolean | null
    stickinessCriteria?: StickinessCriteriaApi | null
}

export interface StickinessQueryApi {
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    /**
     * Colors used in the insight's visualization
     * @nullable
     */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    /**
     * How many intervals comprise a period. Only used for cohorts, otherwise default 1.
     * @nullable
     */
    intervalCount?: number | null
    kind?: StickinessQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
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
          )[]
        | PropertyGroupFilterApi
        | null
    response?: StickinessQueryResponseApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: StickinessFilterApi | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type LifecycleQueryApiKind = (typeof LifecycleQueryApiKind)[keyof typeof LifecycleQueryApiKind]

export const LifecycleQueryApiKind = {
    LifecycleQuery: 'LifecycleQuery',
} as const

export type LifecycleToggleApi = (typeof LifecycleToggleApi)[keyof typeof LifecycleToggleApi]

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
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: LifecycleQueryResponseApiResultsItem[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

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
    dateRange?: DateRangeApi | null
    /**
     * Exclude internal and test users by applying the respective filters
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    kind?: LifecycleQueryApiKind
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: LifecycleFilterApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
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
          )[]
        | PropertyGroupFilterApi
        | null
    response?: LifecycleQueryResponseApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type WebStatsBreakdownApi = (typeof WebStatsBreakdownApi)[keyof typeof WebStatsBreakdownApi]

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

export type WebStatsTableQueryApiKind = (typeof WebStatsTableQueryApiKind)[keyof typeof WebStatsTableQueryApiKind]

export const WebStatsTableQueryApiKind = {
    WebStatsTableQuery: 'WebStatsTableQuery',
} as const

export type WebAnalyticsOrderByFieldsApi =
    (typeof WebAnalyticsOrderByFieldsApi)[keyof typeof WebAnalyticsOrderByFieldsApi]

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
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
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
    forceSamplingRate?: SamplingRateApi | null
}

export const WebStatsTableQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export interface WebStatsTableQueryApi {
    /**
     * Groups aggregation - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    aggregation_group_type_index?: number | null
    breakdownBy: WebStatsBreakdownApi
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /**
     * Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
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
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: WebStatsTableQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /** @nullable */
    orderBy?: (typeof WebStatsTableQueryApiOrderByItem)[keyof typeof WebStatsTableQueryApiOrderByItem][] | null
    properties: (EventPropertyFilterApi | PersonPropertyFilterApi | SessionPropertyFilterApi)[]
    response?: WebStatsTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type WebOverviewQueryApiKind = (typeof WebOverviewQueryApiKind)[keyof typeof WebOverviewQueryApiKind]

export const WebOverviewQueryApiKind = {
    WebOverviewQuery: 'WebOverviewQuery',
} as const

export type WebAnalyticsItemKindApi = (typeof WebAnalyticsItemKindApi)[keyof typeof WebAnalyticsItemKindApi]

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
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: WebOverviewItemApi[]
    samplingRate?: SamplingRateApi | null
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    usedPreAggregatedTables?: boolean | null
}

export const WebOverviewQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export interface WebOverviewQueryApi {
    /**
     * Groups aggregation - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /**
     * Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    /** @nullable */
    doPathCleaning?: boolean | null
    /** @nullable */
    filterTestAccounts?: boolean | null
    /** @nullable */
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: WebOverviewQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    orderBy?: (typeof WebOverviewQueryApiOrderByItem)[keyof typeof WebOverviewQueryApiOrderByItem][] | null
    properties: (EventPropertyFilterApi | PersonPropertyFilterApi | SessionPropertyFilterApi)[]
    response?: WebOverviewQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type DataWarehouseSyncIntervalApi =
    (typeof DataWarehouseSyncIntervalApi)[keyof typeof DataWarehouseSyncIntervalApi]

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
    query?:
        | HogQLQueryApi
        | TrendsQueryApi
        | FunnelsQueryApi
        | RetentionQueryApi
        | PathsQueryApi
        | StickinessQueryApi
        | LifecycleQueryApi
        | WebStatsTableQueryApi
        | WebOverviewQueryApi
        | null
    /** How frequently should the underlying materialized view be updated */
    sync_frequency?: DataWarehouseSyncIntervalApi | null
}

/**
 * Map of Insight query keys to be overridden at execution time. For example:   Assuming query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode","name": "$pageview","event": "$pageview","math": "total"}]}   If query_override = {"series": [{"kind": "EventsNode","name": "$identify","event": "$identify","math": "total"}]}   The query executed will return the count of $identify events, instead of $pageview's
 * @nullable
 */
export type EndpointRunRequestApiQueryOverride = { [key: string]: unknown } | null | null

/**
 * A map for overriding HogQL query variables, where the key is the variable name and the value is the variable value. Variable must be set on the endpoint's query between curly braces (i.e. {variable.from_date}) For example: {"from_date": "1970-01-01"}
 * @nullable
 */
export type EndpointRunRequestApiVariables = { [key: string]: unknown } | null | null

export interface DashboardFilterApi {
    breakdown_filter?: BreakdownFilterApi | null
    /** @nullable */
    date_from?: string | null
    /** @nullable */
    date_to?: string | null
    /** @nullable */
    explicitDate?: boolean | null
    /** @nullable */
    properties?:
        | (
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
          )[]
        | null
}

export type EndpointRefreshModeApi = (typeof EndpointRefreshModeApi)[keyof typeof EndpointRefreshModeApi]

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
    filters_override?: DashboardFilterApi | null
    /**
     * Map of Insight query keys to be overridden at execution time. For example:   Assuming query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode","name": "$pageview","event": "$pageview","math": "total"}]}   If query_override = {"series": [{"kind": "EventsNode","name": "$identify","event": "$identify","math": "total"}]}   The query executed will return the count of $identify events, instead of $pageview's
     * @nullable
     */
    query_override?: EndpointRunRequestApiQueryOverride
    refresh?: EndpointRefreshModeApi | null
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
