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
 * * `private` - Private (only visible to creator)
 * `shared` - Shared with team
 */
export type VisibilityEnumApi = (typeof VisibilityEnumApi)[keyof typeof VisibilityEnumApi]

export const VisibilityEnumApi = {
    Private: 'private',
    Shared: 'shared',
} as const

export interface ColumnConfigurationApi {
    readonly id: string
    /** @maxLength 255 */
    context_key: string
    columns?: string[]
    /** @maxLength 255 */
    name?: string
    filters?: unknown
    visibility?: VisibilityEnumApi
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedColumnConfigurationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ColumnConfigurationApi[]
}

export interface PatchedColumnConfigurationApi {
    readonly id?: string
    /** @maxLength 255 */
    context_key?: string
    columns?: string[]
    /** @maxLength 255 */
    name?: string
    filters?: unknown
    visibility?: VisibilityEnumApi
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
    readonly updated_at?: string
}

export interface ElementApi {
    /**
     * @maxLength 10000
     * @nullable
     */
    text?: string | null
    /**
     * @maxLength 1000
     * @nullable
     */
    tag_name?: string | null
    /** @nullable */
    attr_class?: string[] | null
    /**
     * @maxLength 10000
     * @nullable
     */
    href?: string | null
    /**
     * @maxLength 10000
     * @nullable
     */
    attr_id?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_child?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_of_type?: number | null
    attributes?: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    order?: number | null
}

export interface PaginatedElementListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ElementApi[]
}

export interface PatchedElementApi {
    /**
     * @maxLength 10000
     * @nullable
     */
    text?: string | null
    /**
     * @maxLength 1000
     * @nullable
     */
    tag_name?: string | null
    /** @nullable */
    attr_class?: string[] | null
    /**
     * @maxLength 10000
     * @nullable
     */
    href?: string | null
    /**
     * @maxLength 10000
     * @nullable
     */
    attr_id?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_child?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    nth_of_type?: number | null
    attributes?: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    order?: number | null
}

export type InsightVizNodeApiKind = (typeof InsightVizNodeApiKind)[keyof typeof InsightVizNodeApiKind]

export const InsightVizNodeApiKind = {
    InsightVizNode: 'InsightVizNode',
} as const

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
    DataWarehousePersonProperty: 'data_warehouse_person_property',
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

export interface DateRangeApi {
    /**
   * Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),
-1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year).
   * @nullable
   */
    date_from?: string | null
    /**
     * End of the date range. Same format as date_from. Omit or null for "now".
     * @nullable
     */
    date_to?: string | null
    /**
     * Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.
     * @nullable
     */
    explicitDate?: boolean | null
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

export type InlineCohortCalculationApi = (typeof InlineCohortCalculationApi)[keyof typeof InlineCohortCalculationApi]

export const InlineCohortCalculationApi = {
    Off: 'off',
    Auto: 'auto',
    Always: 'always',
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
    inlineCohortCalculation?: InlineCohortCalculationApi | null
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
    /**
     * Push a `session_id_v7 IN (SELECT … FROM events WHERE …)` predicate into the raw_sessions subquery to limit aggregation to sessions that participate in the outer events filter.
     * @nullable
     */
    sessionIdPushdown?: boolean | null
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

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
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
    key: Key10Api
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

/**
 * @nullable
 */
export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null | null

export interface GroupPropertyFilterApi {
    /** @nullable */
    group_key_names?: GroupPropertyFilterApiGroupKeyNames
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

export type SpanPropertyFilterTypeApi = (typeof SpanPropertyFilterTypeApi)[keyof typeof SpanPropertyFilterTypeApi]

export const SpanPropertyFilterTypeApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export interface SpanPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type: SpanPropertyFilterTypeApi
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

export type WorkflowVariablePropertyFilterApiType =
    (typeof WorkflowVariablePropertyFilterApiType)[keyof typeof WorkflowVariablePropertyFilterApiType]

export const WorkflowVariablePropertyFilterApiType = {
    WorkflowVariable: 'workflow_variable',
} as const

export interface WorkflowVariablePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: WorkflowVariablePropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

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
        | SpanPropertyFilterApi
        | RevenueAnalyticsPropertyFilterApi
        | WorkflowVariablePropertyFilterApi
    )[]
}

export interface PropertyGroupFilterApi {
    type: FilterLogicalOperatorApi
    values: PropertyGroupFilterValueApi[]
}

export interface BoxPlotDatumApi {
    day: string
    label: string
    max: number
    mean: number
    median: number
    min: number
    p25: number
    p75: number
    /** @nullable */
    series_index?: number | null
    /** @nullable */
    series_label?: string | null
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

export type TrendsQueryResponseApiResultsItem = { [key: string]: unknown }

export interface TrendsQueryResponseApi {
    /** @nullable */
    boxplot_data?: BoxPlotDatumApi[] | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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

export type AggregationAxisFormatApi = (typeof AggregationAxisFormatApi)[keyof typeof AggregationAxisFormatApi]

export const AggregationAxisFormatApi = {
    Numeric: 'numeric',
    Duration: 'duration',
    DurationMs: 'duration_ms',
    Percentage: 'percentage',
    PercentageScaled: 'percentage_scaled',
    Currency: 'currency',
    Short: 'short',
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
    Auto: 'Auto',
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
    BoxPlot: 'BoxPlot',
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
    excludeBoxPlotOutliers?: boolean | null
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
    hideWeekends?: boolean | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
    Flow: 'flow',
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
    /**
     * For data warehouse based funnel insights when the aggregation target can't be mapped to persons or groups.
     * @nullable
     */
    customAggregationTarget?: boolean | null
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

export type FunnelsDataWarehouseNodeApiKind =
    (typeof FunnelsDataWarehouseNodeApiKind)[keyof typeof FunnelsDataWarehouseNodeApiKind]

export const FunnelsDataWarehouseNodeApiKind = {
    FunnelsDataWarehouseNode: 'FunnelsDataWarehouseNode',
} as const

export const FunnelsDataWarehouseNodeApiMath = {
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
export type FunnelsDataWarehouseNodeApiResponse = { [key: string]: unknown } | null | null

export interface FunnelsDataWarehouseNodeApi {
    aggregation_target_field: string
    /** @nullable */
    custom_name?: string | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    id: string
    id_field: string
    kind?: FunnelsDataWarehouseNodeApiKind
    math?: (typeof FunnelsDataWarehouseNodeApiMath)[keyof typeof FunnelsDataWarehouseNodeApiMath] | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    response?: FunnelsDataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
    series: (GroupNodeApi | EventsNodeApi | ActionsNodeApi | FunnelsDataWarehouseNodeApi)[]
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
    /** @nullable */
    aggregation_value?: number | null
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

export type AggregationPropertyTypeApi = (typeof AggregationPropertyTypeApi)[keyof typeof AggregationPropertyTypeApi]

export const AggregationPropertyTypeApi = {
    Event: 'event',
    Person: 'person',
} as const

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
    /**
     * Data warehouse field used as the actor identifier
     * @nullable
     */
    aggregation_target_field?: string | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /**
     * Data warehouse table name
     * @nullable
     */
    table_name?: string | null
    /**
     * Data warehouse timestamp field
     * @nullable
     */
    timestamp_field?: string | null
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
    /** The type of property to aggregate on (event or person). Defaults to event. */
    aggregationPropertyType?: AggregationPropertyTypeApi | null
    /** The aggregation type to use for retention */
    aggregationType?: AggregationTypeApi | null
    /** @nullable */
    cumulative?: boolean | null
    /**
     * For data warehouse based retention insights when the aggregation target can't be mapped to persons or groups.
     * @nullable
     */
    customAggregationTarget?: boolean | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
    /** @minimum 1 */
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
     * @minimum 1
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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

export type LifecycleDataWarehouseNodeApiKind =
    (typeof LifecycleDataWarehouseNodeApiKind)[keyof typeof LifecycleDataWarehouseNodeApiKind]

export const LifecycleDataWarehouseNodeApiKind = {
    LifecycleDataWarehouseNode: 'LifecycleDataWarehouseNode',
} as const

export const LifecycleDataWarehouseNodeApiMath = {
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
export type LifecycleDataWarehouseNodeApiResponse = { [key: string]: unknown } | null | null

export interface LifecycleDataWarehouseNodeApi {
    aggregation_target_field: string
    created_at_field: string
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    id: string
    kind?: LifecycleDataWarehouseNodeApiKind
    math?: (typeof LifecycleDataWarehouseNodeApiMath)[keyof typeof LifecycleDataWarehouseNodeApiMath] | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    response?: LifecycleDataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export interface LifecycleQueryApi {
    /**
     * Groups aggregation
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /**
     * For data warehouse based lifecycle insights when the aggregation target can't be mapped to persons or groups.
     * @nullable
     */
    customAggregationTarget?: boolean | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
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
    series: (EventsNodeApi | ActionsNodeApi | LifecycleDataWarehouseNodeApi)[]
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
    InitialReferringURL: 'InitialReferringURL',
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

export interface ActionsPieApi {
    /** @nullable */
    disableHoverOffset?: boolean | null
    /** @nullable */
    hideAggregation?: boolean | null
}

export interface RetentionApi {
    /** @nullable */
    hideLineGraph?: boolean | null
    /** @nullable */
    hideSizeColumn?: boolean | null
    /** @nullable */
    useSmallLayout?: boolean | null
}

export interface VizSpecificOptionsApi {
    ActionsPie?: ActionsPieApi | null
    RETENTION?: RetentionApi | null
}

export interface InsightVizNodeApi {
    /**
     * Query is embedded inside another bordered component
     * @nullable
     */
    embedded?: boolean | null
    /**
     * Show with most visual options enabled. Used in insight scene.
     * @nullable
     */
    full?: boolean | null
    /** @nullable */
    hidePersonsModal?: boolean | null
    /** @nullable */
    hideTooltipOnScroll?: boolean | null
    kind: InsightVizNodeApiKind
    /** @nullable */
    showCorrelationTable?: boolean | null
    /** @nullable */
    showFilters?: boolean | null
    /** @nullable */
    showHeader?: boolean | null
    /** @nullable */
    showLastComputation?: boolean | null
    /** @nullable */
    showLastComputationRefresh?: boolean | null
    /** @nullable */
    showResults?: boolean | null
    /** @nullable */
    showTable?: boolean | null
    source:
        | TrendsQueryApi
        | FunnelsQueryApi
        | RetentionQueryApi
        | PathsQueryApi
        | StickinessQueryApi
        | LifecycleQueryApi
        | WebStatsTableQueryApi
        | WebOverviewQueryApi
    /** @nullable */
    suppressSessionAnalysisWarning?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
    vizSpecificOptions?: VizSpecificOptionsApi | null
}

export type DataTableNodeViewPropsContextTypeApi =
    (typeof DataTableNodeViewPropsContextTypeApi)[keyof typeof DataTableNodeViewPropsContextTypeApi]

export const DataTableNodeViewPropsContextTypeApi = {
    EventDefinition: 'event_definition',
    TeamColumns: 'team_columns',
} as const

export interface DataTableNodeViewPropsContextApi {
    /** @nullable */
    eventDefinitionId?: string | null
    type: DataTableNodeViewPropsContextTypeApi
}

export type DataTableNodeApiKind = (typeof DataTableNodeApiKind)[keyof typeof DataTableNodeApiKind]

export const DataTableNodeApiKind = {
    DataTableNode: 'DataTableNode',
} as const

export interface ResponseApi {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /**
     * Cursor for fetching the next page of results
     * @nullable
     */
    nextCursor?: string | null
    /** @nullable */
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    types: string[]
}

export interface Response1Api {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit: number
    /** @nullable */
    missing_actors_count?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: string[] | null
}

export type Response2ApiKind = (typeof Response2ApiKind)[keyof typeof Response2ApiKind]

export const Response2ApiKind = {
    GroupsQuery: 'GroupsQuery',
} as const

export interface Response2Api {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: Response2ApiKind
    limit: number
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    types: string[]
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

export interface Response3Api {
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

export interface Response4Api {
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

export interface Response5Api {
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

export interface Response6Api {
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
}

export interface WebVitalsPathBreakdownResultItemApi {
    path: string
    value: number
}

export interface WebVitalsPathBreakdownResultApi {
    good: WebVitalsPathBreakdownResultItemApi[]
    needs_improvements: WebVitalsPathBreakdownResultItemApi[]
    poor: WebVitalsPathBreakdownResultItemApi[]
}

export interface Response8Api {
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
    /**
     * @minItems 1
     * @maxItems 1
     */
    results: WebVitalsPathBreakdownResultApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface Response9Api {
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
    results: unknown
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface Response10Api {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
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
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    types: string[]
}

export interface Response11Api {
    /** @nullable */
    columns?: string[] | null
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
    results: unknown[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface Response12Api {
    /** @nullable */
    columns?: string[] | null
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

export interface RevenueAnalyticsMRRQueryResultItemApi {
    churn: unknown
    contraction: unknown
    expansion: unknown
    new: unknown
    total: unknown
}

export interface Response13Api {
    /** @nullable */
    columns?: string[] | null
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
    results: RevenueAnalyticsMRRQueryResultItemApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type RevenueAnalyticsOverviewItemKeyApi =
    (typeof RevenueAnalyticsOverviewItemKeyApi)[keyof typeof RevenueAnalyticsOverviewItemKeyApi]

export const RevenueAnalyticsOverviewItemKeyApi = {
    Revenue: 'revenue',
    PayingCustomerCount: 'paying_customer_count',
    AvgRevenuePerCustomer: 'avg_revenue_per_customer',
} as const

export interface RevenueAnalyticsOverviewItemApi {
    key: RevenueAnalyticsOverviewItemKeyApi
    value: number
}

export interface Response14Api {
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
    results: RevenueAnalyticsOverviewItemApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface Response15Api {
    /** @nullable */
    columns?: string[] | null
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

export interface Response16Api {
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
    results: unknown
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface MarketingAnalyticsItemApi {
    /** @nullable */
    changeFromPreviousPct?: number | null
    /** @nullable */
    hasComparison?: boolean | null
    /** @nullable */
    isIncreaseBad?: boolean | null
    key: string
    kind: WebAnalyticsItemKindApi
    previous?: number | string | null
    value?: number | string | null
}

export interface Response18Api {
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
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export type Response19ApiResults = { [key: string]: MarketingAnalyticsItemApi }

export interface Response19Api {
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
    results: Response19ApiResults
    samplingRate?: SamplingRateApi | null
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface Response20Api {
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
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface VolumeBucketApi {
    label: string
    value: number
}

export interface ErrorTrackingIssueAggregationsApi {
    occurrences: number
    sessions: number
    users: number
    /** @nullable */
    volumeRange?: number[] | null
    volume_buckets: VolumeBucketApi[]
}

export type ErrorTrackingIssueAssigneeTypeApi =
    (typeof ErrorTrackingIssueAssigneeTypeApi)[keyof typeof ErrorTrackingIssueAssigneeTypeApi]

export const ErrorTrackingIssueAssigneeTypeApi = {
    User: 'user',
    Role: 'role',
} as const

export interface ErrorTrackingIssueAssigneeApi {
    id: string | number
    type: ErrorTrackingIssueAssigneeTypeApi
}

export interface ErrorTrackingIssueCohortApi {
    id: number
    name: string
}

export type IntegrationKindApi = (typeof IntegrationKindApi)[keyof typeof IntegrationKindApi]

export const IntegrationKindApi = {
    Slack: 'slack',
    SlackPosthogCode: 'slack-posthog-code',
    Salesforce: 'salesforce',
    Hubspot: 'hubspot',
    GooglePubsub: 'google-pubsub',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
    GoogleCloudStorage: 'google-cloud-storage',
    GoogleAds: 'google-ads',
    GoogleSheets: 'google-sheets',
    LinkedinAds: 'linkedin-ads',
    Snapchat: 'snapchat',
    Intercom: 'intercom',
    Email: 'email',
    Twilio: 'twilio',
    Linear: 'linear',
    Github: 'github',
    Gitlab: 'gitlab',
    MetaAds: 'meta-ads',
    Clickup: 'clickup',
    RedditAds: 'reddit-ads',
    Databricks: 'databricks',
    TiktokAds: 'tiktok-ads',
    BingAds: 'bing-ads',
    Vercel: 'vercel',
    AzureBlob: 'azure-blob',
    Firebase: 'firebase',
    Jira: 'jira',
    PinterestAds: 'pinterest-ads',
    CustomerioApp: 'customerio-app',
    CustomerioWebhook: 'customerio-webhook',
    CustomerioTrack: 'customerio-track',
} as const

export interface ErrorTrackingExternalReferenceIntegrationApi {
    display_name: string
    id: number
    kind: IntegrationKindApi
}

export interface ErrorTrackingExternalReferenceApi {
    external_url: string
    id: string
    integration: ErrorTrackingExternalReferenceIntegrationApi
}

export interface FirstEventApi {
    distinct_id: string
    properties: string
    timestamp: string
    uuid: string
}

export interface LastEventApi {
    distinct_id: string
    properties: string
    timestamp: string
    uuid: string
}

export type ErrorTrackingIssueStatusApi = (typeof ErrorTrackingIssueStatusApi)[keyof typeof ErrorTrackingIssueStatusApi]

export const ErrorTrackingIssueStatusApi = {
    Archived: 'archived',
    Active: 'active',
    Resolved: 'resolved',
    PendingRelease: 'pending_release',
    Suppressed: 'suppressed',
} as const

export interface ErrorTrackingIssueApi {
    aggregations?: ErrorTrackingIssueAggregationsApi | null
    assignee?: ErrorTrackingIssueAssigneeApi | null
    cohort?: ErrorTrackingIssueCohortApi | null
    /** @nullable */
    description?: string | null
    /** @nullable */
    external_issues?: ErrorTrackingExternalReferenceApi[] | null
    first_event?: FirstEventApi | null
    first_seen: string
    /** @nullable */
    function?: string | null
    id: string
    last_event?: LastEventApi | null
    last_seen: string
    /** @nullable */
    library?: string | null
    /** @nullable */
    name?: string | null
    /** @nullable */
    source?: string | null
    status: ErrorTrackingIssueStatusApi
}

export interface Response21Api {
    /** @nullable */
    columns?: string[] | null
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
    results: ErrorTrackingIssueApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface PopulationApi {
    both: number
    exception_only: number
    neither: number
    success_only: number
}

export interface ErrorTrackingCorrelatedIssueApi {
    assignee?: ErrorTrackingIssueAssigneeApi | null
    cohort?: ErrorTrackingIssueCohortApi | null
    /** @nullable */
    description?: string | null
    event: string
    /** @nullable */
    external_issues?: ErrorTrackingExternalReferenceApi[] | null
    first_seen: string
    id: string
    last_seen: string
    /** @nullable */
    library?: string | null
    /** @nullable */
    name?: string | null
    odds_ratio: number
    population: PopulationApi
    status: ErrorTrackingIssueStatusApi
}

export interface Response22Api {
    /** @nullable */
    columns?: string[] | null
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
    results: ErrorTrackingCorrelatedIssueApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export type Response23ApiKind = (typeof Response23ApiKind)[keyof typeof Response23ApiKind]

export const Response23ApiKind = {
    ExperimentFunnelsQuery: 'ExperimentFunnelsQuery',
} as const

export type ExperimentSignificanceCodeApi =
    (typeof ExperimentSignificanceCodeApi)[keyof typeof ExperimentSignificanceCodeApi]

export const ExperimentSignificanceCodeApi = {
    Significant: 'significant',
    NotEnoughExposure: 'not_enough_exposure',
    LowWinProbability: 'low_win_probability',
    HighLoss: 'high_loss',
    HighPValue: 'high_p_value',
} as const

export interface ExperimentVariantFunnelsBaseStatsApi {
    failure_count: number
    key: string
    success_count: number
}

export type Response23ApiCredibleIntervals = { [key: string]: number[] }

export type Response23ApiInsightItemItem = { [key: string]: unknown }

export type Response23ApiProbability = { [key: string]: number }

export interface Response23Api {
    credible_intervals: Response23ApiCredibleIntervals
    expected_loss: number
    funnels_query?: FunnelsQueryApi | null
    insight: Response23ApiInsightItemItem[][]
    kind?: Response23ApiKind
    probability: Response23ApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    /** @nullable */
    stats_version?: number | null
    variants: ExperimentVariantFunnelsBaseStatsApi[]
}

export type Response24ApiKind = (typeof Response24ApiKind)[keyof typeof Response24ApiKind]

export const Response24ApiKind = {
    ExperimentTrendsQuery: 'ExperimentTrendsQuery',
} as const

export interface ExperimentVariantTrendsBaseStatsApi {
    absolute_exposure: number
    count: number
    exposure: number
    key: string
}

export type Response24ApiCredibleIntervals = { [key: string]: number[] }

export type Response24ApiInsightItem = { [key: string]: unknown }

export type Response24ApiProbability = { [key: string]: number }

export interface Response24Api {
    count_query?: TrendsQueryApi | null
    credible_intervals: Response24ApiCredibleIntervals
    exposure_query?: TrendsQueryApi | null
    insight: Response24ApiInsightItem[]
    kind?: Response24ApiKind
    p_value: number
    probability: Response24ApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    /** @nullable */
    stats_version?: number | null
    variants: ExperimentVariantTrendsBaseStatsApi[]
}

export type AIEventTypeApi = (typeof AIEventTypeApi)[keyof typeof AIEventTypeApi]

export const AIEventTypeApi = {
    AiGeneration: '$ai_generation',
    AiEmbedding: '$ai_embedding',
    AiSpan: '$ai_span',
    AiTrace: '$ai_trace',
    AiMetric: '$ai_metric',
    AiFeedback: '$ai_feedback',
    AiEvaluation: '$ai_evaluation',
    AiTraceSummary: '$ai_trace_summary',
    AiGenerationSummary: '$ai_generation_summary',
    AiTraceClusters: '$ai_trace_clusters',
    AiGenerationClusters: '$ai_generation_clusters',
} as const

export type LLMTraceEventApiProperties = { [key: string]: unknown }

export interface LLMTraceEventApi {
    createdAt: string
    event: AIEventTypeApi | string
    id: string
    properties: LLMTraceEventApiProperties
}

export type LLMTracePersonApiProperties = { [key: string]: unknown }

export interface LLMTracePersonApi {
    created_at: string
    distinct_id: string
    properties: LLMTracePersonApiProperties
    uuid: string
}

export interface LLMTraceApi {
    /** @nullable */
    aiSessionId?: string | null
    createdAt: string
    distinctId: string
    /** @nullable */
    errorCount?: number | null
    events: LLMTraceEventApi[]
    id: string
    /** @nullable */
    inputCost?: number | null
    inputState?: unknown | null
    /** @nullable */
    inputTokens?: number | null
    /** @nullable */
    isSupportTrace?: boolean | null
    /** @nullable */
    outputCost?: number | null
    outputState?: unknown | null
    /** @nullable */
    outputTokens?: number | null
    person?: LLMTracePersonApi | null
    /** @nullable */
    requestCost?: number | null
    /** @nullable */
    tools?: string[] | null
    /** @nullable */
    totalCost?: number | null
    /** @nullable */
    totalLatency?: number | null
    /** @nullable */
    traceName?: string | null
    /** @nullable */
    webSearchCost?: number | null
}

export interface Response25Api {
    /** @nullable */
    columns?: string[] | null
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
    results: LLMTraceApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface Response26Api {
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
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export type TaxonomicFilterGroupTypeApi = (typeof TaxonomicFilterGroupTypeApi)[keyof typeof TaxonomicFilterGroupTypeApi]

export const TaxonomicFilterGroupTypeApi = {
    Metadata: 'metadata',
    Actions: 'actions',
    Cohorts: 'cohorts',
    CohortsWithAll: 'cohorts_with_all',
    DataWarehouse: 'data_warehouse',
    DataWarehouseProperties: 'data_warehouse_properties',
    DataWarehousePersonProperties: 'data_warehouse_person_properties',
    Elements: 'elements',
    Events: 'events',
    InternalEvents: 'internal_events',
    InternalEventProperties: 'internal_event_properties',
    EventProperties: 'event_properties',
    EventFeatureFlags: 'event_feature_flags',
    EventMetadata: 'event_metadata',
    NumericalEventProperties: 'numerical_event_properties',
    PersonProperties: 'person_properties',
    PageviewUrls: 'pageview_urls',
    PageviewEvents: 'pageview_events',
    Screens: 'screens',
    ScreenEvents: 'screen_events',
    EmailAddresses: 'email_addresses',
    AutocaptureEvents: 'autocapture_events',
    CustomEvents: 'custom_events',
    Wildcard: 'wildcard',
    Groups: 'groups',
    Persons: 'persons',
    FeatureFlags: 'feature_flags',
    Insights: 'insights',
    Experiments: 'experiments',
    Plugins: 'plugins',
    Dashboards: 'dashboards',
    NameGroups: 'name_groups',
    SessionProperties: 'session_properties',
    HogqlExpression: 'hogql_expression',
    Notebooks: 'notebooks',
    LogEntries: 'log_entries',
    ErrorTrackingIssues: 'error_tracking_issues',
    Logs: 'logs',
    LogAttributes: 'log_attributes',
    LogResourceAttributes: 'log_resource_attributes',
    Spans: 'spans',
    SpanAttributes: 'span_attributes',
    SpanResourceAttributes: 'span_resource_attributes',
    Replay: 'replay',
    ReplaySavedFilters: 'replay_saved_filters',
    RevenueAnalyticsProperties: 'revenue_analytics_properties',
    Resources: 'resources',
    ErrorTrackingProperties: 'error_tracking_properties',
    ActivityLogProperties: 'activity_log_properties',
    MaxAiContext: 'max_ai_context',
    WorkflowVariables: 'workflow_variables',
    SuggestedFilters: 'suggested_filters',
    RecentFilters: 'recent_filters',
    PinnedFilters: 'pinned_filters',
    Empty: 'empty',
} as const

export type HrefMatchingApi = (typeof HrefMatchingApi)[keyof typeof HrefMatchingApi]

export const HrefMatchingApi = {
    Contains: 'contains',
    Exact: 'exact',
    Regex: 'regex',
} as const

export type TextMatchingApi = (typeof TextMatchingApi)[keyof typeof TextMatchingApi]

export const TextMatchingApi = {
    Contains: 'contains',
    Exact: 'exact',
    Regex: 'regex',
} as const

export type UrlMatchingApi = (typeof UrlMatchingApi)[keyof typeof UrlMatchingApi]

export const UrlMatchingApi = {
    Contains: 'contains',
    Exact: 'exact',
    Regex: 'regex',
} as const

export interface EventsQueryActionStepApi {
    /** @nullable */
    event?: string | null
    /** @nullable */
    href?: string | null
    href_matching?: HrefMatchingApi | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    selector?: string | null
    /** @nullable */
    tag_name?: string | null
    /** @nullable */
    text?: string | null
    text_matching?: TextMatchingApi | null
    /** @nullable */
    url?: string | null
    url_matching?: UrlMatchingApi | null
}

export type EventsQueryApiKind = (typeof EventsQueryApiKind)[keyof typeof EventsQueryApiKind]

export const EventsQueryApiKind = {
    EventsQuery: 'EventsQuery',
} as const

export interface EventsQueryResponseApi {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /**
     * Cursor for fetching the next page of results
     * @nullable
     */
    nextCursor?: string | null
    /** @nullable */
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    types: string[]
}

export type CompareApi = (typeof CompareApi)[keyof typeof CompareApi]

export const CompareApi = {
    Current: 'current',
    Previous: 'previous',
} as const

export type InsightActorsQueryApiKind = (typeof InsightActorsQueryApiKind)[keyof typeof InsightActorsQueryApiKind]

export const InsightActorsQueryApiKind = {
    InsightActorsQuery: 'InsightActorsQuery',
} as const

export interface ActorsQueryResponseApi {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit: number
    /** @nullable */
    missing_actors_count?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: string[] | null
}

export interface InsightActorsQueryApi {
    breakdown?: string | string[] | number | null
    compare?: CompareApi | null
    day?: string | number | null
    /** @nullable */
    includeRecordings?: boolean | null
    /**
     * An interval selected out of available intervals in source query.
     * @nullable
     */
    interval?: number | null
    kind?: InsightActorsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ActorsQueryResponseApi | null
    /** @nullable */
    series?: number | null
    source:
        | TrendsQueryApi
        | FunnelsQueryApi
        | RetentionQueryApi
        | PathsQueryApi
        | StickinessQueryApi
        | LifecycleQueryApi
        | WebStatsTableQueryApi
        | WebOverviewQueryApi
    /** @nullable */
    status?: string | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export interface EventsQueryApi {
    /**
     * Show events matching a given action
     * @nullable
     */
    actionId?: number | null
    /**
     * Show events matching action steps directly, used when no actionId is provided (e.g. previewing unsaved actions). Ignored if actionId is set.
     * @nullable
     */
    actionSteps?: EventsQueryActionStepApi[] | null
    /**
     * Only fetch events that happened after this timestamp
     * @nullable
     */
    after?: string | null
    /**
     * Only fetch events that happened before this timestamp
     * @nullable
     */
    before?: string | null
    /**
     * Limit to events matching this string
     * @nullable
     */
    event?: string | null
    /**
     * Filter to events matching any of these event names
     * @nullable
     */
    events?: string[] | null
    /**
     * Filter test accounts
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?:
        | (
              | PropertyGroupFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    kind?: EventsQueryApiKind
    /**
     * Number of rows to return
     * @nullable
     */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /**
     * Number of rows to skip before returning rows
     * @nullable
     */
    offset?: number | null
    /**
     * Columns to order by
     * @nullable
     */
    orderBy?: string[] | null
    /**
     * Show events for a given person
     * @nullable
     */
    personId?: string | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: EventsQueryResponseApi | null
    /** Return a limited set of data. Required. */
    select: string[]
    /** source for querying events for insights */
    source?: InsightActorsQueryApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
    /**
     * HogQL filters to apply on returned data
     * @nullable
     */
    where?: string[] | null
}

export type PersonsNodeApiKind = (typeof PersonsNodeApiKind)[keyof typeof PersonsNodeApiKind]

export const PersonsNodeApiKind = {
    PersonsNode: 'PersonsNode',
} as const

/**
 * @nullable
 */
export type PersonsNodeApiResponse = { [key: string]: unknown } | null | null

export interface PersonsNodeApi {
    /** @nullable */
    cohort?: number | null
    /** @nullable */
    distinctId?: string | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    kind?: PersonsNodeApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    response?: PersonsNodeApiResponse
    /** @nullable */
    search?: string | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ActorsQueryApiKind = (typeof ActorsQueryApiKind)[keyof typeof ActorsQueryApiKind]

export const ActorsQueryApiKind = {
    ActorsQuery: 'ActorsQuery',
} as const

export type FunnelsActorsQueryApiKind = (typeof FunnelsActorsQueryApiKind)[keyof typeof FunnelsActorsQueryApiKind]

export const FunnelsActorsQueryApiKind = {
    FunnelsActorsQuery: 'FunnelsActorsQuery',
} as const

export interface FunnelsActorsQueryApi {
    /**
     * Index of the step for which we want to get the timestamp for, per person. Positive for converted persons, negative for dropped of persons.
     * @nullable
     */
    funnelStep?: number | null
    /** The breakdown value for which to get persons for. This is an array for person and event properties, a string for groups and an integer for cohorts. */
    funnelStepBreakdown?: number | string | number | (number | string | number)[] | null
    /** @nullable */
    funnelTrendsDropOff?: boolean | null
    /**
     * Used together with `funnelTrendsDropOff` for funnels time conversion date for the persons modal.
     * @nullable
     */
    funnelTrendsEntrancePeriodStart?: string | null
    /** @nullable */
    includeRecordings?: boolean | null
    kind?: FunnelsActorsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ActorsQueryResponseApi | null
    source: FunnelsQueryApi
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type FunnelCorrelationActorsQueryApiKind =
    (typeof FunnelCorrelationActorsQueryApiKind)[keyof typeof FunnelCorrelationActorsQueryApiKind]

export const FunnelCorrelationActorsQueryApiKind = {
    FunnelCorrelationActorsQuery: 'FunnelCorrelationActorsQuery',
} as const

export type FunnelCorrelationResultsTypeApi =
    (typeof FunnelCorrelationResultsTypeApi)[keyof typeof FunnelCorrelationResultsTypeApi]

export const FunnelCorrelationResultsTypeApi = {
    Events: 'events',
    Properties: 'properties',
    EventWithProperties: 'event_with_properties',
} as const

export type FunnelCorrelationQueryApiKind =
    (typeof FunnelCorrelationQueryApiKind)[keyof typeof FunnelCorrelationQueryApiKind]

export const FunnelCorrelationQueryApiKind = {
    FunnelCorrelationQuery: 'FunnelCorrelationQuery',
} as const

export type CorrelationTypeApi = (typeof CorrelationTypeApi)[keyof typeof CorrelationTypeApi]

export const CorrelationTypeApi = {
    Success: 'success',
    Failure: 'failure',
} as const

export type EventDefinitionApiProperties = { [key: string]: unknown }

export interface EventDefinitionApi {
    elements: unknown[]
    event: string
    properties: EventDefinitionApiProperties
}

export interface EventOddsRatioSerializedApi {
    correlation_type: CorrelationTypeApi
    event: EventDefinitionApi
    failure_count: number
    odds_ratio: number
    success_count: number
}

export interface FunnelCorrelationResultApi {
    events: EventOddsRatioSerializedApi[]
    skewed: boolean
}

export interface FunnelCorrelationResponseApi {
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
    results: FunnelCorrelationResultApi
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface FunnelCorrelationQueryApi {
    /** @nullable */
    funnelCorrelationEventExcludePropertyNames?: string[] | null
    /** @nullable */
    funnelCorrelationEventNames?: string[] | null
    /** @nullable */
    funnelCorrelationExcludeEventNames?: string[] | null
    /** @nullable */
    funnelCorrelationExcludeNames?: string[] | null
    /** @nullable */
    funnelCorrelationNames?: string[] | null
    funnelCorrelationType: FunnelCorrelationResultsTypeApi
    kind?: FunnelCorrelationQueryApiKind
    response?: FunnelCorrelationResponseApi | null
    source: FunnelsActorsQueryApi
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export interface FunnelCorrelationActorsQueryApi {
    /** @nullable */
    funnelCorrelationPersonConverted?: boolean | null
    funnelCorrelationPersonEntity?: EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi | null
    /** @nullable */
    funnelCorrelationPropertyValues?:
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    includeRecordings?: boolean | null
    kind?: FunnelCorrelationActorsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ActorsQueryResponseApi | null
    source: FunnelCorrelationQueryApi
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ExperimentEventExposureConfigApiKind =
    (typeof ExperimentEventExposureConfigApiKind)[keyof typeof ExperimentEventExposureConfigApiKind]

export const ExperimentEventExposureConfigApiKind = {
    ExperimentEventExposureConfig: 'ExperimentEventExposureConfig',
} as const

/**
 * @nullable
 */
export type ExperimentEventExposureConfigApiResponse = { [key: string]: unknown } | null | null

export interface ExperimentEventExposureConfigApi {
    event: string
    kind?: ExperimentEventExposureConfigApiKind
    properties: (
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
        | SpanPropertyFilterApi
        | RevenueAnalyticsPropertyFilterApi
        | WorkflowVariablePropertyFilterApi
    )[]
    /** @nullable */
    response?: ExperimentEventExposureConfigApiResponse
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ExperimentActorsQueryApiKind =
    (typeof ExperimentActorsQueryApiKind)[keyof typeof ExperimentActorsQueryApiKind]

export const ExperimentActorsQueryApiKind = {
    ExperimentActorsQuery: 'ExperimentActorsQuery',
} as const

export type MultipleVariantHandlingApi = (typeof MultipleVariantHandlingApi)[keyof typeof MultipleVariantHandlingApi]

export const MultipleVariantHandlingApi = {
    Exclude: 'exclude',
    FirstSeen: 'first_seen',
} as const

export type ExperimentQueryApiKind = (typeof ExperimentQueryApiKind)[keyof typeof ExperimentQueryApiKind]

export const ExperimentQueryApiKind = {
    ExperimentQuery: 'ExperimentQuery',
} as const

export type ExperimentMetricGoalApi = (typeof ExperimentMetricGoalApi)[keyof typeof ExperimentMetricGoalApi]

export const ExperimentMetricGoalApi = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

export type ExperimentMeanMetricApiKind = (typeof ExperimentMeanMetricApiKind)[keyof typeof ExperimentMeanMetricApiKind]

export const ExperimentMeanMetricApiKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

export type ExperimentMeanMetricApiMetricType =
    (typeof ExperimentMeanMetricApiMetricType)[keyof typeof ExperimentMeanMetricApiMetricType]

export const ExperimentMeanMetricApiMetricType = {
    Mean: 'mean',
} as const

export type ExperimentDataWarehouseNodeApiKind =
    (typeof ExperimentDataWarehouseNodeApiKind)[keyof typeof ExperimentDataWarehouseNodeApiKind]

export const ExperimentDataWarehouseNodeApiKind = {
    ExperimentDataWarehouseNode: 'ExperimentDataWarehouseNode',
} as const

export const ExperimentDataWarehouseNodeApiMath = {
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
export type ExperimentDataWarehouseNodeApiResponse = { [key: string]: unknown } | null | null

export interface ExperimentDataWarehouseNodeApi {
    /** @nullable */
    custom_name?: string | null
    data_warehouse_join_key: string
    events_join_key: string
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    kind?: ExperimentDataWarehouseNodeApiKind
    math?: (typeof ExperimentDataWarehouseNodeApiMath)[keyof typeof ExperimentDataWarehouseNodeApiMath] | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    response?: ExperimentDataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

/**
 * @nullable
 */
export type ExperimentMeanMetricApiResponse = { [key: string]: unknown } | null | null

export interface ExperimentMeanMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    /** @nullable */
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    /** @nullable */
    fingerprint?: string | null
    goal?: ExperimentMetricGoalApi | null
    /** @nullable */
    ignore_zeros?: boolean | null
    /** @nullable */
    isSharedMetric?: boolean | null
    kind?: ExperimentMeanMetricApiKind
    /** @nullable */
    lower_bound_percentile?: number | null
    metric_type?: ExperimentMeanMetricApiMetricType
    /** @nullable */
    name?: string | null
    /** @nullable */
    response?: ExperimentMeanMetricApiResponse
    /** @nullable */
    sharedMetricId?: number | null
    source: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    /** @nullable */
    upper_bound_percentile?: number | null
    /** @nullable */
    uuid?: string | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ExperimentFunnelMetricApiKind =
    (typeof ExperimentFunnelMetricApiKind)[keyof typeof ExperimentFunnelMetricApiKind]

export const ExperimentFunnelMetricApiKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

export type ExperimentFunnelMetricApiMetricType =
    (typeof ExperimentFunnelMetricApiMetricType)[keyof typeof ExperimentFunnelMetricApiMetricType]

export const ExperimentFunnelMetricApiMetricType = {
    Funnel: 'funnel',
} as const

/**
 * @nullable
 */
export type ExperimentFunnelMetricApiResponse = { [key: string]: unknown } | null | null

export interface ExperimentFunnelMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    /** @nullable */
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    /** @nullable */
    fingerprint?: string | null
    funnel_order_type?: StepOrderValueApi | null
    goal?: ExperimentMetricGoalApi | null
    /** @nullable */
    isSharedMetric?: boolean | null
    kind?: ExperimentFunnelMetricApiKind
    metric_type?: ExperimentFunnelMetricApiMetricType
    /** @nullable */
    name?: string | null
    /** @nullable */
    response?: ExperimentFunnelMetricApiResponse
    series: (EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi)[]
    /** @nullable */
    sharedMetricId?: number | null
    /** @nullable */
    uuid?: string | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ExperimentRatioMetricApiKind =
    (typeof ExperimentRatioMetricApiKind)[keyof typeof ExperimentRatioMetricApiKind]

export const ExperimentRatioMetricApiKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

export type ExperimentRatioMetricApiMetricType =
    (typeof ExperimentRatioMetricApiMetricType)[keyof typeof ExperimentRatioMetricApiMetricType]

export const ExperimentRatioMetricApiMetricType = {
    Ratio: 'ratio',
} as const

/**
 * @nullable
 */
export type ExperimentRatioMetricApiResponse = { [key: string]: unknown } | null | null

export interface ExperimentRatioMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    /** @nullable */
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    denominator: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    /** @nullable */
    fingerprint?: string | null
    goal?: ExperimentMetricGoalApi | null
    /** @nullable */
    isSharedMetric?: boolean | null
    kind?: ExperimentRatioMetricApiKind
    metric_type?: ExperimentRatioMetricApiMetricType
    /** @nullable */
    name?: string | null
    numerator: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    /** @nullable */
    response?: ExperimentRatioMetricApiResponse
    /** @nullable */
    sharedMetricId?: number | null
    /** @nullable */
    uuid?: string | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ExperimentRetentionMetricApiKind =
    (typeof ExperimentRetentionMetricApiKind)[keyof typeof ExperimentRetentionMetricApiKind]

export const ExperimentRetentionMetricApiKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

export type ExperimentRetentionMetricApiMetricType =
    (typeof ExperimentRetentionMetricApiMetricType)[keyof typeof ExperimentRetentionMetricApiMetricType]

export const ExperimentRetentionMetricApiMetricType = {
    Retention: 'retention',
} as const

export type StartHandlingApi = (typeof StartHandlingApi)[keyof typeof StartHandlingApi]

export const StartHandlingApi = {
    FirstSeen: 'first_seen',
    LastSeen: 'last_seen',
} as const

/**
 * @nullable
 */
export type ExperimentRetentionMetricApiResponse = { [key: string]: unknown } | null | null

export interface ExperimentRetentionMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    completion_event: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    /** @nullable */
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    /** @nullable */
    fingerprint?: string | null
    goal?: ExperimentMetricGoalApi | null
    /** @nullable */
    isSharedMetric?: boolean | null
    kind?: ExperimentRetentionMetricApiKind
    metric_type?: ExperimentRetentionMetricApiMetricType
    /** @nullable */
    name?: string | null
    /** @nullable */
    response?: ExperimentRetentionMetricApiResponse
    retention_window_end: number
    retention_window_start: number
    retention_window_unit: FunnelConversionWindowTimeUnitApi
    /** @nullable */
    sharedMetricId?: number | null
    start_event: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    start_handling: StartHandlingApi
    /** @nullable */
    uuid?: string | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type PrecomputationModeApi = (typeof PrecomputationModeApi)[keyof typeof PrecomputationModeApi]

export const PrecomputationModeApi = {
    Precomputed: 'precomputed',
    Direct: 'direct',
} as const

export interface SessionDataApi {
    event_uuid: string
    person_id: string
    session_id: string
    timestamp: string
}

export type ExperimentStatsValidationFailureApi =
    (typeof ExperimentStatsValidationFailureApi)[keyof typeof ExperimentStatsValidationFailureApi]

export const ExperimentStatsValidationFailureApi = {
    NotEnoughExposures: 'not-enough-exposures',
    BaselineMeanIsZero: 'baseline-mean-is-zero',
    NotEnoughMetricData: 'not-enough-metric-data',
} as const

export interface ExperimentStatsBaseValidatedApi {
    /** @nullable */
    denominator_sum?: number | null
    /** @nullable */
    denominator_sum_squares?: number | null
    key: string
    number_of_samples: number
    /** @nullable */
    numerator_denominator_sum_product?: number | null
    /** @nullable */
    step_counts?: number[] | null
    /** @nullable */
    step_sessions?: SessionDataApi[][] | null
    sum: number
    sum_squares: number
    /** @nullable */
    validation_failures?: ExperimentStatsValidationFailureApi[] | null
}

export type ExperimentVariantResultFrequentistApiMethod =
    (typeof ExperimentVariantResultFrequentistApiMethod)[keyof typeof ExperimentVariantResultFrequentistApiMethod]

export const ExperimentVariantResultFrequentistApiMethod = {
    Frequentist: 'frequentist',
} as const

export interface ExperimentVariantResultFrequentistApi {
    /**
     * @minItems 2
     * @maxItems 2
     * @nullable
     */
    confidence_interval?: number[] | null
    /** @nullable */
    denominator_sum?: number | null
    /** @nullable */
    denominator_sum_squares?: number | null
    key: string
    method?: ExperimentVariantResultFrequentistApiMethod
    number_of_samples: number
    /** @nullable */
    numerator_denominator_sum_product?: number | null
    /** @nullable */
    p_value?: number | null
    /** @nullable */
    significant?: boolean | null
    /** @nullable */
    step_counts?: number[] | null
    /** @nullable */
    step_sessions?: SessionDataApi[][] | null
    sum: number
    sum_squares: number
    /** @nullable */
    validation_failures?: ExperimentStatsValidationFailureApi[] | null
}

export type ExperimentVariantResultBayesianApiMethod =
    (typeof ExperimentVariantResultBayesianApiMethod)[keyof typeof ExperimentVariantResultBayesianApiMethod]

export const ExperimentVariantResultBayesianApiMethod = {
    Bayesian: 'bayesian',
} as const

export interface ExperimentVariantResultBayesianApi {
    /** @nullable */
    chance_to_win?: number | null
    /**
     * @minItems 2
     * @maxItems 2
     * @nullable
     */
    credible_interval?: number[] | null
    /** @nullable */
    denominator_sum?: number | null
    /** @nullable */
    denominator_sum_squares?: number | null
    key: string
    method?: ExperimentVariantResultBayesianApiMethod
    number_of_samples: number
    /** @nullable */
    numerator_denominator_sum_product?: number | null
    /** @nullable */
    significant?: boolean | null
    /** @nullable */
    step_counts?: number[] | null
    /** @nullable */
    step_sessions?: SessionDataApi[][] | null
    sum: number
    sum_squares: number
    /** @nullable */
    validation_failures?: ExperimentStatsValidationFailureApi[] | null
}

export interface ExperimentBreakdownResultApi {
    /** Control variant stats for this breakdown */
    baseline: ExperimentStatsBaseValidatedApi
    /** The breakdown values as an array (e.g., ["MacOS", "Chrome"] for multi-breakdown, ["Chrome"] for single) Although `BreakdownKeyType` could be an array, we only use the array form for the breakdown_value. The way `BreakdownKeyType` is defined is problematic. It should be treated as a primitive and allow for the types using it to define if it's and array or an optional value. */
    breakdown_value: (string | number | number)[]
    /** Test variant results with statistical comparisons for this breakdown */
    variants: ExperimentVariantResultFrequentistApi[] | ExperimentVariantResultBayesianApi[]
}

export type ExperimentQueryResponseApiKind =
    (typeof ExperimentQueryResponseApiKind)[keyof typeof ExperimentQueryResponseApiKind]

export const ExperimentQueryResponseApiKind = {
    ExperimentQuery: 'ExperimentQuery',
} as const

/**
 * @nullable
 */
export type ExperimentQueryResponseApiCredibleIntervals = { [key: string]: number[] } | null | null

export type ExperimentQueryResponseApiInsightItem = { [key: string]: unknown }

/**
 * @nullable
 */
export type ExperimentQueryResponseApiProbability = { [key: string]: number } | null | null

export interface ExperimentQueryResponseApi {
    baseline?: ExperimentStatsBaseValidatedApi | null
    /**
     * Results grouped by breakdown value. When present, baseline and variant_results contain aggregated data.
     * @nullable
     */
    breakdown_results?: ExperimentBreakdownResultApi[] | null
    /** @nullable */
    clickhouse_sql?: string | null
    /** @nullable */
    credible_intervals?: ExperimentQueryResponseApiCredibleIntervals
    /** @nullable */
    hogql?: string | null
    /** @nullable */
    insight?: ExperimentQueryResponseApiInsightItem[] | null
    /**
     * Whether exposures were served from the precomputation system
     * @nullable
     */
    is_precomputed?: boolean | null
    kind?: ExperimentQueryResponseApiKind
    metric?:
        | ExperimentMeanMetricApi
        | ExperimentFunnelMetricApi
        | ExperimentRatioMetricApi
        | ExperimentRetentionMetricApi
        | null
    /** @nullable */
    p_value?: number | null
    /** @nullable */
    probability?: ExperimentQueryResponseApiProbability
    significance_code?: ExperimentSignificanceCodeApi | null
    /** @nullable */
    significant?: boolean | null
    /** @nullable */
    stats_version?: number | null
    variant_results?: ExperimentVariantResultFrequentistApi[] | ExperimentVariantResultBayesianApi[] | null
    variants?: ExperimentVariantTrendsBaseStatsApi[] | ExperimentVariantFunnelsBaseStatsApi[] | null
}

export interface ExperimentQueryApi {
    /** @nullable */
    experiment_id?: number | null
    kind?: ExperimentQueryApiKind
    metric:
        | ExperimentMeanMetricApi
        | ExperimentFunnelMetricApi
        | ExperimentRatioMetricApi
        | ExperimentRetentionMetricApi
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    name?: string | null
    precomputation_mode?: PrecomputationModeApi | null
    response?: ExperimentQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export interface ExperimentActorsQueryApi {
    /** Exposure configuration for filtering events. Defines when users were first exposed to the experiment. */
    exposureConfig?: ExperimentEventExposureConfigApi | ActionsNodeApi | null
    /**
     * Feature flag key for breakdown filtering.
     * @nullable
     */
    featureFlagKey?: string | null
    /**
     * Index of the step for which we want to get actors for, per experiment variant. Positive for converted persons, negative for dropped off persons.
     * @nullable
     */
    funnelStep?: number | null
    /** The variant key for filtering actors. For experiments, this filters by feature flag variant (e.g., 'control', 'test'). */
    funnelStepBreakdown?: number | string | number | (number | string | number)[] | null
    /** @nullable */
    includeRecordings?: boolean | null
    kind?: ExperimentActorsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** How to handle users with multiple variant exposures. */
    multipleVariantHandling?: MultipleVariantHandlingApi | null
    response?: ActorsQueryResponseApi | null
    source: ExperimentQueryApi
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type StickinessActorsQueryApiKind =
    (typeof StickinessActorsQueryApiKind)[keyof typeof StickinessActorsQueryApiKind]

export const StickinessActorsQueryApiKind = {
    StickinessActorsQuery: 'StickinessActorsQuery',
} as const

export interface StickinessActorsQueryApi {
    compare?: CompareApi | null
    day?: string | number | null
    /** @nullable */
    includeRecordings?: boolean | null
    kind?: StickinessActorsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    operator?: StickinessOperatorApi | null
    response?: ActorsQueryResponseApi | null
    /** @nullable */
    series?: number | null
    source: StickinessQueryApi
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
}

export type HogQLQueryApiKind = (typeof HogQLQueryApiKind)[keyof typeof HogQLQueryApiKind]

export const HogQLQueryApiKind = {
    HogQLQuery: 'HogQLQuery',
} as const

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
    /**
     * Optional direct external data source id for running against a specific source
     * @nullable
     */
    connectionId?: string | null
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
    /**
     * Run the selected connection query directly without translating it through HogQL first
     * @nullable
     */
    sendRawQuery?: boolean | null
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

export interface ActorsQueryApi {
    /**
     * Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in actor_strategies.py.
     * @nullable
     */
    fixedProperties?:
        | (PersonPropertyFilterApi | CohortPropertyFilterApi | HogQLPropertyFilterApi | EmptyPropertyFilterApi)[]
        | null
    kind?: ActorsQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /** @nullable */
    orderBy?: string[] | null
    /** Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in actor_strategies.py. */
    properties?:
        | (PersonPropertyFilterApi | CohortPropertyFilterApi | HogQLPropertyFilterApi | EmptyPropertyFilterApi)[]
        | PropertyGroupFilterValueApi
        | null
    response?: ActorsQueryResponseApi | null
    /** @nullable */
    search?: string | null
    /** @nullable */
    select?: string[] | null
    source?:
        | InsightActorsQueryApi
        | FunnelsActorsQueryApi
        | FunnelCorrelationActorsQueryApi
        | ExperimentActorsQueryApi
        | StickinessActorsQueryApi
        | HogQLQueryApi
        | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type GroupsQueryApiKind = (typeof GroupsQueryApiKind)[keyof typeof GroupsQueryApiKind]

export const GroupsQueryApiKind = {
    GroupsQuery: 'GroupsQuery',
} as const

export type GroupsQueryResponseApiKind = (typeof GroupsQueryResponseApiKind)[keyof typeof GroupsQueryResponseApiKind]

export const GroupsQueryResponseApiKind = {
    GroupsQuery: 'GroupsQuery',
} as const

export interface GroupsQueryResponseApi {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: GroupsQueryResponseApiKind
    limit: number
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    types: string[]
}

export interface GroupsQueryApi {
    group_type_index: number
    kind?: GroupsQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /** @nullable */
    orderBy?: string[] | null
    /** @nullable */
    properties?: (GroupPropertyFilterApi | HogQLPropertyFilterApi)[] | null
    response?: GroupsQueryResponseApi | null
    /** @nullable */
    search?: string | null
    /** @nullable */
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type WebExternalClicksTableQueryApiKind =
    (typeof WebExternalClicksTableQueryApiKind)[keyof typeof WebExternalClicksTableQueryApiKind]

export const WebExternalClicksTableQueryApiKind = {
    WebExternalClicksTableQuery: 'WebExternalClicksTableQuery',
} as const

export interface WebExternalClicksTableQueryResponseApi {
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
}

export const WebExternalClicksTableQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export interface WebExternalClicksTableQueryApi {
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
    kind?: WebExternalClicksTableQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    orderBy?:
        | (typeof WebExternalClicksTableQueryApiOrderByItem)[keyof typeof WebExternalClicksTableQueryApiOrderByItem][]
        | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebExternalClicksTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /** @nullable */
    stripQueryParams?: boolean | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type WebGoalsQueryApiKind = (typeof WebGoalsQueryApiKind)[keyof typeof WebGoalsQueryApiKind]

export const WebGoalsQueryApiKind = {
    WebGoalsQuery: 'WebGoalsQuery',
} as const

export interface WebGoalsQueryResponseApi {
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
}

export const WebGoalsQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export interface WebGoalsQueryApi {
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
    kind?: WebGoalsQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    orderBy?: (typeof WebGoalsQueryApiOrderByItem)[keyof typeof WebGoalsQueryApiOrderByItem][] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebGoalsQueryResponseApi | null
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

export type WebVitalsQueryApiKind = (typeof WebVitalsQueryApiKind)[keyof typeof WebVitalsQueryApiKind]

export const WebVitalsQueryApiKind = {
    WebVitalsQuery: 'WebVitalsQuery',
} as const

export const WebVitalsQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export interface WebVitalsQueryApi {
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
    kind?: WebVitalsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    orderBy?: (typeof WebVitalsQueryApiOrderByItem)[keyof typeof WebVitalsQueryApiOrderByItem][] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebGoalsQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    source:
        | TrendsQueryApi
        | FunnelsQueryApi
        | RetentionQueryApi
        | PathsQueryApi
        | StickinessQueryApi
        | LifecycleQueryApi
        | WebStatsTableQueryApi
        | WebOverviewQueryApi
    tags?: QueryLogTagsApi | null
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type WebVitalsPathBreakdownQueryApiKind =
    (typeof WebVitalsPathBreakdownQueryApiKind)[keyof typeof WebVitalsPathBreakdownQueryApiKind]

export const WebVitalsPathBreakdownQueryApiKind = {
    WebVitalsPathBreakdownQuery: 'WebVitalsPathBreakdownQuery',
} as const

export type WebVitalsMetricApi = (typeof WebVitalsMetricApi)[keyof typeof WebVitalsMetricApi]

export const WebVitalsMetricApi = {
    Inp: 'INP',
    Lcp: 'LCP',
    Cls: 'CLS',
    Fcp: 'FCP',
} as const

export type WebVitalsPercentileApi = (typeof WebVitalsPercentileApi)[keyof typeof WebVitalsPercentileApi]

export const WebVitalsPercentileApi = {
    P75: 'p75',
    P90: 'p90',
    P99: 'p99',
} as const

export interface WebVitalsPathBreakdownQueryResponseApi {
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
    /**
     * @minItems 1
     * @maxItems 1
     */
    results: WebVitalsPathBreakdownResultApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export const WebVitalsPathBreakdownQueryApiOrderByItem = {
    ...WebAnalyticsOrderByFieldsApi,
    ...WebAnalyticsOrderByDirectionApi,
} as const
export interface WebVitalsPathBreakdownQueryApi {
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
    kind?: WebVitalsPathBreakdownQueryApiKind
    metric: WebVitalsMetricApi
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    orderBy?:
        | (typeof WebVitalsPathBreakdownQueryApiOrderByItem)[keyof typeof WebVitalsPathBreakdownQueryApiOrderByItem][]
        | null
    percentile: WebVitalsPercentileApi
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebVitalsPathBreakdownQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi | null
    /**
     * @minItems 2
     * @maxItems 2
     */
    thresholds: number[]
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export interface FiltersApi {
    dateRange?: DateRangeApi | null
    /** @nullable */
    properties?: SessionPropertyFilterApi[] | null
}

export type SessionAttributionGroupByApi =
    (typeof SessionAttributionGroupByApi)[keyof typeof SessionAttributionGroupByApi]

export const SessionAttributionGroupByApi = {
    ChannelType: 'ChannelType',
    Medium: 'Medium',
    Source: 'Source',
    Campaign: 'Campaign',
    AdIds: 'AdIds',
    ReferringDomain: 'ReferringDomain',
    InitialURL: 'InitialURL',
} as const

export type SessionAttributionExplorerQueryApiKind =
    (typeof SessionAttributionExplorerQueryApiKind)[keyof typeof SessionAttributionExplorerQueryApiKind]

export const SessionAttributionExplorerQueryApiKind = {
    SessionAttributionExplorerQuery: 'SessionAttributionExplorerQuery',
} as const

export interface SessionAttributionExplorerQueryResponseApi {
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
    results: unknown
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface SessionAttributionExplorerQueryApi {
    filters?: FiltersApi | null
    groupBy: SessionAttributionGroupByApi[]
    kind?: SessionAttributionExplorerQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    response?: SessionAttributionExplorerQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type SessionsQueryApiKind = (typeof SessionsQueryApiKind)[keyof typeof SessionsQueryApiKind]

export const SessionsQueryApiKind = {
    SessionsQuery: 'SessionsQuery',
} as const

export interface SessionsQueryResponseApi {
    columns: unknown[]
    /**
     * Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.
     * @nullable
     */
    error?: string | null
    /** @nullable */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
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
    results: unknown[][]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    types: string[]
}

export interface SessionsQueryApi {
    /**
     * Filter sessions by action - sessions that contain events matching this action
     * @nullable
     */
    actionId?: number | null
    /**
     * Only fetch sessions that started after this timestamp
     * @nullable
     */
    after?: string | null
    /**
     * Only fetch sessions that started before this timestamp
     * @nullable
     */
    before?: string | null
    /**
     * Filter sessions by event name - sessions that contain this event
     * @nullable
     */
    event?: string | null
    /**
     * Event property filters - filters sessions that contain events matching these properties
     * @nullable
     */
    eventProperties?:
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /**
     * Filter test accounts
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /**
     * Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)
     * @nullable
     */
    fixedProperties?:
        | (
              | PropertyGroupFilterApi
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    kind?: SessionsQueryApiKind
    /**
     * Number of rows to return
     * @nullable
     */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /**
     * Number of rows to skip before returning rows
     * @nullable
     */
    offset?: number | null
    /**
     * Columns to order by
     * @nullable
     */
    orderBy?: string[] | null
    /**
     * Show sessions for a given person
     * @nullable
     */
    personId?: string | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: SessionsQueryResponseApi | null
    /** Return a limited set of data. Required. */
    select: string[]
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
    /**
     * HogQL filters to apply on returned data
     * @nullable
     */
    where?: string[] | null
}

export type RevenueAnalyticsBreakdownApiType =
    (typeof RevenueAnalyticsBreakdownApiType)[keyof typeof RevenueAnalyticsBreakdownApiType]

export const RevenueAnalyticsBreakdownApiType = {
    RevenueAnalytics: 'revenue_analytics',
} as const

export interface RevenueAnalyticsBreakdownApi {
    property: string
    type?: RevenueAnalyticsBreakdownApiType
}

export type SimpleIntervalTypeApi = (typeof SimpleIntervalTypeApi)[keyof typeof SimpleIntervalTypeApi]

export const SimpleIntervalTypeApi = {
    Day: 'day',
    Month: 'month',
} as const

export type RevenueAnalyticsGrossRevenueQueryApiKind =
    (typeof RevenueAnalyticsGrossRevenueQueryApiKind)[keyof typeof RevenueAnalyticsGrossRevenueQueryApiKind]

export const RevenueAnalyticsGrossRevenueQueryApiKind = {
    RevenueAnalyticsGrossRevenueQuery: 'RevenueAnalyticsGrossRevenueQuery',
} as const

export interface RevenueAnalyticsGrossRevenueQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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
    results: unknown[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface RevenueAnalyticsGrossRevenueQueryApi {
    breakdown: RevenueAnalyticsBreakdownApi[]
    dateRange?: DateRangeApi | null
    interval: SimpleIntervalTypeApi
    kind?: RevenueAnalyticsGrossRevenueQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsGrossRevenueQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type RevenueAnalyticsMetricsQueryApiKind =
    (typeof RevenueAnalyticsMetricsQueryApiKind)[keyof typeof RevenueAnalyticsMetricsQueryApiKind]

export const RevenueAnalyticsMetricsQueryApiKind = {
    RevenueAnalyticsMetricsQuery: 'RevenueAnalyticsMetricsQuery',
} as const

export interface RevenueAnalyticsMetricsQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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

export interface RevenueAnalyticsMetricsQueryApi {
    breakdown: RevenueAnalyticsBreakdownApi[]
    dateRange?: DateRangeApi | null
    interval: SimpleIntervalTypeApi
    kind?: RevenueAnalyticsMetricsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsMetricsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type RevenueAnalyticsMRRQueryApiKind =
    (typeof RevenueAnalyticsMRRQueryApiKind)[keyof typeof RevenueAnalyticsMRRQueryApiKind]

export const RevenueAnalyticsMRRQueryApiKind = {
    RevenueAnalyticsMRRQuery: 'RevenueAnalyticsMRRQuery',
} as const

export interface RevenueAnalyticsMRRQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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
    results: RevenueAnalyticsMRRQueryResultItemApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface RevenueAnalyticsMRRQueryApi {
    breakdown: RevenueAnalyticsBreakdownApi[]
    dateRange?: DateRangeApi | null
    interval: SimpleIntervalTypeApi
    kind?: RevenueAnalyticsMRRQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsMRRQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type RevenueAnalyticsOverviewQueryApiKind =
    (typeof RevenueAnalyticsOverviewQueryApiKind)[keyof typeof RevenueAnalyticsOverviewQueryApiKind]

export const RevenueAnalyticsOverviewQueryApiKind = {
    RevenueAnalyticsOverviewQuery: 'RevenueAnalyticsOverviewQuery',
} as const

export interface RevenueAnalyticsOverviewQueryResponseApi {
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
    results: RevenueAnalyticsOverviewItemApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface RevenueAnalyticsOverviewQueryApi {
    dateRange?: DateRangeApi | null
    kind?: RevenueAnalyticsOverviewQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsOverviewQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type RevenueAnalyticsTopCustomersGroupByApi =
    (typeof RevenueAnalyticsTopCustomersGroupByApi)[keyof typeof RevenueAnalyticsTopCustomersGroupByApi]

export const RevenueAnalyticsTopCustomersGroupByApi = {
    Month: 'month',
    All: 'all',
} as const

export type RevenueAnalyticsTopCustomersQueryApiKind =
    (typeof RevenueAnalyticsTopCustomersQueryApiKind)[keyof typeof RevenueAnalyticsTopCustomersQueryApiKind]

export const RevenueAnalyticsTopCustomersQueryApiKind = {
    RevenueAnalyticsTopCustomersQuery: 'RevenueAnalyticsTopCustomersQuery',
} as const

export interface RevenueAnalyticsTopCustomersQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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

export interface RevenueAnalyticsTopCustomersQueryApi {
    dateRange?: DateRangeApi | null
    groupBy: RevenueAnalyticsTopCustomersGroupByApi
    kind?: RevenueAnalyticsTopCustomersQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsTopCustomersQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type RevenueExampleEventsQueryApiKind =
    (typeof RevenueExampleEventsQueryApiKind)[keyof typeof RevenueExampleEventsQueryApiKind]

export const RevenueExampleEventsQueryApiKind = {
    RevenueExampleEventsQuery: 'RevenueExampleEventsQuery',
} as const

export interface RevenueExampleEventsQueryResponseApi {
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
    results: unknown
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface RevenueExampleEventsQueryApi {
    kind?: RevenueExampleEventsQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    response?: RevenueExampleEventsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type RevenueExampleDataWarehouseTablesQueryApiKind =
    (typeof RevenueExampleDataWarehouseTablesQueryApiKind)[keyof typeof RevenueExampleDataWarehouseTablesQueryApiKind]

export const RevenueExampleDataWarehouseTablesQueryApiKind = {
    RevenueExampleDataWarehouseTablesQuery: 'RevenueExampleDataWarehouseTablesQuery',
} as const

export interface RevenueExampleDataWarehouseTablesQueryResponseApi {
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
    results: unknown
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface RevenueExampleDataWarehouseTablesQueryApi {
    kind?: RevenueExampleDataWarehouseTablesQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    response?: RevenueExampleDataWarehouseTablesQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ConversionGoalFilter1ApiKind =
    (typeof ConversionGoalFilter1ApiKind)[keyof typeof ConversionGoalFilter1ApiKind]

export const ConversionGoalFilter1ApiKind = {
    EventsNode: 'EventsNode',
} as const

export const ConversionGoalFilter1ApiMath = {
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
export type ConversionGoalFilter1ApiResponse = { [key: string]: unknown } | null | null

export type ConversionGoalFilter1ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter1Api {
    conversion_goal_id: string
    conversion_goal_name: string
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    kind?: ConversionGoalFilter1ApiKind
    /** @nullable */
    limit?: number | null
    math?: (typeof ConversionGoalFilter1ApiMath)[keyof typeof ConversionGoalFilter1ApiMath] | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    response?: ConversionGoalFilter1ApiResponse
    schema_map: ConversionGoalFilter1ApiSchemaMap
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ConversionGoalFilter2ApiKind =
    (typeof ConversionGoalFilter2ApiKind)[keyof typeof ConversionGoalFilter2ApiKind]

export const ConversionGoalFilter2ApiKind = {
    ActionsNode: 'ActionsNode',
} as const

export const ConversionGoalFilter2ApiMath = {
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
export type ConversionGoalFilter2ApiResponse = { [key: string]: unknown } | null | null

export type ConversionGoalFilter2ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter2Api {
    conversion_goal_id: string
    conversion_goal_name: string
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    id: number
    kind?: ConversionGoalFilter2ApiKind
    math?: (typeof ConversionGoalFilter2ApiMath)[keyof typeof ConversionGoalFilter2ApiMath] | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    response?: ConversionGoalFilter2ApiResponse
    schema_map: ConversionGoalFilter2ApiSchemaMap
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ConversionGoalFilter3ApiKind =
    (typeof ConversionGoalFilter3ApiKind)[keyof typeof ConversionGoalFilter3ApiKind]

export const ConversionGoalFilter3ApiKind = {
    DataWarehouseNode: 'DataWarehouseNode',
} as const

export const ConversionGoalFilter3ApiMath = {
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
export type ConversionGoalFilter3ApiResponse = { [key: string]: unknown } | null | null

export type ConversionGoalFilter3ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter3Api {
    conversion_goal_id: string
    conversion_goal_name: string
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    id: string
    id_field: string
    kind?: ConversionGoalFilter3ApiKind
    math?: (typeof ConversionGoalFilter3ApiMath)[keyof typeof ConversionGoalFilter3ApiMath] | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /** @nullable */
    response?: ConversionGoalFilter3ApiResponse
    schema_map: ConversionGoalFilter3ApiSchemaMap
    table_name: string
    timestamp_field: string
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type MarketingAnalyticsDrillDownLevelApi =
    (typeof MarketingAnalyticsDrillDownLevelApi)[keyof typeof MarketingAnalyticsDrillDownLevelApi]

export const MarketingAnalyticsDrillDownLevelApi = {
    Channel: 'channel',
    Source: 'source',
    Campaign: 'campaign',
    Medium: 'medium',
    Content: 'content',
    Term: 'term',
} as const

export interface IntegrationFilterApi {
    /**
     * Selected integration source IDs to filter by (e.g., table IDs or source map IDs)
     * @nullable
     */
    integrationSourceIds?: string[] | null
}

export type MarketingAnalyticsTableQueryApiKind =
    (typeof MarketingAnalyticsTableQueryApiKind)[keyof typeof MarketingAnalyticsTableQueryApiKind]

export const MarketingAnalyticsTableQueryApiKind = {
    MarketingAnalyticsTableQuery: 'MarketingAnalyticsTableQuery',
} as const

export type MarketingAnalyticsOrderByEnumApi =
    (typeof MarketingAnalyticsOrderByEnumApi)[keyof typeof MarketingAnalyticsOrderByEnumApi]

export const MarketingAnalyticsOrderByEnumApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export interface MarketingAnalyticsTableQueryResponseApi {
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
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface MarketingAnalyticsTableQueryApi {
    /**
     * Groups aggregation - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Compare to date range */
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
    /** Draft conversion goal that can be set in the UI without saving */
    draftConversionGoal?: ConversionGoalFilter1Api | ConversionGoalFilter2Api | ConversionGoalFilter3Api | null
    /** Drill-down hierarchy level: channel, source, or campaign (default) */
    drillDownLevel?: MarketingAnalyticsDrillDownLevelApi | null
    /**
     * Filter test accounts
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** @nullable */
    includeRevenue?: boolean | null
    /** Filter by integration type */
    integrationFilter?: IntegrationFilterApi | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: MarketingAnalyticsTableQueryApiKind
    /**
     * Number of rows to return
     * @nullable
     */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /**
     * Number of rows to skip before returning rows
     * @nullable
     */
    offset?: number | null
    /**
     * Columns to order by - similar to EventsQuery format
     * @nullable
     */
    orderBy?: (string | MarketingAnalyticsOrderByEnumApi)[][] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: MarketingAnalyticsTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /**
     * Return a limited set of data. Will use default columns if empty.
     * @nullable
     */
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type MarketingAnalyticsAggregatedQueryApiKind =
    (typeof MarketingAnalyticsAggregatedQueryApiKind)[keyof typeof MarketingAnalyticsAggregatedQueryApiKind]

export const MarketingAnalyticsAggregatedQueryApiKind = {
    MarketingAnalyticsAggregatedQuery: 'MarketingAnalyticsAggregatedQuery',
} as const

export type MarketingAnalyticsAggregatedQueryResponseApiResults = { [key: string]: MarketingAnalyticsItemApi }

export interface MarketingAnalyticsAggregatedQueryResponseApi {
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
    results: MarketingAnalyticsAggregatedQueryResponseApiResults
    samplingRate?: SamplingRateApi | null
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface MarketingAnalyticsAggregatedQueryApi {
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
    /** Draft conversion goal that can be set in the UI without saving */
    draftConversionGoal?: ConversionGoalFilter1Api | ConversionGoalFilter2Api | ConversionGoalFilter3Api | null
    /** Drill-down hierarchy level: channel, source, or campaign (default) */
    drillDownLevel?: MarketingAnalyticsDrillDownLevelApi | null
    /** @nullable */
    filterTestAccounts?: boolean | null
    /** @nullable */
    includeRevenue?: boolean | null
    /** Filter by integration IDs */
    integrationFilter?: IntegrationFilterApi | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: MarketingAnalyticsAggregatedQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: MarketingAnalyticsAggregatedQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /**
     * Return a limited set of data. Will use default columns if empty.
     * @nullable
     */
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type NonIntegratedConversionsTableQueryApiKind =
    (typeof NonIntegratedConversionsTableQueryApiKind)[keyof typeof NonIntegratedConversionsTableQueryApiKind]

export const NonIntegratedConversionsTableQueryApiKind = {
    NonIntegratedConversionsTableQuery: 'NonIntegratedConversionsTableQuery',
} as const

export interface NonIntegratedConversionsTableQueryResponseApi {
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
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export interface NonIntegratedConversionsTableQueryApi {
    /**
     * Groups aggregation - not used in Web Analytics but required for type compatibility
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Compare to date range */
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
    /** Draft conversion goal that can be set in the UI without saving */
    draftConversionGoal?: ConversionGoalFilter1Api | ConversionGoalFilter2Api | ConversionGoalFilter3Api | null
    /**
     * Filter test accounts
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** @nullable */
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: NonIntegratedConversionsTableQueryApiKind
    /**
     * Number of rows to return
     * @nullable
     */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /**
     * Number of rows to skip before returning rows
     * @nullable
     */
    offset?: number | null
    /**
     * Columns to order by
     * @nullable
     */
    orderBy?: (string | MarketingAnalyticsOrderByEnumApi)[][] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: NonIntegratedConversionsTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /**
     * Sampling rate
     * @nullable
     */
    samplingFactor?: number | null
    /**
     * Return a limited set of data. Will use default columns if empty.
     * @nullable
     */
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    useSessionsTable?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ErrorTrackingQueryApiKind = (typeof ErrorTrackingQueryApiKind)[keyof typeof ErrorTrackingQueryApiKind]

export const ErrorTrackingQueryApiKind = {
    ErrorTrackingQuery: 'ErrorTrackingQuery',
} as const

export type ErrorTrackingOrderByApi = (typeof ErrorTrackingOrderByApi)[keyof typeof ErrorTrackingOrderByApi]

export const ErrorTrackingOrderByApi = {
    LastSeen: 'last_seen',
    FirstSeen: 'first_seen',
    Occurrences: 'occurrences',
    Users: 'users',
    Sessions: 'sessions',
} as const

export type OrderDirection2Api = (typeof OrderDirection2Api)[keyof typeof OrderDirection2Api]

export const OrderDirection2Api = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export interface ErrorTrackingQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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
    results: ErrorTrackingIssueApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface ErrorTrackingQueryApi {
    assignee?: ErrorTrackingIssueAssigneeApi | null
    /** Date range to filter results. */
    dateRange: DateRangeApi
    filterGroup?: PropertyGroupFilterApi | null
    /**
     * Whether to filter out test accounts.
     * @nullable
     */
    filterTestAccounts?: boolean | null
    /** @nullable */
    groupKey?: string | null
    /** @nullable */
    groupTypeIndex?: number | null
    /**
     * Filter to a specific error tracking issue by ID.
     * @nullable
     */
    issueId?: string | null
    kind?: ErrorTrackingQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /** Field to sort results by. */
    orderBy: ErrorTrackingOrderByApi
    /** Sort direction. */
    orderDirection?: OrderDirection2Api | null
    /** @nullable */
    personId?: string | null
    response?: ErrorTrackingQueryResponseApi | null
    /**
     * Free-text search across exception type, message, and stack frames.
     * @nullable
     */
    searchQuery?: string | null
    /** Filter by issue status. */
    status?: ErrorTrackingIssueStatusApi | string | null
    tags?: QueryLogTagsApi | null
    /**
     * Use V2 query path (ClickHouse postgres connector join instead of separate Postgres queries)
     * @nullable
     */
    useQueryV2?: boolean | null
    /**
     * Use V3 query path (denormalized ClickHouse table, no Postgres joins)
     * @nullable
     */
    useQueryV3?: boolean | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
    volumeResolution: number
    /** @nullable */
    withAggregations?: boolean | null
    /** @nullable */
    withFirstEvent?: boolean | null
    /** @nullable */
    withLastEvent?: boolean | null
}

export type ErrorTrackingIssueCorrelationQueryApiKind =
    (typeof ErrorTrackingIssueCorrelationQueryApiKind)[keyof typeof ErrorTrackingIssueCorrelationQueryApiKind]

export const ErrorTrackingIssueCorrelationQueryApiKind = {
    ErrorTrackingIssueCorrelationQuery: 'ErrorTrackingIssueCorrelationQuery',
} as const

export interface ErrorTrackingIssueCorrelationQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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
    results: ErrorTrackingCorrelatedIssueApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface ErrorTrackingIssueCorrelationQueryApi {
    events: string[]
    kind?: ErrorTrackingIssueCorrelationQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ErrorTrackingIssueCorrelationQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ExperimentFunnelsQueryApiKind =
    (typeof ExperimentFunnelsQueryApiKind)[keyof typeof ExperimentFunnelsQueryApiKind]

export const ExperimentFunnelsQueryApiKind = {
    ExperimentFunnelsQuery: 'ExperimentFunnelsQuery',
} as const

export type ExperimentFunnelsQueryResponseApiKind =
    (typeof ExperimentFunnelsQueryResponseApiKind)[keyof typeof ExperimentFunnelsQueryResponseApiKind]

export const ExperimentFunnelsQueryResponseApiKind = {
    ExperimentFunnelsQuery: 'ExperimentFunnelsQuery',
} as const

export type ExperimentFunnelsQueryResponseApiCredibleIntervals = { [key: string]: number[] }

export type ExperimentFunnelsQueryResponseApiInsightItemItem = { [key: string]: unknown }

export type ExperimentFunnelsQueryResponseApiProbability = { [key: string]: number }

export interface ExperimentFunnelsQueryResponseApi {
    credible_intervals: ExperimentFunnelsQueryResponseApiCredibleIntervals
    expected_loss: number
    funnels_query?: FunnelsQueryApi | null
    insight: ExperimentFunnelsQueryResponseApiInsightItemItem[][]
    kind?: ExperimentFunnelsQueryResponseApiKind
    probability: ExperimentFunnelsQueryResponseApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    /** @nullable */
    stats_version?: number | null
    variants: ExperimentVariantFunnelsBaseStatsApi[]
}

export interface ExperimentFunnelsQueryApi {
    /** @nullable */
    experiment_id?: number | null
    /** @nullable */
    fingerprint?: string | null
    funnels_query: FunnelsQueryApi
    kind?: ExperimentFunnelsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    name?: string | null
    response?: ExperimentFunnelsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    uuid?: string | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type ExperimentTrendsQueryApiKind =
    (typeof ExperimentTrendsQueryApiKind)[keyof typeof ExperimentTrendsQueryApiKind]

export const ExperimentTrendsQueryApiKind = {
    ExperimentTrendsQuery: 'ExperimentTrendsQuery',
} as const

export type ExperimentTrendsQueryResponseApiKind =
    (typeof ExperimentTrendsQueryResponseApiKind)[keyof typeof ExperimentTrendsQueryResponseApiKind]

export const ExperimentTrendsQueryResponseApiKind = {
    ExperimentTrendsQuery: 'ExperimentTrendsQuery',
} as const

export type ExperimentTrendsQueryResponseApiCredibleIntervals = { [key: string]: number[] }

export type ExperimentTrendsQueryResponseApiInsightItem = { [key: string]: unknown }

export type ExperimentTrendsQueryResponseApiProbability = { [key: string]: number }

export interface ExperimentTrendsQueryResponseApi {
    count_query?: TrendsQueryApi | null
    credible_intervals: ExperimentTrendsQueryResponseApiCredibleIntervals
    exposure_query?: TrendsQueryApi | null
    insight: ExperimentTrendsQueryResponseApiInsightItem[]
    kind?: ExperimentTrendsQueryResponseApiKind
    p_value: number
    probability: ExperimentTrendsQueryResponseApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    /** @nullable */
    stats_version?: number | null
    variants: ExperimentVariantTrendsBaseStatsApi[]
}

export interface ExperimentTrendsQueryApi {
    count_query: TrendsQueryApi
    /** @nullable */
    experiment_id?: number | null
    exposure_query?: TrendsQueryApi | null
    /** @nullable */
    fingerprint?: string | null
    kind?: ExperimentTrendsQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    name?: string | null
    response?: ExperimentTrendsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** @nullable */
    uuid?: string | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type TracesQueryApiKind = (typeof TracesQueryApiKind)[keyof typeof TracesQueryApiKind]

export const TracesQueryApiKind = {
    TracesQuery: 'TracesQuery',
} as const

export interface TracesQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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
    results: LLMTraceApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface TracesQueryApi {
    dateRange?: DateRangeApi | null
    /** @nullable */
    filterSupportTraces?: boolean | null
    /** @nullable */
    filterTestAccounts?: boolean | null
    /** @nullable */
    groupKey?: string | null
    /** @nullable */
    groupTypeIndex?: number | null
    kind?: TracesQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /**
     * Person who performed the event
     * @nullable
     */
    personId?: string | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    /**
     * Use random ordering instead of timestamp DESC. Useful for representative sampling to avoid recency bias.
     * @nullable
     */
    randomOrder?: boolean | null
    response?: TracesQueryResponseApi | null
    /** @nullable */
    showColumnConfigurator?: boolean | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type TraceQueryApiKind = (typeof TraceQueryApiKind)[keyof typeof TraceQueryApiKind]

export const TraceQueryApiKind = {
    TraceQuery: 'TraceQuery',
} as const

export interface TraceQueryResponseApi {
    /** @nullable */
    columns?: string[] | null
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
    results: LLMTraceApi[]
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
}

export interface TraceQueryApi {
    dateRange?: DateRangeApi | null
    kind?: TraceQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
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
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: TraceQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    traceId: string
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type EndpointsUsageBreakdownApi = (typeof EndpointsUsageBreakdownApi)[keyof typeof EndpointsUsageBreakdownApi]

export const EndpointsUsageBreakdownApi = {
    Endpoint: 'Endpoint',
    MaterializationType: 'MaterializationType',
    ApiKey: 'ApiKey',
    Status: 'Status',
} as const

export type EndpointsUsageTableQueryApiKind =
    (typeof EndpointsUsageTableQueryApiKind)[keyof typeof EndpointsUsageTableQueryApiKind]

export const EndpointsUsageTableQueryApiKind = {
    EndpointsUsageTableQuery: 'EndpointsUsageTableQuery',
} as const

export type MaterializationTypeApi = (typeof MaterializationTypeApi)[keyof typeof MaterializationTypeApi]

export const MaterializationTypeApi = {
    Materialized: 'materialized',
    Inline: 'inline',
} as const

export type EndpointsUsageOrderByFieldApi =
    (typeof EndpointsUsageOrderByFieldApi)[keyof typeof EndpointsUsageOrderByFieldApi]

export const EndpointsUsageOrderByFieldApi = {
    Requests: 'requests',
    BytesRead: 'bytes_read',
    CpuSeconds: 'cpu_seconds',
    AvgQueryDurationMs: 'avg_query_duration_ms',
    ErrorRate: 'error_rate',
} as const

export type EndpointsUsageOrderByDirectionApi =
    (typeof EndpointsUsageOrderByDirectionApi)[keyof typeof EndpointsUsageOrderByDirectionApi]

export const EndpointsUsageOrderByDirectionApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export interface EndpointsUsageTableQueryResponseApi {
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
    /**
     * Measured timings for different parts of the query generation process
     * @nullable
     */
    timings?: QueryTimingApi[] | null
    /** @nullable */
    types?: unknown[] | null
}

export const EndpointsUsageTableQueryApiOrderByItem = {
    ...EndpointsUsageOrderByFieldApi,
    ...EndpointsUsageOrderByDirectionApi,
} as const
export interface EndpointsUsageTableQueryApi {
    breakdownBy: EndpointsUsageBreakdownApi
    dateRange?: DateRangeApi | null
    /**
     * Filter to specific endpoints by name
     * @nullable
     */
    endpointNames?: string[] | null
    kind?: EndpointsUsageTableQueryApiKind
    /** @nullable */
    limit?: number | null
    /** Filter by materialization type */
    materializationType?: MaterializationTypeApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** @nullable */
    offset?: number | null
    /** @nullable */
    orderBy?:
        | (typeof EndpointsUsageTableQueryApiOrderByItem)[keyof typeof EndpointsUsageTableQueryApiOrderByItem][]
        | null
    response?: EndpointsUsageTableQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type DataTableNodeApiResponse =
    | { [key: string]: unknown }
    | ResponseApi
    | Response1Api
    | Response2Api
    | Response3Api
    | Response4Api
    | Response5Api
    | Response6Api
    | Response8Api
    | Response9Api
    | Response10Api
    | Response11Api
    | Response12Api
    | Response13Api
    | Response14Api
    | Response15Api
    | Response16Api
    | Response18Api
    | Response19Api
    | Response20Api
    | Response21Api
    | Response22Api
    | Response23Api
    | Response24Api
    | Response25Api
    | Response26Api
    | null

export interface DataTableNodeApi {
    /**
     * Can the user click on column headers to sort the table? (default: true)
     * @nullable
     */
    allowSorting?: boolean | null
    /**
     * Columns shown in the table, unless the `source` provides them.
     * @nullable
     */
    columns?: string[] | null
    /** Context for the table, used by components like ColumnConfigurator */
    context?: DataTableNodeViewPropsContextApi | null
    /**
     * Context key for universal column configuration (e.g., "survey:123")
     * @nullable
     */
    contextKey?: string | null
    /**
     * Default columns to use when resetting column configuration
     * @nullable
     */
    defaultColumns?: string[] | null
    /**
     * Uses the embedded version of LemonTable
     * @nullable
     */
    embedded?: boolean | null
    /**
     * Can expand row to show raw event data (default: true)
     * @nullable
     */
    expandable?: boolean | null
    /**
     * Show with most visual options enabled. Used in scenes.
     * @nullable
     */
    full?: boolean | null
    /**
     * Columns that aren't shown in the table, even if in columns or returned data
     * @nullable
     */
    hiddenColumns?: string[] | null
    kind: DataTableNodeApiKind
    /**
     * Columns that are sticky when scrolling horizontally
     * @nullable
     */
    pinnedColumns?: string[] | null
    /**
     * Link properties via the URL (default: false)
     * @nullable
     */
    propertiesViaUrl?: boolean | null
    response?: DataTableNodeApiResponse
    /**
     * Show the kebab menu at the end of the row
     * @nullable
     */
    showActions?: boolean | null
    /**
     * Show a button to configure the table's columns if possible
     * @nullable
     */
    showColumnConfigurator?: boolean | null
    /**
     * Show count of total and filtered results
     * @nullable
     */
    showCount?: boolean | null
    /**
     * Show date range selector
     * @nullable
     */
    showDateRange?: boolean | null
    /**
     * Show the time it takes to run a query
     * @nullable
     */
    showElapsedTime?: boolean | null
    /**
     * Include an event filter above the table (EventsNode only)
     * @nullable
     */
    showEventFilter?: boolean | null
    /**
     * Include an events filter above the table to filter by multiple events (EventsQuery only)
     * @nullable
     */
    showEventsFilter?: boolean | null
    /**
     * Show the export button
     * @nullable
     */
    showExport?: boolean | null
    /**
     * Include a HogQL query editor above HogQL tables
     * @nullable
     */
    showHogQLEditor?: boolean | null
    /**
     * Show a button to open the current query as a new insight. (default: true)
     * @nullable
     */
    showOpenEditorButton?: boolean | null
    /**
     * Show a button to configure and persist the table's default columns if possible
     * @nullable
     */
    showPersistentColumnConfigurator?: boolean | null
    /** Include a property filter above the table */
    showPropertyFilter?: boolean | TaxonomicFilterGroupTypeApi[] | null
    /**
     * Show a recording column for events with session recordings
     * @nullable
     */
    showRecordingColumn?: boolean | null
    /**
     * Show a reload button
     * @nullable
     */
    showReload?: boolean | null
    /**
     * Show a results table
     * @nullable
     */
    showResultsTable?: boolean | null
    /**
     * Show saved filters feature for this table (requires uniqueKey)
     * @nullable
     */
    showSavedFilters?: boolean | null
    /**
     * Shows a list of saved queries
     * @nullable
     */
    showSavedQueries?: boolean | null
    /**
     * Include a free text search field (PersonsNode only)
     * @nullable
     */
    showSearch?: boolean | null
    /**
     * Show actors query options and back to source
     * @nullable
     */
    showSourceQueryOptions?: boolean | null
    /**
     * Show table views feature for this table (requires uniqueKey)
     * @nullable
     */
    showTableViews?: boolean | null
    /**
     * Show filter to exclude test accounts
     * @nullable
     */
    showTestAccountFilters?: boolean | null
    /**
     * Show a detailed query timing breakdown
     * @nullable
     */
    showTimings?: boolean | null
    /** Source of the events */
    source:
        | EventsNodeApi
        | EventsQueryApi
        | PersonsNodeApi
        | ActorsQueryApi
        | GroupsQueryApi
        | HogQLQueryApi
        | WebOverviewQueryApi
        | WebStatsTableQueryApi
        | WebExternalClicksTableQueryApi
        | WebGoalsQueryApi
        | WebVitalsQueryApi
        | WebVitalsPathBreakdownQueryApi
        | SessionAttributionExplorerQueryApi
        | SessionsQueryApi
        | RevenueAnalyticsGrossRevenueQueryApi
        | RevenueAnalyticsMetricsQueryApi
        | RevenueAnalyticsMRRQueryApi
        | RevenueAnalyticsOverviewQueryApi
        | RevenueAnalyticsTopCustomersQueryApi
        | RevenueExampleEventsQueryApi
        | RevenueExampleDataWarehouseTablesQueryApi
        | MarketingAnalyticsTableQueryApi
        | MarketingAnalyticsAggregatedQueryApi
        | NonIntegratedConversionsTableQueryApi
        | ErrorTrackingQueryApi
        | ErrorTrackingIssueCorrelationQueryApi
        | ExperimentFunnelsQueryApi
        | ExperimentTrendsQueryApi
        | TracesQueryApi
        | TraceQueryApi
        | EndpointsUsageTableQueryApi
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export interface HeatmapGradientStopApi {
    color: string
    value: number
}

export type GradientScaleModeApi = (typeof GradientScaleModeApi)[keyof typeof GradientScaleModeApi]

export const GradientScaleModeApi = {
    Absolute: 'absolute',
    Relative: 'relative',
} as const

export type HeatmapSortOrderApi = (typeof HeatmapSortOrderApi)[keyof typeof HeatmapSortOrderApi]

export const HeatmapSortOrderApi = {
    Asc: 'asc',
    Desc: 'desc',
} as const

export interface HeatmapSettingsApi {
    /** @nullable */
    gradient?: HeatmapGradientStopApi[] | null
    /** @nullable */
    gradientPreset?: string | null
    gradientScaleMode?: GradientScaleModeApi | null
    /** @nullable */
    nullLabel?: string | null
    /** @nullable */
    nullValue?: string | null
    /** @nullable */
    sortColumn?: string | null
    sortOrder?: HeatmapSortOrderApi | null
    /** @nullable */
    valueColumn?: string | null
    /** @nullable */
    xAxisColumn?: string | null
    /** @nullable */
    xAxisLabel?: string | null
    /** @nullable */
    yAxisColumn?: string | null
    /** @nullable */
    yAxisLabel?: string | null
}

export type ScaleApi = (typeof ScaleApi)[keyof typeof ScaleApi]

export const ScaleApi = {
    Linear: 'linear',
    Logarithmic: 'logarithmic',
} as const

export interface YAxisSettingsApi {
    scale?: ScaleApi | null
    /** @nullable */
    showGridLines?: boolean | null
    /** @nullable */
    showTicks?: boolean | null
    /**
     * Whether the Y axis should start at zero
     * @nullable
     */
    startAtZero?: boolean | null
}

export type DisplayTypeApi = (typeof DisplayTypeApi)[keyof typeof DisplayTypeApi]

export const DisplayTypeApi = {
    Auto: 'auto',
    Line: 'line',
    Bar: 'bar',
    Area: 'area',
} as const

export type YAxisPositionApi = (typeof YAxisPositionApi)[keyof typeof YAxisPositionApi]

export const YAxisPositionApi = {
    Left: 'left',
    Right: 'right',
} as const

export interface ChartSettingsDisplayApi {
    /** @nullable */
    color?: string | null
    displayType?: DisplayTypeApi | null
    /** @nullable */
    label?: string | null
    /** @nullable */
    trendLine?: boolean | null
    yAxisPosition?: YAxisPositionApi | null
}

export type StyleApi = (typeof StyleApi)[keyof typeof StyleApi]

export const StyleApi = {
    None: 'none',
    Number: 'number',
    Short: 'short',
    Percent: 'percent',
} as const

export interface ChartSettingsFormattingApi {
    /** @nullable */
    decimalPlaces?: number | null
    /** @nullable */
    prefix?: string | null
    style?: StyleApi | null
    /** @nullable */
    suffix?: string | null
}

export interface SettingsApi {
    display?: ChartSettingsDisplayApi | null
    formatting?: ChartSettingsFormattingApi | null
}

export interface ChartAxisApi {
    column: string
    settings?: SettingsApi | null
}

export interface ChartSettingsApi {
    /** @nullable */
    goalLines?: GoalLineApi[] | null
    heatmap?: HeatmapSettingsApi | null
    leftYAxisSettings?: YAxisSettingsApi | null
    rightYAxisSettings?: YAxisSettingsApi | null
    /** @nullable */
    seriesBreakdownColumn?: string | null
    /** @nullable */
    showLegend?: boolean | null
    /** @nullable */
    showNullsAsZero?: boolean | null
    /** @nullable */
    showPieTotal?: boolean | null
    /** @nullable */
    showTotalRow?: boolean | null
    /** @nullable */
    showValuesOnSeries?: boolean | null
    /** @nullable */
    showXAxisBorder?: boolean | null
    /** @nullable */
    showXAxisTicks?: boolean | null
    /** @nullable */
    showYAxisBorder?: boolean | null
    /**
     * Whether we fill the bars to 100% in stacked mode
     * @nullable
     */
    stackBars100?: boolean | null
    xAxis?: ChartAxisApi | null
    /** @nullable */
    yAxis?: ChartAxisApi[] | null
    /**
     * Deprecated: use `[left|right]YAxisSettings`. Whether the Y axis should start at zero
     * @nullable
     */
    yAxisAtZero?: boolean | null
}

export type DataVisualizationNodeApiKind =
    (typeof DataVisualizationNodeApiKind)[keyof typeof DataVisualizationNodeApiKind]

export const DataVisualizationNodeApiKind = {
    DataVisualizationNode: 'DataVisualizationNode',
} as const

export type ColorModeApi = (typeof ColorModeApi)[keyof typeof ColorModeApi]

export const ColorModeApi = {
    Light: 'light',
    Dark: 'dark',
} as const

export interface ConditionalFormattingRuleApi {
    bytecode: unknown[]
    color: string
    colorMode?: ColorModeApi | null
    columnName: string
    id: string
    input: string
    templateId: string
}

export interface TableSettingsApi {
    /** @nullable */
    columns?: ChartAxisApi[] | null
    /** @nullable */
    conditionalFormatting?: ConditionalFormattingRuleApi[] | null
    /** @nullable */
    pinnedColumns?: string[] | null
    /** @nullable */
    transpose?: boolean | null
}

export interface DataVisualizationNodeApi {
    chartSettings?: ChartSettingsApi | null
    display?: ChartDisplayTypeApi | null
    kind: DataVisualizationNodeApiKind
    source: HogQLQueryApi
    tableSettings?: TableSettingsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

export type HogQueryApiKind = (typeof HogQueryApiKind)[keyof typeof HogQueryApiKind]

export const HogQueryApiKind = {
    HogQuery: 'HogQuery',
} as const

export interface HogQueryResponseApi {
    /** @nullable */
    bytecode?: unknown[] | null
    /** @nullable */
    coloredBytecode?: unknown[] | null
    results: unknown
    /** @nullable */
    stdout?: string | null
}

export interface HogQueryApi {
    /** @nullable */
    code?: string | null
    kind: HogQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: HogQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /**
     * version of the node, used for schema migrations
     * @nullable
     */
    version?: number | null
}

/**
 * The query definition for this insight. The `kind` field determines the query type:
- `InsightVizNode` — product analytics (trends, funnels, retention, paths, stickiness, lifecycle)
- `DataVisualizationNode` — SQL insights using HogQL
- `DataTableNode` — raw data tables
- `HogQuery` — Hog language queries
 */
export type _InsightQuerySchemaApi = InsightVizNodeApi | DataTableNodeApi | DataVisualizationNodeApi | HogQueryApi

export interface DashboardTileBasicApi {
    readonly id: number
    readonly dashboard_id: number
    /** @nullable */
    deleted?: boolean | null
}

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

export type EffectiveRestrictionLevelEnumApi =
    (typeof EffectiveRestrictionLevelEnumApi)[keyof typeof EffectiveRestrictionLevelEnumApi]

export const EffectiveRestrictionLevelEnumApi = {
    Number21: 21,
    Number37: 37,
} as const

export type EffectivePrivilegeLevelEnumApi =
    (typeof EffectivePrivilegeLevelEnumApi)[keyof typeof EffectivePrivilegeLevelEnumApi]

export const EffectivePrivilegeLevelEnumApi = {
    Number21: 21,
    Number37: 37,
} as const

/**
 * @nullable
 */
export type InsightApiResolvedDateRange = {
    readonly date_from?: string
    readonly date_to?: string
} | null | null

/**
 * Simplified serializer to speed response times when loading large amounts of objects.
 */
export interface InsightApi {
    readonly id: number
    readonly short_id: string
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    derived_name?: string | null
    query?: _InsightQuerySchemaApi | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    order?: number | null
    deleted?: boolean
    /**
        DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.
        A dashboard ID for each of the dashboards that this insight is displayed on.
         */
    dashboards?: number[]
    /**
    A dashboard tile ID and dashboard_id for each of the dashboards that this insight is displayed on.
     */
    readonly dashboard_tiles: readonly DashboardTileBasicApi[]
    /**
   * 
    The datetime this insight's results were generated.
    If added to one or more dashboards the insight can be refreshed separately on each.
    Returns the appropriate last_refresh datetime for the context the insight is viewed in
    (see from_dashboard query parameter).
    
   * @nullable
   */
    readonly last_refresh: string | null
    /**
     * The target age of the cached results for this insight.
     * @nullable
     */
    readonly cache_target_age: string | null
    /**
   * 
    The earliest possible datetime at which we'll allow the cached results for this insight to be refreshed
    by querying the database.
    
   * @nullable
   */
    readonly next_allowed_client_refresh: string | null
    readonly result: unknown
    /** @nullable */
    readonly hasMore: boolean | null
    /** @nullable */
    readonly columns: readonly string[] | null
    /** @nullable */
    readonly created_at: string | null
    readonly created_by: UserBasicApi
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly updated_at: string
    tags?: unknown[]
    favorited?: boolean
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
    readonly is_sample: boolean
    readonly effective_restriction_level: EffectiveRestrictionLevelEnumApi
    readonly effective_privilege_level: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    /**
     * The timezone this chart is displayed in.
     * @nullable
     */
    readonly timezone: string | null
    readonly is_cached: boolean
    readonly query_status: unknown
    /** @nullable */
    readonly hogql: string | null
    /** @nullable */
    readonly types: readonly unknown[] | null
    /** @nullable */
    readonly resolved_date_range: InsightApiResolvedDateRange
    _create_in_folder?: string
    readonly alerts: readonly unknown[]
    /** @nullable */
    readonly last_viewed_at: string | null
}

export interface PaginatedInsightListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: InsightApi[]
}

/**
 * @nullable
 */
export type PatchedInsightApiResolvedDateRange = {
    readonly date_from?: string
    readonly date_to?: string
} | null | null

/**
 * Simplified serializer to speed response times when loading large amounts of objects.
 */
export interface PatchedInsightApi {
    readonly id?: number
    readonly short_id?: string
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    derived_name?: string | null
    query?: _InsightQuerySchemaApi | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    order?: number | null
    deleted?: boolean
    /**
        DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.
        A dashboard ID for each of the dashboards that this insight is displayed on.
         */
    dashboards?: number[]
    /**
    A dashboard tile ID and dashboard_id for each of the dashboards that this insight is displayed on.
     */
    readonly dashboard_tiles?: readonly DashboardTileBasicApi[]
    /**
   * 
    The datetime this insight's results were generated.
    If added to one or more dashboards the insight can be refreshed separately on each.
    Returns the appropriate last_refresh datetime for the context the insight is viewed in
    (see from_dashboard query parameter).
    
   * @nullable
   */
    readonly last_refresh?: string | null
    /**
     * The target age of the cached results for this insight.
     * @nullable
     */
    readonly cache_target_age?: string | null
    /**
   * 
    The earliest possible datetime at which we'll allow the cached results for this insight to be refreshed
    by querying the database.
    
   * @nullable
   */
    readonly next_allowed_client_refresh?: string | null
    readonly result?: unknown
    /** @nullable */
    readonly hasMore?: boolean | null
    /** @nullable */
    readonly columns?: readonly string[] | null
    /** @nullable */
    readonly created_at?: string | null
    readonly created_by?: UserBasicApi
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly updated_at?: string
    tags?: unknown[]
    favorited?: boolean
    readonly last_modified_at?: string
    readonly last_modified_by?: UserBasicApi
    readonly is_sample?: boolean
    readonly effective_restriction_level?: EffectiveRestrictionLevelEnumApi
    readonly effective_privilege_level?: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    /**
     * The timezone this chart is displayed in.
     * @nullable
     */
    readonly timezone?: string | null
    readonly is_cached?: boolean
    readonly query_status?: unknown
    /** @nullable */
    readonly hogql?: string | null
    /** @nullable */
    readonly types?: readonly unknown[] | null
    /** @nullable */
    readonly resolved_date_range?: PatchedInsightApiResolvedDateRange
    _create_in_folder?: string
    readonly alerts?: readonly unknown[]
    /** @nullable */
    readonly last_viewed_at?: string | null
}

/**
 * * `add` - add
 * `remove` - remove
 * `set` - set
 */
export type ActionEnumApi = (typeof ActionEnumApi)[keyof typeof ActionEnumApi]

export const ActionEnumApi = {
    Add: 'add',
    Remove: 'remove',
    Set: 'set',
} as const

export interface BulkUpdateTagsRequestApi {
    /**
     * List of object IDs to update tags on.
     * @maxItems 500
     */
    ids: number[]
    /** 'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.

* `add` - add
* `remove` - remove
* `set` - set */
    action: ActionEnumApi
    /** Tag names to add, remove, or set. */
    tags: string[]
}

export interface BulkUpdateTagsItemApi {
    id: number
    tags: string[]
}

export interface BulkUpdateTagsErrorApi {
    id: number
    reason: string
}

export interface BulkUpdateTagsResponseApi {
    updated: BulkUpdateTagsItemApi[]
    skipped: BulkUpdateTagsErrorApi[]
}

export type ColumnConfigurationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ElementsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type InsightsListParams = {
    /**
     * Return basic insight metadata only (no results, faster).
     */
    basic?: boolean
    format?: InsightsListFormat
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * 
Whether to refresh the retrieved insights, how aggressively, and if sync or async:
- `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates
- `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache
- `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache
- `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache
- `'force_blocking'` - calculate synchronously, even if fresh results are already cached
- `'force_async'` - kick off background calculation, even if fresh results are already cached
Background calculation can be tracked using the `query_status` response field.
 */
    refresh?: InsightsListRefresh
    short_id?: string
}

export type InsightsListFormat = (typeof InsightsListFormat)[keyof typeof InsightsListFormat]

export const InsightsListFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsListRefresh = (typeof InsightsListRefresh)[keyof typeof InsightsListRefresh]

export const InsightsListRefresh = {
    Async: 'async',
    AsyncExceptOnCacheMiss: 'async_except_on_cache_miss',
    Blocking: 'blocking',
    ForceAsync: 'force_async',
    ForceBlocking: 'force_blocking',
    ForceCache: 'force_cache',
    LazyAsync: 'lazy_async',
} as const

export type InsightsCreateParams = {
    format?: InsightsCreateFormat
}

export type InsightsCreateFormat = (typeof InsightsCreateFormat)[keyof typeof InsightsCreateFormat]

export const InsightsCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsRetrieveParams = {
    format?: InsightsRetrieveFormat
    /**
 * 
Only if loading an insight in the context of a dashboard: The relevant dashboard's ID.
When set, the specified dashboard's filters and date range override will be applied.
 */
    from_dashboard?: number
    /**
 * 
Whether to refresh the insight, how aggresively, and if sync or async:
- `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates
- `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache
- `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache
- `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache
- `'force_blocking'` - calculate synchronously, even if fresh results are already cached
- `'force_async'` - kick off background calculation, even if fresh results are already cached
Background calculation can be tracked using the `query_status` response field.
 */
    refresh?: InsightsRetrieveRefresh
}

export type InsightsRetrieveFormat = (typeof InsightsRetrieveFormat)[keyof typeof InsightsRetrieveFormat]

export const InsightsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsRetrieveRefresh = (typeof InsightsRetrieveRefresh)[keyof typeof InsightsRetrieveRefresh]

export const InsightsRetrieveRefresh = {
    Async: 'async',
    AsyncExceptOnCacheMiss: 'async_except_on_cache_miss',
    Blocking: 'blocking',
    ForceAsync: 'force_async',
    ForceBlocking: 'force_blocking',
    ForceCache: 'force_cache',
    LazyAsync: 'lazy_async',
} as const

export type InsightsUpdateParams = {
    format?: InsightsUpdateFormat
}

export type InsightsUpdateFormat = (typeof InsightsUpdateFormat)[keyof typeof InsightsUpdateFormat]

export const InsightsUpdateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsPartialUpdateParams = {
    format?: InsightsPartialUpdateFormat
}

export type InsightsPartialUpdateFormat = (typeof InsightsPartialUpdateFormat)[keyof typeof InsightsPartialUpdateFormat]

export const InsightsPartialUpdateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsDestroyParams = {
    format?: InsightsDestroyFormat
}

export type InsightsDestroyFormat = (typeof InsightsDestroyFormat)[keyof typeof InsightsDestroyFormat]

export const InsightsDestroyFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsActivityRetrieve2Params = {
    format?: InsightsActivityRetrieve2Format
}

export type InsightsActivityRetrieve2Format =
    (typeof InsightsActivityRetrieve2Format)[keyof typeof InsightsActivityRetrieve2Format]

export const InsightsActivityRetrieve2Format = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsAnalyzeRetrieveParams = {
    format?: InsightsAnalyzeRetrieveFormat
}

export type InsightsAnalyzeRetrieveFormat =
    (typeof InsightsAnalyzeRetrieveFormat)[keyof typeof InsightsAnalyzeRetrieveFormat]

export const InsightsAnalyzeRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsSuggestionsRetrieveParams = {
    format?: InsightsSuggestionsRetrieveFormat
}

export type InsightsSuggestionsRetrieveFormat =
    (typeof InsightsSuggestionsRetrieveFormat)[keyof typeof InsightsSuggestionsRetrieveFormat]

export const InsightsSuggestionsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsSuggestionsCreateParams = {
    format?: InsightsSuggestionsCreateFormat
}

export type InsightsSuggestionsCreateFormat =
    (typeof InsightsSuggestionsCreateFormat)[keyof typeof InsightsSuggestionsCreateFormat]

export const InsightsSuggestionsCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsActivityRetrieveParams = {
    format?: InsightsActivityRetrieveFormat
}

export type InsightsActivityRetrieveFormat =
    (typeof InsightsActivityRetrieveFormat)[keyof typeof InsightsActivityRetrieveFormat]

export const InsightsActivityRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsBulkUpdateTagsCreateParams = {
    format?: InsightsBulkUpdateTagsCreateFormat
}

export type InsightsBulkUpdateTagsCreateFormat =
    (typeof InsightsBulkUpdateTagsCreateFormat)[keyof typeof InsightsBulkUpdateTagsCreateFormat]

export const InsightsBulkUpdateTagsCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsCancelCreateParams = {
    format?: InsightsCancelCreateFormat
}

export type InsightsCancelCreateFormat = (typeof InsightsCancelCreateFormat)[keyof typeof InsightsCancelCreateFormat]

export const InsightsCancelCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsGenerateMetadataCreateParams = {
    format?: InsightsGenerateMetadataCreateFormat
}

export type InsightsGenerateMetadataCreateFormat =
    (typeof InsightsGenerateMetadataCreateFormat)[keyof typeof InsightsGenerateMetadataCreateFormat]

export const InsightsGenerateMetadataCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsMyLastViewedRetrieveParams = {
    format?: InsightsMyLastViewedRetrieveFormat
}

export type InsightsMyLastViewedRetrieveFormat =
    (typeof InsightsMyLastViewedRetrieveFormat)[keyof typeof InsightsMyLastViewedRetrieveFormat]

export const InsightsMyLastViewedRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsTrendingRetrieveParams = {
    format?: InsightsTrendingRetrieveFormat
}

export type InsightsTrendingRetrieveFormat =
    (typeof InsightsTrendingRetrieveFormat)[keyof typeof InsightsTrendingRetrieveFormat]

export const InsightsTrendingRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsViewedCreateParams = {
    format?: InsightsViewedCreateFormat
}

export type InsightsViewedCreateFormat = (typeof InsightsViewedCreateFormat)[keyof typeof InsightsViewedCreateFormat]

export const InsightsViewedCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const
