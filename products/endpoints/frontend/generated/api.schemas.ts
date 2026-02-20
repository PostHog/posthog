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

/**
 * Event properties
 */
export type EventPropertyFilterApiType = (typeof EventPropertyFilterApiType)[keyof typeof EventPropertyFilterApiType]

export const EventPropertyFilterApiType = {
    Event: 'event',
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
    Person: 'person',
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
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export type ElementPropertyFilterApiType =
    (typeof ElementPropertyFilterApiType)[keyof typeof ElementPropertyFilterApiType]

export const ElementPropertyFilterApiType = {
    Element: 'element',
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
    EventMetadata: 'event_metadata',
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
    Session: 'session',
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
    Id: 'id',
} as const

export type CohortPropertyFilterApiType = (typeof CohortPropertyFilterApiType)[keyof typeof CohortPropertyFilterApiType]

export const CohortPropertyFilterApiType = {
    Cohort: 'cohort',
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
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export type RecordingPropertyFilterApiType =
    (typeof RecordingPropertyFilterApiType)[keyof typeof RecordingPropertyFilterApiType]

export const RecordingPropertyFilterApiType = {
    Recording: 'recording',
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
    LogEntry: 'log_entry',
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
    Group: 'group',
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
    Feature: 'feature',
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
    FlagEvaluatesTo: 'flag_evaluates_to',
} as const

/**
 * Feature flag dependency
 */
export type FlagPropertyFilterApiType = (typeof FlagPropertyFilterApiType)[keyof typeof FlagPropertyFilterApiType]

export const FlagPropertyFilterApiType = {
    Flag: 'flag',
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
    Hogql: 'hogql',
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
    Empty: 'empty',
} as const

export interface EmptyPropertyFilterApi {
    type?: EmptyPropertyFilterApiType
}

export type DataWarehousePropertyFilterApiType =
    (typeof DataWarehousePropertyFilterApiType)[keyof typeof DataWarehousePropertyFilterApiType]

export const DataWarehousePropertyFilterApiType = {
    DataWarehouse: 'data_warehouse',
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
    DataWarehousePersonProperty: 'data_warehouse_person_property',
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
    ErrorTrackingIssue: 'error_tracking_issue',
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
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
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
    RevenueAnalytics: 'revenue_analytics',
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
    CountPageviews: 'count_pageviews',
    UniqUrls: 'uniq_urls',
    UniqPageScreenAutocaptures: 'uniq_page_screen_autocaptures',
} as const

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

export type CustomChannelFieldApi = (typeof CustomChannelFieldApi)[keyof typeof CustomChannelFieldApi]

export const CustomChannelFieldApi = {
    UtmSource: 'utm_source',
    UtmMedium: 'utm_medium',
    UtmCampaign: 'utm_campaign',
    ReferringDomain: 'referring_domain',
    Url: 'url',
    Pathname: 'pathname',
    Hostname: 'hostname',
} as const

export type CustomChannelOperatorApi = (typeof CustomChannelOperatorApi)[keyof typeof CustomChannelOperatorApi]

export const CustomChannelOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
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
    Auto: 'auto',
    Leftjoin: 'leftjoin',
    Subquery: 'subquery',
    LeftjoinConjoined: 'leftjoin_conjoined',
} as const

export type MaterializationModeApi = (typeof MaterializationModeApi)[keyof typeof MaterializationModeApi]

export const MaterializationModeApi = {
    Auto: 'auto',
    LegacyNullAsString: 'legacy_null_as_string',
    LegacyNullAsNull: 'legacy_null_as_null',
    Disabled: 'disabled',
} as const

export type MaterializedColumnsOptimizationModeApi =
    (typeof MaterializedColumnsOptimizationModeApi)[keyof typeof MaterializedColumnsOptimizationModeApi]

export const MaterializedColumnsOptimizationModeApi = {
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type PersonsArgMaxVersionApi = (typeof PersonsArgMaxVersionApi)[keyof typeof PersonsArgMaxVersionApi]

export const PersonsArgMaxVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
} as const

export type PersonsJoinModeApi = (typeof PersonsJoinModeApi)[keyof typeof PersonsJoinModeApi]

export const PersonsJoinModeApi = {
    Inner: 'inner',
    Left: 'left',
} as const

export type PersonsOnEventsModeApi = (typeof PersonsOnEventsModeApi)[keyof typeof PersonsOnEventsModeApi]

export const PersonsOnEventsModeApi = {
    Disabled: 'disabled',
    PersonIdNoOverridePropertiesOnEvents: 'person_id_no_override_properties_on_events',
    PersonIdOverridePropertiesOnEvents: 'person_id_override_properties_on_events',
    PersonIdOverridePropertiesJoined: 'person_id_override_properties_joined',
} as const

export type PropertyGroupsModeApi = (typeof PropertyGroupsModeApi)[keyof typeof PropertyGroupsModeApi]

export const PropertyGroupsModeApi = {
    Enabled: 'enabled',
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type SessionTableVersionApi = (typeof SessionTableVersionApi)[keyof typeof SessionTableVersionApi]

export const SessionTableVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
    V3: 'v3',
} as const

export type SessionsV2JoinModeApi = (typeof SessionsV2JoinModeApi)[keyof typeof SessionsV2JoinModeApi]

export const SessionsV2JoinModeApi = {
    String: 'string',
    Uuid: 'uuid',
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
    Undecisive: 'undecisive',
    No: 'no',
    Partial: 'partial',
    Yes: 'yes',
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
    Cohort: 'cohort',
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Group: 'group',
    Session: 'session',
    Hogql: 'hogql',
    RevenueAnalytics: 'revenue_analytics',
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
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
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
    Total: 'total',
    Dau: 'dau',
    WeeklyActive: 'weekly_active',
    MonthlyActive: 'monthly_active',
    UniqueSession: 'unique_session',
    FirstTimeForUser: 'first_time_for_user',
    FirstMatchingEventForUser: 'first_matching_event_for_user',
} as const

export type FunnelMathTypeApi = (typeof FunnelMathTypeApi)[keyof typeof FunnelMathTypeApi]

export const FunnelMathTypeApi = {
    Total: 'total',
    FirstTimeForUser: 'first_time_for_user',
    FirstTimeForUserWithFilters: 'first_time_for_user_with_filters',
} as const

export type PropertyMathTypeApi = (typeof PropertyMathTypeApi)[keyof typeof PropertyMathTypeApi]

export const PropertyMathTypeApi = {
    Avg: 'avg',
    Sum: 'sum',
    Min: 'min',
    Max: 'max',
    Median: 'median',
    P75: 'p75',
    P90: 'p90',
    P95: 'p95',
    P99: 'p99',
} as const

export type CountPerActorMathTypeApi = (typeof CountPerActorMathTypeApi)[keyof typeof CountPerActorMathTypeApi]

export const CountPerActorMathTypeApi = {
    AvgCountPerActor: 'avg_count_per_actor',
    MinCountPerActor: 'min_count_per_actor',
    MaxCountPerActor: 'max_count_per_actor',
    MedianCountPerActor: 'median_count_per_actor',
    P75CountPerActor: 'p75_count_per_actor',
    P90CountPerActor: 'p90_count_per_actor',
    P95CountPerActor: 'p95_count_per_actor',
    P99CountPerActor: 'p99_count_per_actor',
} as const

export type ExperimentMetricMathTypeApi = (typeof ExperimentMetricMathTypeApi)[keyof typeof ExperimentMetricMathTypeApi]

export const ExperimentMetricMathTypeApi = {
    Total: 'total',
    Sum: 'sum',
    UniqueSession: 'unique_session',
    Min: 'min',
    Max: 'max',
    Avg: 'avg',
    Dau: 'dau',
    UniqueGroup: 'unique_group',
    Hogql: 'hogql',
} as const

export type CalendarHeatmapMathTypeApi = (typeof CalendarHeatmapMathTypeApi)[keyof typeof CalendarHeatmapMathTypeApi]

export const CalendarHeatmapMathTypeApi = {
    Total: 'total',
    Dau: 'dau',
} as const

export type MathGroupTypeIndexApi = (typeof MathGroupTypeIndexApi)[keyof typeof MathGroupTypeIndexApi]

export const MathGroupTypeIndexApi = {
    Number0: 0,
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number4: 4,
} as const

export type CurrencyCodeApi = (typeof CurrencyCodeApi)[keyof typeof CurrencyCodeApi]

export const CurrencyCodeApi = {
    Aed: 'AED',
    Afn: 'AFN',
    All: 'ALL',
    Amd: 'AMD',
    Ang: 'ANG',
    Aoa: 'AOA',
    Ars: 'ARS',
    Aud: 'AUD',
    Awg: 'AWG',
    Azn: 'AZN',
    Bam: 'BAM',
    Bbd: 'BBD',
    Bdt: 'BDT',
    Bgn: 'BGN',
    Bhd: 'BHD',
    Bif: 'BIF',
    Bmd: 'BMD',
    Bnd: 'BND',
    Bob: 'BOB',
    Brl: 'BRL',
    Bsd: 'BSD',
    Btc: 'BTC',
    Btn: 'BTN',
    Bwp: 'BWP',
    Byn: 'BYN',
    Bzd: 'BZD',
    Cad: 'CAD',
    Cdf: 'CDF',
    Chf: 'CHF',
    Clp: 'CLP',
    Cny: 'CNY',
    Cop: 'COP',
    Crc: 'CRC',
    Cve: 'CVE',
    Czk: 'CZK',
    Djf: 'DJF',
    Dkk: 'DKK',
    Dop: 'DOP',
    Dzd: 'DZD',
    Egp: 'EGP',
    Ern: 'ERN',
    Etb: 'ETB',
    Eur: 'EUR',
    Fjd: 'FJD',
    Gbp: 'GBP',
    Gel: 'GEL',
    Ghs: 'GHS',
    Gip: 'GIP',
    Gmd: 'GMD',
    Gnf: 'GNF',
    Gtq: 'GTQ',
    Gyd: 'GYD',
    Hkd: 'HKD',
    Hnl: 'HNL',
    Hrk: 'HRK',
    Htg: 'HTG',
    Huf: 'HUF',
    Idr: 'IDR',
    Ils: 'ILS',
    Inr: 'INR',
    Iqd: 'IQD',
    Irr: 'IRR',
    Isk: 'ISK',
    Jmd: 'JMD',
    Jod: 'JOD',
    Jpy: 'JPY',
    Kes: 'KES',
    Kgs: 'KGS',
    Khr: 'KHR',
    Kmf: 'KMF',
    Krw: 'KRW',
    Kwd: 'KWD',
    Kyd: 'KYD',
    Kzt: 'KZT',
    Lak: 'LAK',
    Lbp: 'LBP',
    Lkr: 'LKR',
    Lrd: 'LRD',
    Ltl: 'LTL',
    Lvl: 'LVL',
    Lsl: 'LSL',
    Lyd: 'LYD',
    Mad: 'MAD',
    Mdl: 'MDL',
    Mga: 'MGA',
    Mkd: 'MKD',
    Mmk: 'MMK',
    Mnt: 'MNT',
    Mop: 'MOP',
    Mru: 'MRU',
    Mtl: 'MTL',
    Mur: 'MUR',
    Mvr: 'MVR',
    Mwk: 'MWK',
    Mxn: 'MXN',
    Myr: 'MYR',
    Mzn: 'MZN',
    Nad: 'NAD',
    Ngn: 'NGN',
    Nio: 'NIO',
    Nok: 'NOK',
    Npr: 'NPR',
    Nzd: 'NZD',
    Omr: 'OMR',
    Pab: 'PAB',
    Pen: 'PEN',
    Pgk: 'PGK',
    Php: 'PHP',
    Pkr: 'PKR',
    Pln: 'PLN',
    Pyg: 'PYG',
    Qar: 'QAR',
    Ron: 'RON',
    Rsd: 'RSD',
    Rub: 'RUB',
    Rwf: 'RWF',
    Sar: 'SAR',
    Sbd: 'SBD',
    Scr: 'SCR',
    Sdg: 'SDG',
    Sek: 'SEK',
    Sgd: 'SGD',
    Srd: 'SRD',
    Ssp: 'SSP',
    Stn: 'STN',
    Syp: 'SYP',
    Szl: 'SZL',
    Thb: 'THB',
    Tjs: 'TJS',
    Tmt: 'TMT',
    Tnd: 'TND',
    Top: 'TOP',
    Try: 'TRY',
    Ttd: 'TTD',
    Twd: 'TWD',
    Tzs: 'TZS',
    Uah: 'UAH',
    Ugx: 'UGX',
    Usd: 'USD',
    Uyu: 'UYU',
    Uzs: 'UZS',
    Ves: 'VES',
    Vnd: 'VND',
    Vuv: 'VUV',
    Wst: 'WST',
    Xaf: 'XAF',
    Xcd: 'XCD',
    Xof: 'XOF',
    Xpf: 'XPF',
    Yer: 'YER',
    Zar: 'ZAR',
    Zmw: 'ZMW',
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
    Numeric: 'numeric',
    Duration: 'duration',
    DurationMs: 'duration_ms',
    Percentage: 'percentage',
    PercentageScaled: 'percentage_scaled',
    Currency: 'currency',
} as const

export type DetailedResultsAggregationTypeApi =
    (typeof DetailedResultsAggregationTypeApi)[keyof typeof DetailedResultsAggregationTypeApi]

export const DetailedResultsAggregationTypeApi = {
    Total: 'total',
    Average: 'average',
    Median: 'median',
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
    Start: 'start',
    End: 'end',
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
    Value: 'value',
    Position: 'position',
} as const

export type ResultCustomizationByValueApiAssignmentBy =
    (typeof ResultCustomizationByValueApiAssignmentBy)[keyof typeof ResultCustomizationByValueApiAssignmentBy]

export const ResultCustomizationByValueApiAssignmentBy = {
    Value: 'value',
} as const

export type DataColorTokenApi = (typeof DataColorTokenApi)[keyof typeof DataColorTokenApi]

export const DataColorTokenApi = {
    Preset1: 'preset-1',
    Preset2: 'preset-2',
    Preset3: 'preset-3',
    Preset4: 'preset-4',
    Preset5: 'preset-5',
    Preset6: 'preset-6',
    Preset7: 'preset-7',
    Preset8: 'preset-8',
    Preset9: 'preset-9',
    Preset10: 'preset-10',
    Preset11: 'preset-11',
    Preset12: 'preset-12',
    Preset13: 'preset-13',
    Preset14: 'preset-14',
    Preset15: 'preset-15',
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
    Position: 'position',
} as const

export interface ResultCustomizationByPositionApi {
    assignmentBy?: ResultCustomizationByPositionApiAssignmentBy
    color?: DataColorTokenApi | null
    /** @nullable */
    hidden?: boolean | null
}

export type YAxisScaleTypeApi = (typeof YAxisScaleTypeApi)[keyof typeof YAxisScaleTypeApi]

export const YAxisScaleTypeApi = {
    Log10: 'log10',
    Linear: 'linear',
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
    FirstTouch: 'first_touch',
    LastTouch: 'last_touch',
    AllEvents: 'all_events',
    Step: 'step',
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
    Strict: 'strict',
    Unordered: 'unordered',
    Ordered: 'ordered',
} as const

export type FunnelStepReferenceApi = (typeof FunnelStepReferenceApi)[keyof typeof FunnelStepReferenceApi]

export const FunnelStepReferenceApi = {
    Total: 'total',
    Previous: 'previous',
} as const

export type FunnelVizTypeApi = (typeof FunnelVizTypeApi)[keyof typeof FunnelVizTypeApi]

export const FunnelVizTypeApi = {
    Steps: 'steps',
    TimeToConvert: 'time_to_convert',
    Trends: 'trends',
} as const

export type FunnelConversionWindowTimeUnitApi =
    (typeof FunnelConversionWindowTimeUnitApi)[keyof typeof FunnelConversionWindowTimeUnitApi]

export const FunnelConversionWindowTimeUnitApi = {
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

export type FunnelLayoutApi = (typeof FunnelLayoutApi)[keyof typeof FunnelLayoutApi]

export const FunnelLayoutApi = {
    Horizontal: 'horizontal',
    Vertical: 'vertical',
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
    /**
     * Breakdown table sorting. Format: 'column_key' or '-column_key' (descending)
     * @nullable
     */
    breakdownSorting?: string | null
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
    /**
     * Display linear regression trend lines on the chart (only for historical trends viz)
     * @nullable
     */
    showTrendLines?: boolean | null
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
    series: (GroupNodeApi | EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
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

export type AggregationTypeApi = (typeof AggregationTypeApi)[keyof typeof AggregationTypeApi]

export const AggregationTypeApi = {
    Count: 'count',
    Sum: 'sum',
    Avg: 'avg',
} as const

export type RetentionDashboardDisplayTypeApi =
    (typeof RetentionDashboardDisplayTypeApi)[keyof typeof RetentionDashboardDisplayTypeApi]

export const RetentionDashboardDisplayTypeApi = {
    TableOnly: 'table_only',
    GraphOnly: 'graph_only',
    All: 'all',
} as const

export type MeanRetentionCalculationApi = (typeof MeanRetentionCalculationApi)[keyof typeof MeanRetentionCalculationApi]

export const MeanRetentionCalculationApi = {
    Simple: 'simple',
    Weighted: 'weighted',
    None: 'none',
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
    Total: 'total',
    Previous: 'previous',
} as const

export type RetentionTypeApi = (typeof RetentionTypeApi)[keyof typeof RetentionTypeApi]

export const RetentionTypeApi = {
    RetentionRecurring: 'retention_recurring',
    RetentionFirstTime: 'retention_first_time',
    RetentionFirstEverOccurrence: 'retention_first_ever_occurrence',
} as const

export type RetentionEntityKindApi = (typeof RetentionEntityKindApi)[keyof typeof RetentionEntityKindApi]

export const RetentionEntityKindApi = {
    ActionsNode: 'ActionsNode',
    EventsNode: 'EventsNode',
} as const

export type EntityTypeApi = (typeof EntityTypeApi)[keyof typeof EntityTypeApi]

export const EntityTypeApi = {
    Actions: 'actions',
    Events: 'events',
    DataWarehouse: 'data_warehouse',
    NewEntity: 'new_entity',
    Groups: 'groups',
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
    StrictCalendarDates: 'strict_calendar_dates',
    '24HourWindows': '24_hour_windows',
} as const

export interface RetentionFilterApi {
    /**
     * The property to aggregate when aggregationType is sum or avg
     * @nullable
     */
    aggregationProperty?: string | null
    /** The aggregation type to use for retention */
    aggregationType?: AggregationTypeApi | null
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
    FunnelPathBeforeStep: 'funnel_path_before_step',
    FunnelPathBetweenSteps: 'funnel_path_between_steps',
    FunnelPathAfterStep: 'funnel_path_after_step',
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
    Pageview: '$pageview',
    Screen: '$screen',
    CustomEvent: 'custom_event',
    Hogql: 'hogql',
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
    NonCumulative: 'non_cumulative',
    Cumulative: 'cumulative',
} as const

export type StickinessOperatorApi = (typeof StickinessOperatorApi)[keyof typeof StickinessOperatorApi]

export const StickinessOperatorApi = {
    Gte: 'gte',
    Lte: 'lte',
    Exact: 'exact',
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
    New: 'new',
    Resurrecting: 'resurrecting',
    Returning: 'returning',
    Dormant: 'dormant',
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
    Os: 'OS',
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
    Asc: 'ASC',
    Desc: 'DESC',
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
    includeHost?: boolean | null
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
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
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
    Unit: 'unit',
    DurationS: 'duration_s',
    Percentage: 'percentage',
    Currency: 'currency',
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
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
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
    /**
     * Target a specific version for updates (optional, defaults to current version)
     * @nullable
     */
    version?: number | null
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
    filters_override?: DashboardFilterApi | null
    /**
     * Maximum number of results to return. If not provided, returns all results.
     * @nullable
     */
    limit?: number | null
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

export interface EndpointLastExecutionTimesRequestApi {
    names: string[]
}

export interface QueryStatusResponseApi {
    query_status: QueryStatusApi
}
