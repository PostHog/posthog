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
 * * `shared` - Shared with team
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
    /** Column filter state persisted with this view configuration. */
    filters?: unknown
    /**
     * Ordered list of HogQL expressions describing the table sort. Null preserves the current sort on apply (legacy rows); an empty list explicitly means no sort.
     * @nullable
     */
    order_by?: string[] | null
    /** Product-specific view state that does not fit the columnar fields (e.g. Customer analytics overview tiles and column display). */
    properties?: unknown
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
    /** Column filter state persisted with this view configuration. */
    filters?: unknown
    /**
     * Ordered list of HogQL expressions describing the table sort. Null preserves the current sort on apply (legacy rows); an empty list explicitly means no sort.
     * @nullable
     */
    order_by?: string[] | null
    /** Product-specific view state that does not fit the columnar fields (e.g. Customer analytics overview tiles and column display). */
    properties?: unknown
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
    /**
     * @nullable
     * @items.maxLength 200
     */
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
    /**
     * @nullable
     * @items.maxLength 200
     */
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

export interface ElementStatsApi {
    /** Number of events matching this element chain */
    count: number
    /**
     * Stable identity of the raw element chain (hash computed before any attribute filtering), for deduplicating rows across pages
     * @nullable
     */
    hash: string | null
    /** Event type: $autocapture, $rageclick, or $dead_click */
    type: string
    /** Parsed elements of the chain, clicked element first */
    elements: ElementApi[]
}

export interface ElementStatsResponseApi {
    /** Element chains with event counts, ordered by count */
    results: ElementStatsApi[]
    /**
     * URL for the next page of results, if any
     * @nullable
     */
    next: string | null
    /**
     * URL for the previous page of results, if any
     * @nullable
     */
    previous: string | null
}

export interface ElementValueApi {
    /** A distinct value of the requested element property */
    name: string
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

export interface BreakdownApi {
    group_type_index?: number | null
    histogram_bin_count?: number | null
    normalize_url?: boolean | null
    property: string | number
    type?: MultipleBreakdownTypeApi | null
}

export interface BreakdownFilterApi {
    breakdown?: string | (string | number)[] | number | null
    breakdown_group_type_index?: number | null
    breakdown_hide_other_aggregation?: boolean | null
    breakdown_histogram_bin_count?: number | null
    breakdown_limit?: number | null
    breakdown_normalize_url?: boolean | null
    breakdown_path_cleaning?: boolean | null
    breakdown_type?: BreakdownTypeApi | null
    breakdowns?: BreakdownApi[] | null
}

export interface CalendarHeatmapFilterApi {
    /** When true and the series math is `dau`/`unique_users`, each user contributes to the (day-of-week, hour) bucket of their session's first event only — matching the web overview session-start attribution. When false (default), the user contributes to every bucket they have any event in. No effect on `total` math (event counts are unchanged either way). */
    bucketBySessionStart?: boolean | null
}

export interface CompareFilterApi {
    /** Whether to compare the current date range to a previous date range. */
    compare?: boolean | null
    /** The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago. */
    compare_to?: string | null
}

export interface ActionConversionGoalApi {
    actionId: number
}

export interface CustomEventConversionGoalApi {
    customEventName: string
}

export interface DateRangeApi {
    /** Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),
     * -1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year). */
    date_from?: string | null
    /** End of the date range. Same format as date_from. Omit or null for "now". */
    date_to?: string | null
    /** Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period. */
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

export type ParserModeApi = (typeof ParserModeApi)[keyof typeof ParserModeApi]

export const ParserModeApi = {
    CppOnly: 'cpp_only',
    CppWithRustShadow: 'cpp_with_rust_shadow',
    CppWithRustPyShadow: 'cpp_with_rust_py_shadow',
    RustWithCppShadow: 'rust_with_cpp_shadow',
    RustOnly: 'rust_only',
    RustPyOnly: 'rust_py_only',
    RustPyWithCppShadow: 'rust_py_with_cpp_shadow',
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
    bounceRateDurationSeconds?: number | null
    bounceRatePageViewMode?: BounceRatePageViewModeApi | null
    convertToProjectTimezone?: boolean | null
    customChannelTypeRules?: CustomChannelRuleApi[] | null
    dataWarehouseEventsModifiers?: DataWarehouseEventsModifierApi[] | null
    debug?: boolean | null
    /** If these are provided, the query will fail if these skip indexes are not used */
    forceClickhouseDataSkippingIndexes?: string[] | null
    formatCsvAllowDoubleQuotes?: boolean | null
    inCohortVia?: InCohortViaApi | null
    inlineCohortCalculation?: InlineCohortCalculationApi | null
    materializationMode?: MaterializationModeApi | null
    materializedColumnsOptimizationMode?: MaterializedColumnsOptimizationModeApi | null
    optimizeJoinedFilters?: boolean | null
    optimizeProjections?: boolean | null
    /** HogQL parser backend; absent → `rust_py_with_cpp_shadow` (rust-py is primary, cpp runs as a sampled shadow). `*_shadow` modes return the primary result and sample-compare against the other parser, reporting divergences without failing the request. The `rust_py_*` modes drive the same hand-rolled Rust parser as `rust_*` but build `posthog.hogql.ast` dataclass instances directly via PyO3, skipping the JSON round-trip. */
    parserMode?: ParserModeApi | null
    personsArgMaxVersion?: PersonsArgMaxVersionApi | null
    personsJoinMode?: PersonsJoinModeApi | null
    personsOnEventsMode?: PersonsOnEventsModeApi | null
    propertyGroupsMode?: PropertyGroupsModeApi | null
    pushDownPredicates?: boolean | null
    s3TableUseInvalidColumns?: boolean | null
    /** Push a `session_id_v7 IN (SELECT … FROM events WHERE …)` predicate into the raw_sessions subquery to limit aggregation to sessions that participate in the outer events filter. */
    sessionIdPushdown?: boolean | null
    /** Pre-filter raw_sessions aggregation by `session_id_v7 IN (cheap pre-aggregation that only materializes the columns referenced by the outer-WHERE session predicate)`. Useful when the breakdown/SELECT pulls in many session columns (e.g. `$channel_type`) but the filter only references one (e.g. `$entry_current_url`). */
    sessionPropertyPreAggregation?: boolean | null
    sessionTableVersion?: SessionTableVersionApi | null
    sessionsV2JoinMode?: SessionsV2JoinModeApi | null
    timings?: boolean | null
    useMaterializedViews?: boolean | null
    usePreaggregatedIntermediateResults?: boolean | null
    /** Try to automatically convert HogQL queries to use preaggregated tables at the AST level * */
    usePreaggregatedTableTransforms?: boolean | null
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

export interface EventPropertyFilterApi {
    key: string
    label?: string | null
    operator?: PropertyOperatorApi | null
    /** Event properties */
    type?: 'event'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: 'person'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Top-level columns on the persons table (e.g. created_at), not properties JSON */
    type?: 'person_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export interface ElementPropertyFilterApi {
    key: Key10Api
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'element'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface EventMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'event_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface SessionPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'session'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface CohortPropertyFilterApi {
    cohort_name?: string | null
    key?: 'id'
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: 'cohort'
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export interface RecordingPropertyFilterApi {
    key: DurationTypeApi | string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'recording'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface LogEntryPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'log_entry'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null

export interface GroupPropertyFilterApi {
    group_key_names?: GroupPropertyFilterApiGroupKeyNames
    group_type_index?: number | null
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'group'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FeaturePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: 'feature'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FlagPropertyFilterApi {
    /** The key should be the flag ID */
    key: string
    label?: string | null
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator?: 'flag_evaluates_to'
    /** Feature flag dependency */
    type?: 'flag'
    /** The value can be true, false, or a variant name */
    value: boolean | string
}

export interface HogQLPropertyFilterApi {
    key: string
    label?: string | null
    type?: 'hogql'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export const EmptyPropertyFilterApiValue = {
    type: 'empty',
} as const
export type EmptyPropertyFilterApi = typeof EmptyPropertyFilterApiValue

export interface DataWarehousePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse_person_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface ErrorTrackingIssueFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'error_tracking_issue'
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
    label?: string | null
    operator: PropertyOperatorApi
    type: SpanPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'revenue_analytics'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface WorkflowVariablePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'workflow_variable'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PropertyGroupFilterValueApi {
    type: FilterLogicalOperatorApi
    values: (
        | PropertyGroupFilterValueApi
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | PersonMetadataPropertyFilterApi
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
    series_index?: number | null
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
    /** Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set. */
    complete?: boolean | null
    dashboard_id?: number | null
    /** When did the query execution task finish (whether successfully or not). */
    end_time?: string | null
    /** If the query failed, this will be set to true. More information can be found in the error_message field. */
    error?: boolean | null
    error_message?: string | null
    expiration_time?: string | null
    id: string
    insight_id?: number | null
    labels?: string[] | null
    /** When was the query execution task picked up by a worker. */
    pickup_time?: string | null
    /** ONLY async queries use QueryStatus. */
    query_async?: true
    query_progress?: ClickhouseQueryProgressApi | null
    results?: unknown
    /** When was query execution task enqueued. */
    start_time?: string | null
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

export interface DataWarehouseSyncWarningApi {
    /** Human-readable warning shown to the user */
    message: string
    /** Name of the ExternalDataSchema responsible for syncing the table */
    schema_name: string
    /** ID of the ExternalDataSource, used to link to its management page. Null for self-managed tables. */
    source_id?: string | null
    /** Source type, e.g. "Stripe", "Hubspot" */
    source_type: string
    /** Sync status that triggered the warning, e.g. "Failed", "Paused", "BillingLimitReached" */
    status: string
    /** Name of the warehouse table the warning refers to */
    table_name: string
}

export type TrendsQueryResponseApiResultsItem = { [key: string]: unknown }

export interface TrendsQueryResponseApi {
    boxplot_data?: BoxPlotDatumApi[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Wether more breakdown values are available. */
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: TrendsQueryResponseApiResultsItem[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

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
    property?: string | null
    static?: CurrencyCodeApi | null
}

export type EventsNodeApiResponse = { [key: string]: unknown } | null

export interface EventsNodeApi {
    custom_name?: string | null
    /** The event or `null` for all events. */
    event?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: EventsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ActionsNodeApiResponse = { [key: string]: unknown } | null

export interface ActionsNodeApi {
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'ActionsNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: ActionsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type DataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export interface DataWarehouseNodeApi {
    custom_name?: string | null
    distinct_id_field: string
    dw_source_type?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'DataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: DataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type GroupNodeApiResponse = { [key: string]: unknown } | null

export interface GroupNodeApi {
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'GroupNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    /** Entities to combine in this group */
    nodes: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Group of entities combined with AND/OR operator */
    operator: FilterLogicalOperatorApi
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: GroupNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface QueryLogTagsApi {
    /** Name of the query, preferably unique. For example web_analytics_vitals */
    name?: string | null
    /** Product responsible for this query. Use string, there's no need to churn the Schema when we add a new product * */
    productKey?: string | null
    /** Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a new Scene * */
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
    Metric: 'Metric',
    ActionsPie: 'ActionsPie',
    ActionsBarValue: 'ActionsBarValue',
    ActionsTable: 'ActionsTable',
    WorldMap: 'WorldMap',
    CalendarHeatmap: 'CalendarHeatmap',
    TwoDimensionalHeatmap: 'TwoDimensionalHeatmap',
    BoxPlot: 'BoxPlot',
    SlopeGraph: 'SlopeGraph',
} as const

export interface TrendsFormulaNodeApi {
    /** Optional user-defined name for the formula */
    custom_name?: string | null
    formula: string
}

export type PositionApi = (typeof PositionApi)[keyof typeof PositionApi]

export const PositionApi = {
    Start: 'start',
    End: 'end',
} as const

export interface GoalLineApi {
    borderColor?: string | null
    displayIfCrossed?: boolean | null
    displayLabel?: boolean | null
    label: string
    position?: PositionApi | null
    value: number
}

export type LegendPositionApi = (typeof LegendPositionApi)[keyof typeof LegendPositionApi]

export const LegendPositionApi = {
    Top: 'top',
    Bottom: 'bottom',
    Left: 'left',
    Right: 'right',
} as const

export type MetricSummaryApi = (typeof MetricSummaryApi)[keyof typeof MetricSummaryApi]

export const MetricSummaryApi = {
    Total: 'total',
    Average: 'average',
    Latest: 'latest',
} as const

export type ResultCustomizationByApi = (typeof ResultCustomizationByApi)[keyof typeof ResultCustomizationByApi]

export const ResultCustomizationByApi = {
    Value: 'value',
    Position: 'position',
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
    assignmentBy?: 'value'
    color?: DataColorTokenApi | null
    hidden?: boolean | null
}

export interface ResultCustomizationByPositionApi {
    assignmentBy?: 'position'
    color?: DataColorTokenApi | null
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
    /** Y-axis value formatter. Picks a human-friendly unit per value at render time without changing the underlying series values.
     *
     * - `numeric` (default): raw numbers, e.g. `1,234`.
     * - `duration`: values are in seconds; rendered as friendly units per value (`45s`, `2m 12s`, `1h 4m`). Use this whenever the series is in seconds (latency, session length, time-to-event) instead of dividing in `formula` to force minutes or hours.
     * - `duration_ms`: values are in milliseconds; rendered as friendly units (`850ms`, `1.5s`, `1m 4s`).
     * - `percentage`: values are already in the 0-100 range; appends `%`.
     * - `percentage_scaled`: values are a 0-1 ratio; multiplied and rendered as `%`.
     * - `currency`: values are in the project's base currency (set in project settings, defaults to USD); rendered with that currency symbol. For values pinned to a specific currency regardless of project base (e.g. `$ai_total_cost_usd` is always USD), use `aggregationAxisPrefix` instead.
     * - `short`: compact notation for large counts (`1.2K`, `3.4M`). */
    aggregationAxisFormat?: AggregationAxisFormatApi | null
    /** Literal suffix applied to every value (e.g. ` req`). Reserve for units that `aggregationAxisFormat` cannot express. Do not use ` mins`, ` s`, ` ms`, `%` etc. — pick the matching `aggregationAxisFormat` instead so the underlying values stay numerically correct for breakdowns, formulas, and alerts. Include any leading space yourself. */
    aggregationAxisPostfix?: string | null
    /** Literal prefix applied to every value (e.g. `$`). Use to pin a unit or currency symbol that does not depend on `aggregationAxisFormat` — for example, when values are denominated in a fixed currency regardless of the project's base currency. Include any trailing space yourself. */
    aggregationAxisPrefix?: string | null
    breakdown_histogram_bin_count?: number | null
    confidenceLevel?: number | null
    /** Maximum number of decimal places shown. 1 or 2 is usually right for percentages and currency. */
    decimalPlaces?: number | null
    /** detailed results table */
    detailedResultsAggregationType?: DetailedResultsAggregationTypeApi | null
    display?: ChartDisplayTypeApi | null
    excludeBoxPlotOutliers?: boolean | null
    formula?: string | null
    /** List of formulas with optional custom names. Takes precedence over formula/formulas if set. */
    formulaNodes?: TrendsFormulaNodeApi[] | null
    formulas?: string[] | null
    /** Goal Lines */
    goalLines?: GoalLineApi[] | null
    hiddenLegendIndexes?: number[] | null
    hideWeekends?: boolean | null
    /** Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend. */
    legendPosition?: LegendPositionApi | null
    /** Metric display: change pill color when the metric decreased. Defaults to red. */
    metricChangeDecreaseColor?: string | null
    /** Metric display: change pill color when the metric increased. Defaults to green. */
    metricChangeIncreaseColor?: string | null
    /** Metric display: color the sparkline by whether the metric increased or decreased. */
    metricColorByDirection?: boolean | null
    /** Metric display: line color when the metric decreased. Defaults to red. */
    metricLineDecreaseColor?: string | null
    /** Metric display: line color when the metric increased. Defaults to green. */
    metricLineIncreaseColor?: string | null
    /** Show the period-over-period change pill on the Metric display. */
    metricShowChange?: boolean | null
    /** Metric display: which summary the resting headline shows — the period total, the average, or the latest point. Hovering the sparkline always shows the hovered point's value. Also drives the change pill: total/average compare against the previous period when "compare to previous" is on; latest compares first→last of the series. */
    metricSummary?: MetricSummaryApi | null
    minDecimalPlaces?: number | null
    movingAverageIntervals?: number | null
    /** Wether result datasets are associated by their values or by their order. */
    resultCustomizationBy?: ResultCustomizationByApi | null
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: TrendsFilterApiResultCustomizations
    showAlertThresholdLines?: boolean | null
    showAnnotations?: boolean | null
    showConfidenceIntervals?: boolean | null
    showLabelsOnSeries?: boolean | null
    showLegend?: boolean | null
    showMovingAverage?: boolean | null
    showMultipleYAxes?: boolean | null
    showPercentStackView?: boolean | null
    showTrendLines?: boolean | null
    showValuesOnSeries?: boolean | null
    smoothingIntervals?: number | null
    /** On the horizontal bar-value chart, stack a series' breakdown values into a single bar instead of rendering one bar per breakdown value. */
    stackBreakdownValues?: boolean | null
    /** Custom label rendered under the X axis. */
    xAxisLabel?: string | null
    /** Custom label rendered alongside the Y axis. */
    yAxisLabel?: string | null
    yAxisScaleType?: YAxisScaleTypeApi | null
}

export interface TrendsQueryApi {
    /** Groups aggregation */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi | null
    /** Properties specific to the calendar heatmap display variant. Only consulted when `trendsFilter.display === ChartDisplayType.CalendarHeatmap`; ignored otherwise. */
    calendarHeatmapFilter?: CalendarHeatmapFilterApi | null
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    /** Whether we should be comparing against a specific conversion goal */
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    kind?: 'TrendsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Sampling rate */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (GroupNodeApi | EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** Properties specific to the trends insight */
    trendsFilter?: TrendsFilterApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type BreakdownAttributionTypeApi = (typeof BreakdownAttributionTypeApi)[keyof typeof BreakdownAttributionTypeApi]

export const BreakdownAttributionTypeApi = {
    FirstTouch: 'first_touch',
    LastTouch: 'last_touch',
    AllEvents: 'all_events',
    Step: 'step',
} as const

export type FunnelExclusionEventsNodeApiResponse = { [key: string]: unknown } | null

export interface FunnelExclusionEventsNodeApi {
    custom_name?: string | null
    /** The event or `null` for all events. */
    event?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: FunnelExclusionEventsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type FunnelExclusionActionsNodeApiResponse = { [key: string]: unknown } | null

export interface FunnelExclusionActionsNodeApi {
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'ActionsNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: FunnelExclusionActionsNodeApiResponse
    /** version of the node, used for schema migrations */
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
 */
export type FunnelsFilterApiResultCustomizations = { [key: string]: ResultCustomizationByValueApi } | null

export interface FunnelsFilterApi {
    binCount?: number | null
    breakdownAttributionType?: BreakdownAttributionTypeApi | null
    breakdownAttributionValue?: number | null
    /** Breakdown table sorting. Format: 'column_key' or '-column_key' (descending) */
    breakdownSorting?: string | null
    /** For data warehouse based funnel insights when the aggregation target can't be mapped to persons or groups. */
    customAggregationTarget?: boolean | null
    exclusions?: (FunnelExclusionEventsNodeApi | FunnelExclusionActionsNodeApi)[] | null
    funnelAggregateByHogQL?: string | null
    funnelFromStep?: number | null
    funnelOrderType?: StepOrderValueApi | null
    funnelStepReference?: FunnelStepReferenceApi | null
    /** To select the range of steps for trends & time to convert funnels, 0-indexed */
    funnelToStep?: number | null
    funnelVizType?: FunnelVizTypeApi | null
    funnelWindowInterval?: number | null
    funnelWindowIntervalUnit?: FunnelConversionWindowTimeUnitApi | null
    /** Goal Lines */
    goalLines?: GoalLineApi[] | null
    hiddenLegendBreakdowns?: string[] | null
    /** Trends only: hide periods whose conversion window has not fully elapsed yet, so the recent tail of the trend isn't dragged down by entrants who still have time to convert. */
    hideIncompleteConversionWindowPeriods?: boolean | null
    layout?: FunnelLayoutApi | null
    /** Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend. */
    legendPosition?: LegendPositionApi | null
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: FunnelsFilterApiResultCustomizations
    /** Whether to render annotations on the chart. Only applies to historical-trends funnels. */
    showAnnotations?: boolean | null
    /** Whether to show a legend describing the series. The legend only renders when the funnel has multiple series. Only applies to historical-trends funnels. */
    showLegend?: boolean | null
    /** Display linear regression trend lines on the chart (only for historical trends viz) */
    showTrendLines?: boolean | null
    showValuesOnSeries?: boolean | null
    useUdf?: boolean | null
}

export interface FunnelsQueryResponseApi {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Median total conversion time across all completers, computed breakdown-agnostically for the Steps viz header. */
    total_median_conversion_time?: number | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type FunnelsDataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export interface FunnelsDataWarehouseNodeApi {
    aggregation_target_field: string
    custom_name?: string | null
    dw_source_type?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'FunnelsDataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: FunnelsDataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface FunnelsQueryApi {
    /** Groups aggregation */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi | null
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    /** Properties specific to the funnels insight */
    funnelsFilter?: FunnelsFilterApi | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    kind?: 'FunnelsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Sampling rate */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (GroupNodeApi | EventsNodeApi | ActionsNodeApi | FunnelsDataWarehouseNodeApi)[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface RetentionValueApi {
    aggregation_value?: number | null
    count: number
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
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RetentionResultApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type AggregationPropertyTypeApi = (typeof AggregationPropertyTypeApi)[keyof typeof AggregationPropertyTypeApi]

export const AggregationPropertyTypeApi = {
    Event: 'event',
    Person: 'person',
    DataWarehouse: 'data_warehouse',
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
    /** Data warehouse field used as the actor identifier */
    aggregation_target_field?: string | null
    custom_name?: string | null
    id?: string | number | null
    kind?: RetentionEntityKindApi | null
    name?: string | null
    order?: number | null
    /** filters on the event */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Data warehouse table name */
    table_name?: string | null
    /** Data warehouse timestamp field */
    timestamp_field?: string | null
    type?: EntityTypeApi | null
    uuid?: string | null
}

export type TimeWindowModeApi = (typeof TimeWindowModeApi)[keyof typeof TimeWindowModeApi]

export const TimeWindowModeApi = {
    StrictCalendarDates: 'strict_calendar_dates',
    '24HourWindows': '24_hour_windows',
} as const

export interface RetentionFilterApi {
    /** The property to aggregate when aggregationType is sum or avg */
    aggregationProperty?: string | null
    /** The type of property to aggregate on (event, person or data_warehouse). Defaults to event. */
    aggregationPropertyType?: AggregationPropertyTypeApi | null
    /** The aggregation type to use for retention */
    aggregationType?: AggregationTypeApi | null
    /** Starting index used when labeling cohort columns (e.g. 0 for D0/D1/D2, 1 for D1/D2/D3). Display-only — does not affect retention calculations. */
    cohortLabelStartIndex?: number | null
    cumulative?: boolean | null
    /** For data warehouse based retention insights when the aggregation target can't be mapped to persons or groups. */
    customAggregationTarget?: boolean | null
    dashboardDisplay?: RetentionDashboardDisplayTypeApi | null
    /** controls the display of the retention graph */
    display?: ChartDisplayTypeApi | null
    goalLines?: GoalLineApi[] | null
    meanRetentionCalculation?: MeanRetentionCalculationApi | null
    minimumOccurrences?: number | null
    period?: RetentionPeriodApi | null
    /** Custom brackets for retention calculations */
    retentionCustomBrackets?: number[] | null
    /** Whether retention is with regard to initial cohort size, or that of the previous period. */
    retentionReference?: RetentionReferenceApi | null
    retentionType?: RetentionTypeApi | null
    returningEntity?: RetentionEntityApi | null
    /** The selected interval to display across all cohorts (null = show all intervals for each cohort) */
    selectedInterval?: number | null
    showTrendLines?: boolean | null
    targetEntity?: RetentionEntityApi | null
    /** The time window mode to use for retention calculations */
    timeWindowMode?: TimeWindowModeApi | null
    totalIntervals?: number | null
}

export interface RetentionQueryApi {
    /** Groups aggregation */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    kind?: 'RetentionQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Sampling rate */
    samplingFactor?: number | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
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
    funnelStep?: number | null
}

export type PathTypeApi = (typeof PathTypeApi)[keyof typeof PathTypeApi]

export const PathTypeApi = {
    Pageview: '$pageview',
    Screen: '$screen',
    CustomEvent: 'custom_event',
    Hogql: 'hogql',
} as const

export interface PathCleaningFilterApi {
    alias?: string | null
    order?: number | null
    regex?: string | null
}

export interface PathsFilterApi {
    edgeLimit?: number | null
    endPoint?: string | null
    excludeEvents?: string[] | null
    includeEventTypes?: PathTypeApi[] | null
    localPathCleaningFilters?: PathCleaningFilterApi[] | null
    maxEdgeWeight?: number | null
    minEdgeWeight?: number | null
    /** Relevant only within actors query */
    pathDropoffKey?: string | null
    /** Relevant only within actors query */
    pathEndKey?: string | null
    pathGroupings?: string[] | null
    pathReplacements?: boolean | null
    /** Relevant only within actors query */
    pathStartKey?: string | null
    pathsHogQLExpression?: string | null
    showFullUrls?: boolean | null
    startPoint?: string | null
    stepLimit?: number | null
}

export interface PathsLinkApi {
    average_conversion_time: number
    source: string
    target: string
    value: number
}

export interface PathsQueryResponseApi {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: PathsLinkApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface PathsQueryApi {
    /** Groups aggregation */
    aggregation_group_type_index?: number | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    /** Used for displaying paths in relation to funnel steps. */
    funnelPathsFilter?: FunnelPathsFilterApi | null
    kind?: 'PathsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Properties specific to the paths insight */
    pathsFilter: PathsFilterApi
    /** Property filters for all series */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Sampling rate */
    samplingFactor?: number | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type StickinessQueryResponseApiResultsItem = { [key: string]: unknown }

export interface StickinessQueryResponseApi {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: StickinessQueryResponseApiResultsItem[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
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
    hiddenLegendIndexes?: number[] | null
    /** Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend. */
    legendPosition?: LegendPositionApi | null
    /** Whether result datasets are associated by their values or by their order. */
    resultCustomizationBy?: ResultCustomizationByApi | null
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: StickinessFilterApiResultCustomizations
    showLegend?: boolean | null
    showMultipleYAxes?: boolean | null
    showValuesOnSeries?: boolean | null
    stickinessCriteria?: StickinessCriteriaApi | null
}

export interface StickinessQueryApi {
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    /** How many intervals comprise a period. Only used for cohorts, otherwise default 1. */
    intervalCount?: number | null
    kind?: 'StickinessQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Sampling rate */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: StickinessFilterApi | null
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type LifecycleToggleApi = (typeof LifecycleToggleApi)[keyof typeof LifecycleToggleApi]

export const LifecycleToggleApi = {
    New: 'new',
    Resurrecting: 'resurrecting',
    Returning: 'returning',
    Dormant: 'dormant',
} as const

export interface LifecycleFilterApi {
    /** Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend. */
    legendPosition?: LegendPositionApi | null
    showLegend?: boolean | null
    /** Append per-band percentage to each value label (e.g. `580 (42%)`). Requires `showValuesOnSeries` — on its own it has no visible effect. */
    showPercentagesOnSeries?: boolean | null
    showValuesOnSeries?: boolean | null
    stacked?: boolean | null
    toggledLifecycles?: LifecycleToggleApi[] | null
}

export type LifecycleQueryResponseApiResultsItem = { [key: string]: unknown }

export interface LifecycleQueryResponseApi {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: LifecycleQueryResponseApiResultsItem[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type LifecycleDataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export interface LifecycleDataWarehouseNodeApi {
    aggregation_target_field: string
    created_at_field: string
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'LifecycleDataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: LifecycleDataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface LifecycleQueryApi {
    /** Groups aggregation */
    aggregation_group_type_index?: number | null
    /** For data warehouse based lifecycle insights when the aggregation target can't be mapped to persons or groups. */
    customAggregationTarget?: boolean | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    kind?: 'LifecycleQuery'
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: LifecycleFilterApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Sampling rate */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (EventsNodeApi | ActionsNodeApi | LifecycleDataWarehouseNodeApi)[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
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

export type WebAnalyticsPreComputeStrategyApi =
    (typeof WebAnalyticsPreComputeStrategyApi)[keyof typeof WebAnalyticsPreComputeStrategyApi]

export const WebAnalyticsPreComputeStrategyApi = {
    PreAggregated: 'pre_aggregated',
    LazyPrecompute: 'lazy_precompute',
    Live: 'live',
} as const

export interface SamplingRateApi {
    denominator?: number | null
    numerator: number
}

export interface WebStatsTableQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface WebAnalyticsSamplingApi {
    enabled?: boolean | null
    forceSamplingRate?: SamplingRateApi | null
}

export interface WebStatsTableQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    breakdownBy: WebStatsBreakdownApi
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    filterTestAccounts?: boolean | null
    includeAvgTimeOnPage?: boolean | null
    includeBounceRate?: boolean | null
    includeHost?: boolean | null
    includeRevenue?: boolean | null
    includeScrollDepth?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'WebStatsTableQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    orderBy?: (WebAnalyticsOrderByFieldsApi | WebAnalyticsOrderByDirectionApi)[] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebStatsTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi | null
    useSessionsTable?: boolean | null
    /** Opt this specific query into the web stats table precompute path. Requires the `web-analytics-precompute-toggle` PostHog feature flag to be on for the team's organization for the gate to pass. * */
    useWebAnalyticsPrecompute?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type WebAnalyticsItemKindApi = (typeof WebAnalyticsItemKindApi)[keyof typeof WebAnalyticsItemKindApi]

export const WebAnalyticsItemKindApi = {
    Unit: 'unit',
    DurationS: 'duration_s',
    Percentage: 'percentage',
    Currency: 'currency',
} as const

export interface WebOverviewItemApi {
    changeFromPreviousPct?: number | null
    isIncreaseBad?: boolean | null
    key: string
    kind: WebAnalyticsItemKindApi
    previous?: number | null
    value?: number | null
}

export interface WebOverviewQueryResponseApi {
    dateFrom?: string | null
    dateTo?: string | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: WebOverviewItemApi[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface WebOverviewQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'WebOverviewQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    orderBy?: (WebAnalyticsOrderByFieldsApi | WebAnalyticsOrderByDirectionApi)[] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebOverviewQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi | null
    useSessionsTable?: boolean | null
    /** Opt this specific query into the web_overview_query precompute path. Requires the `web-analytics-precompute-toggle` PostHog feature flag to be on for the team's organization for the gate to pass. * */
    useWebAnalyticsPrecompute?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface ActionsPieApi {
    disableHoverOffset?: boolean | null
    hideAggregation?: boolean | null
}

export interface RetentionApi {
    hideLineGraph?: boolean | null
    hideSizeColumn?: boolean | null
    useSmallLayout?: boolean | null
}

export interface VizSpecificOptionsApi {
    ActionsPie?: ActionsPieApi | null
    RETENTION?: RetentionApi | null
}

export interface InsightVizNodeApi {
    /** Query is embedded inside another bordered component */
    embedded?: boolean | null
    /** Show with most visual options enabled. Used in insight scene. */
    full?: boolean | null
    hidePersonsModal?: boolean | null
    hideTooltipOnScroll?: boolean | null
    kind: InsightVizNodeApiKind
    showCorrelationTable?: boolean | null
    showFilters?: boolean | null
    showHeader?: boolean | null
    showLastComputation?: boolean | null
    showLastComputationRefresh?: boolean | null
    showResults?: boolean | null
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
    suppressSessionAnalysisWarning?: boolean | null
    /** version of the node, used for schema migrations */
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
    eventDefinitionId?: string | null
    type: DataTableNodeViewPropsContextTypeApi
}

export type DataTableNodeApiKind = (typeof DataTableNodeApiKind)[keyof typeof DataTableNodeApiKind]

export const DataTableNodeApiKind = {
    DataTableNode: 'DataTableNode',
} as const

export interface ResponseApi {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Cursor for fetching the next page of results */
    nextCursor?: string | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response1Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit: number
    missing_actors_count?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: string[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response2Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: 'GroupsQuery'
    limit: number
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface HogQLNoticeApi {
    end?: number | null
    fix?: string | null
    message: string
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
    ch_table_names?: string[] | null
    errors: HogQLNoticeApi[]
    isUsingIndices?: QueryIndexUsageApi | null
    isValid?: boolean | null
    notices: HogQLNoticeApi[]
    query?: string | null
    table_names?: string[] | null
    warnings: HogQLNoticeApi[]
}

export interface Response3Api {
    /** Executed ClickHouse query */
    clickhouse?: string | null
    /** Returned columns */
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Query explanation output */
    explain?: string[] | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Query metadata output */
    metadata?: HogQLMetadataResponseApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Input query string */
    query?: string | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Types of returned columns */
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response4Api {
    dateFrom?: string | null
    dateTo?: string | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: WebOverviewItemApi[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response5Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response6Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response7Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
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
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    /**
     * @minItems 1
     * @maxItems 1
     */
    results: WebVitalsPathBreakdownResultApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response9Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response10Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response11Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response12Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueAnalyticsMRRQueryResultItemApi {
    churn: unknown
    contraction: unknown
    expansion: unknown
    new: unknown
    total: unknown
}

export interface Response13Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RevenueAnalyticsMRRQueryResultItemApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
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
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RevenueAnalyticsOverviewItemApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response15Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response16Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface MarketingAnalyticsItemApi {
    changeFromPreviousPct?: number | null
    hasComparison?: boolean | null
    isIncreaseBad?: boolean | null
    key: string
    kind: WebAnalyticsItemKindApi
    previous?: number | string | null
    value?: number | string | null
}

export interface Response18Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type Response19ApiResults = { [key: string]: MarketingAnalyticsItemApi }

export interface Response19Api {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: Response19ApiResults
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response20Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface VolumeBucketApi {
    label: string
    value: number
}

export interface ErrorTrackingIssueAggregationsApi {
    occurrences: number
    sessions: number
    users: number
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
    Salesforce: 'salesforce',
    Hubspot: 'hubspot',
    GooglePubsub: 'google-pubsub',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
    GoogleCloudStorage: 'google-cloud-storage',
    GoogleAds: 'google-ads',
    GoogleAnalytics: 'google-analytics',
    GoogleSearchConsole: 'google-search-console',
    GoogleSheets: 'google-sheets',
    LinkedinAds: 'linkedin-ads',
    Snapchat: 'snapchat',
    Stripe: 'stripe',
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
    Postgresql: 'postgresql',
    AwsS3: 'aws-s3',
    S3Compatible: 's3-compatible',
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
    description?: string | null
    external_issues?: ErrorTrackingExternalReferenceApi[] | null
    first_event?: FirstEventApi | null
    first_seen: string
    function?: string | null
    id: string
    last_event?: LastEventApi | null
    last_seen: string
    library?: string | null
    name?: string | null
    source?: string | null
    status: ErrorTrackingIssueStatusApi
}

export interface Response21Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: ErrorTrackingIssueApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
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
    description?: string | null
    event: string
    external_issues?: ErrorTrackingExternalReferenceApi[] | null
    first_seen: string
    id: string
    last_seen: string
    library?: string | null
    name?: string | null
    odds_ratio: number
    population: PopulationApi
    status: ErrorTrackingIssueStatusApi
}

export interface Response22Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: ErrorTrackingCorrelatedIssueApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

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
    kind?: 'ExperimentFunnelsQuery'
    probability: Response23ApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    stats_version?: number | null
    variants: ExperimentVariantFunnelsBaseStatsApi[]
    /** Data warehouse sync warnings — see AnalyticsQueryResponseBase.warnings for semantics. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

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
    kind?: 'ExperimentTrendsQuery'
    p_value: number
    probability: Response24ApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    stats_version?: number | null
    variants: ExperimentVariantTrendsBaseStatsApi[]
    /** Data warehouse sync warnings — see AnalyticsQueryResponseBase.warnings for semantics. */
    warnings?: DataWarehouseSyncWarningApi[] | null
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
    AiTag: '$ai_tag',
    AiTraceSummary: '$ai_trace_summary',
    AiGenerationSummary: '$ai_generation_summary',
    AiTraceClusters: '$ai_trace_clusters',
    AiGenerationClusters: '$ai_generation_clusters',
} as const

export type LLMSentimentMessageApiScores = { [key: string]: number } | null

export interface LLMSentimentMessageApi {
    label: string
    score: number
    scores?: LLMSentimentMessageApiScores
}

export type LLMSentimentResultApiMessages = { [key: string]: LLMSentimentMessageApi } | null

export type LLMSentimentResultApiScores = { [key: string]: number } | null

export interface LLMSentimentResultApi {
    label: string
    message_count?: number | null
    messages?: LLMSentimentResultApiMessages
    score: number
    scores?: LLMSentimentResultApiScores
}

export type LLMTraceEventApiProperties = { [key: string]: unknown }

export interface LLMTraceEventApi {
    createdAt: string
    event: AIEventTypeApi | string
    id: string
    properties: LLMTraceEventApiProperties
    sentiment?: LLMSentimentResultApi | null
}

export type LLMTracePersonApiProperties = { [key: string]: unknown }

export interface LLMTracePersonApi {
    created_at: string
    distinct_id: string
    properties: LLMTracePersonApiProperties
    uuid: string
}

export interface LLMTraceApi {
    aiSessionId?: string | null
    createdAt: string
    distinctId: string
    errorCount?: number | null
    events: LLMTraceEventApi[]
    id: string
    inputCost?: number | null
    inputState?: unknown
    inputTokens?: number | null
    isSupportTrace?: boolean | null
    outputCost?: number | null
    outputState?: unknown
    outputTokens?: number | null
    person?: LLMTracePersonApi | null
    requestCost?: number | null
    sentiment?: LLMSentimentResultApi | null
    tools?: string[] | null
    totalCost?: number | null
    totalLatency?: number | null
    traceName?: string | null
    webSearchCost?: number | null
}

export interface Response25Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: LLMTraceApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response27Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response28Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: 'AccountsQuery'
    limit: number
    /** When `metrics` is set on the query, the aggregated values in the same order. */
    metricsResults?: (number | null)[] | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type TaxonomicFilterGroupTypeApi = (typeof TaxonomicFilterGroupTypeApi)[keyof typeof TaxonomicFilterGroupTypeApi]

export const TaxonomicFilterGroupTypeApi = {
    Metadata: 'metadata',
    Actions: 'actions',
    Cohorts: 'cohorts',
    CohortsWithAll: 'cohorts_with_all',
    DataWarehouse: 'data_warehouse',
    DataWarehouseSourceTables: 'data_warehouse_source_tables',
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
    PersonMetadata: 'person_metadata',
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
    event?: string | null
    href?: string | null
    href_matching?: HrefMatchingApi | null
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    selector?: string | null
    tag_name?: string | null
    text?: string | null
    text_matching?: TextMatchingApi | null
    url?: string | null
    url_matching?: UrlMatchingApi | null
}

export interface EventsQueryResponseApi {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Cursor for fetching the next page of results */
    nextCursor?: string | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type CompareApi = (typeof CompareApi)[keyof typeof CompareApi]

export const CompareApi = {
    Current: 'current',
    Previous: 'previous',
} as const

export interface ActorsQueryResponseApi {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit: number
    missing_actors_count?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: string[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface InsightActorsQueryApi {
    breakdown?: string | string[] | number | null
    compare?: CompareApi | null
    day?: string | number | null
    includeRecordings?: boolean | null
    /** An interval selected out of available intervals in source query. */
    interval?: number | null
    kind?: 'InsightActorsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ActorsQueryResponseApi | null
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
    status?: string | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface EventsQueryApi {
    /** Show events matching a given action */
    actionId?: number | null
    /** Show events matching action steps directly, used when no actionId is provided (e.g. previewing unsaved actions). Ignored if actionId is set. */
    actionSteps?: EventsQueryActionStepApi[] | null
    /** Only fetch events that happened after this timestamp */
    after?: string | null
    /** Only fetch events that happened before this timestamp */
    before?: string | null
    /** Limit to events matching this string */
    event?: string | null
    /** Filter to events matching any of these event names */
    events?: string[] | null
    /** Filter test accounts */
    filterTestAccounts?: boolean | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | PropertyGroupFilterApi
              | PropertyGroupFilterValueApi
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'EventsQuery'
    /** Number of rows to return */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Number of rows to skip before returning rows */
    offset?: number | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Show events for a given person */
    personId?: string | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** version of the node, used for schema migrations */
    version?: number | null
    /** HogQL filters to apply on returned data */
    where?: string[] | null
}

export type PersonsNodeApiResponse = { [key: string]: unknown } | null

export interface PersonsNodeApi {
    cohort?: number | null
    distinctId?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'PersonsNode'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: PersonsNodeApiResponse
    search?: string | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface FunnelsActorsQueryApi {
    /** When the source funnel has compare-to-previous enabled, scopes the actors to a single period. The runner resolves `'previous'` to the shifted date range; `'current'` (or unset) uses the source's own date range. */
    compare?: CompareApi | null
    /** Index of the step for which we want to get the timestamp for, per person. Positive for converted persons, negative for dropped of persons. */
    funnelStep?: number | null
    /** The breakdown value for which to get persons for. This is an array for person and event properties, a string for groups and an integer for cohorts. */
    funnelStepBreakdown?: number | string | (number | string)[] | null
    funnelTrendsDropOff?: boolean | null
    /** Used together with `funnelTrendsDropOff` for funnels time conversion date for the persons modal. */
    funnelTrendsEntrancePeriodStart?: string | null
    includeRecordings?: boolean | null
    kind?: 'FunnelsActorsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ActorsQueryResponseApi | null
    source: FunnelsQueryApi
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type FunnelCorrelationResultsTypeApi =
    (typeof FunnelCorrelationResultsTypeApi)[keyof typeof FunnelCorrelationResultsTypeApi]

export const FunnelCorrelationResultsTypeApi = {
    Events: 'events',
    Properties: 'properties',
    EventWithProperties: 'event_with_properties',
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
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: FunnelCorrelationResultApi
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface FunnelCorrelationQueryApi {
    funnelCorrelationEventExcludePropertyNames?: string[] | null
    funnelCorrelationEventNames?: string[] | null
    funnelCorrelationExcludeEventNames?: string[] | null
    funnelCorrelationExcludeNames?: string[] | null
    funnelCorrelationNames?: string[] | null
    funnelCorrelationType: FunnelCorrelationResultsTypeApi
    kind?: 'FunnelCorrelationQuery'
    response?: FunnelCorrelationResponseApi | null
    source: FunnelsActorsQueryApi
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface FunnelCorrelationActorsQueryApi {
    funnelCorrelationPersonConverted?: boolean | null
    funnelCorrelationPersonEntity?: EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi | null
    funnelCorrelationPropertyValues?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    includeRecordings?: boolean | null
    kind?: 'FunnelCorrelationActorsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ActorsQueryResponseApi | null
    source: FunnelCorrelationQueryApi
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ExperimentEventExposureConfigApiResponse = { [key: string]: unknown } | null

export interface ExperimentEventExposureConfigApi {
    event: string
    kind?: 'ExperimentEventExposureConfig'
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | PersonMetadataPropertyFilterApi
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
    response?: ExperimentEventExposureConfigApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type MultipleVariantHandlingApi = (typeof MultipleVariantHandlingApi)[keyof typeof MultipleVariantHandlingApi]

export const MultipleVariantHandlingApi = {
    Exclude: 'exclude',
    FirstSeen: 'first_seen',
} as const

export type ExperimentMetricGoalApi = (typeof ExperimentMetricGoalApi)[keyof typeof ExperimentMetricGoalApi]

export const ExperimentMetricGoalApi = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

export type ExperimentDataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export interface ExperimentDataWarehouseNodeApi {
    custom_name?: string | null
    data_warehouse_join_key: string
    events_join_key: string
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'ExperimentDataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: ExperimentDataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ExperimentMeanMetricApiResponse = { [key: string]: unknown } | null

export interface ExperimentMeanMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    fingerprint?: string | null
    goal?: ExperimentMetricGoalApi | null
    ignore_zeros?: boolean | null
    isSharedMetric?: boolean | null
    kind?: 'ExperimentMetric'
    /** Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). */
    lower_bound_percentile?: number | null
    metric_type?: 'mean'
    name?: string | null
    response?: ExperimentMeanMetricApiResponse
    sharedMetricId?: number | null
    source: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    /** When set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types. */
    threshold?: number | null
    /** Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). */
    upper_bound_percentile?: number | null
    uuid?: string | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ExperimentFunnelMetricApiResponse = { [key: string]: unknown } | null

export interface ExperimentFunnelMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    fingerprint?: string | null
    funnel_order_type?: StepOrderValueApi | null
    goal?: ExperimentMetricGoalApi | null
    isSharedMetric?: boolean | null
    kind?: 'ExperimentMetric'
    metric_type?: 'funnel'
    name?: string | null
    response?: ExperimentFunnelMetricApiResponse
    series: (EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi)[]
    sharedMetricId?: number | null
    uuid?: string | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface ExperimentMetricOutlierHandlingApi {
    ignore_zeros?: boolean | null
    /** Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). */
    lower_bound_percentile?: number | null
    /** Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). */
    upper_bound_percentile?: number | null
}

export type ExperimentRatioMetricApiResponse = { [key: string]: unknown } | null

export interface ExperimentRatioMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    denominator: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    denominator_outlier_handling?: ExperimentMetricOutlierHandlingApi | null
    fingerprint?: string | null
    goal?: ExperimentMetricGoalApi | null
    isSharedMetric?: boolean | null
    kind?: 'ExperimentMetric'
    metric_type?: 'ratio'
    name?: string | null
    numerator: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    numerator_outlier_handling?: ExperimentMetricOutlierHandlingApi | null
    response?: ExperimentRatioMetricApiResponse
    sharedMetricId?: number | null
    uuid?: string | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type StartHandlingApi = (typeof StartHandlingApi)[keyof typeof StartHandlingApi]

export const StartHandlingApi = {
    FirstSeen: 'first_seen',
    LastSeen: 'last_seen',
} as const

export type ExperimentRetentionMetricApiResponse = { [key: string]: unknown } | null

export interface ExperimentRetentionMetricApi {
    breakdownFilter?: BreakdownFilterApi | null
    completion_event: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    conversion_window?: number | null
    conversion_window_unit?: FunnelConversionWindowTimeUnitApi | null
    fingerprint?: string | null
    goal?: ExperimentMetricGoalApi | null
    isSharedMetric?: boolean | null
    kind?: 'ExperimentMetric'
    metric_type?: 'retention'
    name?: string | null
    response?: ExperimentRetentionMetricApiResponse
    retention_window_end: number
    retention_window_start: number
    retention_window_unit: FunnelConversionWindowTimeUnitApi
    sharedMetricId?: number | null
    start_event: EventsNodeApi | ActionsNodeApi | ExperimentDataWarehouseNodeApi
    start_handling: StartHandlingApi
    uuid?: string | null
    /** version of the node, used for schema migrations */
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
    covariate_sum?: number | null
    covariate_sum_product?: number | null
    covariate_sum_squares?: number | null
    denominator_sum?: number | null
    denominator_sum_squares?: number | null
    key: string
    number_of_samples: number
    numerator_denominator_sum_product?: number | null
    step_counts?: number[] | null
    step_sessions?: SessionDataApi[][] | null
    sum: number
    sum_squares: number
    validation_failures?: ExperimentStatsValidationFailureApi[] | null
}

export interface ExperimentVariantResultFrequentistApi {
    confidence_interval?: number[] | null
    covariate_sum?: number | null
    covariate_sum_product?: number | null
    covariate_sum_squares?: number | null
    denominator_sum?: number | null
    denominator_sum_squares?: number | null
    key: string
    method?: 'frequentist'
    number_of_samples: number
    numerator_denominator_sum_product?: number | null
    p_value?: number | null
    significant?: boolean | null
    step_counts?: number[] | null
    step_sessions?: SessionDataApi[][] | null
    sum: number
    sum_squares: number
    validation_failures?: ExperimentStatsValidationFailureApi[] | null
}

export interface ExperimentVariantResultBayesianApi {
    chance_to_win?: number | null
    covariate_sum?: number | null
    covariate_sum_product?: number | null
    covariate_sum_squares?: number | null
    credible_interval?: number[] | null
    denominator_sum?: number | null
    denominator_sum_squares?: number | null
    key: string
    method?: 'bayesian'
    number_of_samples: number
    numerator_denominator_sum_product?: number | null
    significant?: boolean | null
    step_counts?: number[] | null
    step_sessions?: SessionDataApi[][] | null
    sum: number
    sum_squares: number
    validation_failures?: ExperimentStatsValidationFailureApi[] | null
}

export interface ExperimentBreakdownResultApi {
    /** Control variant stats for this breakdown */
    baseline: ExperimentStatsBaseValidatedApi
    /** The breakdown values as an array (e.g., ["MacOS", "Chrome"] for multi-breakdown, ["Chrome"] for single) Although `BreakdownKeyType` could be an array, we only use the array form for the breakdown_value. The way `BreakdownKeyType` is defined is problematic. It should be treated as a primitive and allow for the types using it to define if it's and array or an optional value. */
    breakdown_value: (string | number)[]
    /** Test variant results with statistical comparisons for this breakdown */
    variants: ExperimentVariantResultFrequentistApi[] | ExperimentVariantResultBayesianApi[]
}

export type ExperimentQueryResponseApiCredibleIntervals = { [key: string]: number[] } | null

export type ExperimentQueryResponseApiInsight = { [key: string]: unknown }[] | null

export type ExperimentQueryResponseApiProbability = { [key: string]: number } | null

export interface ExperimentQueryResponseApi {
    baseline?: ExperimentStatsBaseValidatedApi | null
    /** Results grouped by breakdown value. When present, baseline and variant_results contain aggregated data. */
    breakdown_results?: ExperimentBreakdownResultApi[] | null
    clickhouse_sql?: string | null
    credible_intervals?: ExperimentQueryResponseApiCredibleIntervals
    hogql?: string | null
    insight?: ExperimentQueryResponseApiInsight
    /** Whether exposures were served from the precomputation system */
    is_precomputed?: boolean | null
    kind?: 'ExperimentQuery'
    metric?:
        | ExperimentMeanMetricApi
        | ExperimentFunnelMetricApi
        | ExperimentRatioMetricApi
        | ExperimentRetentionMetricApi
        | null
    p_value?: number | null
    probability?: ExperimentQueryResponseApiProbability
    significance_code?: ExperimentSignificanceCodeApi | null
    significant?: boolean | null
    stats_version?: number | null
    variant_results?: ExperimentVariantResultFrequentistApi[] | ExperimentVariantResultBayesianApi[] | null
    variants?: ExperimentVariantTrendsBaseStatsApi[] | ExperimentVariantFunnelsBaseStatsApi[] | null
    /** Data warehouse sync warnings — see AnalyticsQueryResponseBase.warnings for semantics. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface ExperimentQueryApi {
    experiment_id?: number | null
    kind?: 'ExperimentQuery'
    metric:
        | ExperimentMeanMetricApi
        | ExperimentFunnelMetricApi
        | ExperimentRatioMetricApi
        | ExperimentRetentionMetricApi
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    name?: string | null
    precomputation_mode?: PrecomputationModeApi | null
    response?: ExperimentQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface ExperimentActorsQueryApi {
    /** Exposure configuration for filtering events. Defines when users were first exposed to the experiment. */
    exposureConfig?: ExperimentEventExposureConfigApi | ActionsNodeApi | null
    /** Feature flag key for breakdown filtering. */
    featureFlagKey?: string | null
    /** Index of the step for which we want to get actors for, per experiment variant. Positive for converted persons, negative for dropped off persons. */
    funnelStep?: number | null
    /** The variant key for filtering actors. For experiments, this filters by feature flag variant (e.g., 'control', 'test'). */
    funnelStepBreakdown?: number | string | (number | string)[] | null
    includeRecordings?: boolean | null
    kind?: 'ExperimentActorsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** How to handle users with multiple variant exposures. */
    multipleVariantHandling?: MultipleVariantHandlingApi | null
    response?: ActorsQueryResponseApi | null
    source: ExperimentQueryApi
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface StickinessActorsQueryApi {
    compare?: CompareApi | null
    day?: string | number | null
    includeRecordings?: boolean | null
    kind?: 'StickinessActorsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    operator?: StickinessOperatorApi | null
    response?: ActorsQueryResponseApi | null
    series?: number | null
    source: StickinessQueryApi
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface HogQLFiltersApi {
    dateRange?: DateRangeApi | null
    filterTestAccounts?: boolean | null
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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

export interface HogQLQueryResponseApi {
    /** Executed ClickHouse query */
    clickhouse?: string | null
    /** Returned columns */
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Query explanation output */
    explain?: string[] | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Query metadata output */
    metadata?: HogQLMetadataResponseApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Input query string */
    query?: string | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Types of returned columns */
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface HogQLVariableApi {
    code_name: string
    isNull?: boolean | null
    value?: unknown
    variableId: string
}

/**
 * Constant values that can be referenced with the {placeholder} syntax in the query
 */
export type HogQLQueryApiValues = { [key: string]: unknown } | null

/**
 * Variables to be substituted into the query
 */
export type HogQLQueryApiVariables = { [key: string]: HogQLVariableApi } | null

export interface HogQLQueryApi {
    /** Optional id of a direct external data source (access_method='direct') to run against instead of ClickHouse. Warehouse import sources are not valid here. */
    connectionId?: string | null
    explain?: boolean | null
    filters?: HogQLFiltersApi | null
    kind?: 'HogQLQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Client provided name of the query */
    name?: string | null
    query: string
    response?: HogQLQueryResponseApi | null
    /** Run the selected connection query directly without translating it through HogQL first */
    sendRawQuery?: boolean | null
    tags?: QueryLogTagsApi | null
    /** Constant values that can be referenced with the {placeholder} syntax in the query */
    values?: HogQLQueryApiValues
    /** Variables to be substituted into the query */
    variables?: HogQLQueryApiVariables
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface ActorsQueryApi {
    /** Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in actor_strategies.py. */
    fixedProperties?:
        | (
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | CohortPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
          )[]
        | null
    kind?: 'ActorsQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    orderBy?: string[] | null
    /** Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in actor_strategies.py. */
    properties?:
        | (
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | CohortPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
          )[]
        | PropertyGroupFilterValueApi
        | null
    response?: ActorsQueryResponseApi | null
    search?: string | null
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
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface GroupsQueryResponseApi {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: 'GroupsQuery'
    limit: number
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface GroupsQueryApi {
    group_type_index: number
    kind?: 'GroupsQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    orderBy?: string[] | null
    properties?: (GroupPropertyFilterApi | HogQLPropertyFilterApi)[] | null
    response?: GroupsQueryResponseApi | null
    search?: string | null
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface WebExternalClicksTableQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface WebExternalClicksTableQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'WebExternalClicksTableQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    orderBy?: (WebAnalyticsOrderByFieldsApi | WebAnalyticsOrderByDirectionApi)[] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebExternalClicksTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    stripQueryParams?: boolean | null
    tags?: QueryLogTagsApi | null
    useSessionsTable?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface WebGoalsQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface WebGoalsQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'WebGoalsQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    orderBy?: (WebAnalyticsOrderByFieldsApi | WebAnalyticsOrderByDirectionApi)[] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebGoalsQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi | null
    useSessionsTable?: boolean | null
    /** Opt this specific query into the web_goals_query precompute path. Requires the `web-analytics-precompute-toggle` PostHog feature flag to be on for the team's organization for the gate to pass. * */
    useWebAnalyticsPrecompute?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface WebVitalsQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'WebVitalsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    orderBy?: (WebAnalyticsOrderByFieldsApi | WebAnalyticsOrderByDirectionApi)[] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebGoalsQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
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
    useSessionsTable?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

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
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    /**
     * @minItems 1
     * @maxItems 1
     */
    results: WebVitalsPathBreakdownResultApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface WebVitalsPathBreakdownQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'WebVitalsPathBreakdownQuery'
    metric: WebVitalsMetricApi
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    orderBy?: (WebAnalyticsOrderByFieldsApi | WebAnalyticsOrderByDirectionApi)[] | null
    percentile: WebVitalsPercentileApi
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: WebVitalsPathBreakdownQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    tags?: QueryLogTagsApi | null
    /**
     * @minItems 2
     * @maxItems 2
     */
    thresholds: number[]
    useSessionsTable?: boolean | null
    /** Opt this specific query into the web vitals path breakdown precompute path. Requires the `web-analytics-precompute-toggle` PostHog feature flag to be on for the team's organization for the gate to pass. * */
    useWebAnalyticsPrecompute?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface FiltersApi {
    dateRange?: DateRangeApi | null
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

export interface SessionAttributionExplorerQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface SessionAttributionExplorerQueryApi {
    filters?: FiltersApi | null
    groupBy: SessionAttributionGroupByApi[]
    kind?: 'SessionAttributionExplorerQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    response?: SessionAttributionExplorerQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface SessionsQueryResponseApi {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface SessionsQueryApi {
    /** Filter sessions by action - sessions that contain events matching this action */
    actionId?: number | null
    /** Only fetch sessions that started after this timestamp */
    after?: string | null
    /** Only fetch sessions that started before this timestamp */
    before?: string | null
    /** Filter sessions by event name - sessions that contain this event */
    event?: string | null
    /** Event property filters - filters sessions that contain events matching these properties */
    eventProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Filter test accounts */
    filterTestAccounts?: boolean | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | PropertyGroupFilterApi
              | PropertyGroupFilterValueApi
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'SessionsQuery'
    /** Number of rows to return */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Number of rows to skip before returning rows */
    offset?: number | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Show sessions for a given person */
    personId?: string | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** version of the node, used for schema migrations */
    version?: number | null
    /** HogQL filters to apply on returned data */
    where?: string[] | null
}

export interface RevenueAnalyticsBreakdownApi {
    property: string
    type?: 'revenue_analytics'
}

export type SimpleIntervalTypeApi = (typeof SimpleIntervalTypeApi)[keyof typeof SimpleIntervalTypeApi]

export const SimpleIntervalTypeApi = {
    Day: 'day',
    Month: 'month',
} as const

export interface RevenueAnalyticsGrossRevenueQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueAnalyticsGrossRevenueQueryApi {
    breakdown: RevenueAnalyticsBreakdownApi[]
    dateRange?: DateRangeApi | null
    interval: SimpleIntervalTypeApi
    kind?: 'RevenueAnalyticsGrossRevenueQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsGrossRevenueQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface RevenueAnalyticsMetricsQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueAnalyticsMetricsQueryApi {
    breakdown: RevenueAnalyticsBreakdownApi[]
    dateRange?: DateRangeApi | null
    interval: SimpleIntervalTypeApi
    kind?: 'RevenueAnalyticsMetricsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsMetricsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface RevenueAnalyticsMRRQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RevenueAnalyticsMRRQueryResultItemApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueAnalyticsMRRQueryApi {
    breakdown: RevenueAnalyticsBreakdownApi[]
    dateRange?: DateRangeApi | null
    interval: SimpleIntervalTypeApi
    kind?: 'RevenueAnalyticsMRRQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsMRRQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface RevenueAnalyticsOverviewQueryResponseApi {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RevenueAnalyticsOverviewItemApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueAnalyticsOverviewQueryApi {
    dateRange?: DateRangeApi | null
    kind?: 'RevenueAnalyticsOverviewQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsOverviewQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type RevenueAnalyticsTopCustomersGroupByApi =
    (typeof RevenueAnalyticsTopCustomersGroupByApi)[keyof typeof RevenueAnalyticsTopCustomersGroupByApi]

export const RevenueAnalyticsTopCustomersGroupByApi = {
    Month: 'month',
    All: 'all',
} as const

export interface RevenueAnalyticsTopCustomersQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueAnalyticsTopCustomersQueryApi {
    dateRange?: DateRangeApi | null
    groupBy: RevenueAnalyticsTopCustomersGroupByApi
    kind?: 'RevenueAnalyticsTopCustomersQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    properties: RevenueAnalyticsPropertyFilterApi[]
    response?: RevenueAnalyticsTopCustomersQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface RevenueExampleEventsQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueExampleEventsQueryApi {
    kind?: 'RevenueExampleEventsQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    response?: RevenueExampleEventsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface RevenueExampleDataWarehouseTablesQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface RevenueExampleDataWarehouseTablesQueryApi {
    kind?: 'RevenueExampleDataWarehouseTablesQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    response?: RevenueExampleDataWarehouseTablesQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ConversionGoalFilter1ApiResponse = { [key: string]: unknown } | null

export type ConversionGoalFilter1ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter1Api {
    conversion_goal_id: string
    conversion_goal_name: string
    custom_name?: string | null
    /** The event or `null` for all events. */
    event?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: ConversionGoalFilter1ApiResponse
    schema_map: ConversionGoalFilter1ApiSchemaMap
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ConversionGoalFilter2ApiResponse = { [key: string]: unknown } | null

export type ConversionGoalFilter2ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter2Api {
    conversion_goal_id: string
    conversion_goal_name: string
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'ActionsNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: ConversionGoalFilter2ApiResponse
    schema_map: ConversionGoalFilter2ApiSchemaMap
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ConversionGoalFilter3ApiResponse = { [key: string]: unknown } | null

export type ConversionGoalFilter3ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter3Api {
    conversion_goal_id: string
    conversion_goal_name: string
    custom_name?: string | null
    distinct_id_field: string
    dw_source_type?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    kind?: 'DataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    response?: ConversionGoalFilter3ApiResponse
    schema_map: ConversionGoalFilter3ApiSchemaMap
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type MarketingAnalyticsDrillDownLevelApi =
    (typeof MarketingAnalyticsDrillDownLevelApi)[keyof typeof MarketingAnalyticsDrillDownLevelApi]

export const MarketingAnalyticsDrillDownLevelApi = {
    Channel: 'channel',
    Source: 'source',
    Campaign: 'campaign',
    AdGroup: 'ad_group',
    Ad: 'ad',
    Medium: 'medium',
    Content: 'content',
    Term: 'term',
} as const

export interface IntegrationFilterApi {
    /** Selected integration source IDs to filter by (e.g., table IDs or source map IDs) */
    integrationSourceIds?: string[] | null
}

export type MarketingAnalyticsOrderByEnumApi =
    (typeof MarketingAnalyticsOrderByEnumApi)[keyof typeof MarketingAnalyticsOrderByEnumApi]

export const MarketingAnalyticsOrderByEnumApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export interface MarketingAnalyticsTableQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface MarketingAnalyticsTableQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    /** Draft conversion goal that can be set in the UI without saving */
    draftConversionGoal?: ConversionGoalFilter1Api | ConversionGoalFilter2Api | ConversionGoalFilter3Api | null
    /** Drill-down hierarchy level: channel, source, or campaign (default) */
    drillDownLevel?: MarketingAnalyticsDrillDownLevelApi | null
    /** Filter test accounts */
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Filter by integration type */
    integrationFilter?: IntegrationFilterApi | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'MarketingAnalyticsTableQuery'
    /** Number of rows to return */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Number of rows to skip before returning rows */
    offset?: number | null
    /** Columns to order by - similar to EventsQuery format */
    orderBy?: (string | MarketingAnalyticsOrderByEnumApi)[][] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: MarketingAnalyticsTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    /** Return a limited set of data. Will use default columns if empty. */
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    useSessionsTable?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type MarketingAnalyticsAggregatedQueryResponseApiResults = { [key: string]: MarketingAnalyticsItemApi }

export interface MarketingAnalyticsAggregatedQueryResponseApi {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: MarketingAnalyticsAggregatedQueryResponseApiResults
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface MarketingAnalyticsAggregatedQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    /** Draft conversion goal that can be set in the UI without saving */
    draftConversionGoal?: ConversionGoalFilter1Api | ConversionGoalFilter2Api | ConversionGoalFilter3Api | null
    /** Drill-down hierarchy level: channel, source, or campaign (default) */
    drillDownLevel?: MarketingAnalyticsDrillDownLevelApi | null
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Filter by integration IDs */
    integrationFilter?: IntegrationFilterApi | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'MarketingAnalyticsAggregatedQuery'
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
    /** Sampling rate */
    samplingFactor?: number | null
    /** Return a limited set of data. Will use default columns if empty. */
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    useSessionsTable?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface NonIntegratedConversionsTableQueryResponseApi {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface NonIntegratedConversionsTableQueryApi {
    /** Groups aggregation - not used in Web Analytics but required for type compatibility */
    aggregation_group_type_index?: number | null
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    conversionGoal?: ActionConversionGoalApi | CustomEventConversionGoalApi | null
    /** Colors used in the insight's visualization - not used in Web Analytics but required for type compatibility */
    dataColorTheme?: number | null
    dateRange?: DateRangeApi | null
    doPathCleaning?: boolean | null
    /** Draft conversion goal that can be set in the UI without saving */
    draftConversionGoal?: ConversionGoalFilter1Api | ConversionGoalFilter2Api | ConversionGoalFilter3Api | null
    /** Filter test accounts */
    filterTestAccounts?: boolean | null
    includeRevenue?: boolean | null
    /** Interval for date range calculation (affects date_to rounding for hour vs day ranges) */
    interval?: IntervalTypeApi | null
    kind?: 'NonIntegratedConversionsTableQuery'
    /** Number of rows to return */
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Number of rows to skip before returning rows */
    offset?: number | null
    /** Columns to order by */
    orderBy?: (string | MarketingAnalyticsOrderByEnumApi)[][] | null
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
    )[]
    response?: NonIntegratedConversionsTableQueryResponseApi | null
    sampling?: WebAnalyticsSamplingApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    /** Return a limited set of data. Will use default columns if empty. */
    select?: string[] | null
    tags?: QueryLogTagsApi | null
    useSessionsTable?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

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

export interface ErrorTrackingPendingFingerprintIssueStateUpdateApi {
    assigned_role_id?: string | null
    assigned_user_id?: number | null
    fingerprint: string
    /** ISO 8601 datetime string. */
    first_seen: string
    is_deleted: number
    issue_description?: string | null
    issue_id: string
    issue_name?: string | null
    issue_status: string
    /** Client-stamped monotonic version (`Date.now()` ms at mutation success). */
    version: number
}

export interface ErrorTrackingQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: ErrorTrackingIssueApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface ErrorTrackingQueryApi {
    assignee?: ErrorTrackingIssueAssigneeApi | null
    /** Date range to filter results. */
    dateRange: DateRangeApi
    filterGroup?: PropertyGroupFilterApi | null
    /** Whether to filter out test accounts. */
    filterTestAccounts?: boolean | null
    groupKey?: string | null
    groupTypeIndex?: number | null
    /** Filter to a specific error tracking issue by ID. */
    issueId?: string | null
    kind?: 'ErrorTrackingQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Field to sort results by. */
    orderBy: ErrorTrackingOrderByApi
    /** Sort direction. */
    orderDirection?: OrderDirection2Api | null
    /** Pending fingerprint issue state updates UNIONed into the fingerprint issue state subquery. The backend caps the list at 50 entries; extras are dropped silently. */
    pendingFingerprintIssueStateUpdates?: ErrorTrackingPendingFingerprintIssueStateUpdateApi[] | null
    personId?: string | null
    response?: ErrorTrackingQueryResponseApi | null
    /** Free-text search across exception type, message, and stack frames. */
    searchQuery?: string | null
    /** Filter by issue status. */
    status?: ErrorTrackingIssueStatusApi | string | null
    tags?: QueryLogTagsApi | null
    useQueryV2?: boolean | null
    useQueryV3?: boolean | null
    /** version of the node, used for schema migrations */
    version?: number | null
    volumeResolution: number
    withAggregations?: boolean | null
    withFirstEvent?: boolean | null
    withLastEvent?: boolean | null
}

export interface ErrorTrackingIssueCorrelationQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: ErrorTrackingCorrelatedIssueApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface ErrorTrackingIssueCorrelationQueryApi {
    events: string[]
    kind?: 'ErrorTrackingIssueCorrelationQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: ErrorTrackingIssueCorrelationQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ExperimentFunnelsQueryResponseApiCredibleIntervals = { [key: string]: number[] }

export type ExperimentFunnelsQueryResponseApiInsightItemItem = { [key: string]: unknown }

export type ExperimentFunnelsQueryResponseApiProbability = { [key: string]: number }

export interface ExperimentFunnelsQueryResponseApi {
    credible_intervals: ExperimentFunnelsQueryResponseApiCredibleIntervals
    expected_loss: number
    funnels_query?: FunnelsQueryApi | null
    insight: ExperimentFunnelsQueryResponseApiInsightItemItem[][]
    kind?: 'ExperimentFunnelsQuery'
    probability: ExperimentFunnelsQueryResponseApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    stats_version?: number | null
    variants: ExperimentVariantFunnelsBaseStatsApi[]
    /** Data warehouse sync warnings — see AnalyticsQueryResponseBase.warnings for semantics. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface ExperimentFunnelsQueryApi {
    experiment_id?: number | null
    fingerprint?: string | null
    funnels_query: FunnelsQueryApi
    kind?: 'ExperimentFunnelsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    name?: string | null
    response?: ExperimentFunnelsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    uuid?: string | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ExperimentTrendsQueryResponseApiCredibleIntervals = { [key: string]: number[] }

export type ExperimentTrendsQueryResponseApiInsightItem = { [key: string]: unknown }

export type ExperimentTrendsQueryResponseApiProbability = { [key: string]: number }

export interface ExperimentTrendsQueryResponseApi {
    count_query?: TrendsQueryApi | null
    credible_intervals: ExperimentTrendsQueryResponseApiCredibleIntervals
    exposure_query?: TrendsQueryApi | null
    insight: ExperimentTrendsQueryResponseApiInsightItem[]
    kind?: 'ExperimentTrendsQuery'
    p_value: number
    probability: ExperimentTrendsQueryResponseApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    stats_version?: number | null
    variants: ExperimentVariantTrendsBaseStatsApi[]
    /** Data warehouse sync warnings — see AnalyticsQueryResponseBase.warnings for semantics. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface ExperimentTrendsQueryApi {
    count_query: TrendsQueryApi
    experiment_id?: number | null
    exposure_query?: TrendsQueryApi | null
    fingerprint?: string | null
    kind?: 'ExperimentTrendsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    name?: string | null
    response?: ExperimentTrendsQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    uuid?: string | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface TracesQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: LLMTraceApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface TracesQueryApi {
    dateRange?: DateRangeApi | null
    filterSupportTraces?: boolean | null
    filterTestAccounts?: boolean | null
    groupKey?: string | null
    groupTypeIndex?: number | null
    /** Include stored sentiment evaluation results for returned traces and direct generation events. */
    includeSentiment?: boolean | null
    kind?: 'TracesQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Person who performed the event */
    personId?: string | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** Use random ordering instead of timestamp DESC. Useful for representative sampling to avoid recency bias. */
    randomOrder?: boolean | null
    response?: TracesQueryResponseApi | null
    showColumnConfigurator?: boolean | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface TraceQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: LLMTraceApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface TraceQueryApi {
    dateRange?: DateRangeApi | null
    /** Include stored sentiment evaluation results for the trace and its generations. */
    includeSentiment?: boolean | null
    kind?: 'TraceQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
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
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface SessionQueryResponseApi {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: LLMTraceApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface SessionQueryApi {
    dateRange?: DateRangeApi | null
    /** Include stored sentiment evaluation results for returned traces and generation events. */
    includeSentiment?: boolean | null
    kind?: 'SessionQuery'
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    response?: SessionQueryResponseApi | null
    sessionId: string
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type EndpointsUsageBreakdownApi = (typeof EndpointsUsageBreakdownApi)[keyof typeof EndpointsUsageBreakdownApi]

export const EndpointsUsageBreakdownApi = {
    Endpoint: 'Endpoint',
    MaterializationType: 'MaterializationType',
    ApiKey: 'ApiKey',
    Status: 'Status',
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
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface EndpointsUsageTableQueryApi {
    breakdownBy: EndpointsUsageBreakdownApi
    dateRange?: DateRangeApi | null
    /** Filter to specific endpoints by name */
    endpointNames?: string[] | null
    kind?: 'EndpointsUsageTableQuery'
    limit?: number | null
    /** Filter by materialization type */
    materializationType?: MaterializationTypeApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    orderBy?: (EndpointsUsageOrderByFieldApi | EndpointsUsageOrderByDirectionApi)[] | null
    response?: EndpointsUsageTableQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface AccountsQueryResponseApi {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: 'AccountsQuery'
    limit: number
    /** When `metrics` is set on the query, the aggregated values in the same order. */
    metricsResults?: (number | null)[] | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface AccountsQueryApi {
    /** Match accounts with no active relationship of any definition. */
    allRolesUnassigned?: boolean | null
    /** Match accounts where any of these user ids actively holds any relationship (CSM, Account executive, or a custom definition). Drives the "My accounts" shortcut (the current user's id) and the shareable "Assigned to" filter — the ids are explicit so a shared URL resolves identically for every viewer. */
    assignedToUserIds?: number[] | null
    /** Optional HogQL boolean expression AND-ed into the WHERE clause. Used by the overview tile click-to-filter affordance. */
    filterExpression?: string | null
    kind?: 'AccountsQuery'
    limit?: number | null
    /** Aggregation expressions evaluated against the filtered account set; one value per metric is returned in `metricsResults`. When `metrics` is set without a `select`, the runner skips the regular row fetch and returns only the aggregated values. */
    metrics?: string[] | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    orderBy?: string[] | null
    response?: AccountsQueryResponseApi | null
    search?: string | null
    select?: string[] | null
    tagNames?: string[] | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
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
    | Response7Api
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
    | Response27Api
    | Response28Api
    | null

export interface DataTableNodeApi {
    /** Can the user click on column headers to sort the table? (default: true) */
    allowSorting?: boolean | null
    /** Columns shown in the table, unless the `source` provides them. */
    columns?: string[] | null
    /** Context for the table, used by components like ColumnConfigurator */
    context?: DataTableNodeViewPropsContextApi | null
    /** Context key for universal column configuration (e.g., "survey:123") */
    contextKey?: string | null
    /** Default columns to use when resetting column configuration */
    defaultColumns?: string[] | null
    /** Uses the embedded version of LemonTable */
    embedded?: boolean | null
    /** Can expand row to show raw event data (default: true) */
    expandable?: boolean | null
    /** Show with most visual options enabled. Used in scenes. */
    full?: boolean | null
    /** Columns that aren't shown in the table, even if in columns or returned data */
    hiddenColumns?: string[] | null
    kind: DataTableNodeApiKind
    /** Columns that are sticky when scrolling horizontally */
    pinnedColumns?: string[] | null
    /** Link properties via the URL (default: false) */
    propertiesViaUrl?: boolean | null
    response?: DataTableNodeApiResponse
    /** Render date-time columns (timestamp, created_at, last_seen, last_seen_at, session_start, session_end) as absolute date+time instead of relative ("X ago"). The toggle is exposed in the column header menu only on EventsQuery / ActorsQuery sources. */
    showAbsoluteTime?: boolean | null
    /** Show the kebab menu at the end of the row */
    showActions?: boolean | null
    /** Show a button to configure the table's columns if possible */
    showColumnConfigurator?: boolean | null
    /** Show count of total and filtered results */
    showCount?: boolean | null
    /** Show date range selector */
    showDateRange?: boolean | null
    /** Show the time it takes to run a query */
    showElapsedTime?: boolean | null
    /** Include an event filter above the table (EventsNode only) */
    showEventFilter?: boolean | null
    /** Include an events filter above the table to filter by multiple events (EventsQuery only) */
    showEventsFilter?: boolean | null
    /** Show the export button */
    showExport?: boolean | null
    /** Include a HogQL query editor above HogQL tables */
    showHogQLEditor?: boolean | null
    /** Show a button to open the current query as a new insight. (default: true) */
    showOpenEditorButton?: boolean | null
    /** Show a button to configure and persist the table's default columns if possible */
    showPersistentColumnConfigurator?: boolean | null
    /** Include a property filter above the table */
    showPropertyFilter?: boolean | TaxonomicFilterGroupTypeApi[] | null
    /** Show a recording column for events with session recordings */
    showRecordingColumn?: boolean | null
    /** Show a reload button */
    showReload?: boolean | null
    /** Show a results table */
    showResultsTable?: boolean | null
    /** Show saved filters feature for this table (requires uniqueKey) */
    showSavedFilters?: boolean | null
    /** Shows a list of saved queries */
    showSavedQueries?: boolean | null
    /** Include a free text search field (PersonsNode only) */
    showSearch?: boolean | null
    /** Show actors query options and back to source */
    showSourceQueryOptions?: boolean | null
    /** Show table views feature for this table (requires uniqueKey) */
    showTableViews?: boolean | null
    /** Show filter to exclude test accounts */
    showTestAccountFilters?: boolean | null
    /** Show a detailed query timing breakdown */
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
        | SessionQueryApi
        | EndpointsUsageTableQueryApi
        | AccountsQueryApi
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
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
    gradient?: HeatmapGradientStopApi[] | null
    gradientPreset?: string | null
    gradientScaleMode?: GradientScaleModeApi | null
    nullLabel?: string | null
    nullValue?: string | null
    sortColumn?: string | null
    sortOrder?: HeatmapSortOrderApi | null
    valueColumn?: string | null
    xAxisColumn?: string | null
    xAxisLabel?: string | null
    yAxisColumn?: string | null
    yAxisLabel?: string | null
}

export type ScaleApi = (typeof ScaleApi)[keyof typeof ScaleApi]

export const ScaleApi = {
    Linear: 'linear',
    Logarithmic: 'logarithmic',
} as const

export interface YAxisSettingsApi {
    label?: string | null
    scale?: ScaleApi | null
    showGridLines?: boolean | null
    showTicks?: boolean | null
    /** Whether the Y axis should start at zero */
    startAtZero?: boolean | null
}

export type SliceContentApi = (typeof SliceContentApi)[keyof typeof SliceContentApi]

export const SliceContentApi = {
    Labels: 'labels',
    Values: 'values',
    None: 'none',
} as const

export type ValueDisplayApi = (typeof ValueDisplayApi)[keyof typeof ValueDisplayApi]

export const ValueDisplayApi = {
    Absolute: 'absolute',
    Percentage: 'percentage',
} as const

export interface PieChartSettingsApi {
    /** Whether to show the aggregation total below the chart. Defaults to on. */
    showTotal?: boolean | null
    /** What to render on each slice. Defaults to labels. */
    sliceContent?: SliceContentApi | null
    /** Whether slice values show as absolute amounts or shares of the total. Only applies when `sliceContent` is `values`. */
    valueDisplay?: ValueDisplayApi | null
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
    color?: string | null
    displayType?: DisplayTypeApi | null
    label?: string | null
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
    decimalPlaces?: number | null
    prefix?: string | null
    style?: StyleApi | null
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

/**
 * Per-breakdown-value color customizations. Keyed by the raw breakdown column value.
 */
export type ChartSettingsApiResultCustomizations = { [key: string]: ResultCustomizationByValueApi } | null

export interface ChartSettingsApi {
    goalLines?: GoalLineApi[] | null
    heatmap?: HeatmapSettingsApi | null
    leftYAxisSettings?: YAxisSettingsApi | null
    pie?: PieChartSettingsApi | null
    /** Per-breakdown-value color customizations. Keyed by the raw breakdown column value. */
    resultCustomizations?: ChartSettingsApiResultCustomizations
    rightYAxisSettings?: YAxisSettingsApi | null
    seriesBreakdownColumn?: string | null
    showLegend?: boolean | null
    showNullsAsZero?: boolean | null
    showPieTotal?: boolean | null
    showTotalRow?: boolean | null
    showValuesOnSeries?: boolean | null
    showXAxisBorder?: boolean | null
    showXAxisTicks?: boolean | null
    showYAxisBorder?: boolean | null
    /** Whether we fill the bars to 100% in stacked mode */
    stackBars100?: boolean | null
    xAxis?: ChartAxisApi | null
    xAxisLabel?: string | null
    yAxis?: ChartAxisApi[] | null
    /** Deprecated: use `[left|right]YAxisSettings`. Whether the Y axis should start at zero */
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
    columns?: ChartAxisApi[] | null
    conditionalFormatting?: ConditionalFormattingRuleApi[] | null
    pinnedColumns?: string[] | null
    transpose?: boolean | null
}

export interface DataVisualizationNodeApi {
    chartSettings?: ChartSettingsApi | null
    display?: ChartDisplayTypeApi | null
    kind: DataVisualizationNodeApiKind
    source: HogQLQueryApi
    tableSettings?: TableSettingsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type HogQueryApiKind = (typeof HogQueryApiKind)[keyof typeof HogQueryApiKind]

export const HogQueryApiKind = {
    HogQuery: 'HogQuery',
} as const

export interface HogQueryResponseApi {
    bytecode?: unknown[] | null
    coloredBytecode?: unknown[] | null
    results: unknown
    stdout?: string | null
}

export interface HogQueryApi {
    code?: string | null
    kind: HogQueryApiKind
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    response?: HogQueryResponseApi | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

/**
 * The query definition for this insight. The `kind` field determines the query type:
 * - `InsightVizNode` — product analytics (trends, funnels, retention, paths, stickiness, lifecycle)
 * - `DataVisualizationNode` — SQL insights using HogQL
 * - `DataTableNode` — raw data tables
 * - `HogQuery` — Hog language queries
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

export type EffectivePrivilegeLevelEnumApi =
    (typeof EffectivePrivilegeLevelEnumApi)[keyof typeof EffectivePrivilegeLevelEnumApi]

export const EffectivePrivilegeLevelEnumApi = {
    Number21: 21,
    Number37: 37,
} as const

export type SearchMatchTypeEnumApi = (typeof SearchMatchTypeEnumApi)[keyof typeof SearchMatchTypeEnumApi]

export const SearchMatchTypeEnumApi = {
    Exact: 'exact',
    Similar: 'similar',
} as const

/**
 * @nullable
 */
export type InsightApiResolvedDateRange = {
    readonly date_from?: string
    readonly date_to?: string
} | null

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
     *         DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.
     *         A dashboard ID for each of the dashboards that this insight is displayed on.
     *          */
    dashboards?: number[]
    /**
     *     A dashboard tile ID and dashboard_id for each of the dashboards that this insight is displayed on.
     *      */
    readonly dashboard_tiles: readonly DashboardTileBasicApi[]
    /**
     *
     *     The datetime this insight's results were generated.
     *     If added to one or more dashboards the insight can be refreshed separately on each.
     *     Returns the appropriate last_refresh datetime for the context the insight is viewed in
     *     (see from_dashboard query parameter).
     *
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
     *     The earliest possible datetime at which we'll allow the cached results for this insight to be refreshed
     *     by querying the database.
     *
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
    readonly effective_restriction_level: EffectivePrivilegeLevelEnumApi
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
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
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
} | null

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
     *         DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.
     *         A dashboard ID for each of the dashboards that this insight is displayed on.
     *          */
    dashboards?: number[]
    /**
     *     A dashboard tile ID and dashboard_id for each of the dashboards that this insight is displayed on.
     *      */
    readonly dashboard_tiles?: readonly DashboardTileBasicApi[]
    /**
     *
     *     The datetime this insight's results were generated.
     *     If added to one or more dashboards the insight can be refreshed separately on each.
     *     Returns the appropriate last_refresh datetime for the context the insight is viewed in
     *     (see from_dashboard query parameter).
     *
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
     *     The earliest possible datetime at which we'll allow the cached results for this insight to be refreshed
     *     by querying the database.
     *
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
    readonly effective_restriction_level?: EffectivePrivilegeLevelEnumApi
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
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type?: SearchMatchTypeEnumApi | null
}

export interface ChangeApi {
    readonly type: string
    readonly action: string
    readonly field: string
    readonly before: unknown
    readonly after: unknown
}

export interface MergeApi {
    readonly type: string
    readonly source: unknown
    readonly target: unknown
}

export interface TriggerApi {
    readonly job_type: string
    readonly job_id: string
    readonly payload: unknown
}

export interface DetailApi {
    readonly id: string
    changes?: ChangeApi[]
    merge?: MergeApi
    trigger?: TriggerApi
    readonly name: string
    readonly short_id: string
    readonly type: string
}

/**
 * @nullable
 */
export type ActivityLogEntryApiUser = { [key: string]: unknown } | null

export interface ActivityLogEntryApi {
    readonly id: string
    /** @nullable */
    readonly user: ActivityLogEntryApiUser
    readonly activity: string
    readonly scope: string
    readonly item_id: string
    detail?: DetailApi
    readonly created_at: string
}

/**
 * Response shape for paginated activity log endpoints.
 */
export interface ActivityLogPaginatedResponseApi {
    results: ActivityLogEntryApi[]
    /** @nullable */
    next: string | null
    /** @nullable */
    previous: string | null
    total_count: number
}

export interface InsightBulkDeleteRequestApi {
    /**
     * Insight IDs to soft-delete (or restore). At most 1000 ids per request. Soft-deleted insights can be brought back via the bulk_restore endpoint.
     * @maxItems 1000
     * @items.minimum 1
     */
    ids: number[]
}

export interface InsightBulkOperationResultApi {
    /** ID of the insight that was soft-deleted or restored. */
    id: number
    /**
     * The insight's name (or derived name) at the time of the operation; null when it has neither.
     * @nullable
     */
    name: string | null
}

export interface InsightBulkOperationSkippedApi {
    /** ID of the insight that was skipped. */
    id: number
    /** Human-readable reason the insight was skipped (for example, not found or no edit permission). */
    reason: string
}

export interface InsightBulkDeleteResponseApi {
    /** Insights that were successfully soft-deleted. */
    deleted: InsightBulkOperationResultApi[]
    /** Insights that were not deleted, with the reason for each. */
    skipped: InsightBulkOperationSkippedApi[]
}

export interface InsightBulkRestoreResponseApi {
    /** Insights that were successfully restored. */
    restored: InsightBulkOperationResultApi[]
    /** Insights that were not restored, with the reason for each. */
    skipped: InsightBulkOperationSkippedApi[]
}

/**
 * * `add` - add
 * * `remove` - remove
 * * `set` - set
 */
export type BulkUpdateTagsActionEnumApi = (typeof BulkUpdateTagsActionEnumApi)[keyof typeof BulkUpdateTagsActionEnumApi]

export const BulkUpdateTagsActionEnumApi = {
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
     *
     * * `add` - add
     * * `remove` - remove
     * * `set` - set */
    action: BulkUpdateTagsActionEnumApi
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

/**
 * Insight enriched with view-count and recent-viewer fields, used by the trending action.
 */
export interface TrendingInsightApi {
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
    query?: unknown
    readonly dashboards: readonly number[]
    readonly dashboard_tiles: readonly DashboardTileBasicApi[]
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** @nullable */
    readonly last_refresh: string | null
    readonly refreshing: boolean
    tags?: unknown[]
    readonly updated_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    last_modified_at?: string
    favorited?: boolean
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    /** @nullable */
    readonly last_viewed_at: string | null
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
    /** Number of distinct viewers in the time window. Higher values indicate insights that more people in the project actively look at, which is a strong proxy for which insights matter. */
    readonly view_count: number
    /** Up to 3 of the most recent users who viewed this insight in the time window. */
    readonly viewers: readonly UserBasicApi[]
    /** User who last modified this insight, or null if never modified after creation. */
    readonly last_modified_by: UserBasicApi
}

export interface PaginatedTrendingInsightListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TrendingInsightApi[]
}

export interface InsightViewedRequestApi {
    /**
     * Insight IDs that were just viewed by the current user. At most 2500 ids per request.
     * @maxItems 2500
     */
    insight_ids: number[]
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

export type ElementsStatsRetrieveParams = {
    /**
     * Comma-separated data attribute names (wildcards allowed, e.g. data-*). When provided, each element's attributes map is filtered to matching attr__* keys, shrinking the response.
     */
    data_attributes?: string
    /**
     * Start of the date range (e.g. -7d, 2024-01-01). Defaults to last 7 days.
     */
    date_from?: string
    /**
     * End of the date range (e.g. 2024-01-31). Defaults to now.
     */
    date_to?: string
    /**
     * When true, applies the project's internal-and-test-account filters to the underlying events. Pass the lowercase string true; other truthy spellings are ignored.
     */
    filter_test_accounts?: boolean
    /**
     * Event types to include: $autocapture, $rageclick, $dead_click. Defaults to all three. Accepts repeated parameters, a JSON array, or a comma-separated list.
     */
    include?: string[]
    /**
     * Maximum rows per page
     */
    limit?: number
    /**
     * Pagination offset
     */
    offset?: number
    /**
     * JSON-encoded list of property filters to apply to the underlying events, e.g. [{"key": "$current_url", "value": "https://example.com/page"}] or [{"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}]. Supports event, person, cohort, element, and HogQL property filter types.
     */
    properties?: string
    /**
     * Sampling factor between 0 and 1
     */
    sampling_factor?: number
}

export type ElementsValuesListParams = {
    /**
     * Element property to list values for: tag_name, text, href, or attr_id.
     */
    key: string
    /**
     * Optional substring to filter values by (case-sensitive contains match).
     */
    value?: string
}

export type InsightsListParams = {
    /**
     * Return basic insight metadata only (no results, faster).
     */
    basic?: boolean
    /**
     * JSON-encoded array of user IDs. Only returns insights whose `created_by` is in the list, e.g. `[1,42]`.
     */
    created_by?: string
    /**
     * Filter by `created_at > created_date_from`. Accepts absolute or relative dates.
     */
    created_date_from?: string
    /**
     * Filter by `created_at < created_date_to`. Accepts absolute or relative dates.
     */
    created_date_to?: string
    /**
     * JSON-encoded array of dashboard IDs. Returns insights attached to every listed dashboard (AND).
     */
    dashboards?: string
    /**
     * Filter by `last_modified_at > date_from`. Accepts absolute dates (`2025-04-23`) or relative strings (`-7d`, `-1m`).
     */
    date_from?: string
    /**
     * Filter by `last_modified_at < date_to`. Accepts absolute dates or relative strings.
     */
    date_to?: string
    /**
     * Include this parameter (any value) to restrict results to insights marked as favorited.
     */
    favorited?: boolean
    format?: InsightsListFormat
    /**
     * Restrict to a single insight type. `JSON` matches non-wrapper query insights; `SQL` matches HogQL queries.
     */
    insight?: InsightsListInsight
    /**
     * Filter by `last_viewed_at > last_viewed_date_from`. Accepts absolute or relative dates.
     */
    last_viewed_date_from?: string
    /**
     * Filter by `last_viewed_at < last_viewed_date_to`. Accepts absolute or relative dates.
     */
    last_viewed_date_to?: string
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
     * Whether to refresh the retrieved insights, how aggressively, and if sync or async:
     * - `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates
     * - `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache
     * - `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache
     * - `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache
     * - `'force_blocking'` - calculate synchronously, even if fresh results are already cached
     * - `'force_async'` - kick off background calculation, even if fresh results are already cached
     * Background calculation can be tracked using the `query_status` response field.
     */
    refresh?: InsightsListRefresh
    /**
     * When truthy, restricts results to insights that are saved (or attached to a visible dashboard). When falsy, only unsaved insights.
     */
    saved?: boolean
    /**
     * Search term matched across name, derived_name, description, and tag names. Returns case-insensitive substring matches and fuzzy trigram matches together in one list, ordered exact-first; each result's `search_match_type` is `exact` or `similar`.
     */
    search?: string
    short_id?: string
    /**
     * JSON-encoded array of tag names. Returns insights with any of the listed tags.
     */
    tags?: string
    /**
     * Include this parameter (any value) to restrict results to insights created by the authenticated user.
     */
    user?: boolean
}

export type InsightsListFormat = (typeof InsightsListFormat)[keyof typeof InsightsListFormat]

export const InsightsListFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsListInsight = (typeof InsightsListInsight)[keyof typeof InsightsListInsight]

export const InsightsListInsight = {
    Funnels: 'FUNNELS',
    Json: 'JSON',
    Lifecycle: 'LIFECYCLE',
    Paths: 'PATHS',
    Retention: 'RETENTION',
    Sql: 'SQL',
    Stickiness: 'STICKINESS',
    Trends: 'TRENDS',
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
    /**
     * Object (or pre-encoded JSON string) to override the insight's filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.
     */
    filters_override?: string
    format?: InsightsRetrieveFormat
    /**
     *
     * Only if loading an insight in the context of a dashboard: The relevant dashboard's ID.
     * When set, the specified dashboard's filters and date range override will be applied.
     */
    from_dashboard?: number
    /**
     *
     * Whether to refresh the insight, how aggresively, and if sync or async:
     * - `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates
     * - `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache
     * - `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache
     * - `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache
     * - `'force_blocking'` - calculate synchronously, even if fresh results are already cached
     * - `'force_async'` - kick off background calculation, even if fresh results are already cached
     * Background calculation can be tracked using the `query_status` response field.
     */
    refresh?: InsightsRetrieveRefresh
    /**
     * Object (or pre-encoded JSON string) to override the insight's HogQL variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `insight-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.
     */
    variables_override?: string
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

export type InsightsActivityRetrieveParams = {
    format?: InsightsActivityRetrieveFormat
    /**
     * Page size. Defaults to 10.
     */
    limit?: number
    /**
     * 1-indexed page number. Defaults to 1.
     */
    page?: number
}

export type InsightsActivityRetrieveFormat =
    (typeof InsightsActivityRetrieveFormat)[keyof typeof InsightsActivityRetrieveFormat]

export const InsightsActivityRetrieveFormat = {
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

export type InsightsAllActivityRetrieveParams = {
    format?: InsightsAllActivityRetrieveFormat
    /**
     * Page size. Defaults to 10.
     */
    limit?: number
    /**
     * 1-indexed page number. Defaults to 1.
     */
    page?: number
}

export type InsightsAllActivityRetrieveFormat =
    (typeof InsightsAllActivityRetrieveFormat)[keyof typeof InsightsAllActivityRetrieveFormat]

export const InsightsAllActivityRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsBulkDeleteCreateParams = {
    format?: InsightsBulkDeleteCreateFormat
}

export type InsightsBulkDeleteCreateFormat =
    (typeof InsightsBulkDeleteCreateFormat)[keyof typeof InsightsBulkDeleteCreateFormat]

export const InsightsBulkDeleteCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type InsightsBulkRestoreCreateParams = {
    format?: InsightsBulkRestoreCreateFormat
}

export type InsightsBulkRestoreCreateFormat =
    (typeof InsightsBulkRestoreCreateFormat)[keyof typeof InsightsBulkRestoreCreateFormat]

export const InsightsBulkRestoreCreateFormat = {
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
    /**
     * Time window in days to compute view counts over. Defaults to 7. Larger windows surface consistently popular insights; smaller windows surface what's hot right now.
     */
    days?: number
    format?: InsightsTrendingRetrieveFormat
    /**
     * Maximum number of insights to return. Defaults to 10. Capped at 100.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
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
