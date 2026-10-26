/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type PropertyGroupOperatorEnumApi =
    (typeof PropertyGroupOperatorEnumApi)[keyof typeof PropertyGroupOperatorEnumApi]

export const PropertyGroupOperatorEnumApi = {
    And: 'AND',
    Or: 'OR',
} as const

/**
 * * `exact` - exact
 * * `is_not` - is_not
 * * `icontains` - icontains
 * * `not_icontains` - not_icontains
 * * `starts_with` - starts_with
 * * `not_starts_with` - not_starts_with
 * * `ends_with` - ends_with
 * * `not_ends_with` - not_ends_with
 * * `regex` - regex
 * * `not_regex` - not_regex
 * * `gt` - gt
 * * `lt` - lt
 * * `gte` - gte
 * * `lte` - lte
 * * `is_set` - is_set
 * * `is_not_set` - is_not_set
 * * `is_date_exact` - is_date_exact
 * * `is_date_after` - is_date_after
 * * `is_date_before` - is_date_before
 * * `in` - in
 * * `not_in` - not_in
 */
export type PropertyItemOperatorEnumApi = (typeof PropertyItemOperatorEnumApi)[keyof typeof PropertyItemOperatorEnumApi]

export const PropertyItemOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    StartsWith: 'starts_with',
    NotStartsWith: 'not_starts_with',
    EndsWith: 'ends_with',
    NotEndsWith: 'not_ends_with',
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

/**
 * * `event` - event
 * * `event_metadata` - event_metadata
 * * `feature` - feature
 * * `person` - person
 * * `person_metadata` - person_metadata
 * * `cohort` - cohort
 * * `element` - element
 * * `static-cohort` - static-cohort
 * * `dynamic-cohort` - dynamic-cohort
 * * `precalculated-cohort` - precalculated-cohort
 * * `group` - group
 * * `recording` - recording
 * * `log_entry` - log_entry
 * * `behavioral` - behavioral
 * * `session` - session
 * * `hogql` - hogql
 * * `data_warehouse` - data_warehouse
 * * `data_warehouse_person_property` - data_warehouse_person_property
 * * `error_tracking_issue` - error_tracking_issue
 * * `log` - log
 * * `log_attribute` - log_attribute
 * * `log_resource_attribute` - log_resource_attribute
 * * `metric_attribute` - metric_attribute
 * * `span` - span
 * * `span_attribute` - span_attribute
 * * `span_resource_attribute` - span_resource_attribute
 * * `revenue_analytics` - revenue_analytics
 * * `account_custom_property` - account_custom_property
 * * `flag` - flag
 * * `workflow_variable` - workflow_variable
 */
export type PropertyFilterTypeEnumApi = (typeof PropertyFilterTypeEnumApi)[keyof typeof PropertyFilterTypeEnumApi]

export const PropertyFilterTypeEnumApi = {
    Event: 'event',
    EventMetadata: 'event_metadata',
    Feature: 'feature',
    Person: 'person',
    PersonMetadata: 'person_metadata',
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
    MetricAttribute: 'metric_attribute',
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
    RevenueAnalytics: 'revenue_analytics',
    AccountCustomProperty: 'account_custom_property',
    Flag: 'flag',
    WorkflowVariable: 'workflow_variable',
} as const

export const PropertyItemApiType = { ...PropertyFilterTypeEnumApi, ...BlankEnumApi } as const
export interface PropertyItemApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url` */
    key: string
    /** Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]` */
    value: string | number | boolean | (string | number)[]
    operator?: PropertyItemOperatorEnumApi | BlankEnumApi | null
    type?: (typeof PropertyItemApiType)[keyof typeof PropertyItemApiType]
}

export interface PropertyApi {
    /**
     *  You can use a simplified version:
     * ```json
     * {
     *     "properties": [
     *         {
     *             "key": "email",
     *             "value": "x@y.com",
     *             "operator": "exact",
     *             "type": "event"
     *         }
     *     ]
     * }
     * ```
     *
     * Or you can create more complicated queries with AND and OR:
     * ```json
     * {
     *     "properties": {
     *         "type": "AND",
     *         "values": [
     *             {
     *                 "type": "OR",
     *                 "values": [
     *                     {"key": "email", ...},
     *                     {"key": "email", ...}
     *                 ]
     *             },
     *             {
     *                 "type": "AND",
     *                 "values": [
     *                     {"key": "email", ...},
     *                     {"key": "email", ...}
     *                 ]
     *             }
     *         ]
     *     ]
     * }
     * ```
     *
     *
     * * `AND` - AND
     * * `OR` - OR */
    type?: PropertyGroupOperatorEnumApi
    values: PropertyItemApi[]
}

/**
 * * `distinct_id` - Distinct ID
 * * `email` - Email
 * * `name` - Name
 * * `id` - Person ID
 */
export type PersonSearchMatchFieldEnumApi =
    (typeof PersonSearchMatchFieldEnumApi)[keyof typeof PersonSearchMatchFieldEnumApi]

export const PersonSearchMatchFieldEnumApi = {
    DistinctId: 'distinct_id',
    Email: 'email',
    Name: 'name',
    Id: 'id',
} as const

export interface PersonListRecordApi {
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
    /** Only on a search result with `include_matched_fields`: the searched fields the term was found in. */
    matched_fields?: PersonSearchMatchFieldEnumApi[]
}

export interface PaginatedPersonListRecordListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    count?: number
    results?: PersonListRecordApi[]
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
    /** A property key, or a list of property keys, to remove from this person. */
    $unset: string | string[]
}

export interface MessageAssetApi {
    /** The workflow run this email was sent in. */
    invocation_id: string
    /** The email step (action node) within the workflow that sent this email. */
    action_id: string
    /** The workflow id that sent this email — used to navigate from a person's Emails tab back into the originating workflow. */
    function_id: string
    /** Human-readable workflow name for display. Empty when the workflow has been deleted; clients should fall back to function_id in that case. */
    function_name: string
    /** The batch run this email belongs to, for batch-triggered workflows. Empty for event-triggered runs. */
    parent_run_id: string
    /** Message channel this asset was sent on: 'email' or 'push'. The per-person endpoints return one channel each. */
    kind: string
    /** The recipient's distinct_id. */
    distinct_id: string
    /** The recipient's person UUID, if resolved. */
    person_id: string
    /** Who the message went to: the email address for 'email', or the recipient's distinct ID for 'push'. */
    recipient: string
    /** The email subject line, or the push notification title. */
    subject: string
    /** Delivery status at capture time. Currently always 'sent' - only delivered messages are captured. */
    status: string
    /** When the message was sent. */
    sent_at: string
}

export type CompareApi = (typeof CompareApi)[keyof typeof CompareApi]

export const CompareApi = {
    Current: 'current',
    Previous: 'previous',
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

export type CustomBotFieldApi = (typeof CustomBotFieldApi)[keyof typeof CustomBotFieldApi]

export const CustomBotFieldApi = {
    RawUserAgent: '$raw_user_agent',
    Ip: '$ip',
    Lib: '$lib',
    Host: '$host',
    Pathname: '$pathname',
    CurrentUrl: '$current_url',
    Browser: '$browser',
    Os: '$os',
    BrowserLanguage: '$browser_language',
    ScreenWidth: '$screen_width',
    ScreenHeight: '$screen_height',
    GeoipCountryCode: '$geoip_country_code',
    Referrer: '$referrer',
    ReferringDomain: '$referring_domain',
} as const

export type CustomBotMatcherApi = (typeof CustomBotMatcherApi)[keyof typeof CustomBotMatcherApi]

export const CustomBotMatcherApi = {
    Contains: 'contains',
    Regex: 'regex',
    Exact: 'exact',
    Cidr: 'cidr',
} as const

export interface CustomBotConditionApi {
    id: string
    /** The event property this condition reads. */
    key: CustomBotFieldApi
    matcher: CustomBotMatcherApi
    /** Matched against the property named by `key`. */
    pattern: string
}

export interface CustomBotRuleApi {
    /** Reported by `$virt_traffic_category`. Defaults to `custom`. */
    category?: string | null
    /** Whether every condition must match (AND) or any one of them (OR). */
    combiner: FilterLogicalOperatorApi
    id: string
    items: CustomBotConditionApi[]
    /** Reported by `$virt_bot_name` and `$virt_bot_operator` when the rule matches. */
    name: string
}

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
    /** Do not treat a missing user agent as automation on cookieless events. Positive bot signals and custom project rules still apply. Resolved server-side; not intended to be set by clients. */
    cookielessTrafficIsRegular?: boolean | null
    customBotDefinitions?: CustomBotRuleApi[] | null
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
    /** Merge sibling aggregating LEFT JOINs over federated Postgres tables into one UNION ALL join, so their scans overlap */
    mergeFederatedAggregateJoins?: boolean | null
    /** Replace negated person-property filters in the WHERE of an `events` query (such as `email not_icontains`) with `person_id NOT IN (SELECT id FROM persons WHERE <the filters fail>)`, so the query no longer joins every person. Applies only when every filtered person property has a materialized column, nothing else in the query reads that persons join, and the join would be a LEFT JOIN. */
    negatedPersonFiltersNotIn?: boolean | null
    optimizeJoinedFilters?: boolean | null
    optimizeProjections?: boolean | null
    /** HogQL parser backend; absent → `rust_py_with_cpp_shadow` (rust-py is primary, cpp runs as a sampled shadow). `*_shadow` modes return the primary result and sample-compare against the other parser, reporting divergences without failing the request. The `rust_py_*` modes drive the same hand-rolled Rust parser as `rust_*` but build `posthog.hogql.ast` dataclass instances directly via PyO3, skipping the JSON round-trip. */
    parserMode?: ParserModeApi | null
    /** Push an `id IN (SELECT person_id FROM <left table> WHERE …)` predicate into the joined persons subquery, so the latest-version lookup only reads persons that the outer query's left-table filters can reach. Applies only to a persons join from the query's own FROM table. */
    personIdPushdown?: boolean | null
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
    /** Padding, in minutes, on each side of the event time range when it filters the sessions table by session start. Defaults to 3 days. It can only narrow the range: values above the default are ignored. Lower it only for a query that keeps just the sessions that start inside its own time range. */
    sessionTimestampBufferMinutes?: number | null
    sessionsV2JoinMode?: SessionsV2JoinModeApi | null
    timings?: boolean | null
    /** Remove provably redundant casts and nullability wrappers (e.g. `toString(String)`, `assumeNotNull(non_nullable)`, dead `ifNull` fallbacks) using inferred expression types */
    typeAwareCastSimplification?: boolean | null
    useMaterializedViews?: boolean | null
    /** Read this query from the native events cluster and native JSON events table (`true`), or keep its existing connection (`false` or unset). This is an internal rollout switch for eligible projects. PostHog staff manage eligibility through instance settings. Each query must opt in; project defaults cannot enable it. Only synchronous HogQLQuery SQL comparisons are supported. */
    useNewEventsCluster?: boolean | null
    /** Read events from the native JSON events table (`true`) or the legacy events table (`false`). When unset, the project's stored value applies, then the `CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA` instance settings. This is an internal rollout switch. PostHog staff set the project value in Django admin and the project settings API ignores it. */
    useNewEventsSchema?: boolean | null
    usePreaggregatedIntermediateResults?: boolean | null
    /** Try to automatically convert HogQL queries to use preaggregated tables at the AST level * */
    usePreaggregatedTableTransforms?: boolean | null
    useWebAnalyticsPreAggregatedTables?: boolean | null
    /** Serve filters on the stored session-entry attribution properties (`$channel_type`, `$entry_utm_*`, `$entry_referring_domain`) by recomputing the value from the session's first pageview. Resolved server-side; not intended to be set by clients. */
    webAnalyticsFirstPageviewFilters?: boolean | null
}

export interface ClickhouseQueryProgressApi {
    active_cpu_time: number
    bytes_read: number
    estimated_rows_total: number
    rows_read: number
    time_elapsed: number
}

export type QueryScanFixLocationApi = (typeof QueryScanFixLocationApi)[keyof typeof QueryScanFixLocationApi]

export const QueryScanFixLocationApi = {
    Query: 'query',
    Subquery: 'subquery',
    View: 'view',
    InsightDateRange: 'insight_date_range',
    DashboardDateFilter: 'dashboard_date_filter',
} as const

export type QueryScanFindingKindApi = (typeof QueryScanFindingKindApi)[keyof typeof QueryScanFindingKindApi]

export const QueryScanFindingKindApi = {
    NoEventFilter: 'no_event_filter',
    NoStartDate: 'no_start_date',
    PersonsJoin: 'persons_join',
} as const

export interface QueryScanWarningApi {
    /** Whether the person can change the query so it reads less and still answers the same question. Surfaces show the full advice and "Fix with AI" only when a finding is actionable. */
    actionable: boolean
    /** True when the query reads this much on purpose, so reading less would change the answer. Absent means no. */
    by_design?: boolean | null
    /** A label for what in the query text kept the read wide, such as `in_or`. Only analytics and the assistant read it, and the labels can change. */
    cause?: string | null
    /** The one fact the finding rests on. */
    evidence?: string | null
    /** What "Fix with AI" and the assistant are told to do. */
    fix: string
    /** Where the change goes. Absent means the query itself. */
    fix_location?: QueryScanFixLocationApi | null
    kind: QueryScanFindingKindApi
    /** Shown to the person: what happened and what to do. */
    message: string
}

export interface QueryScanAnalysisApi {
    /** The message the Fix with AI button sends to the assistant. Absent when no finding can be fixed in the query. */
    assistant_prompt?: string | null
    /** Every finding, fixable or not. Empty when the analysis found none. */
    findings: QueryScanWarningApi[]
    /** How much of all the project's events the query read, 0 to 1. */
    project_share?: number | null
    /** How much of the project's events in the query's date range the query read, 0 to 1. */
    range_share?: number | null
}

export interface QueryScanSummaryApi {
    /** The stored analysis, put on the response when it is served. Absent while the analysis runs, and when none was requested. */
    analysis?: QueryScanAnalysisApi | null
    /** True when the run asked for an analysis, or found one stored. While `analysis` is absent, poll `GET /query/scan/{cache_key}` for it. */
    analysis_requested?: boolean | null
    /** ClickHouse time for the last fresh run, summed over its ClickHouse queries. */
    duration_ms: number
    /** True when ClickHouse stopped the run instead of finishing it. */
    killed?: boolean | null
    /** Rows ClickHouse read for the last fresh run, all tables included. */
    rows_read: number
}

export interface QueryStatusApi {
    budget_remaining_bytes?: number | null
    bytes_read?: number | null
    /** Cache key of the run that failed, so clients can ask for its query scan. */
    cache_key?: string | null
    /** Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set. */
    complete?: boolean | null
    dashboard_id?: number | null
    /** When did the query execution task finish (whether successfully or not). */
    end_time?: string | null
    /** If the query failed, this will be set to true. More information can be found in the error_message field. */
    error?: boolean | null
    /** Stable machine-readable code for the error, when known: the DRF exception code, the ClickHouse error name, the HogQL error code, or `unhandled_<exception class>` for a failure that no handler classified. */
    error_code?: string | null
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
    query_scan?: QueryScanSummaryApi | null
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

export interface DataWarehouseSourceUsageApi {
    /** ExternalDataSource id */
    id: string
    /** Connector type of the source (e.g. Stripe, Postgres), if known */
    source_type?: string | null
    /** Warehouse table name that was referenced */
    table_name: string
}

export interface DataWarehouseSyncWarningApi {
    /** True when the last sync is still within the table's sync interval, so the data is current and the warning only says it will stop updating (a sync paused recently). False or absent when the data is out of date. */
    data_is_current?: boolean | null
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
    /** Tells warning kinds apart in the shared `warnings` list */
    type?: 'warehouse_sync'
}

export interface AccessControlFilterWarningApi {
    /** Human-readable warning shown to the user */
    message: string
    /** Resource types the user has access restrictions on, referenced by the query, e.g. ["insight", "dashboard"] */
    resources: string[]
    /** Tells warning kinds apart in the shared `warnings` list */
    type?: 'access_control'
}

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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
}

export type BreakdownTypeApi = (typeof BreakdownTypeApi)[keyof typeof BreakdownTypeApi]

export const BreakdownTypeApi = {
    Cohort: 'cohort',
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Element: 'element',
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
    Element: 'element',
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

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

export const PropertyOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    StartsWith: 'starts_with',
    NotStartsWith: 'not_starts_with',
    EndsWith: 'ends_with',
    NotEndsWith: 'not_ends_with',
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
    IsCleanedPathNotExact: 'is_cleaned_path_not_exact',
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

export interface SessionPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'session'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface CohortPropertyFilterApi {
    /** Set by the feature flag API when the cohort is deleted or does not exist. */
    cohort_deleted?: boolean | null
    /** Set by the feature flag API when the cohort does not exist, so it cannot be restored. */
    cohort_missing?: boolean | null
    cohort_name?: string | null
    key?: 'id'
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: 'cohort'
    value: number
}

export interface ActionConversionGoalApi {
    actionId: number
    properties?:
        | (EventPropertyFilterApi | PersonPropertyFilterApi | SessionPropertyFilterApi | CohortPropertyFilterApi)[]
        | null
}

export interface CustomEventConversionGoalApi {
    customEventName: string
    properties?:
        | (EventPropertyFilterApi | PersonPropertyFilterApi | SessionPropertyFilterApi | CohortPropertyFilterApi)[]
        | null
}

export type DaysOfWeekEnumApi = (typeof DaysOfWeekEnumApi)[keyof typeof DaysOfWeekEnumApi]

export const DaysOfWeekEnumApi = {
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number4: 4,
    Number5: 5,
    Number6: 6,
    Number7: 7,
} as const

export interface DateRangeApi {
    /** Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),
     * -1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year). */
    date_from?: string | null
    /** End of the date range. Same format as date_from. Omit or null for "now". A calendar day without a time (2024-01-15) is inclusive: it rounds to the last moment of that day in the project timezone, unless explicitDate is set. */
    date_to?: string | null
    /** Restrict the query to events occurring on these ISO days of week (1=Monday to 7=Sunday), evaluated in the project timezone. Omit or empty for all days. Only applied by insight queries. */
    daysOfWeek?: DaysOfWeekEnumApi[] | null
    /** Exclude the current, still-collecting period by clipping date_to to the end of the last complete interval (evaluated in the project timezone). No-op when the range contains no complete interval. Only applied by insight queries. */
    excludeIncompletePeriods?: boolean | null
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
    Quarter: 'quarter',
    Year: 'year',
} as const

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

export interface MetricPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'metric_attribute'
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

export interface AccountCustomPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Customer analytics account custom property — the key is the property definition id */
    type?: 'account_custom_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface WorkflowVariablePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'workflow_variable'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type BehavioralEventSourceApi = (typeof BehavioralEventSourceApi)[keyof typeof BehavioralEventSourceApi]

export const BehavioralEventSourceApi = {
    Events: 'events',
    Actions: 'actions',
} as const

export type TimeUnitTypeApi = (typeof TimeUnitTypeApi)[keyof typeof TimeUnitTypeApi]

export const TimeUnitTypeApi = {
    Day: 'day',
    Week: 'week',
    Month: 'month',
    Year: 'year',
} as const

export type InlineBehavioralTypeApi = (typeof InlineBehavioralTypeApi)[keyof typeof InlineBehavioralTypeApi]

export const InlineBehavioralTypeApi = {
    PerformedEvent: 'performed_event',
    PerformedEventMultiple: 'performed_event_multiple',
} as const

export interface BehavioralPropertyFilterApi {
    /** Extra property filters the matching events must satisfy. Deliberately excludes nested behavioral/cohort filters and groups */
    event_filters?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | FeaturePropertyFilterApi
              | HogQLPropertyFilterApi
          )[]
        | null
    event_type: BehavioralEventSourceApi
    /** Absolute or relative (e.g. -30d) lower date bound — alternative to time_value/time_interval */
    explicit_datetime?: string | null
    explicit_datetime_to?: string | null
    /** Event name, or action id when event_type is 'actions' */
    key: string
    label?: string | null
    /** Match persons who did NOT satisfy the criterion. Not the same as a low count — zero-occurrence persons never match count operators */
    negation?: boolean | null
    /** Count comparison for performed_event_multiple, defaults to exact */
    operator?: PropertyOperatorApi | null
    /** Count threshold for performed_event_multiple */
    operator_value?: number | null
    time_interval?: TimeUnitTypeApi | null
    /** Relative time window size, paired with time_interval */
    time_value?: number | null
    /** Person performed (or didn't perform) an event in a time window. ClickHouse-only — not evaluable by flags or CDP */
    type?: 'behavioral'
    value: InlineBehavioralTypeApi
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

export type GroupMathTypeApi = (typeof GroupMathTypeApi)[keyof typeof GroupMathTypeApi]

export const GroupMathTypeApi = {
    UniqueGroup: 'unique_group',
    FirstTimeForGroup: 'first_time_for_group',
    FirstMatchingEventForGroup: 'first_matching_event_for_group',
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: DataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface MarketingAnalyticsCostFallbackApi {
    /**
     * @minItems 1
     * @maxItems 200
     */
    series: DataWarehouseNodeApi[]
    /**
     * @minItems 1
     * @maxItems 200
     */
    sourceIds: string[]
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
        | MetricPropertyFilterApi
        | SpanPropertyFilterApi
        | RevenueAnalyticsPropertyFilterApi
        | AccountCustomPropertyFilterApi
        | WorkflowVariablePropertyFilterApi
        | BehavioralPropertyFilterApi
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    id: number
    kind?: 'ActionsNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: ActionsNodeApiResponse
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    kind?: 'GroupNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: GroupNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface QueryLogTagsApi {
    /** Name of the query, preferably unique. For example web_analytics_vitals */
    name?: string | null
    /** Short id of the saved Web analytics filter preset this query was run under, if any. */
    presetId?: string | null
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
    DurationNs: 'duration_ns',
    Percentage: 'percentage',
    PercentageScaled: 'percentage_scaled',
    Currency: 'currency',
    Short: 'short',
} as const

export type AnnotationScopeApi = (typeof AnnotationScopeApi)[keyof typeof AnnotationScopeApi]

export const AnnotationScopeApi = {
    DashboardItem: 'dashboard_item',
    Dashboard: 'dashboard',
    Project: 'project',
    Organization: 'organization',
} as const

export type CurveApi = (typeof CurveApi)[keyof typeof CurveApi]

export const CurveApi = {
    Linear: 'linear',
    Smooth: 'smooth',
} as const

export type SeriesColorModeApi = (typeof SeriesColorModeApi)[keyof typeof SeriesColorModeApi]

export const SeriesColorModeApi = {
    Palette: 'palette',
    Opacity: 'opacity',
} as const

export interface ChartStyleApi {
    /** Line interpolation: straight segments or a smoothed curve through the points. */
    curve?: CurveApi | null
    /** How series are told apart: one color per series, or one color at stepped opacities. */
    seriesColorMode?: SeriesColorModeApi | null
}

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
    ActionsDonut: 'ActionsDonut',
    ActionsProportionBar: 'ActionsProportionBar',
    ActionsBarValue: 'ActionsBarValue',
    ActionsTable: 'ActionsTable',
    WorldMap: 'WorldMap',
    CalendarHeatmap: 'CalendarHeatmap',
    TwoDimensionalHeatmap: 'TwoDimensionalHeatmap',
    BoxPlot: 'BoxPlot',
    SlopeGraph: 'SlopeGraph',
    ScatterPlot: 'ScatterPlot',
} as const

export interface TrendsFormulaNodeApi {
    /** Optional user-defined name for the formula */
    custom_name?: string | null
    formula: string
}

export type CalculationApi = (typeof CalculationApi)[keyof typeof CalculationApi]

export const CalculationApi = {
    Fixed: 'fixed',
    Mean: 'mean',
    Median: 'median',
    Min: 'min',
    Max: 'max',
} as const

export type PositionApi = (typeof PositionApi)[keyof typeof PositionApi]

export const PositionApi = {
    Start: 'start',
    End: 'end',
} as const

export type ScopeApi = (typeof ScopeApi)[keyof typeof ScopeApi]

export const ScopeApi = {
    All: 'all',
    Series: 'series',
} as const

export interface GoalLineApi {
    borderColor?: string | null
    /** Recalculate from returned chart marks. An absent calculation uses the fixed value. */
    calculation?: CalculationApi | null
    displayIfCrossed?: boolean | null
    displayLabel?: boolean | null
    label: string
    position?: PositionApi | null
    /** SQL chart calculations use the primary axis, across all series or separately per series. */
    scope?: ScopeApi | null
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
    customColor?: string | null
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
    /** Render only annotations with this scope. Unset renders every scope. */
    annotationsScope?: AnnotationScopeApi | null
    breakdown_histogram_bin_count?: number | null
    /** Chart rendering style overrides (line shape). */
    chartStyle?: ChartStyleApi | null
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
    /** Ignored. Superseded by `dateRange.daysOfWeek`, which excludes the days from the query instead of only hiding their buckets. Still accepted so existing API clients keep working. */
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
    /** Pins the top of the y-axis; unset means automatic. Ignored in the same cases as `yAxisStartAtZero`, and when `yAxisMin` is not below it. */
    yAxisMax?: number | null
    /** Pins the bottom of the y-axis; unset means automatic. Ignored in the same cases as `yAxisStartAtZero`, while it is on, and when not below `yAxisMax`. */
    yAxisMin?: number | null
    yAxisScaleType?: YAxisScaleTypeApi | null
    /** Y-axis baseline. When false the axis floats to the data range instead of starting at zero. Ignored on bar displays (bars always draw from zero), on a logarithmic scale, and while showing percentages. */
    yAxisStartAtZero?: boolean | null
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
    /** Live series for a Marketing cost trend when materialization coverage is incomplete. */
    marketingAnalyticsCostFallback?: MarketingAnalyticsCostFallbackApi | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | PropertyGroupFilterApi
        | null
    response?: TrendsQueryResponseApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    /**
     * Events and actions to include
     * @maxItems 200
     */
    series: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi | GroupNodeApi)[]
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
    /** Render only annotations with this scope. Only applies to historical-trends funnels. */
    annotationsScope?: AnnotationScopeApi | null
    binCount?: number | null
    breakdownAttributionType?: BreakdownAttributionTypeApi | null
    breakdownAttributionValue?: number | null
    /** Breakdown table sorting. Format: 'column_key' or '-column_key' (descending) */
    breakdownSorting?: string | null
    /** Chart rendering style overrides (line shape). Only applies to historical-trends funnels. */
    chartStyle?: ChartStyleApi | null
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | PropertyGroupFilterApi
        | null
    response?: FunnelsQueryResponseApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (EventsNodeApi | ActionsNodeApi | FunnelsDataWarehouseNodeApi | GroupNodeApi)[]
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
    /** Chart rendering style overrides (line shape). */
    chartStyle?: ChartStyleApi | null
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
    /** Draw the mean across cohorts as one line on the retention graph. */
    showMeanLine?: boolean | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
    /** The replacement for the matched path. Use angle-bracket placeholders (`<id>`, `<uuid>`, `<slug>`) by convention, or reuse a capture group from the regex with ClickHouse `replaceRegexpAll` replacement syntax: `\1` to `\9` for a group and `\0` for the whole match. */
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
    /** Remove the query string from page view URLs, so pages that differ only in query parameters become one path item */
    stripQueryString?: boolean | null
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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

export interface PathsV2ItemApi {
    /** Event of the step source this item belongs to. */
    event: string
    /** Label value from the source's naming property, after path cleaning. An empty string when the property is missing on the event. Null for sources without a naming property. */
    label?: string | null
}

export type PathsV2AnchorTypeApi = (typeof PathsV2AnchorTypeApi)[keyof typeof PathsV2AnchorTypeApi]

export const PathsV2AnchorTypeApi = {
    Start: 'start',
    End: 'end',
} as const

export interface PathsV2AnchorApi {
    /** The path item the chart anchors on. Its event must be one of the step sources. */
    item: PathsV2ItemApi
    /** `start` runs each actor's single sequence forward from the anchor item; `end` runs it up to the anchor item. Either way the anchor is the grid's single 100% node. */
    type: PathsV2AnchorTypeApi
}

export interface PathsV2StepSourceApi {
    /** Name of the event this source matches. */
    event: string
    /** Event property whose value labels the path item, e.g. `$pathname` for pageviews. Team path cleaning rules are applied to the value. Without a naming property, the event itself is the path item. */
    namingProperty?: string | null
}

export interface PathsV2FilterApi {
    /** Anchor selecting anchored mode. When set, each actor contributes exactly one sequence bounded by the conversion window, so every displayed segment equals a plain funnel. Absent selects open mode, which splits an actor's events into journeys on the inactivity gap instead. */
    anchor?: PathsV2AnchorApi | null
    /** Apply the team's path cleaning rules to naming property values before they become path items. */
    applyTeamPathCleaning?: boolean | null
    /** Merge immediate repeats of the same path item within a journey. */
    collapseRepeats?: boolean | null
    /** Anchored mode's single conversion window W, anchored at the anchor and reused verbatim as the emitted funnel's window. Bounds per unit are validated server-side against CONVERSION_WINDOW_INTERVAL_BOUNDS, the same funnel conversion window bounds as the gap. */
    conversionWindowInterval?: number | null
    conversionWindowIntervalUnit?: FunnelConversionWindowTimeUnitApi | null
    /** Path items dropped from the item universe: events deriving to one of these items are ignored as if their event were not a step source, on both the paths side and the "view as funnel" side. */
    excludedItems?: PathsV2ItemApi[] | null
    /** Inactivity gap that splits an actor's events into journeys. Bounds per unit are validated server-side against CONVERSION_WINDOW_INTERVAL_BOUNDS, the funnel conversion window bounds. */
    gapInterval?: number | null
    gapIntervalUnit?: FunnelConversionWindowTimeUnitApi | null
    /** Path cleaning rules for this insight only, applied after the team's rules. */
    localPathCleaningFilters?: PathCleaningFilterApi[] | null
    /** Number of path item rows per step; items beyond this go into the "other" row. */
    maxRowsPerStep?: number | null
    /** Number of journey steps (columns) shown. */
    maxSteps?: number | null
    /** Step sources defining which events can become path items. Defaults to the pageviews preset: `$pageview` named by `$pathname`. */
    stepSources?: PathsV2StepSourceApi[] | null
}

export interface PathsV2EdgeApi {
    /** Unique actors who transition from source to target at any step of any of their whole journeys, the position-free count behind "went source → target at any step". Equals the two-step item-strict funnel's converted count. Only set in open mode on edges between two named items. */
    anyStepCount?: number | null
    /** Unique actors with a journey that transitions from source to target between these steps. */
    count: number
    /** Source path item, or null for the source column's "other" row. */
    source: PathsV2ItemApi | null
    /** 0-based step index of the source column; the target sits at `stepIndex + 1`. */
    stepIndex: number
    /** Target path item, or null for the target column's "other" row. */
    target: PathsV2ItemApi | null
}

export interface PathsV2PrefixApi {
    /** Unique actors whose anchored sequence begins with exactly these items. */
    count: number
    /** The chain's path items in order, starting at the anchor. */
    items: PathsV2ItemApi[]
}

export interface PathsV2RowApi {
    /** Unique actors with a journey whose item at this step is this path item. */
    count: number
    item: PathsV2ItemApi
}

export interface PathsV2StepApi {
    /** Unique actors whose journey ends at this step. */
    dropOffCount: number
    /** Unique actors at this step whose path item is beyond the top rows. */
    otherCount: number
    /** Top path items at this step, ordered by unique-actor count descending. */
    rows: PathsV2RowApi[]
    /** 0-based step index (column) in the journey grid. */
    stepIndex: number
}

export interface PathsV2ResultsApi {
    edges: PathsV2EdgeApi[]
    /** Concrete anchored chains with per-chain unique-actor counts, ordered by descending count. Empty in open mode; in anchored mode it carries the counts the hover funnel preview reads per chain. Only chains the grid displays in full are carried: chains through the other bucket are omitted, so the response never exposes labels the chart hides. */
    prefixes: PathsV2PrefixApi[]
    steps: PathsV2StepApi[]
}

export interface PathsV2QueryResponseApi {
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
    results: PathsV2ResultsApi
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
}

export interface PathsV2QueryApi {
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    kind?: 'PathsV2Query'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Properties specific to the paths v2 insight */
    pathsV2Filter?: PathsV2FilterApi | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | PropertyGroupFilterApi
        | null
    response?: PathsV2QueryResponseApi | null
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
    /** Chart rendering style overrides (line shape). */
    chartStyle?: ChartStyleApi | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | PropertyGroupFilterApi
        | null
    response?: StickinessQueryResponseApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    /**
     * Events and actions to include
     * @maxItems 200
     */
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    id: string
    kind?: 'LifecycleDataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
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
    FirstPageviewChannelType: 'FirstPageviewChannelType',
    FirstPageviewReferringDomain: 'FirstPageviewReferringDomain',
    FirstPageviewUTMSource: 'FirstPageviewUTMSource',
    FirstPageviewUTMCampaign: 'FirstPageviewUTMCampaign',
    FirstPageviewUTMMedium: 'FirstPageviewUTMMedium',
    FirstPageviewUTMTerm: 'FirstPageviewUTMTerm',
    FirstPageviewUTMContent: 'FirstPageviewUTMContent',
    FirstPageviewUTMSourceMediumCampaign: 'FirstPageviewUTMSourceMediumCampaign',
    Browser: 'Browser',
    InAppBrowser: 'InAppBrowser',
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
    /** Why a live response skipped precompute: the eligibility-gate reason that refused it. Unset when the query was eligible. */
    preComputeIneligibleReason?: string | null
    /** Whether a lazy-precompute read was served from expired-within-grace (stale) jobs instead of recomputing inline. */
    preComputeStale?: boolean | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** When the oldest precomputed window this response used was computed. Unset for live responses. */
    preComputedAt?: string | null
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
    includeTrafficMetrics?: boolean | null
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
    /** Why a live response skipped precompute: the eligibility-gate reason that refused it. Unset when the query was eligible. */
    preComputeIneligibleReason?: string | null
    /** Whether a lazy-precompute read was served from expired-within-grace (stale) jobs instead of recomputing inline. */
    preComputeStale?: boolean | null
    preComputeStrategy?: WebAnalyticsPreComputeStrategyApi | null
    /** When the oldest precomputed window this response used was computed. Unset for live responses. */
    preComputedAt?: string | null
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
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi)[] | null
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
        | PathsV2QueryApi
        | StickinessQueryApi
        | LifecycleQueryApi
        | WebStatsTableQueryApi
        | WebOverviewQueryApi
    status?: string | null
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface PropertiesTimelineRequestApi {
    /** The actors query of the insight data point, as the persons modal sends it. The timeline reads the person's events in the data point's time window, and tracks the person properties that the series, the insight's filters and its breakdown use. The source must be a Trends query, and the selected series must be an events or actions series. */
    query: InsightActorsQueryApi
}

/**
 * The person's properties as that event recorded them.
 */
export type PropertiesTimelinePointApiProperties = { [key: string]: unknown }

export interface PropertiesTimelinePointApi {
    /** The time of the first event in the window that has this combination of key property values. */
    timestamp: string
    /** The person's properties as that event recorded them. */
    properties: PropertiesTimelinePointApiProperties
    /** The number of the person's events in the window from this point until the next point. */
    relevant_event_count: number
}

export interface PropertiesTimelineResponseApi {
    /** One point for each change of the key property values, oldest first. */
    points: PropertiesTimelinePointApi[]
    /** The key person properties: those the insight's query uses. Empty when it uses none. */
    crucial_property_keys: string[]
    /** The start of the window, in the project's time zone. */
    effective_date_from: string
    /** The end of the window, in the project's time zone. */
    effective_date_to: string
}

export interface PersonSplitRequestApi {
    /**
     * The distinct_id to **keep** on this person; every *other* distinct_id is moved to its own new single-id person. If omitted, the first distinct_id on the person is kept. The original person always retains its properties; to clear individual properties afterward, use the delete_property endpoint. To surgically *remove* one or more distinct_ids while leaving the merge intact, use `distinct_ids_to_split` instead — these parameters are inverses of each other and cannot be combined.
     * @nullable
     */
    main_distinct_id?: string | null
    /**
     * List of distinct_ids to **move off** this person onto new single-id persons. The original person keeps every other distinct_id and its properties. New persons are created with deterministic UUIDs derived from `(team_id, distinct_id)`. Cannot be combined with `main_distinct_id`.
     * @nullable
     */
    distinct_ids_to_split?: string[] | null
}

export interface PersonSplitResponseApi {
    /** Always `true` when the split task was enqueued. The split itself runs asynchronously — a 201 response means the task was accepted, not that the merge state has already been updated. */
    success: boolean
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
    /** Number of person records deleted from the database during this request. 0 if keep_person was true or if the deletion was queued (see persons_queued_for_deletion). */
    persons_deleted: number
    /** Number of persons queued for deletion in the background. Their person records and distinct IDs are removed shortly after the request completes. 0 if keep_person was true. */
    persons_queued_for_deletion: number
    /** Whether event deletion was requested for the matched persons. If a deletion was already queued for a person, it will not be duplicated. */
    events_queued_for_deletion: boolean
    /** Whether recording deletion was requested for the matched persons. If a deletion was already queued for a person, it will not be duplicated. */
    recordings_queued_for_deletion: boolean
    /** Persons whose deletion did not fully complete in this request. Each entry contains 'person_uuid' and 'step', the deletion step that failed for that person. Failures are reported here rather than as an error status, so a 202 with entries means those persons were not deleted and the request should be retried for them. Two steps are exceptions, and retrying won't find these persons. For 'log_activity', the person was deleted, but the activity log entry was not written. For 'publish_clickhouse_tombstone', the person was deleted, but it can still show in analytics until a weekly cleanup job removes it. Always empty when the deletion was queued (see persons_queued_for_deletion). Contact support if this persists. */
    deletion_errors?: PersonBulkDeleteResponseApiDeletionErrorsItem[]
}

/**
 * Minimal serializer for cohort references, read by the person cohorts endpoint.
 */
export interface CohortMinimalApi {
    readonly id: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    count?: number | null
}

export interface PersonCohortsResponseApi {
    /** Cohorts the person currently belongs to. */
    results: CohortMinimalApi[]
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
     * Names the ClickHouse query this request runs. Send the same id to `DELETE /api/projects/:project_id/query/:client_query_id/` to stop a search that is still running. Up to 128 characters.
     */
    client_query_id?: string
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
     * Tag each search result with `matched_fields`, the searched fields the term was found in. A complete email address that exactly matches a distinct ID then returns that person first, followed by every person whose email or name property contains the address.
     */
    include_matched_fields?: boolean
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
     * Search persons by email, name, person ID, or distinct ID. Partial values match. When the term is a complete email address or UUID that exactly matches a distinct ID or person ID, only that person is returned.
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

export type PersonsEmailsListParams = {
    /**
     * Start of the time range, matched on sent time. Relative ('-30d', '-24h') or ISO 8601. Defaults to -30d (the retention window) — bounds the ClickHouse partition scan.
     * @minLength 1
     */
    after?: string
    /**
     * End of the time range, matched on sent time. Same format as 'after'. Defaults to now.
     * @minLength 1
     */
    before?: string
    format?: PersonsEmailsListFormat
    /**
     * Maximum number of assets to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of assets to skip, for pagination.
     * @minimum 0
     */
    offset?: number
}

export type PersonsEmailsListFormat = (typeof PersonsEmailsListFormat)[keyof typeof PersonsEmailsListFormat]

export const PersonsEmailsListFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsPropertiesTimelineCreateParams = {
    format?: PersonsPropertiesTimelineCreateFormat
}

export type PersonsPropertiesTimelineCreateFormat =
    (typeof PersonsPropertiesTimelineCreateFormat)[keyof typeof PersonsPropertiesTimelineCreateFormat]

export const PersonsPropertiesTimelineCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type PersonsPushNotificationsListParams = {
    /**
     * Start of the time range, matched on sent time. Relative ('-30d', '-24h') or ISO 8601. Defaults to -30d (the retention window) — bounds the ClickHouse partition scan.
     * @minLength 1
     */
    after?: string
    /**
     * End of the time range, matched on sent time. Same format as 'after'. Defaults to now.
     * @minLength 1
     */
    before?: string
    format?: PersonsPushNotificationsListFormat
    /**
     * Maximum number of assets to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of assets to skip, for pagination.
     * @minimum 0
     */
    offset?: number
}

export type PersonsPushNotificationsListFormat =
    (typeof PersonsPushNotificationsListFormat)[keyof typeof PersonsPushNotificationsListFormat]

export const PersonsPushNotificationsListFormat = {
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
