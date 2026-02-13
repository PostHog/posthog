export namespace Schemas {
  // <Schemas>
  export type AIEventType =
    | "$ai_generation"
    | "$ai_embedding"
    | "$ai_span"
    | "$ai_trace"
    | "$ai_metric"
    | "$ai_feedback"
    | "$ai_evaluation"
    | "$ai_trace_summary"
    | "$ai_generation_summary"
    | "$ai_trace_clusters"
    | "$ai_generation_clusters";
  export type UrlMatchingEnum = "contains" | "regex" | "exact";
  export type NullEnum = null;
  export type ActionStepJSON = {
    event?: (string | null) | undefined;
    properties?: (Array<Record<string, unknown>> | null) | undefined;
    selector?: (string | null) | undefined;
    selector_regex: string | null;
    tag_name?: (string | null) | undefined;
    text?: (string | null) | undefined;
    text_matching?: ((UrlMatchingEnum | NullEnum) | null) | undefined;
    href?: (string | null) | undefined;
    href_matching?: ((UrlMatchingEnum | NullEnum) | null) | undefined;
    url?: (string | null) | undefined;
    url_matching?: ((UrlMatchingEnum | NullEnum) | null) | undefined;
  };
  export type RoleAtOrganizationEnum =
    | "engineering"
    | "data"
    | "product"
    | "founder"
    | "leadership"
    | "marketing"
    | "sales"
    | "other";
  export type BlankEnum = "";
  export type UserBasic = {
    id: number;
    uuid: string;
    distinct_id?: (string | null) | undefined;
    first_name?: string | undefined;
    last_name?: string | undefined;
    email: string;
    is_email_verified?: (boolean | null) | undefined;
    hedgehog_config: Record<string, unknown> | null;
    role_at_organization?: ((RoleAtOrganizationEnum | BlankEnum | NullEnum) | null) | undefined;
  };
  export type Action = {
    id: number;
    name?: (string | null) | undefined;
    description?: string | undefined;
    tags?: Array<unknown> | undefined;
    post_to_slack?: boolean | undefined;
    slack_message_format?: string | undefined;
    steps?: Array<ActionStepJSON> | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    deleted?: boolean | undefined;
    is_calculating: boolean;
    last_calculated_at?: string | undefined;
    team_id: number;
    is_action: boolean;
    bytecode_error: string | null;
    pinned_at?: (string | null) | undefined;
    creation_context: string;
    _create_in_folder?: string | undefined;
    user_access_level: string | null;
  };
  export type ActionConversionGoal = { actionId: number };
  export type PropertyOperator =
    | "exact"
    | "is_not"
    | "icontains"
    | "not_icontains"
    | "regex"
    | "not_regex"
    | "gt"
    | "gte"
    | "lt"
    | "lte"
    | "is_set"
    | "is_not_set"
    | "is_date_exact"
    | "is_date_before"
    | "is_date_after"
    | "between"
    | "not_between"
    | "min"
    | "max"
    | "in"
    | "not_in"
    | "is_cleaned_path_exact"
    | "flag_evaluates_to"
    | "semver_eq"
    | "semver_neq"
    | "semver_gt"
    | "semver_gte"
    | "semver_lt"
    | "semver_lte"
    | "semver_tilde"
    | "semver_caret"
    | "semver_wildcard";
  export type EventPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator?: PropertyOperator | undefined;
    type?: "event" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type PersonPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "person" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type Key = "tag_name" | "text" | "href" | "selector";
  export type ElementPropertyFilter = {
    key: Key;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "element" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type EventMetadataPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "event_metadata" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type SessionPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "session" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type CohortPropertyFilter = {
    cohort_name?: (string | null) | undefined;
    key?: "id" | undefined;
    label?: (string | null) | undefined;
    operator?: PropertyOperator | undefined;
    type?: "cohort" | undefined;
    value: number;
  };
  export type DurationType = "duration" | "active_seconds" | "inactive_seconds";
  export type RecordingPropertyFilter = {
    key: DurationType | string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "recording" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type LogEntryPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "log_entry" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type GroupPropertyFilter = {
    group_type_index?: (number | null) | undefined;
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "group" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type FeaturePropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "feature" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type FlagPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator?: "flag_evaluates_to" | undefined;
    type?: "flag" | undefined;
    value: boolean | string;
  };
  export type HogQLPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    type?: "hogql" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type EmptyPropertyFilter = Partial<{ type: "empty" }>;
  export type DataWarehousePropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "data_warehouse" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type DataWarehousePersonPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "data_warehouse_person_property" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type ErrorTrackingIssueFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "error_tracking_issue" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type LogPropertyFilterType = "log" | "log_attribute" | "log_resource_attribute";
  export type LogPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type: LogPropertyFilterType;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type RevenueAnalyticsPropertyFilter = {
    key: string;
    label?: (string | null) | undefined;
    operator: PropertyOperator;
    type?: "revenue_analytics" | undefined;
    value?: ((Array<string | number | boolean> | string | number | boolean) | null) | undefined;
  };
  export type BaseMathType =
    | "total"
    | "dau"
    | "weekly_active"
    | "monthly_active"
    | "unique_session"
    | "first_time_for_user"
    | "first_matching_event_for_user";
  export type FunnelMathType = "total" | "first_time_for_user" | "first_time_for_user_with_filters";
  export type PropertyMathType = "avg" | "sum" | "min" | "max" | "median" | "p75" | "p90" | "p95" | "p99";
  export type CountPerActorMathType =
    | "avg_count_per_actor"
    | "min_count_per_actor"
    | "max_count_per_actor"
    | "median_count_per_actor"
    | "p75_count_per_actor"
    | "p90_count_per_actor"
    | "p95_count_per_actor"
    | "p99_count_per_actor";
  export type ExperimentMetricMathType =
    | "total"
    | "sum"
    | "unique_session"
    | "min"
    | "max"
    | "avg"
    | "dau"
    | "unique_group"
    | "hogql";
  export type CalendarHeatmapMathType = "total" | "dau";
  export type MathGroupTypeIndex = 0 | 1 | 2 | 3 | 4;
  export type CurrencyCode =
    | "AED"
    | "AFN"
    | "ALL"
    | "AMD"
    | "ANG"
    | "AOA"
    | "ARS"
    | "AUD"
    | "AWG"
    | "AZN"
    | "BAM"
    | "BBD"
    | "BDT"
    | "BGN"
    | "BHD"
    | "BIF"
    | "BMD"
    | "BND"
    | "BOB"
    | "BRL"
    | "BSD"
    | "BTC"
    | "BTN"
    | "BWP"
    | "BYN"
    | "BZD"
    | "CAD"
    | "CDF"
    | "CHF"
    | "CLP"
    | "CNY"
    | "COP"
    | "CRC"
    | "CVE"
    | "CZK"
    | "DJF"
    | "DKK"
    | "DOP"
    | "DZD"
    | "EGP"
    | "ERN"
    | "ETB"
    | "EUR"
    | "FJD"
    | "GBP"
    | "GEL"
    | "GHS"
    | "GIP"
    | "GMD"
    | "GNF"
    | "GTQ"
    | "GYD"
    | "HKD"
    | "HNL"
    | "HRK"
    | "HTG"
    | "HUF"
    | "IDR"
    | "ILS"
    | "INR"
    | "IQD"
    | "IRR"
    | "ISK"
    | "JMD"
    | "JOD"
    | "JPY"
    | "KES"
    | "KGS"
    | "KHR"
    | "KMF"
    | "KRW"
    | "KWD"
    | "KYD"
    | "KZT"
    | "LAK"
    | "LBP"
    | "LKR"
    | "LRD"
    | "LTL"
    | "LVL"
    | "LSL"
    | "LYD"
    | "MAD"
    | "MDL"
    | "MGA"
    | "MKD"
    | "MMK"
    | "MNT"
    | "MOP"
    | "MRU"
    | "MTL"
    | "MUR"
    | "MVR"
    | "MWK"
    | "MXN"
    | "MYR"
    | "MZN"
    | "NAD"
    | "NGN"
    | "NIO"
    | "NOK"
    | "NPR"
    | "NZD"
    | "OMR"
    | "PAB"
    | "PEN"
    | "PGK"
    | "PHP"
    | "PKR"
    | "PLN"
    | "PYG"
    | "QAR"
    | "RON"
    | "RSD"
    | "RUB"
    | "RWF"
    | "SAR"
    | "SBD"
    | "SCR"
    | "SDG"
    | "SEK"
    | "SGD"
    | "SRD"
    | "SSP"
    | "STN"
    | "SYP"
    | "SZL"
    | "THB"
    | "TJS"
    | "TMT"
    | "TND"
    | "TOP"
    | "TRY"
    | "TTD"
    | "TWD"
    | "TZS"
    | "UAH"
    | "UGX"
    | "USD"
    | "UYU"
    | "UZS"
    | "VES"
    | "VND"
    | "VUV"
    | "WST"
    | "XAF"
    | "XCD"
    | "XOF"
    | "XPF"
    | "YER"
    | "ZAR"
    | "ZMW";
  export type RevenueCurrencyPropertyConfig = Partial<{ property: string | null; static: CurrencyCode }>;
  export type ActionsNode = {
    custom_name?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    id: number;
    kind?: "ActionsNode" | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type ActionsPie = Partial<{ disableHoverOffset: boolean | null; hideAggregation: boolean | null }>;
  export type ActiveBreakpoint = {
    id: string;
    repository?: (string | null) | undefined;
    filename: string;
    line_number: number;
    enabled: boolean;
    condition?: (string | null) | undefined;
  };
  export type ActiveBreakpointsResponse = { breakpoints: Array<ActiveBreakpoint> };
  export type ActivityLog = {
    id: string;
    user: UserBasic;
    unread: boolean;
    organization_id?: (string | null) | undefined;
    was_impersonated?: (boolean | null) | undefined;
    is_system?: (boolean | null) | undefined;
    activity: string;
    item_id?: (string | null) | undefined;
    scope: string;
    detail?: (unknown | null) | undefined;
    created_at?: string | undefined;
  };
  export type Change = { type: string; action: string; field: string; before: unknown; after: unknown };
  export type Merge = { type: string; source: unknown; target: unknown };
  export type Trigger = { job_type: string; job_id: string; payload: unknown };
  export type Detail = {
    id: string;
    changes?: Array<Change> | undefined;
    merge?: Merge | undefined;
    trigger?: Trigger | undefined;
    name: string;
    short_id: string;
    type: string;
  };
  export type ActivityLogEntry = {
    user: string;
    activity: string;
    scope: string;
    item_id: string;
    detail?: Detail | undefined;
    created_at: string;
  };
  export type ActivityLogPaginatedResponse = {
    results: Array<ActivityLogEntry>;
    next: string | null;
    previous: string | null;
    total_count: number;
  };
  export type BounceRatePageViewMode = "count_pageviews" | "uniq_urls" | "uniq_page_screen_autocaptures";
  export type FilterLogicalOperator = "AND" | "OR";
  export type CustomChannelField =
    | "utm_source"
    | "utm_medium"
    | "utm_campaign"
    | "referring_domain"
    | "url"
    | "pathname"
    | "hostname";
  export type CustomChannelOperator =
    | "exact"
    | "is_not"
    | "is_set"
    | "is_not_set"
    | "icontains"
    | "not_icontains"
    | "regex"
    | "not_regex";
  export type CustomChannelCondition = {
    id: string;
    key: CustomChannelField;
    op: CustomChannelOperator;
    value?: ((string | Array<string>) | null) | undefined;
  };
  export type CustomChannelRule = {
    channel_type: string;
    combiner: FilterLogicalOperator;
    id: string;
    items: Array<CustomChannelCondition>;
  };
  export type DataWarehouseEventsModifier = {
    distinct_id_field: string;
    id_field: string;
    table_name: string;
    timestamp_field: string;
  };
  export type InCohortVia = "auto" | "leftjoin" | "subquery" | "leftjoin_conjoined";
  export type MaterializationMode = "auto" | "legacy_null_as_string" | "legacy_null_as_null" | "disabled";
  export type MaterializedColumnsOptimizationMode = "disabled" | "optimized";
  export type PersonsArgMaxVersion = "auto" | "v1" | "v2";
  export type PersonsJoinMode = "inner" | "left";
  export type PersonsOnEventsMode =
    | "disabled"
    | "person_id_no_override_properties_on_events"
    | "person_id_override_properties_on_events"
    | "person_id_override_properties_joined";
  export type PropertyGroupsMode = "enabled" | "disabled" | "optimized";
  export type SessionTableVersion = "auto" | "v1" | "v2" | "v3";
  export type SessionsV2JoinMode = "string" | "uuid";
  export type HogQLQueryModifiers = Partial<{
    bounceRateDurationSeconds: number | null;
    bounceRatePageViewMode: BounceRatePageViewMode;
    convertToProjectTimezone: boolean | null;
    customChannelTypeRules: Array<CustomChannelRule> | null;
    dataWarehouseEventsModifiers: Array<DataWarehouseEventsModifier> | null;
    debug: boolean | null;
    forceClickhouseDataSkippingIndexes: Array<string> | null;
    formatCsvAllowDoubleQuotes: boolean | null;
    inCohortVia: InCohortVia;
    materializationMode: MaterializationMode;
    materializedColumnsOptimizationMode: MaterializedColumnsOptimizationMode;
    optimizeJoinedFilters: boolean | null;
    optimizeProjections: boolean | null;
    personsArgMaxVersion: PersonsArgMaxVersion;
    personsJoinMode: PersonsJoinMode;
    personsOnEventsMode: PersonsOnEventsMode;
    propertyGroupsMode: PropertyGroupsMode;
    s3TableUseInvalidColumns: boolean | null;
    sessionTableVersion: SessionTableVersion;
    sessionsV2JoinMode: SessionsV2JoinMode;
    timings: boolean | null;
    useMaterializedViews: boolean | null;
    usePreaggregatedIntermediateResults: boolean | null;
    usePreaggregatedTableTransforms: boolean | null;
    useWebAnalyticsPreAggregatedTables: boolean | null;
  }>;
  export type ClickhouseQueryProgress = {
    active_cpu_time: number;
    bytes_read: number;
    estimated_rows_total: number;
    rows_read: number;
    time_elapsed: number;
  };
  export type QueryStatus = {
    complete?: (boolean | null) | undefined;
    dashboard_id?: (number | null) | undefined;
    end_time?: (string | null) | undefined;
    error?: (boolean | null) | undefined;
    error_message?: (string | null) | undefined;
    expiration_time?: (string | null) | undefined;
    id: string;
    insight_id?: (number | null) | undefined;
    labels?: (Array<string> | null) | undefined;
    pickup_time?: (string | null) | undefined;
    query_async?: true | undefined;
    query_progress?: ClickhouseQueryProgress | undefined;
    results?: (unknown | null) | undefined;
    start_time?: (string | null) | undefined;
    task_id?: (string | null) | undefined;
    team_id: number;
  };
  export type ResolvedDateRangeResponse = { date_from: string; date_to: string };
  export type ActorsPropertyTaxonomyResponse = {
    sample_count: number;
    sample_values: Array<string | number | boolean | number>;
  };
  export type QueryTiming = { k: string; t: number };
  export type ActorsPropertyTaxonomyQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: ActorsPropertyTaxonomyResponse | Array<ActorsPropertyTaxonomyResponse>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryLogTags = Partial<{ name: string | null; productKey: string | null; scene: string | null }>;
  export type ActorsPropertyTaxonomyQuery = {
    groupTypeIndex?: (number | null) | undefined;
    kind?: "ActorsPropertyTaxonomyQuery" | undefined;
    maxPropertyValues?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties: Array<string>;
    response?: ActorsPropertyTaxonomyQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type PropertyGroupFilterValue = {
    type: FilterLogicalOperator;
    values: Array<
      | PropertyGroupFilterValue
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    >;
  };
  export type ActorsQueryResponse = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit: number;
    missing_actors_count?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<string> | null) | undefined;
  };
  export type Compare = "current" | "previous";
  export type BreakdownType =
    | "cohort"
    | "person"
    | "event"
    | "event_metadata"
    | "group"
    | "session"
    | "hogql"
    | "data_warehouse"
    | "data_warehouse_person_property"
    | "revenue_analytics";
  export type MultipleBreakdownType =
    | "cohort"
    | "person"
    | "event"
    | "event_metadata"
    | "group"
    | "session"
    | "hogql"
    | "revenue_analytics";
  export type Breakdown = {
    group_type_index?: (number | null) | undefined;
    histogram_bin_count?: (number | null) | undefined;
    normalize_url?: (boolean | null) | undefined;
    property: string | number;
    type?: MultipleBreakdownType | undefined;
  };
  export type BreakdownFilter = Partial<{
    breakdown: (string | Array<string | number> | number) | null;
    breakdown_group_type_index: number | null;
    breakdown_hide_other_aggregation: boolean | null;
    breakdown_histogram_bin_count: number | null;
    breakdown_limit: number | null;
    breakdown_normalize_url: boolean | null;
    breakdown_path_cleaning: boolean | null;
    breakdown_type: BreakdownType;
    breakdowns: Array<Breakdown> | null;
  }>;
  export type CompareFilter = Partial<{ compare: boolean | null; compare_to: string | null }>;
  export type CustomEventConversionGoal = { customEventName: string };
  export type DateRange = Partial<{ date_from: string | null; date_to: string | null; explicitDate: boolean | null }>;
  export type IntervalType = "second" | "minute" | "hour" | "day" | "week" | "month";
  export type PropertyGroupFilter = { type: FilterLogicalOperator; values: Array<PropertyGroupFilterValue> };
  export type TrendsQueryResponse = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type EventsNode = Partial<{
    custom_name: string | null;
    event: string | null;
    fixedProperties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    kind: "EventsNode";
    limit: number | null;
    math:
      | (
          | BaseMathType
          | FunnelMathType
          | PropertyMathType
          | CountPerActorMathType
          | ExperimentMetricMathType
          | CalendarHeatmapMathType
          | "unique_group"
          | "hogql"
        )
      | null;
    math_group_type_index: MathGroupTypeIndex;
    math_hogql: string | null;
    math_multiplier: number | null;
    math_property: string | null;
    math_property_revenue_currency: RevenueCurrencyPropertyConfig;
    math_property_type: string | null;
    name: string | null;
    optionalInFunnel: boolean | null;
    orderBy: Array<string> | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    response: Record<string, unknown> | null;
    version: number | null;
  }>;
  export type DataWarehouseNode = {
    custom_name?: (string | null) | undefined;
    distinct_id_field: string;
    dw_source_type?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    id: string;
    id_field: string;
    kind?: "DataWarehouseNode" | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    table_name: string;
    timestamp_field: string;
    version?: (number | null) | undefined;
  };
  export type GroupNode = {
    custom_name?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    kind?: "GroupNode" | undefined;
    limit?: (number | null) | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    nodes: Array<EventsNode | ActionsNode | DataWarehouseNode>;
    operator: FilterLogicalOperator;
    optionalInFunnel?: (boolean | null) | undefined;
    orderBy?: (Array<string> | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type AggregationAxisFormat =
    | "numeric"
    | "duration"
    | "duration_ms"
    | "percentage"
    | "percentage_scaled"
    | "currency";
  export type DetailedResultsAggregationType = "total" | "average" | "median";
  export type ChartDisplayType =
    | "ActionsLineGraph"
    | "ActionsBar"
    | "ActionsUnstackedBar"
    | "ActionsStackedBar"
    | "ActionsAreaGraph"
    | "ActionsLineGraphCumulative"
    | "BoldNumber"
    | "ActionsPie"
    | "ActionsBarValue"
    | "ActionsTable"
    | "WorldMap"
    | "CalendarHeatmap"
    | "TwoDimensionalHeatmap";
  export type TrendsFormulaNode = { custom_name?: (string | null) | undefined; formula: string };
  export type Position = "start" | "end";
  export type GoalLine = {
    borderColor?: (string | null) | undefined;
    displayIfCrossed?: (boolean | null) | undefined;
    displayLabel?: (boolean | null) | undefined;
    label: string;
    position?: Position | undefined;
    value: number;
  };
  export type ResultCustomizationBy = "value" | "position";
  export type DataColorToken =
    | "preset-1"
    | "preset-2"
    | "preset-3"
    | "preset-4"
    | "preset-5"
    | "preset-6"
    | "preset-7"
    | "preset-8"
    | "preset-9"
    | "preset-10"
    | "preset-11"
    | "preset-12"
    | "preset-13"
    | "preset-14"
    | "preset-15";
  export type ResultCustomizationByValue = Partial<{
    assignmentBy: "value";
    color: DataColorToken;
    hidden: boolean | null;
  }>;
  export type ResultCustomizationByPosition = Partial<{
    assignmentBy: "position";
    color: DataColorToken;
    hidden: boolean | null;
  }>;
  export type YAxisScaleType = "log10" | "linear";
  export type TrendsFilter = Partial<{
    aggregationAxisFormat: AggregationAxisFormat;
    aggregationAxisPostfix: string | null;
    aggregationAxisPrefix: string | null;
    breakdown_histogram_bin_count: number | null;
    confidenceLevel: number | null;
    decimalPlaces: number | null;
    detailedResultsAggregationType: DetailedResultsAggregationType;
    display: ChartDisplayType;
    formula: string | null;
    formulaNodes: Array<TrendsFormulaNode> | null;
    formulas: Array<string> | null;
    goalLines: Array<GoalLine> | null;
    hiddenLegendIndexes: Array<number> | null;
    minDecimalPlaces: number | null;
    movingAverageIntervals: number | null;
    resultCustomizationBy: ResultCustomizationBy;
    resultCustomizations: (Record<string, unknown> | Record<string, unknown>) | null;
    showAlertThresholdLines: boolean | null;
    showConfidenceIntervals: boolean | null;
    showLabelsOnSeries: boolean | null;
    showLegend: boolean | null;
    showMovingAverage: boolean | null;
    showMultipleYAxes: boolean | null;
    showPercentStackView: boolean | null;
    showTrendLines: boolean | null;
    showValuesOnSeries: boolean | null;
    smoothingIntervals: number | null;
    yAxisScaleType: YAxisScaleType;
  }>;
  export type TrendsQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    breakdownFilter?: BreakdownFilter | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "TrendsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (
          | (
              | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                >
              | PropertyGroupFilter
            )
          | null
        )
      | undefined;
    response?: TrendsQueryResponse | undefined;
    samplingFactor?: (number | null) | undefined;
    series: Array<GroupNode | EventsNode | ActionsNode | DataWarehouseNode>;
    tags?: QueryLogTags | undefined;
    trendsFilter?: TrendsFilter | undefined;
    version?: (number | null) | undefined;
  };
  export type BreakdownAttributionType = "first_touch" | "last_touch" | "all_events" | "step";
  export type FunnelExclusionEventsNode = {
    custom_name?: (string | null) | undefined;
    event?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    funnelFromStep: number;
    funnelToStep: number;
    kind?: "EventsNode" | undefined;
    limit?: (number | null) | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    orderBy?: (Array<string> | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type FunnelExclusionActionsNode = {
    custom_name?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    funnelFromStep: number;
    funnelToStep: number;
    id: number;
    kind?: "ActionsNode" | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type StepOrderValue = "strict" | "unordered" | "ordered";
  export type FunnelStepReference = "total" | "previous";
  export type FunnelVizType = "steps" | "time_to_convert" | "trends";
  export type FunnelConversionWindowTimeUnit = "second" | "minute" | "hour" | "day" | "week" | "month";
  export type FunnelLayout = "horizontal" | "vertical";
  export type FunnelsFilter = Partial<{
    binCount: number | null;
    breakdownAttributionType: BreakdownAttributionType;
    breakdownAttributionValue: number | null;
    breakdownSorting: string | null;
    exclusions: Array<FunnelExclusionEventsNode | FunnelExclusionActionsNode> | null;
    funnelAggregateByHogQL: string | null;
    funnelFromStep: number | null;
    funnelOrderType: StepOrderValue;
    funnelStepReference: FunnelStepReference;
    funnelToStep: number | null;
    funnelVizType: FunnelVizType;
    funnelWindowInterval: number | null;
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit;
    goalLines: Array<GoalLine> | null;
    hiddenLegendBreakdowns: Array<string> | null;
    layout: FunnelLayout;
    resultCustomizations: Record<string, unknown> | null;
    showValuesOnSeries: boolean | null;
    useUdf: boolean | null;
  }>;
  export type FunnelsQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type FunnelsQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    breakdownFilter?: BreakdownFilter | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    funnelsFilter?: FunnelsFilter | undefined;
    interval?: IntervalType | undefined;
    kind?: "FunnelsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (
          | (
              | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                >
              | PropertyGroupFilter
            )
          | null
        )
      | undefined;
    response?: FunnelsQueryResponse | undefined;
    samplingFactor?: (number | null) | undefined;
    series: Array<EventsNode | ActionsNode | DataWarehouseNode>;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type RetentionValue = { count: number; label?: (string | null) | undefined };
  export type RetentionResult = {
    breakdown_value?: ((string | number) | null) | undefined;
    date: string;
    label: string;
    values: Array<RetentionValue>;
  };
  export type RetentionQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RetentionResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type AggregationType = "count" | "sum" | "avg";
  export type RetentionDashboardDisplayType = "table_only" | "graph_only" | "all";
  export type MeanRetentionCalculation = "simple" | "weighted" | "none";
  export type RetentionPeriod = "Hour" | "Day" | "Week" | "Month";
  export type RetentionReference = "total" | "previous";
  export type RetentionType = "retention_recurring" | "retention_first_time" | "retention_first_ever_occurrence";
  export type RetentionEntityKind = "ActionsNode" | "EventsNode";
  export type EntityType = "actions" | "events" | "data_warehouse" | "new_entity" | "groups";
  export type RetentionEntity = Partial<{
    custom_name: string | null;
    id: (string | number) | null;
    kind: RetentionEntityKind;
    name: string | null;
    order: number | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    type: EntityType;
    uuid: string | null;
  }>;
  export type TimeWindowMode = "strict_calendar_dates" | "24_hour_windows";
  export type RetentionFilter = Partial<{
    aggregationProperty: string | null;
    aggregationType: AggregationType;
    cumulative: boolean | null;
    dashboardDisplay: RetentionDashboardDisplayType;
    display: ChartDisplayType;
    goalLines: Array<GoalLine> | null;
    meanRetentionCalculation: MeanRetentionCalculation;
    minimumOccurrences: number | null;
    period: RetentionPeriod;
    retentionCustomBrackets: Array<number> | null;
    retentionReference: RetentionReference;
    retentionType: RetentionType;
    returningEntity: RetentionEntity;
    selectedInterval: number | null;
    showTrendLines: boolean | null;
    targetEntity: RetentionEntity;
    timeWindowMode: TimeWindowMode;
    totalIntervals: number | null;
  }>;
  export type RetentionQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    breakdownFilter?: BreakdownFilter | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    kind?: "RetentionQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (
          | (
              | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                >
              | PropertyGroupFilter
            )
          | null
        )
      | undefined;
    response?: RetentionQueryResponse | undefined;
    retentionFilter: RetentionFilter;
    samplingFactor?: (number | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type FunnelPathType = "funnel_path_before_step" | "funnel_path_between_steps" | "funnel_path_after_step";
  export type FunnelPathsFilter = {
    funnelPathType?: FunnelPathType | undefined;
    funnelSource: FunnelsQuery;
    funnelStep?: (number | null) | undefined;
  };
  export type PathType = "$pageview" | "$screen" | "custom_event" | "hogql";
  export type PathCleaningFilter = Partial<{ alias: string | null; order: number | null; regex: string | null }>;
  export type PathsFilter = Partial<{
    edgeLimit: number | null;
    endPoint: string | null;
    excludeEvents: Array<string> | null;
    includeEventTypes: Array<PathType> | null;
    localPathCleaningFilters: Array<PathCleaningFilter> | null;
    maxEdgeWeight: number | null;
    minEdgeWeight: number | null;
    pathDropoffKey: string | null;
    pathEndKey: string | null;
    pathGroupings: Array<string> | null;
    pathReplacements: boolean | null;
    pathStartKey: string | null;
    pathsHogQLExpression: string | null;
    showFullUrls: boolean | null;
    startPoint: string | null;
    stepLimit: number | null;
  }>;
  export type PathsLink = { average_conversion_time: number; source: string; target: string; value: number };
  export type PathsQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<PathsLink>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type PathsQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    funnelPathsFilter?: FunnelPathsFilter | undefined;
    kind?: "PathsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    pathsFilter: PathsFilter;
    properties?:
      | (
          | (
              | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                >
              | PropertyGroupFilter
            )
          | null
        )
      | undefined;
    response?: PathsQueryResponse | undefined;
    samplingFactor?: (number | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type StickinessQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type StickinessComputationMode = "non_cumulative" | "cumulative";
  export type StickinessOperator = "gte" | "lte" | "exact";
  export type StickinessCriteria = { operator: StickinessOperator; value: number };
  export type StickinessFilter = Partial<{
    computedAs: StickinessComputationMode;
    display: ChartDisplayType;
    hiddenLegendIndexes: Array<number> | null;
    resultCustomizationBy: ResultCustomizationBy;
    resultCustomizations: (Record<string, unknown> | Record<string, unknown>) | null;
    showLegend: boolean | null;
    showMultipleYAxes: boolean | null;
    showValuesOnSeries: boolean | null;
    stickinessCriteria: StickinessCriteria;
  }>;
  export type StickinessQuery = {
    compareFilter?: CompareFilter | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    intervalCount?: (number | null) | undefined;
    kind?: "StickinessQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (
          | (
              | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                >
              | PropertyGroupFilter
            )
          | null
        )
      | undefined;
    response?: StickinessQueryResponse | undefined;
    samplingFactor?: (number | null) | undefined;
    series: Array<EventsNode | ActionsNode | DataWarehouseNode>;
    stickinessFilter?: StickinessFilter | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type LifecycleToggle = "new" | "resurrecting" | "returning" | "dormant";
  export type LifecycleFilter = Partial<{
    showLegend: boolean | null;
    showValuesOnSeries: boolean | null;
    stacked: boolean | null;
    toggledLifecycles: Array<LifecycleToggle> | null;
  }>;
  export type LifecycleQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type LifecycleQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "LifecycleQuery" | undefined;
    lifecycleFilter?: LifecycleFilter | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (
          | (
              | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                >
              | PropertyGroupFilter
            )
          | null
        )
      | undefined;
    response?: LifecycleQueryResponse | undefined;
    samplingFactor?: (number | null) | undefined;
    series: Array<EventsNode | ActionsNode | DataWarehouseNode>;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type WebStatsBreakdown =
    | "Page"
    | "InitialPage"
    | "ExitPage"
    | "ExitClick"
    | "PreviousPage"
    | "ScreenName"
    | "InitialChannelType"
    | "InitialReferringDomain"
    | "InitialUTMSource"
    | "InitialUTMCampaign"
    | "InitialUTMMedium"
    | "InitialUTMTerm"
    | "InitialUTMContent"
    | "InitialUTMSourceMediumCampaign"
    | "Browser"
    | "OS"
    | "Viewport"
    | "DeviceType"
    | "Country"
    | "Region"
    | "City"
    | "Timezone"
    | "Language"
    | "FrustrationMetrics";
  export type WebAnalyticsOrderByFields =
    | "Visitors"
    | "Views"
    | "AvgTimeOnPage"
    | "Clicks"
    | "BounceRate"
    | "AverageScrollPercentage"
    | "ScrollGt80Percentage"
    | "TotalConversions"
    | "UniqueConversions"
    | "ConversionRate"
    | "ConvertingUsers"
    | "RageClicks"
    | "DeadClicks"
    | "Errors";
  export type WebAnalyticsOrderByDirection = "ASC" | "DESC";
  export type SamplingRate = { denominator?: (number | null) | undefined; numerator: number };
  export type WebStatsTableQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type WebAnalyticsSampling = Partial<{ enabled: boolean | null; forceSamplingRate: SamplingRate }>;
  export type WebStatsTableQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    breakdownBy: WebStatsBreakdown;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeAvgTimeOnPage?: (boolean | null) | undefined;
    includeBounceRate?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    includeScrollDepth?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "WebStatsTableQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebStatsTableQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type WebAnalyticsItemKind = "unit" | "duration_s" | "percentage" | "currency";
  export type WebOverviewItem = {
    changeFromPreviousPct?: (number | null) | undefined;
    isIncreaseBad?: (boolean | null) | undefined;
    key: string;
    kind: WebAnalyticsItemKind;
    previous?: (number | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
    value?: (number | null) | undefined;
  };
  export type WebOverviewQueryResponse = {
    dateFrom?: (string | null) | undefined;
    dateTo?: (string | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebOverviewItem>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type WebOverviewQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "WebOverviewQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebOverviewQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type InsightActorsQuery = {
    breakdown?: ((string | Array<string> | number) | null) | undefined;
    compare?: Compare | undefined;
    day?: ((string | number) | null) | undefined;
    includeRecordings?: (boolean | null) | undefined;
    interval?: (number | null) | undefined;
    kind?: "InsightActorsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: ActorsQueryResponse | undefined;
    series?: (number | null) | undefined;
    source:
      | TrendsQuery
      | FunnelsQuery
      | RetentionQuery
      | PathsQuery
      | StickinessQuery
      | LifecycleQuery
      | WebStatsTableQuery
      | WebOverviewQuery;
    status?: (string | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type FunnelsActorsQuery = {
    funnelStep?: (number | null) | undefined;
    funnelStepBreakdown?: ((number | string | number | Array<number | string | number>) | null) | undefined;
    funnelTrendsDropOff?: (boolean | null) | undefined;
    funnelTrendsEntrancePeriodStart?: (string | null) | undefined;
    includeRecordings?: (boolean | null) | undefined;
    kind?: "FunnelsActorsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: ActorsQueryResponse | undefined;
    source: FunnelsQuery;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type FunnelCorrelationResultsType = "events" | "properties" | "event_with_properties";
  export type CorrelationType = "success" | "failure";
  export type EventDefinition = { elements: Array<unknown>; event: string; properties: Record<string, unknown> };
  export type EventOddsRatioSerialized = {
    correlation_type: CorrelationType;
    event: EventDefinition;
    failure_count: number;
    odds_ratio: number;
    success_count: number;
  };
  export type FunnelCorrelationResult = { events: Array<EventOddsRatioSerialized>; skewed: boolean };
  export type FunnelCorrelationResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: FunnelCorrelationResult;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type FunnelCorrelationQuery = {
    funnelCorrelationEventExcludePropertyNames?: (Array<string> | null) | undefined;
    funnelCorrelationEventNames?: (Array<string> | null) | undefined;
    funnelCorrelationExcludeEventNames?: (Array<string> | null) | undefined;
    funnelCorrelationExcludeNames?: (Array<string> | null) | undefined;
    funnelCorrelationNames?: (Array<string> | null) | undefined;
    funnelCorrelationType: FunnelCorrelationResultsType;
    kind?: "FunnelCorrelationQuery" | undefined;
    response?: FunnelCorrelationResponse | undefined;
    source: FunnelsActorsQuery;
    version?: (number | null) | undefined;
  };
  export type FunnelCorrelationActorsQuery = {
    funnelCorrelationPersonConverted?: (boolean | null) | undefined;
    funnelCorrelationPersonEntity?: ((EventsNode | ActionsNode | DataWarehouseNode) | null) | undefined;
    funnelCorrelationPropertyValues?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    includeRecordings?: (boolean | null) | undefined;
    kind?: "FunnelCorrelationActorsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: ActorsQueryResponse | undefined;
    source: FunnelCorrelationQuery;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type StickinessActorsQuery = {
    compare?: Compare | undefined;
    day?: ((string | number) | null) | undefined;
    includeRecordings?: (boolean | null) | undefined;
    kind?: "StickinessActorsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    operator?: StickinessOperator | undefined;
    response?: ActorsQueryResponse | undefined;
    series?: (number | null) | undefined;
    source: StickinessQuery;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type HogQLFilters = Partial<{
    dateRange: DateRange;
    filterTestAccounts: boolean | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
  }>;
  export type HogQLNotice = {
    end?: (number | null) | undefined;
    fix?: (string | null) | undefined;
    message: string;
    start?: (number | null) | undefined;
  };
  export type QueryIndexUsage = "undecisive" | "no" | "partial" | "yes";
  export type HogQLMetadataResponse = {
    ch_table_names?: (Array<string> | null) | undefined;
    errors: Array<HogQLNotice>;
    isUsingIndices?: QueryIndexUsage | undefined;
    isValid?: (boolean | null) | undefined;
    notices: Array<HogQLNotice>;
    query?: (string | null) | undefined;
    table_names?: (Array<string> | null) | undefined;
    warnings: Array<HogQLNotice>;
  };
  export type HogQLQueryResponse = {
    clickhouse?: (string | null) | undefined;
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    explain?: (Array<string> | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    metadata?: HogQLMetadataResponse | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query?: (string | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type HogQLVariable = {
    code_name: string;
    isNull?: (boolean | null) | undefined;
    value?: (unknown | null) | undefined;
    variableId: string;
  };
  export type HogQLQuery = {
    explain?: (boolean | null) | undefined;
    filters?: HogQLFilters | undefined;
    kind?: "HogQLQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    name?: (string | null) | undefined;
    query: string;
    response?: HogQLQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    values?: (Record<string, unknown> | null) | undefined;
    variables?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type ActorsQuery = Partial<{
    fixedProperties: Array<
      PersonPropertyFilter | CohortPropertyFilter | HogQLPropertyFilter | EmptyPropertyFilter
    > | null;
    kind: "ActorsQuery";
    limit: number | null;
    modifiers: HogQLQueryModifiers;
    offset: number | null;
    orderBy: Array<string> | null;
    properties:
      | (
          | Array<PersonPropertyFilter | CohortPropertyFilter | HogQLPropertyFilter | EmptyPropertyFilter>
          | PropertyGroupFilterValue
        )
      | null;
    response: ActorsQueryResponse;
    search: string | null;
    select: Array<string> | null;
    source:
      | (InsightActorsQuery | FunnelsActorsQuery | FunnelCorrelationActorsQuery | StickinessActorsQuery | HogQLQuery)
      | null;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type AgentModeEnum =
    | "product_analytics"
    | "sql"
    | "session_replay"
    | "error_tracking"
    | "plan"
    | "execution"
    | "survey"
    | "research"
    | "flags";
  export type InsightsThresholdBounds = Partial<{ lower: number | null; upper: number | null }>;
  export type InsightThresholdType = "absolute" | "percentage";
  export type InsightThreshold = { bounds?: InsightsThresholdBounds | undefined; type: InsightThresholdType };
  export type Threshold = {
    id: string;
    created_at: string;
    name?: string | undefined;
    configuration: InsightThreshold;
  };
  export type AlertConditionType = "absolute_value" | "relative_increase" | "relative_decrease";
  export type AlertCondition = { type: AlertConditionType };
  export type State66aEnum = "Firing" | "Not firing" | "Errored" | "Snoozed";
  export type AlertCheck = {
    id: string;
    created_at: string;
    calculated_value: number | null;
    state: State66aEnum & unknown;
    targets_notified: boolean;
  };
  export type TrendsAlertConfig = {
    check_ongoing_interval?: (boolean | null) | undefined;
    series_index: number;
    type?: "TrendsAlertConfig" | undefined;
  };
  export type CalculationIntervalEnum = "hourly" | "daily" | "weekly" | "monthly";
  export type Alert = {
    id: string;
    created_by: UserBasic & unknown;
    created_at: string;
    insight: number;
    name?: string | undefined;
    subscribed_users: Array<number>;
    threshold: Threshold;
    condition?: ((AlertCondition & (unknown | null)) | null) | undefined;
    state: State66aEnum & unknown;
    enabled?: boolean | undefined;
    last_notified_at: string | null;
    last_checked_at: string | null;
    next_check_at: string | null;
    checks: Array<AlertCheck>;
    config?: ((TrendsAlertConfig & (unknown | null)) | null) | undefined;
    calculation_interval?: ((CalculationIntervalEnum | BlankEnum | NullEnum) | null) | undefined;
    snoozed_until?: (string | null) | undefined;
    skip_weekend?: (boolean | null) | undefined;
  };
  export type CreationTypeEnum = "USR" | "GIT";
  export type AnnotationScopeEnum = "dashboard_item" | "dashboard" | "project" | "organization" | "recording";
  export type Annotation = {
    id: number;
    content?: (string | null) | undefined;
    date_marker?: (string | null) | undefined;
    creation_type?: CreationTypeEnum | undefined;
    dashboard_item?: (number | null) | undefined;
    dashboard_id?: (number | null) | undefined;
    dashboard_name: string | null;
    insight_short_id: string | null;
    insight_name: string | null;
    insight_derived_name: string | null;
    created_by: UserBasic & unknown;
    created_at: string | null;
    updated_at: string;
    deleted?: boolean | undefined;
    scope?: AnnotationScopeEnum | undefined;
  };
  export type TranscriptSegment = {
    timestamp?: (number | null) | undefined;
    speaker?: (string | null) | undefined;
    text: string;
    confidence?: (number | null) | undefined;
    is_final?: (boolean | null) | undefined;
  };
  export type AppendSegments = { segments: Array<TranscriptSegment> };
  export type AttributionModeEnum = "first_touch" | "last_touch";
  export type AutocompleteCompletionItemKind =
    | "Method"
    | "Function"
    | "Constructor"
    | "Field"
    | "Variable"
    | "Class"
    | "Struct"
    | "Interface"
    | "Module"
    | "Property"
    | "Event"
    | "Operator"
    | "Unit"
    | "Value"
    | "Constant"
    | "Enum"
    | "EnumMember"
    | "Keyword"
    | "Text"
    | "Color"
    | "File"
    | "Reference"
    | "Customcolor"
    | "Folder"
    | "TypeParameter"
    | "User"
    | "Issue"
    | "Snippet";
  export type AutocompleteCompletionItem = {
    detail?: (string | null) | undefined;
    documentation?: (string | null) | undefined;
    insertText: string;
    kind: AutocompleteCompletionItemKind;
    label: string;
  };
  export type BaseCurrencyEnum =
    | "AED"
    | "AFN"
    | "ALL"
    | "AMD"
    | "ANG"
    | "AOA"
    | "ARS"
    | "AUD"
    | "AWG"
    | "AZN"
    | "BAM"
    | "BBD"
    | "BDT"
    | "BGN"
    | "BHD"
    | "BIF"
    | "BMD"
    | "BND"
    | "BOB"
    | "BRL"
    | "BSD"
    | "BTC"
    | "BTN"
    | "BWP"
    | "BYN"
    | "BZD"
    | "CAD"
    | "CDF"
    | "CHF"
    | "CLP"
    | "CNY"
    | "COP"
    | "CRC"
    | "CVE"
    | "CZK"
    | "DJF"
    | "DKK"
    | "DOP"
    | "DZD"
    | "EGP"
    | "ERN"
    | "ETB"
    | "EUR"
    | "FJD"
    | "GBP"
    | "GEL"
    | "GHS"
    | "GIP"
    | "GMD"
    | "GNF"
    | "GTQ"
    | "GYD"
    | "HKD"
    | "HNL"
    | "HRK"
    | "HTG"
    | "HUF"
    | "IDR"
    | "ILS"
    | "INR"
    | "IQD"
    | "IRR"
    | "ISK"
    | "JMD"
    | "JOD"
    | "JPY"
    | "KES"
    | "KGS"
    | "KHR"
    | "KMF"
    | "KRW"
    | "KWD"
    | "KYD"
    | "KZT"
    | "LAK"
    | "LBP"
    | "LKR"
    | "LRD"
    | "LTL"
    | "LVL"
    | "LSL"
    | "LYD"
    | "MAD"
    | "MDL"
    | "MGA"
    | "MKD"
    | "MMK"
    | "MNT"
    | "MOP"
    | "MRU"
    | "MTL"
    | "MUR"
    | "MVR"
    | "MWK"
    | "MXN"
    | "MYR"
    | "MZN"
    | "NAD"
    | "NGN"
    | "NIO"
    | "NOK"
    | "NPR"
    | "NZD"
    | "OMR"
    | "PAB"
    | "PEN"
    | "PGK"
    | "PHP"
    | "PKR"
    | "PLN"
    | "PYG"
    | "QAR"
    | "RON"
    | "RSD"
    | "RUB"
    | "RWF"
    | "SAR"
    | "SBD"
    | "SCR"
    | "SDG"
    | "SEK"
    | "SGD"
    | "SRD"
    | "SSP"
    | "STN"
    | "SYP"
    | "SZL"
    | "THB"
    | "TJS"
    | "TMT"
    | "TND"
    | "TOP"
    | "TRY"
    | "TTD"
    | "TWD"
    | "TZS"
    | "UAH"
    | "UGX"
    | "USD"
    | "UYU"
    | "UZS"
    | "VES"
    | "VND"
    | "VUV"
    | "WST"
    | "XAF"
    | "XCD"
    | "XOF"
    | "XPF"
    | "YER"
    | "ZAR"
    | "ZMW";
  export type ModeEnum = "minimal" | "detailed";
  export type BatchCheckRequest = {
    trace_ids: Array<string>;
    mode?: (ModeEnum & unknown) | undefined;
    model?: (string | null) | undefined;
  };
  export type CachedSummary = { trace_id: string; title: string; cached?: boolean | undefined };
  export type BatchCheckResponse = { summaries: Array<CachedSummary> };
  export type ModelEnum = "events" | "persons" | "sessions";
  export type BatchExportDestinationTypeEnum =
    | "S3"
    | "Snowflake"
    | "Postgres"
    | "Redshift"
    | "BigQuery"
    | "Databricks"
    | "AzureBlob"
    | "Workflows"
    | "HTTP"
    | "NoOp";
  export type BatchExportDestination = {
    type: BatchExportDestinationTypeEnum;
    config?: unknown | undefined;
    integration?: (number | null) | undefined;
    integration_id?: (number | null) | undefined;
  };
  export type IntervalEnum = "hour" | "day" | "week" | "every 5 minutes";
  export type BatchExportRunStatusEnum =
    | "Cancelled"
    | "Completed"
    | "ContinuedAsNew"
    | "Failed"
    | "FailedRetryable"
    | "FailedBilling"
    | "Terminated"
    | "TimedOut"
    | "Running"
    | "Starting";
  export type BatchExportRun = {
    id: string;
    status: BatchExportRunStatusEnum;
    records_completed?: (number | null) | undefined;
    latest_error?: (string | null) | undefined;
    data_interval_start?: (string | null) | undefined;
    data_interval_end: string;
    cursor?: (string | null) | undefined;
    created_at: string;
    finished_at?: (string | null) | undefined;
    last_updated_at: string;
    records_total_count?: (number | null) | undefined;
    bytes_exported?: (number | null) | undefined;
    batch_export: string;
    backfill?: (string | null) | undefined;
  };
  export type TimezoneEnum =
    | "Africa/Abidjan"
    | "Africa/Accra"
    | "Africa/Addis_Ababa"
    | "Africa/Algiers"
    | "Africa/Asmara"
    | "Africa/Asmera"
    | "Africa/Bamako"
    | "Africa/Bangui"
    | "Africa/Banjul"
    | "Africa/Bissau"
    | "Africa/Blantyre"
    | "Africa/Brazzaville"
    | "Africa/Bujumbura"
    | "Africa/Cairo"
    | "Africa/Casablanca"
    | "Africa/Ceuta"
    | "Africa/Conakry"
    | "Africa/Dakar"
    | "Africa/Dar_es_Salaam"
    | "Africa/Djibouti"
    | "Africa/Douala"
    | "Africa/El_Aaiun"
    | "Africa/Freetown"
    | "Africa/Gaborone"
    | "Africa/Harare"
    | "Africa/Johannesburg"
    | "Africa/Juba"
    | "Africa/Kampala"
    | "Africa/Khartoum"
    | "Africa/Kigali"
    | "Africa/Kinshasa"
    | "Africa/Lagos"
    | "Africa/Libreville"
    | "Africa/Lome"
    | "Africa/Luanda"
    | "Africa/Lubumbashi"
    | "Africa/Lusaka"
    | "Africa/Malabo"
    | "Africa/Maputo"
    | "Africa/Maseru"
    | "Africa/Mbabane"
    | "Africa/Mogadishu"
    | "Africa/Monrovia"
    | "Africa/Nairobi"
    | "Africa/Ndjamena"
    | "Africa/Niamey"
    | "Africa/Nouakchott"
    | "Africa/Ouagadougou"
    | "Africa/Porto-Novo"
    | "Africa/Sao_Tome"
    | "Africa/Timbuktu"
    | "Africa/Tripoli"
    | "Africa/Tunis"
    | "Africa/Windhoek"
    | "America/Adak"
    | "America/Anchorage"
    | "America/Anguilla"
    | "America/Antigua"
    | "America/Araguaina"
    | "America/Argentina/Buenos_Aires"
    | "America/Argentina/Catamarca"
    | "America/Argentina/ComodRivadavia"
    | "America/Argentina/Cordoba"
    | "America/Argentina/Jujuy"
    | "America/Argentina/La_Rioja"
    | "America/Argentina/Mendoza"
    | "America/Argentina/Rio_Gallegos"
    | "America/Argentina/Salta"
    | "America/Argentina/San_Juan"
    | "America/Argentina/San_Luis"
    | "America/Argentina/Tucuman"
    | "America/Argentina/Ushuaia"
    | "America/Aruba"
    | "America/Asuncion"
    | "America/Atikokan"
    | "America/Atka"
    | "America/Bahia"
    | "America/Bahia_Banderas"
    | "America/Barbados"
    | "America/Belem"
    | "America/Belize"
    | "America/Blanc-Sablon"
    | "America/Boa_Vista"
    | "America/Bogota"
    | "America/Boise"
    | "America/Buenos_Aires"
    | "America/Cambridge_Bay"
    | "America/Campo_Grande"
    | "America/Cancun"
    | "America/Caracas"
    | "America/Catamarca"
    | "America/Cayenne"
    | "America/Cayman"
    | "America/Chicago"
    | "America/Chihuahua"
    | "America/Ciudad_Juarez"
    | "America/Coral_Harbour"
    | "America/Cordoba"
    | "America/Costa_Rica"
    | "America/Creston"
    | "America/Cuiaba"
    | "America/Curacao"
    | "America/Danmarkshavn"
    | "America/Dawson"
    | "America/Dawson_Creek"
    | "America/Denver"
    | "America/Detroit"
    | "America/Dominica"
    | "America/Edmonton"
    | "America/Eirunepe"
    | "America/El_Salvador"
    | "America/Ensenada"
    | "America/Fort_Nelson"
    | "America/Fort_Wayne"
    | "America/Fortaleza"
    | "America/Glace_Bay"
    | "America/Godthab"
    | "America/Goose_Bay"
    | "America/Grand_Turk"
    | "America/Grenada"
    | "America/Guadeloupe"
    | "America/Guatemala"
    | "America/Guayaquil"
    | "America/Guyana"
    | "America/Halifax"
    | "America/Havana"
    | "America/Hermosillo"
    | "America/Indiana/Indianapolis"
    | "America/Indiana/Knox"
    | "America/Indiana/Marengo"
    | "America/Indiana/Petersburg"
    | "America/Indiana/Tell_City"
    | "America/Indiana/Vevay"
    | "America/Indiana/Vincennes"
    | "America/Indiana/Winamac"
    | "America/Indianapolis"
    | "America/Inuvik"
    | "America/Iqaluit"
    | "America/Jamaica"
    | "America/Jujuy"
    | "America/Juneau"
    | "America/Kentucky/Louisville"
    | "America/Kentucky/Monticello"
    | "America/Knox_IN"
    | "America/Kralendijk"
    | "America/La_Paz"
    | "America/Lima"
    | "America/Los_Angeles"
    | "America/Louisville"
    | "America/Lower_Princes"
    | "America/Maceio"
    | "America/Managua"
    | "America/Manaus"
    | "America/Marigot"
    | "America/Martinique"
    | "America/Matamoros"
    | "America/Mazatlan"
    | "America/Mendoza"
    | "America/Menominee"
    | "America/Merida"
    | "America/Metlakatla"
    | "America/Mexico_City"
    | "America/Miquelon"
    | "America/Moncton"
    | "America/Monterrey"
    | "America/Montevideo"
    | "America/Montreal"
    | "America/Montserrat"
    | "America/Nassau"
    | "America/New_York"
    | "America/Nipigon"
    | "America/Nome"
    | "America/Noronha"
    | "America/North_Dakota/Beulah"
    | "America/North_Dakota/Center"
    | "America/North_Dakota/New_Salem"
    | "America/Nuuk"
    | "America/Ojinaga"
    | "America/Panama"
    | "America/Pangnirtung"
    | "America/Paramaribo"
    | "America/Phoenix"
    | "America/Port-au-Prince"
    | "America/Port_of_Spain"
    | "America/Porto_Acre"
    | "America/Porto_Velho"
    | "America/Puerto_Rico"
    | "America/Punta_Arenas"
    | "America/Rainy_River"
    | "America/Rankin_Inlet"
    | "America/Recife"
    | "America/Regina"
    | "America/Resolute"
    | "America/Rio_Branco"
    | "America/Rosario"
    | "America/Santa_Isabel"
    | "America/Santarem"
    | "America/Santiago"
    | "America/Santo_Domingo"
    | "America/Sao_Paulo"
    | "America/Scoresbysund"
    | "America/Shiprock"
    | "America/Sitka"
    | "America/St_Barthelemy"
    | "America/St_Johns"
    | "America/St_Kitts"
    | "America/St_Lucia"
    | "America/St_Thomas"
    | "America/St_Vincent"
    | "America/Swift_Current"
    | "America/Tegucigalpa"
    | "America/Thule"
    | "America/Thunder_Bay"
    | "America/Tijuana"
    | "America/Toronto"
    | "America/Tortola"
    | "America/Vancouver"
    | "America/Virgin"
    | "America/Whitehorse"
    | "America/Winnipeg"
    | "America/Yakutat"
    | "America/Yellowknife"
    | "Antarctica/Casey"
    | "Antarctica/Davis"
    | "Antarctica/DumontDUrville"
    | "Antarctica/Macquarie"
    | "Antarctica/Mawson"
    | "Antarctica/McMurdo"
    | "Antarctica/Palmer"
    | "Antarctica/Rothera"
    | "Antarctica/South_Pole"
    | "Antarctica/Syowa"
    | "Antarctica/Troll"
    | "Antarctica/Vostok"
    | "Arctic/Longyearbyen"
    | "Asia/Aden"
    | "Asia/Almaty"
    | "Asia/Amman"
    | "Asia/Anadyr"
    | "Asia/Aqtau"
    | "Asia/Aqtobe"
    | "Asia/Ashgabat"
    | "Asia/Ashkhabad"
    | "Asia/Atyrau"
    | "Asia/Baghdad"
    | "Asia/Bahrain"
    | "Asia/Baku"
    | "Asia/Bangkok"
    | "Asia/Barnaul"
    | "Asia/Beirut"
    | "Asia/Bishkek"
    | "Asia/Brunei"
    | "Asia/Calcutta"
    | "Asia/Chita"
    | "Asia/Choibalsan"
    | "Asia/Chongqing"
    | "Asia/Chungking"
    | "Asia/Colombo"
    | "Asia/Dacca"
    | "Asia/Damascus"
    | "Asia/Dhaka"
    | "Asia/Dili"
    | "Asia/Dubai"
    | "Asia/Dushanbe"
    | "Asia/Famagusta"
    | "Asia/Gaza"
    | "Asia/Harbin"
    | "Asia/Hebron"
    | "Asia/Ho_Chi_Minh"
    | "Asia/Hong_Kong"
    | "Asia/Hovd"
    | "Asia/Irkutsk"
    | "Asia/Istanbul"
    | "Asia/Jakarta"
    | "Asia/Jayapura"
    | "Asia/Jerusalem"
    | "Asia/Kabul"
    | "Asia/Kamchatka"
    | "Asia/Karachi"
    | "Asia/Kashgar"
    | "Asia/Kathmandu"
    | "Asia/Katmandu"
    | "Asia/Khandyga"
    | "Asia/Kolkata"
    | "Asia/Krasnoyarsk"
    | "Asia/Kuala_Lumpur"
    | "Asia/Kuching"
    | "Asia/Kuwait"
    | "Asia/Macao"
    | "Asia/Macau"
    | "Asia/Magadan"
    | "Asia/Makassar"
    | "Asia/Manila"
    | "Asia/Muscat"
    | "Asia/Nicosia"
    | "Asia/Novokuznetsk"
    | "Asia/Novosibirsk"
    | "Asia/Omsk"
    | "Asia/Oral"
    | "Asia/Phnom_Penh"
    | "Asia/Pontianak"
    | "Asia/Pyongyang"
    | "Asia/Qatar"
    | "Asia/Qostanay"
    | "Asia/Qyzylorda"
    | "Asia/Rangoon"
    | "Asia/Riyadh"
    | "Asia/Saigon"
    | "Asia/Sakhalin"
    | "Asia/Samarkand"
    | "Asia/Seoul"
    | "Asia/Shanghai"
    | "Asia/Singapore"
    | "Asia/Srednekolymsk"
    | "Asia/Taipei"
    | "Asia/Tashkent"
    | "Asia/Tbilisi"
    | "Asia/Tehran"
    | "Asia/Tel_Aviv"
    | "Asia/Thimbu"
    | "Asia/Thimphu"
    | "Asia/Tokyo"
    | "Asia/Tomsk"
    | "Asia/Ujung_Pandang"
    | "Asia/Ulaanbaatar"
    | "Asia/Ulan_Bator"
    | "Asia/Urumqi"
    | "Asia/Ust-Nera"
    | "Asia/Vientiane"
    | "Asia/Vladivostok"
    | "Asia/Yakutsk"
    | "Asia/Yangon"
    | "Asia/Yekaterinburg"
    | "Asia/Yerevan"
    | "Atlantic/Azores"
    | "Atlantic/Bermuda"
    | "Atlantic/Canary"
    | "Atlantic/Cape_Verde"
    | "Atlantic/Faeroe"
    | "Atlantic/Faroe"
    | "Atlantic/Jan_Mayen"
    | "Atlantic/Madeira"
    | "Atlantic/Reykjavik"
    | "Atlantic/South_Georgia"
    | "Atlantic/St_Helena"
    | "Atlantic/Stanley"
    | "Australia/ACT"
    | "Australia/Adelaide"
    | "Australia/Brisbane"
    | "Australia/Broken_Hill"
    | "Australia/Canberra"
    | "Australia/Currie"
    | "Australia/Darwin"
    | "Australia/Eucla"
    | "Australia/Hobart"
    | "Australia/LHI"
    | "Australia/Lindeman"
    | "Australia/Lord_Howe"
    | "Australia/Melbourne"
    | "Australia/NSW"
    | "Australia/North"
    | "Australia/Perth"
    | "Australia/Queensland"
    | "Australia/South"
    | "Australia/Sydney"
    | "Australia/Tasmania"
    | "Australia/Victoria"
    | "Australia/West"
    | "Australia/Yancowinna"
    | "Brazil/Acre"
    | "Brazil/DeNoronha"
    | "Brazil/East"
    | "Brazil/West"
    | "CET"
    | "CST6CDT"
    | "Canada/Atlantic"
    | "Canada/Central"
    | "Canada/Eastern"
    | "Canada/Mountain"
    | "Canada/Newfoundland"
    | "Canada/Pacific"
    | "Canada/Saskatchewan"
    | "Canada/Yukon"
    | "Chile/Continental"
    | "Chile/EasterIsland"
    | "Cuba"
    | "EET"
    | "EST"
    | "EST5EDT"
    | "Egypt"
    | "Eire"
    | "Etc/GMT"
    | "Etc/GMT+0"
    | "Etc/GMT+1"
    | "Etc/GMT+10"
    | "Etc/GMT+11"
    | "Etc/GMT+12"
    | "Etc/GMT+2"
    | "Etc/GMT+3"
    | "Etc/GMT+4"
    | "Etc/GMT+5"
    | "Etc/GMT+6"
    | "Etc/GMT+7"
    | "Etc/GMT+8"
    | "Etc/GMT+9"
    | "Etc/GMT-0"
    | "Etc/GMT-1"
    | "Etc/GMT-10"
    | "Etc/GMT-11"
    | "Etc/GMT-12"
    | "Etc/GMT-13"
    | "Etc/GMT-14"
    | "Etc/GMT-2"
    | "Etc/GMT-3"
    | "Etc/GMT-4"
    | "Etc/GMT-5"
    | "Etc/GMT-6"
    | "Etc/GMT-7"
    | "Etc/GMT-8"
    | "Etc/GMT-9"
    | "Etc/GMT0"
    | "Etc/Greenwich"
    | "Etc/UCT"
    | "Etc/UTC"
    | "Etc/Universal"
    | "Etc/Zulu"
    | "Europe/Amsterdam"
    | "Europe/Andorra"
    | "Europe/Astrakhan"
    | "Europe/Athens"
    | "Europe/Belfast"
    | "Europe/Belgrade"
    | "Europe/Berlin"
    | "Europe/Bratislava"
    | "Europe/Brussels"
    | "Europe/Bucharest"
    | "Europe/Budapest"
    | "Europe/Busingen"
    | "Europe/Chisinau"
    | "Europe/Copenhagen"
    | "Europe/Dublin"
    | "Europe/Gibraltar"
    | "Europe/Guernsey"
    | "Europe/Helsinki"
    | "Europe/Isle_of_Man"
    | "Europe/Istanbul"
    | "Europe/Jersey"
    | "Europe/Kaliningrad"
    | "Europe/Kiev"
    | "Europe/Kirov"
    | "Europe/Kyiv"
    | "Europe/Lisbon"
    | "Europe/Ljubljana"
    | "Europe/London"
    | "Europe/Luxembourg"
    | "Europe/Madrid"
    | "Europe/Malta"
    | "Europe/Mariehamn"
    | "Europe/Minsk"
    | "Europe/Monaco"
    | "Europe/Moscow"
    | "Europe/Nicosia"
    | "Europe/Oslo"
    | "Europe/Paris"
    | "Europe/Podgorica"
    | "Europe/Prague"
    | "Europe/Riga"
    | "Europe/Rome"
    | "Europe/Samara"
    | "Europe/San_Marino"
    | "Europe/Sarajevo"
    | "Europe/Saratov"
    | "Europe/Simferopol"
    | "Europe/Skopje"
    | "Europe/Sofia"
    | "Europe/Stockholm"
    | "Europe/Tallinn"
    | "Europe/Tirane"
    | "Europe/Tiraspol"
    | "Europe/Ulyanovsk"
    | "Europe/Uzhgorod"
    | "Europe/Vaduz"
    | "Europe/Vatican"
    | "Europe/Vienna"
    | "Europe/Vilnius"
    | "Europe/Volgograd"
    | "Europe/Warsaw"
    | "Europe/Zagreb"
    | "Europe/Zaporozhye"
    | "Europe/Zurich"
    | "GB"
    | "GB-Eire"
    | "GMT"
    | "GMT+0"
    | "GMT-0"
    | "GMT0"
    | "Greenwich"
    | "HST"
    | "Hongkong"
    | "Iceland"
    | "Indian/Antananarivo"
    | "Indian/Chagos"
    | "Indian/Christmas"
    | "Indian/Cocos"
    | "Indian/Comoro"
    | "Indian/Kerguelen"
    | "Indian/Mahe"
    | "Indian/Maldives"
    | "Indian/Mauritius"
    | "Indian/Mayotte"
    | "Indian/Reunion"
    | "Iran"
    | "Israel"
    | "Jamaica"
    | "Japan"
    | "Kwajalein"
    | "Libya"
    | "MET"
    | "MST"
    | "MST7MDT"
    | "Mexico/BajaNorte"
    | "Mexico/BajaSur"
    | "Mexico/General"
    | "NZ"
    | "NZ-CHAT"
    | "Navajo"
    | "PRC"
    | "PST8PDT"
    | "Pacific/Apia"
    | "Pacific/Auckland"
    | "Pacific/Bougainville"
    | "Pacific/Chatham"
    | "Pacific/Chuuk"
    | "Pacific/Easter"
    | "Pacific/Efate"
    | "Pacific/Enderbury"
    | "Pacific/Fakaofo"
    | "Pacific/Fiji"
    | "Pacific/Funafuti"
    | "Pacific/Galapagos"
    | "Pacific/Gambier"
    | "Pacific/Guadalcanal"
    | "Pacific/Guam"
    | "Pacific/Honolulu"
    | "Pacific/Johnston"
    | "Pacific/Kanton"
    | "Pacific/Kiritimati"
    | "Pacific/Kosrae"
    | "Pacific/Kwajalein"
    | "Pacific/Majuro"
    | "Pacific/Marquesas"
    | "Pacific/Midway"
    | "Pacific/Nauru"
    | "Pacific/Niue"
    | "Pacific/Norfolk"
    | "Pacific/Noumea"
    | "Pacific/Pago_Pago"
    | "Pacific/Palau"
    | "Pacific/Pitcairn"
    | "Pacific/Pohnpei"
    | "Pacific/Ponape"
    | "Pacific/Port_Moresby"
    | "Pacific/Rarotonga"
    | "Pacific/Saipan"
    | "Pacific/Samoa"
    | "Pacific/Tahiti"
    | "Pacific/Tarawa"
    | "Pacific/Tongatapu"
    | "Pacific/Truk"
    | "Pacific/Wake"
    | "Pacific/Wallis"
    | "Pacific/Yap"
    | "Poland"
    | "Portugal"
    | "ROC"
    | "ROK"
    | "Singapore"
    | "Turkey"
    | "UCT"
    | "US/Alaska"
    | "US/Aleutian"
    | "US/Arizona"
    | "US/Central"
    | "US/East-Indiana"
    | "US/Eastern"
    | "US/Hawaii"
    | "US/Indiana-Starke"
    | "US/Michigan"
    | "US/Mountain"
    | "US/Pacific"
    | "US/Samoa"
    | "UTC"
    | "Universal"
    | "W-SU"
    | "WET"
    | "Zulu";
  export type BatchExport = {
    id: string;
    team_id: number;
    name: string;
    model?: ((ModelEnum | BlankEnum | NullEnum) | null) | undefined;
    destination: BatchExportDestination;
    interval: IntervalEnum;
    paused?: boolean | undefined;
    created_at: string;
    last_updated_at: string;
    last_paused_at?: (string | null) | undefined;
    start_at?: (string | null) | undefined;
    end_at?: (string | null) | undefined;
    latest_runs: Array<BatchExportRun>;
    hogql_query?: string | undefined;
    schema: unknown | null;
    filters?: (unknown | null) | undefined;
    timezone?: ((TimezoneEnum | NullEnum) | null) | undefined;
    offset_day?: (number | null) | undefined;
    offset_hour?: (number | null) | undefined;
  };
  export type BatchExportBackfillStatusEnum =
    | "Cancelled"
    | "Completed"
    | "ContinuedAsNew"
    | "Failed"
    | "FailedRetryable"
    | "Terminated"
    | "TimedOut"
    | "Running"
    | "Starting";
  export type BatchExportBackfill = {
    id: string;
    progress: string;
    start_at?: (string | null) | undefined;
    end_at?: (string | null) | undefined;
    status: BatchExportBackfillStatusEnum;
    created_at: string;
    finished_at?: (string | null) | undefined;
    last_updated_at: string;
    team: number;
    batch_export: string;
  };
  export type BreakdownItem = { label: string; value: string | number };
  export type BreakdownValue = { count: number; value: string };
  export type BreakpointHit = {
    id: string;
    lineNumber: number;
    functionName: string;
    timestamp: string;
    variables: Record<string, unknown>;
    stackTrace: Array<unknown>;
    breakpoint_id: string;
    filename: string;
  };
  export type BreakpointHitsResponse = { results: Array<BreakpointHit>; count: number; has_more: boolean };
  export type BucketingIdentifierEnum = "distinct_id" | "device_id";
  export type BusinessModelEnum = "b2b" | "b2c" | "other";
  export type ByweekdayEnum = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";
  export type CalendarHeatmapFilter = Partial<{ dummy: string | null }>;
  export type EventsHeatMapColumnAggregationResult = { column: number; value: number };
  export type EventsHeatMapDataResult = { column: number; row: number; value: number };
  export type EventsHeatMapRowAggregationResult = { row: number; value: number };
  export type EventsHeatMapStructuredResult = {
    allAggregations: number;
    columnAggregations: Array<EventsHeatMapColumnAggregationResult>;
    data: Array<EventsHeatMapDataResult>;
    rowAggregations: Array<EventsHeatMapRowAggregationResult>;
  };
  export type CalendarHeatmapResponse = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: EventsHeatMapStructuredResult;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type CalendarHeatmapQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    calendarHeatmapFilter?: CalendarHeatmapFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "CalendarHeatmapQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (
          | (
              | Array<
                  | EventPropertyFilter
                  | PersonPropertyFilter
                  | ElementPropertyFilter
                  | EventMetadataPropertyFilter
                  | SessionPropertyFilter
                  | CohortPropertyFilter
                  | RecordingPropertyFilter
                  | LogEntryPropertyFilter
                  | GroupPropertyFilter
                  | FeaturePropertyFilter
                  | FlagPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
                  | DataWarehousePropertyFilter
                  | DataWarehousePersonPropertyFilter
                  | ErrorTrackingIssueFilter
                  | LogPropertyFilter
                  | RevenueAnalyticsPropertyFilter
                >
              | PropertyGroupFilter
            )
          | null
        )
      | undefined;
    response?: CalendarHeatmapResponse | undefined;
    samplingFactor?: (number | null) | undefined;
    series: Array<EventsNode | ActionsNode | DataWarehouseNode>;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type ChannelSourceEnum = "widget" | "email" | "slack";
  export type DisplayType = "auto" | "line" | "bar";
  export type YAxisPosition = "left" | "right";
  export type ChartSettingsDisplay = Partial<{
    color: string | null;
    displayType: DisplayType;
    label: string | null;
    trendLine: boolean | null;
    yAxisPosition: YAxisPosition;
  }>;
  export type Style = "none" | "number" | "percent";
  export type ChartSettingsFormatting = Partial<{
    decimalPlaces: number | null;
    prefix: string | null;
    style: Style;
    suffix: string | null;
  }>;
  export type Settings = Partial<{ display: ChartSettingsDisplay; formatting: ChartSettingsFormatting }>;
  export type ChartAxis = { column: string; settings?: Settings | undefined };
  export type HeatmapGradientStop = { color: string; value: number };
  export type GradientScaleMode = "absolute" | "relative";
  export type HeatmapSettings = Partial<{
    gradient: Array<HeatmapGradientStop> | null;
    gradientPreset: string | null;
    gradientScaleMode: GradientScaleMode;
    valueColumn: string | null;
    xAxisColumn: string | null;
    xAxisLabel: string | null;
    yAxisColumn: string | null;
    yAxisLabel: string | null;
  }>;
  export type Scale = "linear" | "logarithmic";
  export type YAxisSettings = Partial<{
    scale: Scale;
    showGridLines: boolean | null;
    showTicks: boolean | null;
    startAtZero: boolean | null;
  }>;
  export type ChartSettings = Partial<{
    goalLines: Array<GoalLine> | null;
    heatmap: HeatmapSettings;
    leftYAxisSettings: YAxisSettings;
    rightYAxisSettings: YAxisSettings;
    seriesBreakdownColumn: string | null;
    showLegend: boolean | null;
    showTotalRow: boolean | null;
    showXAxisBorder: boolean | null;
    showXAxisTicks: boolean | null;
    showYAxisBorder: boolean | null;
    stackBars100: boolean | null;
    xAxis: ChartAxis;
    yAxis: Array<ChartAxis> | null;
    yAxisAtZero: boolean | null;
  }>;
  export type ClickhouseEvent = {
    id: string;
    distinct_id: string;
    properties: string;
    event: string;
    timestamp: string;
    person: string;
    elements: string;
    elements_chain: string;
  };
  export type CohortTypeEnum = "static" | "person_property" | "behavioral" | "realtime" | "analytical";
  export type Cohort = {
    id: number;
    name?: (string | null) | undefined;
    description?: string | undefined;
    groups?: unknown | undefined;
    deleted?: boolean | undefined;
    filters?: (unknown | null) | undefined;
    query?: (unknown | null) | undefined;
    version: number | null;
    pending_version: number | null;
    is_calculating: boolean;
    created_by: UserBasic & unknown;
    created_at: string | null;
    last_calculation: string | null;
    errors_calculating: number;
    last_error_message: string | null;
    count: number | null;
    is_static?: boolean | undefined;
    cohort_type?: ((CohortTypeEnum | BlankEnum | NullEnum) | null) | undefined;
    experiment_set: Array<number>;
    _create_in_folder?: string | undefined;
    _create_static_person_ids?: Array<string> | undefined;
  };
  export type ColorMode = "light" | "dark";
  export type CompareItem = { label: string; value: string };
  export type ConclusionEnum = "won" | "lost" | "inconclusive" | "stopped_early" | "invalid";
  export type ConditionalFormattingRule = {
    bytecode: Array<unknown>;
    color: string;
    colorMode?: ColorMode | undefined;
    columnName: string;
    id: string;
    input: string;
    templateId: string;
  };
  export type ConversationStatusEnum = "idle" | "in_progress" | "canceling";
  export type ConversationTypeEnum = "assistant" | "tool_call" | "deep_research" | "slack";
  export type Conversation = {
    id: string;
    status: ConversationStatusEnum & unknown;
    title: string | null;
    user: UserBasic & unknown;
    created_at: string | null;
    updated_at: string | null;
    type: ConversationTypeEnum & unknown;
    is_internal: boolean | null;
    slack_thread_key: string | null;
    slack_workspace_domain: string | null;
    messages: Array<Record<string, unknown>>;
    has_unsupported_content: boolean;
    agent_mode: string | null;
    pending_approvals: Array<Record<string, unknown>>;
  };
  export type ConversionGoalFilter1 = {
    conversion_goal_id: string;
    conversion_goal_name: string;
    custom_name?: (string | null) | undefined;
    event?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    kind?: "EventsNode" | undefined;
    limit?: (number | null) | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    orderBy?: (Array<string> | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    schema_map: Record<string, unknown>;
    version?: (number | null) | undefined;
  };
  export type ConversionGoalFilter2 = {
    conversion_goal_id: string;
    conversion_goal_name: string;
    custom_name?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    id: number;
    kind?: "ActionsNode" | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    schema_map: Record<string, unknown>;
    version?: (number | null) | undefined;
  };
  export type ConversionGoalFilter3 = {
    conversion_goal_id: string;
    conversion_goal_name: string;
    custom_name?: (string | null) | undefined;
    distinct_id_field: string;
    dw_source_type?: (string | null) | undefined;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    id: string;
    id_field: string;
    kind?: "DataWarehouseNode" | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    schema_map: Record<string, unknown>;
    table_name: string;
    timestamp_field: string;
    version?: (number | null) | undefined;
  };
  export type CookielessServerHashModeEnum = 0 | 1 | 2;
  export type CreateGroup = {
    group_type_index: number;
    group_key: string;
    group_properties?: (unknown | null) | undefined;
  };
  export type CreateRecordingRequestPlatformEnum = "zoom" | "teams" | "meet" | "desktop_audio" | "slack";
  export type CreateRecordingRequest = Partial<{ platform: CreateRecordingRequestPlatformEnum & unknown }>;
  export type Platform9aaEnum = "zoom" | "teams" | "meet" | "desktop_audio" | "slack";
  export type Status292Enum = "recording" | "uploading" | "processing" | "ready" | "error";
  export type Task = { title: string; description?: string | undefined; assignee?: (string | null) | undefined };
  export type CreateRecordingResponse = {
    id: string;
    team: number;
    created_by: number | null;
    sdk_upload_id: string;
    recall_recording_id?: (string | null) | undefined;
    platform: Platform9aaEnum;
    meeting_title?: (string | null) | undefined;
    meeting_url?: (string | null) | undefined;
    duration_seconds?: (number | null) | undefined;
    status?: Status292Enum | undefined;
    notes?: (string | null) | undefined;
    error_message?: (string | null) | undefined;
    video_url?: (string | null) | undefined;
    video_size_bytes?: (number | null) | undefined;
    participants?: Array<string> | undefined;
    transcript_text: string;
    transcript_segments?: Array<TranscriptSegment> | undefined;
    summary?: (string | null) | undefined;
    extracted_tasks?: Array<Task> | undefined;
    tasks_generated_at?: (string | null) | undefined;
    summary_generated_at?: (string | null) | undefined;
    started_at?: string | undefined;
    completed_at?: (string | null) | undefined;
    created_at: string;
    updated_at: string;
    upload_token: string;
  };
  export type CreationModeEnum = "default" | "template" | "duplicate" | "unlisted";
  export type Credential = {
    id: string;
    created_by: UserBasic & unknown;
    created_at: string;
    access_key: string;
    access_secret: string;
  };
  export type CustomerProfileConfigScopeEnum = "person" | "group_0" | "group_1" | "group_2" | "group_3" | "group_4";
  export type CustomerProfileConfig = {
    id: string;
    scope: CustomerProfileConfigScopeEnum;
    content?: (unknown | null) | undefined;
    sidebar?: (unknown | null) | undefined;
    created_at: string;
    updated_at: string | null;
  };
  export type DashboardRestrictionLevel = 21 | 37;
  export type EffectiveRestrictionLevelEnum = 21 | 37;
  export type EffectivePrivilegeLevelEnum = 21 | 37;
  export type Dashboard = {
    id: number;
    name?: (string | null) | undefined;
    description?: string | undefined;
    pinned?: boolean | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    last_accessed_at?: (string | null) | undefined;
    last_viewed_at: string | null;
    is_shared: boolean;
    deleted?: boolean | undefined;
    creation_mode: CreationModeEnum & unknown;
    filters: Record<string, unknown>;
    variables: Record<string, unknown> | null;
    breakdown_colors?: unknown | undefined;
    data_color_theme_id?: (number | null) | undefined;
    tags?: Array<unknown> | undefined;
    restriction_level?: (DashboardRestrictionLevel & unknown) | undefined;
    effective_restriction_level: EffectiveRestrictionLevelEnum & unknown;
    effective_privilege_level: EffectivePrivilegeLevelEnum & unknown;
    user_access_level: string | null;
    access_control_version: string;
    last_refresh?: (string | null) | undefined;
    persisted_filters: Record<string, unknown> | null;
    persisted_variables: Record<string, unknown> | null;
    team_id: number;
    tiles: Array<Record<string, unknown>> | null;
    use_template?: string | undefined;
    use_dashboard?: (number | null) | undefined;
    delete_insights?: boolean | undefined;
    _create_in_folder?: string | undefined;
  };
  export type DashboardBasic = {
    id: number;
    name: string | null;
    description: string;
    pinned: boolean;
    created_at: string;
    created_by: UserBasic & unknown;
    last_accessed_at: string | null;
    last_viewed_at: string | null;
    is_shared: boolean;
    deleted: boolean;
    creation_mode: CreationModeEnum & unknown;
    tags?: Array<unknown> | undefined;
    restriction_level: DashboardRestrictionLevel & unknown;
    effective_restriction_level: EffectiveRestrictionLevelEnum & unknown;
    effective_privilege_level: EffectivePrivilegeLevelEnum & unknown;
    user_access_level: string | null;
    access_control_version: string;
    last_refresh: string | null;
    team_id: number;
  };
  export type DashboardCollaborator = {
    id: string;
    dashboard_id: number;
    user: UserBasic & unknown;
    level: DashboardRestrictionLevel & unknown;
    added_at: string;
    updated_at: string;
    user_uuid: string;
  };
  export type DashboardFilter = Partial<{
    breakdown_filter: BreakdownFilter;
    date_from: string | null;
    date_to: string | null;
    explicitDate: boolean | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
  }>;
  export type DashboardTemplateScopeEnum = "team" | "global" | "feature_flag";
  export type DashboardTemplate = {
    id: string;
    template_name?: (string | null) | undefined;
    dashboard_description?: (string | null) | undefined;
    dashboard_filters?: (unknown | null) | undefined;
    tags?: (Array<string> | null) | undefined;
    tiles?: (unknown | null) | undefined;
    variables?: (unknown | null) | undefined;
    deleted?: (boolean | null) | undefined;
    created_at: string | null;
    created_by?: (number | null) | undefined;
    image_url?: (string | null) | undefined;
    team_id: number | null;
    scope?: ((DashboardTemplateScopeEnum | BlankEnum | NullEnum) | null) | undefined;
    availability_contexts?: (Array<string> | null) | undefined;
  };
  export type DashboardTileBasic = { id: number; dashboard_id: number; deleted?: (boolean | null) | undefined };
  export type DataColorTheme = {
    id: number;
    name: string;
    colors?: unknown | undefined;
    is_global: string;
    created_at: string | null;
    created_by: UserBasic & unknown;
  };
  export type DataTableNodeViewPropsContextType = "event_definition" | "team_columns";
  export type DataTableNodeViewPropsContext = {
    eventDefinitionId?: (string | null) | undefined;
    type: DataTableNodeViewPropsContextType;
  };
  export type Response = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type Response1 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit: number;
    missing_actors_count?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<string> | null) | undefined;
  };
  export type Response2 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    kind?: "GroupsQuery" | undefined;
    limit: number;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type Response3 = {
    clickhouse?: (string | null) | undefined;
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    explain?: (Array<string> | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    metadata?: HogQLMetadataResponse | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query?: (string | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type Response4 = {
    dateFrom?: (string | null) | undefined;
    dateTo?: (string | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebOverviewItem>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type Response5 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type Response6 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type WebVitalsPathBreakdownResultItem = { path: string; value: number };
  export type WebVitalsPathBreakdownResult = {
    good: Array<WebVitalsPathBreakdownResultItem>;
    needs_improvements: Array<WebVitalsPathBreakdownResultItem>;
    poor: Array<WebVitalsPathBreakdownResultItem>;
  };
  export type Response8 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebVitalsPathBreakdownResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type Response9 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type Response10 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type Response11 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type Response12 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueAnalyticsMRRQueryResultItem = {
    churn: unknown;
    contraction: unknown;
    expansion: unknown;
    new: unknown;
    total: unknown;
  };
  export type Response13 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsMRRQueryResultItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueAnalyticsOverviewItemKey = "revenue" | "paying_customer_count" | "avg_revenue_per_customer";
  export type RevenueAnalyticsOverviewItem = { key: RevenueAnalyticsOverviewItemKey; value: number };
  export type Response14 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsOverviewItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type Response15 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type Response16 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type MarketingAnalyticsItem = {
    changeFromPreviousPct?: (number | null) | undefined;
    hasComparison?: (boolean | null) | undefined;
    isIncreaseBad?: (boolean | null) | undefined;
    key: string;
    kind: WebAnalyticsItemKind;
    previous?: ((number | string) | null) | undefined;
    value?: ((number | string) | null) | undefined;
  };
  export type Response18 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type Response19 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Record<string, unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type Response20 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type VolumeBucket = { label: string; value: number };
  export type ErrorTrackingIssueAggregations = {
    occurrences: number;
    sessions: number;
    users: number;
    volumeRange?: (Array<number> | null) | undefined;
    volume_buckets: Array<VolumeBucket>;
  };
  export type ErrorTrackingIssueAssigneeType = "user" | "role";
  export type ErrorTrackingIssueAssignee = { id: string | number; type: ErrorTrackingIssueAssigneeType };
  export type ErrorTrackingIssueCohort = { id: number; name: string };
  export type IntegrationKind =
    | "slack"
    | "salesforce"
    | "hubspot"
    | "google-pubsub"
    | "google-cloud-storage"
    | "google-ads"
    | "google-sheets"
    | "linkedin-ads"
    | "snapchat"
    | "intercom"
    | "email"
    | "twilio"
    | "linear"
    | "github"
    | "gitlab"
    | "meta-ads"
    | "clickup"
    | "reddit-ads"
    | "databricks"
    | "tiktok-ads"
    | "bing-ads"
    | "vercel"
    | "azure-blob"
    | "firebase"
    | "jira";
  export type ErrorTrackingExternalReferenceIntegration = { display_name: string; id: number; kind: IntegrationKind };
  export type ErrorTrackingExternalReference = {
    external_url: string;
    id: string;
    integration: ErrorTrackingExternalReferenceIntegration;
  };
  export type FirstEvent = { distinct_id: string; properties: string; timestamp: string; uuid: string };
  export type LastEvent = { distinct_id: string; properties: string; timestamp: string; uuid: string };
  export type ErrorTrackingIssueStatus = "archived" | "active" | "resolved" | "pending_release" | "suppressed";
  export type ErrorTrackingIssue = {
    aggregations?: ErrorTrackingIssueAggregations | undefined;
    assignee?: ErrorTrackingIssueAssignee | undefined;
    cohort?: ErrorTrackingIssueCohort | undefined;
    description?: (string | null) | undefined;
    external_issues?: (Array<ErrorTrackingExternalReference> | null) | undefined;
    first_event?: FirstEvent | undefined;
    first_seen: string;
    function?: (string | null) | undefined;
    id: string;
    last_event?: LastEvent | undefined;
    last_seen: string;
    library?: (string | null) | undefined;
    name?: (string | null) | undefined;
    revenue?: (number | null) | undefined;
    source?: (string | null) | undefined;
    status: ErrorTrackingIssueStatus;
  };
  export type Response21 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<ErrorTrackingIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type Population = { both: number; exception_only: number; neither: number; success_only: number };
  export type ErrorTrackingCorrelatedIssue = {
    assignee?: ErrorTrackingIssueAssignee | undefined;
    cohort?: ErrorTrackingIssueCohort | undefined;
    description?: (string | null) | undefined;
    event: string;
    external_issues?: (Array<ErrorTrackingExternalReference> | null) | undefined;
    first_seen: string;
    id: string;
    last_seen: string;
    library?: (string | null) | undefined;
    name?: (string | null) | undefined;
    odds_ratio: number;
    population: Population;
    status: ErrorTrackingIssueStatus;
  };
  export type Response22 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<ErrorTrackingCorrelatedIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type ExperimentSignificanceCode =
    | "significant"
    | "not_enough_exposure"
    | "low_win_probability"
    | "high_loss"
    | "high_p_value";
  export type ExperimentVariantFunnelsBaseStats = { failure_count: number; key: string; success_count: number };
  export type Response23 = {
    credible_intervals: Record<string, Array<number>>;
    expected_loss: number;
    funnels_query?: FunnelsQuery | undefined;
    insight: Array<Array<Record<string, unknown>>>;
    kind?: "ExperimentFunnelsQuery" | undefined;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantFunnelsBaseStats>;
  };
  export type ExperimentVariantTrendsBaseStats = {
    absolute_exposure: number;
    count: number;
    exposure: number;
    key: string;
  };
  export type Response24 = {
    count_query?: TrendsQuery | undefined;
    credible_intervals: Record<string, Array<number>>;
    exposure_query?: TrendsQuery | undefined;
    insight: Array<Record<string, unknown>>;
    kind?: "ExperimentTrendsQuery" | undefined;
    p_value: number;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantTrendsBaseStats>;
  };
  export type LLMTraceEvent = {
    createdAt: string;
    event: AIEventType | string;
    id: string;
    properties: Record<string, unknown>;
  };
  export type LLMTracePerson = {
    created_at: string;
    distinct_id: string;
    properties: Record<string, unknown>;
    uuid: string;
  };
  export type LLMTrace = {
    aiSessionId?: (string | null) | undefined;
    createdAt: string;
    errorCount?: (number | null) | undefined;
    events: Array<LLMTraceEvent>;
    id: string;
    inputCost?: (number | null) | undefined;
    inputState?: (unknown | null) | undefined;
    inputTokens?: (number | null) | undefined;
    isSupportTrace?: (boolean | null) | undefined;
    outputCost?: (number | null) | undefined;
    outputState?: (unknown | null) | undefined;
    outputTokens?: (number | null) | undefined;
    person: LLMTracePerson;
    totalCost?: (number | null) | undefined;
    totalLatency?: (number | null) | undefined;
    traceName?: (string | null) | undefined;
  };
  export type Response25 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<LLMTrace>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type Response26 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type TaxonomicFilterGroupType =
    | "metadata"
    | "actions"
    | "cohorts"
    | "cohorts_with_all"
    | "data_warehouse"
    | "data_warehouse_properties"
    | "data_warehouse_person_properties"
    | "elements"
    | "events"
    | "internal_events"
    | "internal_event_properties"
    | "event_properties"
    | "event_feature_flags"
    | "event_metadata"
    | "numerical_event_properties"
    | "person_properties"
    | "pageview_urls"
    | "screens"
    | "custom_events"
    | "wildcard"
    | "groups"
    | "persons"
    | "feature_flags"
    | "insights"
    | "experiments"
    | "plugins"
    | "dashboards"
    | "name_groups"
    | "session_properties"
    | "hogql_expression"
    | "notebooks"
    | "log_entries"
    | "error_tracking_issues"
    | "logs"
    | "log_attributes"
    | "log_resource_attributes"
    | "replay"
    | "revenue_analytics_properties"
    | "resources"
    | "error_tracking_properties"
    | "activity_log_properties"
    | "max_ai_context"
    | "workflow_variables"
    | "empty";
  export type EventsQueryResponse = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type EventsQuery = {
    actionId?: (number | null) | undefined;
    after?: (string | null) | undefined;
    before?: (string | null) | undefined;
    event?: (string | null) | undefined;
    events?: (Array<string> | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    fixedProperties?:
      | (Array<
          | PropertyGroupFilter
          | PropertyGroupFilterValue
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    kind?: "EventsQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<string> | null) | undefined;
    personId?: (string | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: EventsQueryResponse | undefined;
    select: Array<string>;
    source?: InsightActorsQuery | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
    where?: (Array<string> | null) | undefined;
  };
  export type PersonsNode = Partial<{
    cohort: number | null;
    distinctId: string | null;
    fixedProperties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    kind: "PersonsNode";
    limit: number | null;
    modifiers: HogQLQueryModifiers;
    offset: number | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    response: Record<string, unknown> | null;
    search: string | null;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type GroupsQueryResponse = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    kind?: "GroupsQuery" | undefined;
    limit: number;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type GroupsQuery = {
    group_type_index: number;
    kind?: "GroupsQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<string> | null) | undefined;
    properties?: (Array<GroupPropertyFilter | HogQLPropertyFilter> | null) | undefined;
    response?: GroupsQueryResponse | undefined;
    search?: (string | null) | undefined;
    select?: (Array<string> | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type WebExternalClicksTableQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type WebExternalClicksTableQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "WebExternalClicksTableQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebExternalClicksTableQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    stripQueryParams?: (boolean | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type WebGoalsQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type WebGoalsQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "WebGoalsQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebGoalsQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type WebVitalsQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "WebVitalsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebGoalsQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    source:
      | TrendsQuery
      | FunnelsQuery
      | RetentionQuery
      | PathsQuery
      | StickinessQuery
      | LifecycleQuery
      | WebStatsTableQuery
      | WebOverviewQuery;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type WebVitalsMetric = "INP" | "LCP" | "CLS" | "FCP";
  export type WebVitalsPercentile = "p75" | "p90" | "p99";
  export type WebVitalsPathBreakdownQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebVitalsPathBreakdownResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type WebVitalsPathBreakdownQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "WebVitalsPathBreakdownQuery" | undefined;
    metric: WebVitalsMetric;
    modifiers?: HogQLQueryModifiers | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    percentile: WebVitalsPercentile;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebVitalsPathBreakdownQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    tags?: QueryLogTags | undefined;
    thresholds: Array<number>;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type Filters = Partial<{ dateRange: DateRange; properties: Array<SessionPropertyFilter> | null }>;
  export type SessionAttributionGroupBy =
    | "ChannelType"
    | "Medium"
    | "Source"
    | "Campaign"
    | "AdIds"
    | "ReferringDomain"
    | "InitialURL";
  export type SessionAttributionExplorerQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type SessionAttributionExplorerQuery = {
    filters?: Filters | undefined;
    groupBy: Array<SessionAttributionGroupBy>;
    kind?: "SessionAttributionExplorerQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    response?: SessionAttributionExplorerQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type SessionsQueryResponse = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type SessionsQuery = {
    actionId?: (number | null) | undefined;
    after?: (string | null) | undefined;
    before?: (string | null) | undefined;
    event?: (string | null) | undefined;
    eventProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    fixedProperties?:
      | (Array<
          | PropertyGroupFilter
          | PropertyGroupFilterValue
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    kind?: "SessionsQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<string> | null) | undefined;
    personId?: (string | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: SessionsQueryResponse | undefined;
    select: Array<string>;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
    where?: (Array<string> | null) | undefined;
  };
  export type RevenueAnalyticsBreakdown = { property: string; type?: "revenue_analytics" | undefined };
  export type SimpleIntervalType = "day" | "month";
  export type RevenueAnalyticsGrossRevenueQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueAnalyticsGrossRevenueQuery = {
    breakdown: Array<RevenueAnalyticsBreakdown>;
    dateRange?: DateRange | undefined;
    interval: SimpleIntervalType;
    kind?: "RevenueAnalyticsGrossRevenueQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties: Array<RevenueAnalyticsPropertyFilter>;
    response?: RevenueAnalyticsGrossRevenueQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type RevenueAnalyticsMetricsQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueAnalyticsMetricsQuery = {
    breakdown: Array<RevenueAnalyticsBreakdown>;
    dateRange?: DateRange | undefined;
    interval: SimpleIntervalType;
    kind?: "RevenueAnalyticsMetricsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties: Array<RevenueAnalyticsPropertyFilter>;
    response?: RevenueAnalyticsMetricsQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type RevenueAnalyticsMRRQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsMRRQueryResultItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueAnalyticsMRRQuery = {
    breakdown: Array<RevenueAnalyticsBreakdown>;
    dateRange?: DateRange | undefined;
    interval: SimpleIntervalType;
    kind?: "RevenueAnalyticsMRRQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties: Array<RevenueAnalyticsPropertyFilter>;
    response?: RevenueAnalyticsMRRQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type RevenueAnalyticsOverviewQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsOverviewItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueAnalyticsOverviewQuery = {
    dateRange?: DateRange | undefined;
    kind?: "RevenueAnalyticsOverviewQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties: Array<RevenueAnalyticsPropertyFilter>;
    response?: RevenueAnalyticsOverviewQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type RevenueAnalyticsTopCustomersGroupBy = "month" | "all";
  export type RevenueAnalyticsTopCustomersQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueAnalyticsTopCustomersQuery = {
    dateRange?: DateRange | undefined;
    groupBy: RevenueAnalyticsTopCustomersGroupBy;
    kind?: "RevenueAnalyticsTopCustomersQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties: Array<RevenueAnalyticsPropertyFilter>;
    response?: RevenueAnalyticsTopCustomersQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type RevenueExampleEventsQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type RevenueExampleEventsQuery = Partial<{
    kind: "RevenueExampleEventsQuery";
    limit: number | null;
    modifiers: HogQLQueryModifiers;
    offset: number | null;
    response: RevenueExampleEventsQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type RevenueExampleDataWarehouseTablesQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type RevenueExampleDataWarehouseTablesQuery = Partial<{
    kind: "RevenueExampleDataWarehouseTablesQuery";
    limit: number | null;
    modifiers: HogQLQueryModifiers;
    offset: number | null;
    response: RevenueExampleDataWarehouseTablesQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type IntegrationFilter = Partial<{ integrationSourceIds: Array<string> | null }>;
  export type MarketingAnalyticsOrderByEnum = "ASC" | "DESC";
  export type MarketingAnalyticsTableQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type MarketingAnalyticsTableQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    draftConversionGoal?: ((ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3) | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    integrationFilter?: IntegrationFilter | undefined;
    interval?: IntervalType | undefined;
    kind?: "MarketingAnalyticsTableQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<Array<string | MarketingAnalyticsOrderByEnum>> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: MarketingAnalyticsTableQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    select?: (Array<string> | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type MarketingAnalyticsAggregatedQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Record<string, unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type MarketingAnalyticsAggregatedQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    draftConversionGoal?: ((ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3) | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    integrationFilter?: IntegrationFilter | undefined;
    interval?: IntervalType | undefined;
    kind?: "MarketingAnalyticsAggregatedQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: MarketingAnalyticsAggregatedQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    select?: (Array<string> | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type NonIntegratedConversionsTableQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type NonIntegratedConversionsTableQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    draftConversionGoal?: ((ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3) | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "NonIntegratedConversionsTableQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<Array<string | MarketingAnalyticsOrderByEnum>> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: NonIntegratedConversionsTableQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    select?: (Array<string> | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type OrderBy1 = "last_seen" | "first_seen" | "occurrences" | "users" | "sessions" | "revenue";
  export type OrderDirection1 = "ASC" | "DESC";
  export type ErrorTrackingQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<ErrorTrackingIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type RevenueEntity = "person" | "group_0" | "group_1" | "group_2" | "group_3" | "group_4";
  export type RevenuePeriod = "all_time" | "mrr";
  export type ErrorTrackingQuery = {
    assignee?: ErrorTrackingIssueAssignee | undefined;
    dateRange: DateRange;
    filterGroup?: PropertyGroupFilter | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    groupKey?: (string | null) | undefined;
    groupTypeIndex?: (number | null) | undefined;
    issueId?: (string | null) | undefined;
    kind?: "ErrorTrackingQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy: OrderBy1;
    orderDirection?: OrderDirection1 | undefined;
    personId?: (string | null) | undefined;
    response?: ErrorTrackingQueryResponse | undefined;
    revenueEntity?: RevenueEntity | undefined;
    revenuePeriod?: RevenuePeriod | undefined;
    searchQuery?: (string | null) | undefined;
    status?: ((ErrorTrackingIssueStatus | string) | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
    volumeResolution: number;
    withAggregations?: (boolean | null) | undefined;
    withFirstEvent?: (boolean | null) | undefined;
    withLastEvent?: (boolean | null) | undefined;
  };
  export type ErrorTrackingIssueCorrelationQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<ErrorTrackingCorrelatedIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type ErrorTrackingIssueCorrelationQuery = {
    events: Array<string>;
    kind?: "ErrorTrackingIssueCorrelationQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: ErrorTrackingIssueCorrelationQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type ExperimentFunnelsQueryResponse = {
    credible_intervals: Record<string, Array<number>>;
    expected_loss: number;
    funnels_query?: FunnelsQuery | undefined;
    insight: Array<Array<Record<string, unknown>>>;
    kind?: "ExperimentFunnelsQuery" | undefined;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantFunnelsBaseStats>;
  };
  export type ExperimentFunnelsQuery = {
    experiment_id?: (number | null) | undefined;
    fingerprint?: (string | null) | undefined;
    funnels_query: FunnelsQuery;
    kind?: "ExperimentFunnelsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    name?: (string | null) | undefined;
    response?: ExperimentFunnelsQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    uuid?: (string | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type ExperimentTrendsQueryResponse = {
    count_query?: TrendsQuery | undefined;
    credible_intervals: Record<string, Array<number>>;
    exposure_query?: TrendsQuery | undefined;
    insight: Array<Record<string, unknown>>;
    kind?: "ExperimentTrendsQuery" | undefined;
    p_value: number;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantTrendsBaseStats>;
  };
  export type ExperimentTrendsQuery = {
    count_query: TrendsQuery;
    experiment_id?: (number | null) | undefined;
    exposure_query?: TrendsQuery | undefined;
    fingerprint?: (string | null) | undefined;
    kind?: "ExperimentTrendsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    name?: (string | null) | undefined;
    response?: ExperimentTrendsQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    uuid?: (string | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type TracesQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<LLMTrace>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type TracesQuery = Partial<{
    dateRange: DateRange;
    filterSupportTraces: boolean | null;
    filterTestAccounts: boolean | null;
    groupKey: string | null;
    groupTypeIndex: number | null;
    kind: "TracesQuery";
    limit: number | null;
    modifiers: HogQLQueryModifiers;
    offset: number | null;
    personId: string | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    randomOrder: boolean | null;
    response: TracesQueryResponse;
    showColumnConfigurator: boolean | null;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type TraceQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<LLMTrace>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type TraceQuery = {
    dateRange?: DateRange | undefined;
    kind?: "TraceQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: TraceQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    traceId: string;
    version?: (number | null) | undefined;
  };
  export type EndpointsUsageBreakdown = "Endpoint" | "MaterializationType" | "ApiKey" | "Status";
  export type MaterializationType = "materialized" | "inline" | null;
  export type EndpointsUsageOrderByField =
    | "requests"
    | "bytes_read"
    | "cpu_seconds"
    | "avg_query_duration_ms"
    | "error_rate";
  export type EndpointsUsageOrderByDirection = "ASC" | "DESC";
  export type EndpointsUsageTableQueryResponse = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type EndpointsUsageTableQuery = {
    breakdownBy: EndpointsUsageBreakdown;
    dateRange?: DateRange | undefined;
    endpointNames?: (Array<string> | null) | undefined;
    kind?: "EndpointsUsageTableQuery" | undefined;
    limit?: (number | null) | undefined;
    materializationType?: MaterializationType | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<EndpointsUsageOrderByField | EndpointsUsageOrderByDirection> | null) | undefined;
    response?: EndpointsUsageTableQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type DataTableNode = {
    allowSorting?: (boolean | null) | undefined;
    columns?: (Array<string> | null) | undefined;
    context?: DataTableNodeViewPropsContext | undefined;
    contextKey?: (string | null) | undefined;
    defaultColumns?: (Array<string> | null) | undefined;
    embedded?: (boolean | null) | undefined;
    expandable?: (boolean | null) | undefined;
    full?: (boolean | null) | undefined;
    hiddenColumns?: (Array<string> | null) | undefined;
    kind?: "DataTableNode" | undefined;
    pinnedColumns?: (Array<string> | null) | undefined;
    propertiesViaUrl?: (boolean | null) | undefined;
    response?:
      | (
          | (
              | Record<string, unknown>
              | Response
              | Response1
              | Response2
              | Response3
              | Response4
              | Response5
              | Response6
              | Response8
              | Response9
              | Response10
              | Response11
              | Response12
              | Response13
              | Response14
              | Response15
              | Response16
              | Response18
              | Response19
              | Response20
              | Response21
              | Response22
              | Response23
              | Response24
              | Response25
              | Response26
            )
          | null
        )
      | undefined;
    showActions?: (boolean | null) | undefined;
    showColumnConfigurator?: (boolean | null) | undefined;
    showCount?: (boolean | null) | undefined;
    showDateRange?: (boolean | null) | undefined;
    showElapsedTime?: (boolean | null) | undefined;
    showEventFilter?: (boolean | null) | undefined;
    showEventsFilter?: (boolean | null) | undefined;
    showExport?: (boolean | null) | undefined;
    showHogQLEditor?: (boolean | null) | undefined;
    showOpenEditorButton?: (boolean | null) | undefined;
    showPersistentColumnConfigurator?: (boolean | null) | undefined;
    showPropertyFilter?: ((boolean | Array<TaxonomicFilterGroupType>) | null) | undefined;
    showRecordingColumn?: (boolean | null) | undefined;
    showReload?: (boolean | null) | undefined;
    showResultsTable?: (boolean | null) | undefined;
    showSavedFilters?: (boolean | null) | undefined;
    showSavedQueries?: (boolean | null) | undefined;
    showSearch?: (boolean | null) | undefined;
    showSourceQueryOptions?: (boolean | null) | undefined;
    showTableViews?: (boolean | null) | undefined;
    showTestAccountFilters?: (boolean | null) | undefined;
    showTimings?: (boolean | null) | undefined;
    source:
      | EventsNode
      | EventsQuery
      | PersonsNode
      | ActorsQuery
      | GroupsQuery
      | HogQLQuery
      | WebOverviewQuery
      | WebStatsTableQuery
      | WebExternalClicksTableQuery
      | WebGoalsQuery
      | WebVitalsQuery
      | WebVitalsPathBreakdownQuery
      | SessionAttributionExplorerQuery
      | SessionsQuery
      | RevenueAnalyticsGrossRevenueQuery
      | RevenueAnalyticsMetricsQuery
      | RevenueAnalyticsMRRQuery
      | RevenueAnalyticsOverviewQuery
      | RevenueAnalyticsTopCustomersQuery
      | RevenueExampleEventsQuery
      | RevenueExampleDataWarehouseTablesQuery
      | MarketingAnalyticsTableQuery
      | MarketingAnalyticsAggregatedQuery
      | NonIntegratedConversionsTableQuery
      | ErrorTrackingQuery
      | ErrorTrackingIssueCorrelationQuery
      | ExperimentFunnelsQuery
      | ExperimentTrendsQuery
      | TracesQuery
      | TraceQuery
      | EndpointsUsageTableQuery;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type TableSettings = Partial<{
    columns: Array<ChartAxis> | null;
    conditionalFormatting: Array<ConditionalFormattingRule> | null;
    pinnedColumns: Array<string> | null;
  }>;
  export type DataVisualizationNode = {
    chartSettings?: ChartSettings | undefined;
    display?: ChartDisplayType | undefined;
    kind?: "DataVisualizationNode" | undefined;
    source: HogQLQuery;
    tableSettings?: TableSettings | undefined;
    version?: (number | null) | undefined;
  };
  export type StatusD5cEnum = "Cancelled" | "Modified" | "Completed" | "Failed" | "Running";
  export type OriginEnum = "data_warehouse" | "endpoint" | "managed_viewset";
  export type DataWarehouseSavedQuery = {
    id: string;
    deleted?: (boolean | null) | undefined;
    name: string;
    query?: (unknown | null) | undefined;
    created_by: UserBasic & unknown;
    created_at: string;
    sync_frequency: string;
    columns: string;
    status: (StatusD5cEnum | NullEnum) | null;
    last_run_at: string | null;
    managed_viewset_kind: string;
    latest_error: string | null;
    edited_history_id?: (string | null) | undefined;
    latest_history_id: string;
    soft_update?: (boolean | null) | undefined;
    is_materialized: boolean | null;
    origin: (OriginEnum | NullEnum) | null;
  };
  export type DataWarehouseSavedQueryMinimal = {
    id: string;
    deleted: boolean | null;
    name: string;
    created_by: UserBasic & unknown;
    created_at: string;
    sync_frequency: string;
    columns: string;
    status: (StatusD5cEnum | NullEnum) | null;
    last_run_at: string | null;
    managed_viewset_kind: string;
    latest_error: string | null;
    is_materialized: boolean | null;
    origin: (OriginEnum | NullEnum) | null;
  };
  export type DataWarehouseSyncInterval = "5min" | "30min" | "1hour" | "6hour" | "12hour" | "24hour" | "7day" | "30day";
  export type DataWarehouseViewLinkConfiguration = Partial<{
    experiments_optimized: boolean | null;
    experiments_timestamp_key: string | null;
  }>;
  export type HedgehogColorOptions =
    | "green"
    | "red"
    | "blue"
    | "purple"
    | "dark"
    | "light"
    | "sepia"
    | "invert"
    | "invert-hue"
    | "greyscale";
  export type MinimalHedgehogConfig = {
    accessories: Array<string>;
    color?: HedgehogColorOptions | undefined;
    use_as_profile: boolean;
  };
  export type UserBasicType = {
    distinct_id: string;
    email: string;
    first_name: string;
    hedgehog_config?: MinimalHedgehogConfig | undefined;
    id: number;
    is_email_verified?: (unknown | null) | undefined;
    last_name?: (string | null) | undefined;
    role_at_organization?: (string | null) | undefined;
    uuid: string;
  };
  export type DataWarehouseViewLink = {
    configuration?: DataWarehouseViewLinkConfiguration | undefined;
    created_at?: (string | null) | undefined;
    created_by?: UserBasicType | undefined;
    field_name?: (string | null) | undefined;
    id: string;
    joining_table_key?: (string | null) | undefined;
    joining_table_name?: (string | null) | undefined;
    source_table_key?: (string | null) | undefined;
    source_table_name?: (string | null) | undefined;
  };
  export type DatabaseSerializedFieldType =
    | "integer"
    | "float"
    | "decimal"
    | "string"
    | "datetime"
    | "date"
    | "boolean"
    | "array"
    | "json"
    | "lazy_table"
    | "virtual_table"
    | "field_traverser"
    | "expression"
    | "view"
    | "materialized_view"
    | "unknown";
  export type DatabaseSchemaField = {
    chain?: (Array<string | number> | null) | undefined;
    fields?: (Array<string> | null) | undefined;
    hogql_value: string;
    id?: (string | null) | undefined;
    name: string;
    schema_valid: boolean;
    table?: (string | null) | undefined;
    type: DatabaseSerializedFieldType;
  };
  export type DatabaseSchemaBatchExportTable = {
    fields: Record<string, unknown>;
    id: string;
    name: string;
    row_count?: (number | null) | undefined;
    type?: "batch_export" | undefined;
  };
  export type DatabaseSchemaSchema = {
    id: string;
    incremental: boolean;
    last_synced_at?: (string | null) | undefined;
    name: string;
    should_sync: boolean;
    status?: (string | null) | undefined;
  };
  export type DatabaseSchemaSource = {
    id: string;
    last_synced_at?: (string | null) | undefined;
    prefix: string;
    source_type: string;
    status: string;
  };
  export type DatabaseSchemaDataWarehouseTable = {
    fields: Record<string, unknown>;
    format: string;
    id: string;
    name: string;
    row_count?: (number | null) | undefined;
    schema?: DatabaseSchemaSchema | undefined;
    source?: DatabaseSchemaSource | undefined;
    type?: "data_warehouse" | undefined;
    url_pattern: string;
  };
  export type DatabaseSchemaEndpointTable = {
    fields: Record<string, unknown>;
    id: string;
    name: string;
    query: HogQLQuery;
    row_count?: (number | null) | undefined;
    status?: (string | null) | undefined;
    type?: "endpoint" | undefined;
  };
  export type DatabaseSchemaManagedViewTableKind =
    | "revenue_analytics_charge"
    | "revenue_analytics_customer"
    | "revenue_analytics_mrr"
    | "revenue_analytics_product"
    | "revenue_analytics_revenue_item"
    | "revenue_analytics_subscription";
  export type DatabaseSchemaManagedViewTable = {
    fields: Record<string, unknown>;
    id: string;
    kind: DatabaseSchemaManagedViewTableKind;
    name: string;
    query: HogQLQuery;
    row_count?: (number | null) | undefined;
    source_id?: (string | null) | undefined;
    type?: "managed_view" | undefined;
  };
  export type DatabaseSchemaMaterializedViewTable = {
    fields: Record<string, unknown>;
    id: string;
    last_run_at?: (string | null) | undefined;
    name: string;
    query: HogQLQuery;
    row_count?: (number | null) | undefined;
    status?: (string | null) | undefined;
    type?: "materialized_view" | undefined;
  };
  export type DatabaseSchemaPostHogTable = {
    fields: Record<string, unknown>;
    id: string;
    name: string;
    row_count?: (number | null) | undefined;
    type?: "posthog" | undefined;
  };
  export type DatabaseSchemaSystemTable = {
    fields: Record<string, unknown>;
    id: string;
    name: string;
    row_count?: (number | null) | undefined;
    type?: "system" | undefined;
  };
  export type DatabaseSchemaViewTable = {
    fields: Record<string, unknown>;
    id: string;
    name: string;
    query: HogQLQuery;
    row_count?: (number | null) | undefined;
    type?: "view" | undefined;
  };
  export type DatabaseSchemaQueryResponse = { joins: Array<DataWarehouseViewLink>; tables: Record<string, unknown> };
  export type DatabaseSchemaQuery = Partial<{
    kind: "DatabaseSchemaQuery";
    modifiers: HogQLQueryModifiers;
    response: DatabaseSchemaQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type Dataset = {
    id: string;
    name: string;
    description?: (string | null) | undefined;
    metadata?: (unknown | null) | undefined;
    created_at: string;
    updated_at: string | null;
    deleted?: (boolean | null) | undefined;
    created_by: UserBasic & unknown;
    team: number;
  };
  export type DatasetItem = {
    id: string;
    dataset: string;
    input?: (unknown | null) | undefined;
    output?: (unknown | null) | undefined;
    metadata?: (unknown | null) | undefined;
    ref_trace_id?: (string | null) | undefined;
    ref_timestamp?: (string | null) | undefined;
    ref_source_id?: (string | null) | undefined;
    deleted?: (boolean | null) | undefined;
    created_at: string;
    updated_at: string | null;
    created_by: UserBasic & unknown;
    team: number;
  };
  export type DayItem = { label: string; value: string | string | number };
  export type DefaultExperimentStatsMethodEnum = "bayesian" | "frequentist";
  export type DesktopRecording = {
    id: string;
    team: number;
    created_by: number | null;
    sdk_upload_id: string;
    recall_recording_id?: (string | null) | undefined;
    platform: Platform9aaEnum;
    meeting_title?: (string | null) | undefined;
    meeting_url?: (string | null) | undefined;
    duration_seconds?: (number | null) | undefined;
    status?: Status292Enum | undefined;
    notes?: (string | null) | undefined;
    error_message?: (string | null) | undefined;
    video_url?: (string | null) | undefined;
    video_size_bytes?: (number | null) | undefined;
    participants?: Array<string> | undefined;
    transcript_text: string;
    transcript_segments?: Array<TranscriptSegment> | undefined;
    summary?: (string | null) | undefined;
    extracted_tasks?: Array<Task> | undefined;
    tasks_generated_at?: (string | null) | undefined;
    summary_generated_at?: (string | null) | undefined;
    started_at?: string | undefined;
    completed_at?: (string | null) | undefined;
    created_at: string;
    updated_at: string;
  };
  export type DisplayEnum = "number" | "sparkline";
  export type DistanceFunc = "L1Distance" | "L2Distance" | "cosineDistance";
  export type OrderBy = "distance" | "timestamp";
  export type OrderDirection = "asc" | "desc";
  export type EmbeddedDocument = { document_id: string; document_type: string; product: string; timestamp: string };
  export type EmbeddingModelName = "text-embedding-3-small-1536" | "text-embedding-3-large-3072";
  export type EmbeddingRecord = {
    document_id: string;
    document_type: string;
    model_name: EmbeddingModelName;
    product: string;
    rendering: string;
    timestamp: string;
  };
  export type EmbeddingDistance = { distance: number; origin?: EmbeddingRecord | undefined; result: EmbeddingRecord };
  export type DocumentSimilarityQueryResponse = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<EmbeddingDistance>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type DocumentSimilarityQuery = {
    dateRange: DateRange;
    distance_func: DistanceFunc;
    document_types: Array<string>;
    kind?: "DocumentSimilarityQuery" | undefined;
    limit?: (number | null) | undefined;
    model: string;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    order_by: OrderBy;
    order_direction: OrderDirection;
    origin: EmbeddedDocument;
    products: Array<string>;
    renderings: Array<string>;
    response?: DocumentSimilarityQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    threshold?: (number | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type EvaluationRuntimeEnum = "server" | "client" | "all";
  export type MinimalFeatureFlag = {
    id: number;
    team_id: number;
    name?: string | undefined;
    key: string;
    filters?: Record<string, unknown> | undefined;
    deleted?: boolean | undefined;
    active?: boolean | undefined;
    ensure_experience_continuity?: (boolean | null) | undefined;
    has_encrypted_payloads?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
    evaluation_runtime?: ((EvaluationRuntimeEnum | BlankEnum | NullEnum) | null) | undefined;
    bucketing_identifier?: ((BucketingIdentifierEnum | BlankEnum | NullEnum) | null) | undefined;
    evaluation_tags: Array<string>;
  };
  export type StageEnum = "draft" | "concept" | "alpha" | "beta" | "general-availability" | "archived";
  export type EarlyAccessFeature = {
    id: string;
    feature_flag: MinimalFeatureFlag & unknown;
    name: string;
    description?: string | undefined;
    stage: StageEnum;
    documentation_url?: string | undefined;
    payload: string;
    created_at: string;
  };
  export type EarlyAccessFeatureSerializerCreateOnly = {
    id: string;
    name: string;
    description?: string | undefined;
    stage: StageEnum;
    documentation_url?: string | undefined;
    payload?: unknown | undefined;
    created_at: string;
    feature_flag_id?: number | undefined;
    feature_flag: MinimalFeatureFlag & unknown;
    _create_in_folder?: string | undefined;
  };
  export type EffectiveMembershipLevelEnum = 1 | 8 | 15;
  export type ElementType = {
    attr_class?: (Array<string> | null) | undefined;
    attr_id?: (string | null) | undefined;
    attributes: Record<string, string>;
    href?: (string | null) | undefined;
    nth_child?: (number | null) | undefined;
    nth_of_type?: (number | null) | undefined;
    order?: (number | null) | undefined;
    tag_name: string;
    text?: (string | null) | undefined;
  };
  export type EndpointLastExecutionTimesRequest = { names: Array<string> };
  export type EndpointRefreshMode = "cache" | "force" | "direct";
  export type EndpointRequest = Partial<{
    cache_age_seconds: number | null;
    derived_from_insight: string | null;
    description: string | null;
    is_active: boolean | null;
    is_materialized: boolean | null;
    name: string | null;
    query:
      | (
          | HogQLQuery
          | TrendsQuery
          | FunnelsQuery
          | RetentionQuery
          | PathsQuery
          | StickinessQuery
          | LifecycleQuery
          | WebStatsTableQuery
          | WebOverviewQuery
        )
      | null;
    sync_frequency: DataWarehouseSyncInterval;
    version: number | null;
  }>;
  export type EndpointRunRequest = Partial<{
    client_query_id: string | null;
    debug: boolean | null;
    filters_override: DashboardFilter;
    limit: number | null;
    refresh: EndpointRefreshMode;
    variables: Record<string, unknown> | null;
    version: number | null;
  }>;
  export type EndpointsUsageOverviewItemKey =
    | "total_requests"
    | "total_bytes_read"
    | "total_cpu_seconds"
    | "avg_query_duration_ms"
    | "p95_query_duration_ms"
    | "error_rate"
    | "materialized_requests"
    | "inline_requests";
  export type EndpointsUsageOverviewItem = {
    changeFromPreviousPct?: (number | null) | undefined;
    key: EndpointsUsageOverviewItemKey;
    previous?: (number | null) | undefined;
    value?: (number | null) | undefined;
  };
  export type EndpointsUsageOverviewQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<EndpointsUsageOverviewItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type EndpointsUsageOverviewQuery = Partial<{
    compareFilter: CompareFilter;
    dateRange: DateRange;
    endpointNames: Array<string> | null;
    kind: "EndpointsUsageOverviewQuery";
    materializationType: MaterializationType;
    modifiers: HogQLQueryModifiers;
    response: EndpointsUsageOverviewQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type Metric = "bytes_read" | "cpu_seconds" | "requests" | "query_duration" | "error_rate";
  export type EndpointsUsageTrendsQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type EndpointsUsageTrendsQuery = {
    breakdownBy?: EndpointsUsageBreakdown | undefined;
    compareFilter?: CompareFilter | undefined;
    dateRange?: DateRange | undefined;
    endpointNames?: (Array<string> | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "EndpointsUsageTrendsQuery" | undefined;
    materializationType?: MaterializationType | undefined;
    metric: Metric;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: EndpointsUsageTrendsQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type EnterpriseEventDefinition = {
    id: string;
    name: string;
    owner?: (number | null) | undefined;
    description?: (string | null) | undefined;
    tags?: Array<unknown> | undefined;
    created_at: string | null;
    updated_at: string;
    updated_by: UserBasic & unknown;
    last_seen_at: string | null;
    last_updated_at: string;
    verified?: boolean | undefined;
    verified_at: string | null;
    verified_by: UserBasic & unknown;
    hidden?: (boolean | null) | undefined;
    is_action: boolean;
    action_id: number;
    is_calculating: boolean;
    last_calculated_at: string;
    created_by: UserBasic & unknown;
    post_to_slack?: boolean | undefined;
    default_columns?: Array<string> | undefined;
  };
  export type PropertyTypeEnum = "DateTime" | "String" | "Numeric" | "Boolean" | "Duration";
  export type EnterprisePropertyDefinition = {
    id: string;
    name: string;
    description?: (string | null) | undefined;
    tags?: Array<unknown> | undefined;
    is_numerical: boolean;
    updated_at: string;
    updated_by: UserBasic & unknown;
    is_seen_on_filtered_events: boolean | null;
    property_type?: ((PropertyTypeEnum | BlankEnum | NullEnum) | null) | undefined;
    verified?: boolean | undefined;
    verified_at: string | null;
    verified_by: UserBasic & unknown;
    hidden?: (boolean | null) | undefined;
  };
  export type EnvironmentEnum = "local" | "cloud";
  export type ErrorResponse = { error: string };
  export type ErrorTrackingAssignmentRule = {
    id: string;
    filters: unknown;
    assignee: string;
    order_key: number;
    disabled_data?: (unknown | null) | undefined;
  };
  export type LibraryEnum = "web";
  export type MatchTypeEnum = "all" | "any";
  export type ErrorTrackingAutoCaptureControls = {
    id: string;
    library: LibraryEnum & unknown;
    match_type?: MatchTypeEnum | undefined;
    sample_rate?: string | undefined;
    linked_feature_flag?: (unknown | null) | undefined;
    event_triggers?: (Array<string | null> | null) | undefined;
    url_triggers?: (Array<unknown | null> | null) | undefined;
    url_blocklist?: (Array<unknown | null> | null) | undefined;
  };
  export type Results = { total_count: number; values: Array<BreakdownValue> };
  export type ErrorTrackingBreakdownsQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Record<string, unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type ErrorTrackingBreakdownsQuery = {
    breakdownProperties: Array<string>;
    dateRange?: DateRange | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    issueId: string;
    kind?: "ErrorTrackingBreakdownsQuery" | undefined;
    maxValuesPerProperty?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: ErrorTrackingBreakdownsQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type ErrorTrackingFingerprint = { fingerprint: string; issue_id: string; created_at: string };
  export type ErrorTrackingGroupingRule = {
    id: string;
    filters: unknown;
    assignee: string;
    order_key: number;
    disabled_data?: (unknown | null) | undefined;
  };
  export type ErrorTrackingRelease = {
    id: string;
    hash_id: string;
    team_id: number;
    created_at: string;
    metadata?: (unknown | null) | undefined;
    version: string;
    project: string;
  };
  export type SimilarIssue = {
    description: string;
    distance: number;
    first_seen: string;
    id: string;
    library?: (string | null) | undefined;
    name: string;
    status: string;
  };
  export type ErrorTrackingSimilarIssuesQueryResponse = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<SimilarIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type ErrorTrackingSimilarIssuesQuery = {
    dateRange?: DateRange | undefined;
    issueId: string;
    kind?: "ErrorTrackingSimilarIssuesQuery" | undefined;
    limit?: (number | null) | undefined;
    maxDistance?: (number | null) | undefined;
    modelName?: EmbeddingModelName | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    rendering?: (string | null) | undefined;
    response?: ErrorTrackingSimilarIssuesQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type ErrorTrackingSuppressionRule = { id: string; filters: unknown; order_key: number };
  export type ErrorTrackingSymbolSet = {
    id: string;
    ref: string;
    team_id: number;
    created_at: string;
    last_used?: (string | null) | undefined;
    storage_ptr?: (string | null) | undefined;
    failure_reason?: (string | null) | undefined;
    release: string;
  };
  export type EvaluationTypeEnum = "llm_judge";
  export type OutputTypeEnum = "boolean";
  export type ProviderEnum = "openai" | "anthropic" | "gemini" | "openrouter";
  export type ModelConfiguration = {
    provider: ProviderEnum;
    model: string;
    provider_key_id?: (string | null) | undefined;
    provider_key_name: string | null;
  };
  export type Evaluation = {
    id: string;
    name: string;
    description?: string | undefined;
    enabled?: boolean | undefined;
    evaluation_type: EvaluationTypeEnum;
    evaluation_config?: unknown | undefined;
    output_type: OutputTypeEnum;
    output_config?: unknown | undefined;
    conditions?: unknown | undefined;
    model_configuration?: ((ModelConfiguration & (unknown | null)) | null) | undefined;
    created_at: string;
    updated_at: string;
    created_by: UserBasic & unknown;
    deleted?: boolean | undefined;
  };
  export type EvaluationPattern = {
    title: string;
    description: string;
    frequency: string;
    example_reasoning: string;
    example_generation_ids: Array<string>;
  };
  export type FilterEnum = "all" | "pass" | "fail" | "na";
  export type EvaluationSummaryRequest = {
    evaluation_id: string;
    filter?: (FilterEnum & unknown) | undefined;
    generation_ids?: Array<string> | undefined;
    force_refresh?: boolean | undefined;
  };
  export type EvaluationSummaryStatistics = {
    total_analyzed: number;
    pass_count: number;
    fail_count: number;
    na_count: number;
  };
  export type EvaluationSummaryResponse = {
    overall_assessment: string;
    pass_patterns: Array<EvaluationPattern>;
    fail_patterns: Array<EvaluationPattern>;
    na_patterns: Array<EvaluationPattern>;
    recommendations: Array<string>;
    statistics: EvaluationSummaryStatistics;
  };
  export type EventTaxonomyItem = { property: string; sample_count: number; sample_values: Array<string> };
  export type EventTaxonomyQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<EventTaxonomyItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type EventTaxonomyQuery = Partial<{
    actionId: number | null;
    event: string | null;
    kind: "EventTaxonomyQuery";
    maxPropertyValues: number | null;
    modifiers: HogQLQueryModifiers;
    properties: Array<string> | null;
    response: EventTaxonomyQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type Person = {
    id: number;
    name: string;
    distinct_ids: Array<string>;
    properties?: unknown | undefined;
    created_at: string;
    uuid: string;
  };
  export type EventType = {
    distinct_id: string;
    elements: Array<ElementType>;
    elements_chain?: (string | null) | undefined;
    event: string;
    id: string;
    person?: Person | undefined;
    person_id?: (string | null) | undefined;
    person_mode?: (string | null) | undefined;
    properties: Record<string, unknown>;
    timestamp: string;
    uuid?: (string | null) | undefined;
  };
  export type EventTypeEnum = "$ai_generation" | "$ai_span" | "$ai_embedding" | "$ai_trace";
  export type ExperimentHoldout = {
    id: number;
    name: string;
    description?: (string | null) | undefined;
    filters?: unknown | undefined;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
  };
  export type ExperimentToSavedMetric = {
    id: number;
    experiment: number;
    saved_metric: number;
    metadata?: unknown | undefined;
    created_at: string;
    query: unknown;
    name: string;
  };
  export type ExperimentTypeEnum = "web" | "product";
  export type Experiment = {
    id: number;
    name: string;
    description?: (string | null) | undefined;
    start_date?: (string | null) | undefined;
    end_date?: (string | null) | undefined;
    feature_flag_key: string;
    feature_flag: MinimalFeatureFlag & unknown;
    holdout: ExperimentHoldout & unknown;
    holdout_id?: (number | null) | undefined;
    exposure_cohort: number | null;
    parameters?: (unknown | null) | undefined;
    secondary_metrics?: (unknown | null) | undefined;
    saved_metrics: Array<ExperimentToSavedMetric>;
    saved_metrics_ids?: (Array<unknown> | null) | undefined;
    filters?: unknown | undefined;
    archived?: boolean | undefined;
    deleted?: (boolean | null) | undefined;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
    type?: ((ExperimentTypeEnum | BlankEnum | NullEnum) | null) | undefined;
    exposure_criteria?: (unknown | null) | undefined;
    metrics?: (unknown | null) | undefined;
    metrics_secondary?: (unknown | null) | undefined;
    stats_config?: (unknown | null) | undefined;
    scheduling_config?: (unknown | null) | undefined;
    _create_in_folder?: string | undefined;
    conclusion?: ((ConclusionEnum | BlankEnum | NullEnum) | null) | undefined;
    conclusion_comment?: (string | null) | undefined;
    primary_metrics_ordered_uuids?: (unknown | null) | undefined;
    secondary_metrics_ordered_uuids?: (unknown | null) | undefined;
    user_access_level: string | null;
  };
  export type SessionData = { event_uuid: string; person_id: string; session_id: string; timestamp: string };
  export type ExperimentStatsValidationFailure =
    | "not-enough-exposures"
    | "baseline-mean-is-zero"
    | "not-enough-metric-data";
  export type ExperimentStatsBaseValidated = {
    denominator_sum?: (number | null) | undefined;
    denominator_sum_squares?: (number | null) | undefined;
    key: string;
    number_of_samples: number;
    numerator_denominator_sum_product?: (number | null) | undefined;
    step_counts?: (Array<number> | null) | undefined;
    step_sessions?: (Array<Array<SessionData>> | null) | undefined;
    sum: number;
    sum_squares: number;
    validation_failures?: (Array<ExperimentStatsValidationFailure> | null) | undefined;
  };
  export type ExperimentVariantResultFrequentist = {
    confidence_interval?: (Array<number> | null) | undefined;
    denominator_sum?: (number | null) | undefined;
    denominator_sum_squares?: (number | null) | undefined;
    key: string;
    method?: "frequentist" | undefined;
    number_of_samples: number;
    numerator_denominator_sum_product?: (number | null) | undefined;
    p_value?: (number | null) | undefined;
    significant?: (boolean | null) | undefined;
    step_counts?: (Array<number> | null) | undefined;
    step_sessions?: (Array<Array<SessionData>> | null) | undefined;
    sum: number;
    sum_squares: number;
    validation_failures?: (Array<ExperimentStatsValidationFailure> | null) | undefined;
  };
  export type ExperimentVariantResultBayesian = {
    chance_to_win?: (number | null) | undefined;
    credible_interval?: (Array<number> | null) | undefined;
    denominator_sum?: (number | null) | undefined;
    denominator_sum_squares?: (number | null) | undefined;
    key: string;
    method?: "bayesian" | undefined;
    number_of_samples: number;
    numerator_denominator_sum_product?: (number | null) | undefined;
    significant?: (boolean | null) | undefined;
    step_counts?: (Array<number> | null) | undefined;
    step_sessions?: (Array<Array<SessionData>> | null) | undefined;
    sum: number;
    sum_squares: number;
    validation_failures?: (Array<ExperimentStatsValidationFailure> | null) | undefined;
  };
  export type ExperimentBreakdownResult = {
    baseline: ExperimentStatsBaseValidated;
    breakdown_value: Array<string | number | number>;
    variants: Array<ExperimentVariantResultFrequentist> | Array<ExperimentVariantResultBayesian>;
  };
  export type ExperimentDataWarehouseNode = {
    custom_name?: (string | null) | undefined;
    data_warehouse_join_key: string;
    events_join_key: string;
    fixedProperties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    kind?: "ExperimentDataWarehouseNode" | undefined;
    math?:
      | (
          | (
              | BaseMathType
              | FunnelMathType
              | PropertyMathType
              | CountPerActorMathType
              | ExperimentMetricMathType
              | CalendarHeatmapMathType
              | "unique_group"
              | "hogql"
            )
          | null
        )
      | undefined;
    math_group_type_index?: MathGroupTypeIndex | undefined;
    math_hogql?: (string | null) | undefined;
    math_multiplier?: (number | null) | undefined;
    math_property?: (string | null) | undefined;
    math_property_revenue_currency?: RevenueCurrencyPropertyConfig | undefined;
    math_property_type?: (string | null) | undefined;
    name?: (string | null) | undefined;
    optionalInFunnel?: (boolean | null) | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    table_name: string;
    timestamp_field: string;
    version?: (number | null) | undefined;
  };
  export type ExperimentEventExposureConfig = {
    event: string;
    kind?: "ExperimentEventExposureConfig" | undefined;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    >;
    response?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type MultipleVariantHandling = "exclude" | "first_seen";
  export type ExperimentExposureCriteria = Partial<{
    exposure_config: (ExperimentEventExposureConfig | ActionsNode) | null;
    filterTestAccounts: boolean | null;
    multiple_variant_handling: MultipleVariantHandling;
  }>;
  export type FeatureFlagGroupType = Partial<{
    description: string | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    rollout_percentage: number | null;
    sort_key: string | null;
    users_affected: number | null;
    variant: string | null;
  }>;
  export type ExperimentHoldoutType = {
    created_at?: (string | null) | undefined;
    created_by?: UserBasicType | undefined;
    description?: (string | null) | undefined;
    filters: Array<FeatureFlagGroupType>;
    id?: (number | null) | undefined;
    name: string;
    updated_at?: (string | null) | undefined;
  };
  export type SampleRatioMismatch = { expected: Record<string, number>; p_value: number };
  export type ExperimentExposureTimeSeries = { days: Array<string>; exposure_counts: Array<number>; variant: string };
  export type ExperimentExposureQueryResponse = {
    date_range: DateRange;
    kind?: "ExperimentExposureQuery" | undefined;
    sample_ratio_mismatch?: SampleRatioMismatch | undefined;
    timeseries: Array<ExperimentExposureTimeSeries>;
    total_exposures: Record<string, number>;
  };
  export type ExperimentExposureQuery = {
    end_date?: (string | null) | undefined;
    experiment_id?: (number | null) | undefined;
    experiment_name: string;
    exposure_criteria?: ExperimentExposureCriteria | undefined;
    feature_flag: Record<string, unknown>;
    holdout?: ExperimentHoldoutType | undefined;
    kind?: "ExperimentExposureQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: ExperimentExposureQueryResponse | undefined;
    start_date?: (string | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type ExperimentMetricGoal = "increase" | "decrease";
  export type ExperimentFunnelMetric = {
    breakdownFilter?: BreakdownFilter | undefined;
    conversion_window?: (number | null) | undefined;
    conversion_window_unit?: FunnelConversionWindowTimeUnit | undefined;
    fingerprint?: (string | null) | undefined;
    funnel_order_type?: StepOrderValue | undefined;
    goal?: ExperimentMetricGoal | undefined;
    isSharedMetric?: (boolean | null) | undefined;
    kind?: "ExperimentMetric" | undefined;
    metric_type?: "funnel" | undefined;
    name?: (string | null) | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    series: Array<EventsNode | ActionsNode>;
    sharedMetricId?: (number | null) | undefined;
    uuid?: (string | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type ExperimentMeanMetric = {
    breakdownFilter?: BreakdownFilter | undefined;
    conversion_window?: (number | null) | undefined;
    conversion_window_unit?: FunnelConversionWindowTimeUnit | undefined;
    fingerprint?: (string | null) | undefined;
    goal?: ExperimentMetricGoal | undefined;
    ignore_zeros?: (boolean | null) | undefined;
    isSharedMetric?: (boolean | null) | undefined;
    kind?: "ExperimentMetric" | undefined;
    lower_bound_percentile?: (number | null) | undefined;
    metric_type?: "mean" | undefined;
    name?: (string | null) | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    sharedMetricId?: (number | null) | undefined;
    source: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
    upper_bound_percentile?: (number | null) | undefined;
    uuid?: (string | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type ExperimentRatioMetric = {
    breakdownFilter?: BreakdownFilter | undefined;
    conversion_window?: (number | null) | undefined;
    conversion_window_unit?: FunnelConversionWindowTimeUnit | undefined;
    denominator: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
    fingerprint?: (string | null) | undefined;
    goal?: ExperimentMetricGoal | undefined;
    isSharedMetric?: (boolean | null) | undefined;
    kind?: "ExperimentMetric" | undefined;
    metric_type?: "ratio" | undefined;
    name?: (string | null) | undefined;
    numerator: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
    response?: (Record<string, unknown> | null) | undefined;
    sharedMetricId?: (number | null) | undefined;
    uuid?: (string | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type StartHandling = "first_seen" | "last_seen";
  export type ExperimentRetentionMetric = {
    breakdownFilter?: BreakdownFilter | undefined;
    completion_event: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
    conversion_window?: (number | null) | undefined;
    conversion_window_unit?: FunnelConversionWindowTimeUnit | undefined;
    fingerprint?: (string | null) | undefined;
    goal?: ExperimentMetricGoal | undefined;
    isSharedMetric?: (boolean | null) | undefined;
    kind?: "ExperimentMetric" | undefined;
    metric_type?: "retention" | undefined;
    name?: (string | null) | undefined;
    response?: (Record<string, unknown> | null) | undefined;
    retention_window_end: number;
    retention_window_start: number;
    retention_window_unit: FunnelConversionWindowTimeUnit;
    sharedMetricId?: (number | null) | undefined;
    start_event: EventsNode | ActionsNode | ExperimentDataWarehouseNode;
    start_handling: StartHandling;
    uuid?: (string | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type ExperimentQueryResponse = Partial<{
    baseline: ExperimentStatsBaseValidated;
    breakdown_results: Array<ExperimentBreakdownResult> | null;
    clickhouse_sql: string | null;
    credible_intervals: Record<string, Array<number>> | null;
    hogql: string | null;
    insight: Array<Record<string, unknown>> | null;
    kind: "ExperimentQuery";
    metric: (ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric) | null;
    p_value: number | null;
    probability: Record<string, number> | null;
    significance_code: ExperimentSignificanceCode;
    significant: boolean | null;
    stats_version: number | null;
    variant_results: (Array<ExperimentVariantResultFrequentist> | Array<ExperimentVariantResultBayesian>) | null;
    variants: (Array<ExperimentVariantTrendsBaseStats> | Array<ExperimentVariantFunnelsBaseStats>) | null;
  }>;
  export type ExperimentQuery = {
    experiment_id?: (number | null) | undefined;
    kind?: "ExperimentQuery" | undefined;
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric;
    modifiers?: HogQLQueryModifiers | undefined;
    name?: (string | null) | undefined;
    response?: ExperimentQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type ExperimentSavedMetric = {
    id: number;
    name: string;
    description?: (string | null) | undefined;
    query: unknown;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
    tags?: Array<unknown> | undefined;
    user_access_level: string | null;
  };
  export type ExplainRequest = { uuid: string; timestamp: string; force_refresh?: boolean | undefined };
  export type ExportFormatEnum =
    | "image/png"
    | "application/pdf"
    | "text/csv"
    | "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    | "video/webm"
    | "video/mp4"
    | "image/gif"
    | "application/json";
  export type ExportedAsset = {
    id: number;
    dashboard?: (number | null) | undefined;
    insight?: (number | null) | undefined;
    export_format: ExportFormatEnum;
    created_at: string;
    has_content: string;
    export_context?: (unknown | null) | undefined;
    filename: string;
    expires_after: string | null;
    exception: string | null;
  };
  export type ExternalDataSourceRevenueAnalyticsConfig = Partial<{
    enabled: boolean;
    include_invoiceless_charges: boolean;
  }>;
  export type SourceTypeEnum =
    | "Ashby"
    | "Supabase"
    | "CustomerIO"
    | "Github"
    | "Stripe"
    | "Hubspot"
    | "Postgres"
    | "Zendesk"
    | "Snowflake"
    | "Salesforce"
    | "MySQL"
    | "MongoDB"
    | "MSSQL"
    | "Vitally"
    | "BigQuery"
    | "Chargebee"
    | "Clerk"
    | "GoogleAds"
    | "TemporalIO"
    | "DoIt"
    | "GoogleSheets"
    | "MetaAds"
    | "Klaviyo"
    | "Mailchimp"
    | "Braze"
    | "Mailjet"
    | "Redshift"
    | "Polar"
    | "RevenueCat"
    | "LinkedinAds"
    | "RedditAds"
    | "TikTokAds"
    | "BingAds"
    | "Shopify"
    | "Attio"
    | "SnapchatAds";
  export type ExternalDataSourceSerializers = {
    id: string;
    created_at: string;
    created_by: string | null;
    status: string;
    client_secret: string;
    account_id: string;
    source_type: SourceTypeEnum & unknown;
    latest_error: string;
    prefix: string | null;
    description?: (string | null) | undefined;
    last_run_at: string;
    schemas: string;
    job_inputs?: (unknown | null) | undefined;
    revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfig & unknown;
    user_access_level: string | null;
  };
  export type ExternalQueryErrorCode = "platform_access_required" | "query_execution_failed";
  export type ExternalQueryError = { code: ExternalQueryErrorCode; detail: string };
  export type ExternalQueryStatus = "success" | "error";
  export type FeatureFlagCreationContextEnum =
    | "feature_flags"
    | "experiments"
    | "surveys"
    | "early_access_features"
    | "web_experiments"
    | "product_tours";
  export type FeatureFlag = {
    id: number;
    name?: string | undefined;
    key: string;
    filters?: Record<string, unknown> | undefined;
    deleted?: boolean | undefined;
    active?: boolean | undefined;
    created_by: UserBasic & unknown;
    created_at?: string | undefined;
    updated_at: string | null;
    version?: number | undefined;
    last_modified_by: UserBasic & unknown;
    ensure_experience_continuity?: (boolean | null) | undefined;
    experiment_set: string;
    surveys: Record<string, unknown>;
    features: Record<string, unknown>;
    rollback_conditions?: (unknown | null) | undefined;
    performed_rollback?: (boolean | null) | undefined;
    can_edit: boolean;
    tags?: Array<unknown> | undefined;
    evaluation_tags?: Array<unknown> | undefined;
    usage_dashboard: number;
    analytics_dashboards?: Array<number> | undefined;
    has_enriched_analytics?: (boolean | null) | undefined;
    user_access_level: string | null;
    creation_context?: (FeatureFlagCreationContextEnum & unknown) | undefined;
    is_remote_configuration?: (boolean | null) | undefined;
    has_encrypted_payloads?: (boolean | null) | undefined;
    status: string;
    evaluation_runtime?: ((EvaluationRuntimeEnum | BlankEnum | NullEnum) | null) | undefined;
    bucketing_identifier?: ((BucketingIdentifierEnum | BlankEnum | NullEnum) | null) | undefined;
    last_called_at?: (string | null) | undefined;
    _create_in_folder?: string | undefined;
    _should_create_usage_dashboard?: boolean | undefined;
  };
  export type FileSystem = {
    id: string;
    path: string;
    depth: number | null;
    type?: string | undefined;
    ref?: (string | null) | undefined;
    href?: (string | null) | undefined;
    meta?: (unknown | null) | undefined;
    shortcut?: (boolean | null) | undefined;
    created_at: string;
    last_viewed_at: string | null;
  };
  export type FileSystemShortcut = {
    id: string;
    path: string;
    type?: string | undefined;
    ref?: (string | null) | undefined;
    href?: (string | null) | undefined;
    created_at: string;
  };
  export type FrequencyEnum = "daily" | "weekly" | "monthly" | "yearly";
  export type Group = {
    group_type_index: number;
    group_key: string;
    group_properties?: unknown | undefined;
    created_at: string;
  };
  export type GroupType = {
    group_type: string;
    group_type_index: number;
    name_singular?: (string | null) | undefined;
    name_plural?: (string | null) | undefined;
    detail_dashboard?: (number | null) | undefined;
    default_columns?: (Array<string> | null) | undefined;
    created_at?: (string | null) | undefined;
  };
  export type GroupUsageMetricFormatEnum = "numeric" | "currency";
  export type GroupUsageMetric = {
    id: string;
    name: string;
    format?: GroupUsageMetricFormatEnum | undefined;
    interval?: number | undefined;
    display?: DisplayEnum | undefined;
    filters: unknown;
  };
  export type HogFunctionTypeEnum =
    | "destination"
    | "site_destination"
    | "internal_destination"
    | "source_webhook"
    | "site_app"
    | "transformation";
  export type InputsSchemaItemTypeEnum =
    | "string"
    | "number"
    | "boolean"
    | "dictionary"
    | "choice"
    | "json"
    | "integration"
    | "integration_field"
    | "email"
    | "native_email";
  export type InputsSchemaItemTemplatingEnum = true | false | "hog" | "liquid";
  export type InputsSchemaItem = {
    type: InputsSchemaItemTypeEnum;
    key: string;
    label?: string | undefined;
    choices?: Array<Record<string, unknown>> | undefined;
    required?: boolean | undefined;
    default?: unknown | undefined;
    secret?: boolean | undefined;
    hidden?: boolean | undefined;
    description?: string | undefined;
    integration?: string | undefined;
    integration_key?: string | undefined;
    requires_field?: string | undefined;
    integration_field?: string | undefined;
    requiredScopes?: string | undefined;
    templating?: InputsSchemaItemTemplatingEnum | undefined;
  };
  export type InputsItemTemplatingEnum = "hog" | "liquid";
  export type InputsItem = {
    value?: string | undefined;
    templating?: InputsItemTemplatingEnum | undefined;
    bytecode: Array<unknown>;
    order: number;
    transpiled: unknown;
  };
  export type HogFunctionFiltersSourceEnum = "events" | "person-updates" | "data-warehouse-table";
  export type HogFunctionFilters = Partial<{
    source: HogFunctionFiltersSourceEnum & unknown;
    actions: Array<Record<string, unknown>>;
    events: Array<Record<string, unknown>>;
    data_warehouse: Array<Record<string, unknown>>;
    properties: Array<Record<string, unknown>>;
    bytecode: unknown | null;
    transpiled: unknown;
    filter_test_accounts: boolean;
    bytecode_error: string;
  }>;
  export type HogFunctionMasking = {
    ttl: number;
    threshold?: (number | null) | undefined;
    hash: string;
    bytecode?: (unknown | null) | undefined;
  };
  export type Mappings = Partial<{
    name: string;
    inputs_schema: Array<InputsSchemaItem>;
    inputs: Record<string, unknown>;
    filters: HogFunctionFilters;
  }>;
  export type HogFunctionMappingTemplate = {
    name: string;
    include_by_default?: (boolean | null) | undefined;
    filters?: (unknown | null) | undefined;
    inputs?: (unknown | null) | undefined;
    inputs_schema?: (unknown | null) | undefined;
  };
  export type HogFunctionTemplate = {
    id: string;
    name: string;
    description?: (string | null) | undefined;
    code: string;
    code_language?: string | undefined;
    inputs_schema: unknown;
    type: string;
    status?: string | undefined;
    category?: unknown | undefined;
    free?: boolean | undefined;
    icon_url?: (string | null) | undefined;
    filters?: (unknown | null) | undefined;
    masking?: (unknown | null) | undefined;
    mapping_templates?: (Array<HogFunctionMappingTemplate> | null) | undefined;
  };
  export type HogFunctionStatusStateEnum = 0 | 1 | 2 | 3 | 11 | 12;
  export type HogFunctionStatus = { state: HogFunctionStatusStateEnum; tokens: number };
  export type HogFunction = {
    id: string;
    type?: ((HogFunctionTypeEnum | NullEnum) | null) | undefined;
    name?: (string | null) | undefined;
    description?: string | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    updated_at: string;
    enabled?: boolean | undefined;
    deleted?: boolean | undefined;
    hog?: string | undefined;
    bytecode: unknown | null;
    transpiled: string | null;
    inputs_schema?: Array<InputsSchemaItem> | undefined;
    inputs?: Record<string, unknown> | undefined;
    filters?: HogFunctionFilters | undefined;
    masking?: ((HogFunctionMasking & (unknown | null)) | null) | undefined;
    mappings?: (Array<Mappings> | null) | undefined;
    icon_url?: (string | null) | undefined;
    template: HogFunctionTemplate & unknown;
    template_id?: (string | null) | undefined;
    status: (HogFunctionStatus & (unknown | null)) | null;
    execution_order?: (number | null) | undefined;
    _create_in_folder?: string | undefined;
    batch_export_id: string | null;
  };
  export type HogFunctionMinimal = {
    id: string;
    type: string | null;
    name: string | null;
    description: string;
    created_at: string;
    created_by: UserBasic & unknown;
    updated_at: string;
    enabled: boolean;
    hog: string;
    filters: unknown | null;
    icon_url: string | null;
    template: HogFunctionTemplate & unknown;
    status: (HogFunctionStatus & (unknown | null)) | null;
    execution_order: number | null;
  };
  export type HogLanguage = "hog" | "hogJson" | "hogQL" | "hogQLExpr" | "hogTemplate" | "liquid";
  export type HogQLASTQuery = {
    explain?: (boolean | null) | undefined;
    filters?: HogQLFilters | undefined;
    kind?: "HogQLASTQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    name?: (string | null) | undefined;
    query: Record<string, unknown>;
    response?: HogQLQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    values?: (Record<string, unknown> | null) | undefined;
    variables?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type HogQLAutocompleteResponse = {
    incomplete_list: boolean;
    suggestions: Array<AutocompleteCompletionItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type MultipleBreakdownOptions = { values: Array<BreakdownItem> };
  export type IntervalItem = { label: string; value: number };
  export type Series = { label: string; value: number };
  export type StatusItem = { label: string; value: string };
  export type InsightActorsQueryOptionsResponse = Partial<{
    breakdown: Array<BreakdownItem> | null;
    breakdowns: Array<MultipleBreakdownOptions> | null;
    compare: Array<CompareItem> | null;
    day: Array<DayItem> | null;
    interval: Array<IntervalItem> | null;
    series: Array<Series> | null;
    status: Array<StatusItem> | null;
  }>;
  export type InsightActorsQueryOptions = {
    kind?: "InsightActorsQueryOptions" | undefined;
    response?: InsightActorsQueryOptionsResponse | undefined;
    source: InsightActorsQuery | FunnelsActorsQuery | FunnelCorrelationActorsQuery | StickinessActorsQuery;
    version?: (number | null) | undefined;
  };
  export type TimelineEntry = {
    events: Array<EventType>;
    recording_duration_s?: (number | null) | undefined;
    sessionId?: (string | null) | undefined;
  };
  export type SessionsTimelineQueryResponse = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<TimelineEntry>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type SessionsTimelineQuery = Partial<{
    after: string | null;
    before: string | null;
    kind: "SessionsTimelineQuery";
    modifiers: HogQLQueryModifiers;
    personId: string | null;
    response: SessionsTimelineQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type HogQueryResponse = {
    bytecode?: (Array<unknown> | null) | undefined;
    coloredBytecode?: (Array<unknown> | null) | undefined;
    results: unknown;
    stdout?: (string | null) | undefined;
  };
  export type HogQuery = Partial<{
    code: string | null;
    kind: "HogQuery";
    modifiers: HogQLQueryModifiers;
    response: HogQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type PageURL = { url: string };
  export type WebPageURLSearchQueryResponse = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<PageURL>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type WebPageURLSearchQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval?: IntervalType | undefined;
    kind?: "WebPageURLSearchQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebPageURLSearchQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    searchTerm?: (string | null) | undefined;
    stripQueryParams?: (boolean | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type WebTrendsMetric =
    | "UniqueUsers"
    | "PageViews"
    | "Sessions"
    | "Bounces"
    | "SessionDuration"
    | "TotalSessions";
  export type Metrics = Partial<{
    Bounces: number | null;
    PageViews: number | null;
    SessionDuration: number | null;
    Sessions: number | null;
    TotalSessions: number | null;
    UniqueUsers: number | null;
  }>;
  export type WebTrendsItem = { bucket: string; metrics: Metrics };
  export type WebTrendsQueryResponse = {
    clickhouse?: (string | null) | undefined;
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    explain?: (Array<string> | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    metadata?: HogQLMetadataResponse | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query?: (string | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebTrendsItem>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type WebTrendsQuery = {
    aggregation_group_type_index?: (number | null) | undefined;
    compareFilter?: CompareFilter | undefined;
    conversionGoal?: ((ActionConversionGoal | CustomEventConversionGoal) | null) | undefined;
    dataColorTheme?: (number | null) | undefined;
    dateRange?: DateRange | undefined;
    doPathCleaning?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    includeRevenue?: (boolean | null) | undefined;
    interval: IntervalType;
    kind?: "WebTrendsQuery" | undefined;
    limit?: (number | null) | undefined;
    metrics: Array<WebTrendsMetric>;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null) | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebTrendsQueryResponse | undefined;
    sampling?: WebAnalyticsSampling | undefined;
    samplingFactor?: (number | null) | undefined;
    tags?: QueryLogTags | undefined;
    useSessionsTable?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type WebAnalyticsExternalSummaryQueryResponse = {
    data: Record<string, unknown>;
    error?: ExternalQueryError | undefined;
    status: ExternalQueryStatus;
  };
  export type WebAnalyticsExternalSummaryQuery = {
    dateRange: DateRange;
    kind?: "WebAnalyticsExternalSummaryQuery" | undefined;
    properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>;
    response?: WebAnalyticsExternalSummaryQueryResponse | undefined;
    version?: (number | null) | undefined;
  };
  export type OrderBy3 = "latest" | "earliest";
  export type LogsQueryResponse = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    nextCursor?: (string | null) | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type LogSeverityLevel = "trace" | "debug" | "info" | "warn" | "error" | "fatal";
  export type LogsSparklineBreakdownBy = "severity" | "service";
  export type LogsQuery = {
    after?: (string | null) | undefined;
    dateRange: DateRange;
    filterGroup: PropertyGroupFilter;
    kind?: "LogsQuery" | undefined;
    limit?: (number | null) | undefined;
    liveLogsCheckpoint?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    orderBy?: OrderBy3 | undefined;
    resourceFingerprint?: (string | null) | undefined;
    response?: LogsQueryResponse | undefined;
    searchTerm?: (string | null) | undefined;
    serviceNames: Array<string>;
    severityLevels: Array<LogSeverityLevel>;
    sparklineBreakdownBy?: LogsSparklineBreakdownBy | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type LogAttributesQueryResponse = {
    count: number;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type LogAttributesQuery = {
    attributeType: string;
    dateRange?: DateRange | undefined;
    filterGroup?: PropertyGroupFilter | undefined;
    kind?: "LogAttributesQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    response?: LogAttributesQueryResponse | undefined;
    search?: (string | null) | undefined;
    serviceNames?: (Array<string> | null) | undefined;
    severityLevels?: (Array<LogSeverityLevel> | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type LogValueResult = { id: string; name: string };
  export type LogValuesQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<LogValueResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type LogValuesQuery = {
    attributeKey: string;
    attributeType: string;
    dateRange?: DateRange | undefined;
    filterGroup?: PropertyGroupFilter | undefined;
    kind?: "LogValuesQuery" | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    response?: LogValuesQueryResponse | undefined;
    search?: (string | null) | undefined;
    serviceNames?: (Array<string> | null) | undefined;
    severityLevels?: (Array<LogSeverityLevel> | null) | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type RecordingOrder =
    | "duration"
    | "recording_duration"
    | "inactive_seconds"
    | "active_seconds"
    | "start_time"
    | "console_error_count"
    | "click_count"
    | "keypress_count"
    | "mouse_activity_count"
    | "activity_score"
    | "recording_ttl";
  export type RecordingOrderDirection = "ASC" | "DESC";
  export type IntegrationKindEnum =
    | "slack"
    | "salesforce"
    | "hubspot"
    | "google-pubsub"
    | "google-cloud-storage"
    | "google-ads"
    | "google-sheets"
    | "snapchat"
    | "linkedin-ads"
    | "reddit-ads"
    | "tiktok-ads"
    | "bing-ads"
    | "intercom"
    | "email"
    | "linear"
    | "github"
    | "gitlab"
    | "meta-ads"
    | "twilio"
    | "clickup"
    | "vercel"
    | "databricks"
    | "azure-blob"
    | "firebase"
    | "jira";
  export type Integration = {
    id: number;
    kind: IntegrationKindEnum;
    config?: unknown | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    errors: string;
    display_name: string;
  };
  export type SessionRecordingExternalReference = {
    external_url: string;
    id: string;
    integration: Integration;
    issue_id: string;
    metadata?: (Record<string, string> | null) | undefined;
    title: string;
  };
  export type MatchedRecordingEvent = { timestamp: string; uuid: string };
  export type MatchedRecording = { events: Array<MatchedRecordingEvent>; session_id?: (string | null) | undefined };
  export type PersonType = {
    created_at?: (string | null) | undefined;
    distinct_ids: Array<string>;
    id?: (string | null) | undefined;
    is_identified?: (boolean | null) | undefined;
    name?: (string | null) | undefined;
    properties: Record<string, unknown>;
    uuid?: (string | null) | undefined;
  };
  export type SnapshotSource = "web" | "mobile" | "unknown";
  export type SessionRecordingType = {
    active_seconds?: (number | null) | undefined;
    activity_score?: (number | null) | undefined;
    click_count?: (number | null) | undefined;
    console_error_count?: (number | null) | undefined;
    console_log_count?: (number | null) | undefined;
    console_warn_count?: (number | null) | undefined;
    distinct_id?: (string | null) | undefined;
    email?: (string | null) | undefined;
    end_time: string;
    expiry_time?: (string | null) | undefined;
    external_references?: (Array<SessionRecordingExternalReference> | null) | undefined;
    id: string;
    inactive_seconds?: (number | null) | undefined;
    keypress_count?: (number | null) | undefined;
    matching_events?: (Array<MatchedRecording> | null) | undefined;
    mouse_activity_count?: (number | null) | undefined;
    ongoing?: (boolean | null) | undefined;
    person?: PersonType | undefined;
    recording_duration: number;
    recording_ttl?: (number | null) | undefined;
    retention_period_days?: (number | null) | undefined;
    snapshot_library?: (string | null) | undefined;
    snapshot_source: SnapshotSource;
    start_time: string;
    start_url?: (string | null) | undefined;
    summary?: (string | null) | undefined;
    viewed: boolean;
    viewers: Array<string>;
  };
  export type RecordingsQueryResponse = {
    has_next: boolean;
    next_cursor?: (string | null) | undefined;
    results: Array<SessionRecordingType>;
  };
  export type RecordingsQuery = Partial<{
    actions: Array<Record<string, unknown>> | null;
    after: string | null;
    comment_text: RecordingPropertyFilter;
    console_log_filters: Array<LogEntryPropertyFilter> | null;
    date_from: string | null;
    date_to: string | null;
    distinct_ids: Array<string> | null;
    events: Array<Record<string, unknown>> | null;
    filter_test_accounts: boolean | null;
    having_predicates: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    kind: "RecordingsQuery";
    limit: number | null;
    modifiers: HogQLQueryModifiers;
    offset: number | null;
    operand: FilterLogicalOperator;
    order: RecordingOrder;
    order_direction: RecordingOrderDirection;
    person_uuid: string | null;
    properties: Array<
      | EventPropertyFilter
      | PersonPropertyFilter
      | ElementPropertyFilter
      | EventMetadataPropertyFilter
      | SessionPropertyFilter
      | CohortPropertyFilter
      | RecordingPropertyFilter
      | LogEntryPropertyFilter
      | GroupPropertyFilter
      | FeaturePropertyFilter
      | FlagPropertyFilter
      | HogQLPropertyFilter
      | EmptyPropertyFilter
      | DataWarehousePropertyFilter
      | DataWarehousePersonPropertyFilter
      | ErrorTrackingIssueFilter
      | LogPropertyFilter
      | RevenueAnalyticsPropertyFilter
    > | null;
    response: RecordingsQueryResponse;
    session_ids: Array<string> | null;
    session_recording_id: string | null;
    tags: QueryLogTags;
    user_modified_filters: Record<string, unknown> | null;
    version: number | null;
  }>;
  export type TraceNeighborsQueryResponse = Partial<{
    newerTimestamp: string | null;
    newerTraceId: string | null;
    olderTimestamp: string | null;
    olderTraceId: string | null;
    timings: Array<QueryTiming> | null;
  }>;
  export type TraceNeighborsQuery = {
    dateRange?: DateRange | undefined;
    filterSupportTraces?: (boolean | null) | undefined;
    filterTestAccounts?: (boolean | null) | undefined;
    kind?: "TraceNeighborsQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    properties?:
      | (Array<
          | EventPropertyFilter
          | PersonPropertyFilter
          | ElementPropertyFilter
          | EventMetadataPropertyFilter
          | SessionPropertyFilter
          | CohortPropertyFilter
          | RecordingPropertyFilter
          | LogEntryPropertyFilter
          | GroupPropertyFilter
          | FeaturePropertyFilter
          | FlagPropertyFilter
          | HogQLPropertyFilter
          | EmptyPropertyFilter
          | DataWarehousePropertyFilter
          | DataWarehousePersonPropertyFilter
          | ErrorTrackingIssueFilter
          | LogPropertyFilter
          | RevenueAnalyticsPropertyFilter
        > | null)
      | undefined;
    response?: TraceNeighborsQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    timestamp: string;
    traceId: string;
    version?: (number | null) | undefined;
  };
  export type VectorSearchResponseItem = { distance: number; id: string };
  export type VectorSearchQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<VectorSearchResponseItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type VectorSearchQuery = {
    embedding: Array<number>;
    embeddingVersion?: (number | null) | undefined;
    kind?: "VectorSearchQuery" | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    response?: VectorSearchQueryResponse | undefined;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type UsageMetricDisplay = "number" | "sparkline";
  export type UsageMetricFormat = "numeric" | "currency";
  export type UsageMetric = {
    change_from_previous_pct?: (number | null) | undefined;
    display: UsageMetricDisplay;
    format: UsageMetricFormat;
    id: string;
    interval: number;
    name: string;
    previous: number;
    value: number;
  };
  export type UsageMetricsQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<UsageMetric>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type UsageMetricsQuery = Partial<{
    group_key: string | null;
    group_type_index: number | null;
    kind: "UsageMetricsQuery";
    modifiers: HogQLQueryModifiers;
    person_id: string | null;
    response: UsageMetricsQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type HogQLMetadata = {
    debug?: (boolean | null) | undefined;
    filters?: HogQLFilters | undefined;
    globals?: (Record<string, unknown> | null) | undefined;
    kind?: "HogQLMetadata" | undefined;
    language: HogLanguage;
    modifiers?: HogQLQueryModifiers | undefined;
    query: string;
    response?: HogQLMetadataResponse | undefined;
    sourceQuery?:
      | (
          | (
              | EventsNode
              | ActionsNode
              | PersonsNode
              | EventsQuery
              | SessionsQuery
              | ActorsQuery
              | GroupsQuery
              | InsightActorsQuery
              | InsightActorsQueryOptions
              | SessionsTimelineQuery
              | HogQuery
              | HogQLQuery
              | HogQLMetadata
              | HogQLAutocomplete
              | RevenueAnalyticsGrossRevenueQuery
              | RevenueAnalyticsMetricsQuery
              | RevenueAnalyticsMRRQuery
              | RevenueAnalyticsOverviewQuery
              | RevenueAnalyticsTopCustomersQuery
              | MarketingAnalyticsTableQuery
              | MarketingAnalyticsAggregatedQuery
              | NonIntegratedConversionsTableQuery
              | WebOverviewQuery
              | WebStatsTableQuery
              | WebExternalClicksTableQuery
              | WebGoalsQuery
              | WebVitalsQuery
              | WebVitalsPathBreakdownQuery
              | WebPageURLSearchQuery
              | WebTrendsQuery
              | WebAnalyticsExternalSummaryQuery
              | SessionAttributionExplorerQuery
              | RevenueExampleEventsQuery
              | RevenueExampleDataWarehouseTablesQuery
              | ErrorTrackingQuery
              | ErrorTrackingSimilarIssuesQuery
              | ErrorTrackingBreakdownsQuery
              | ErrorTrackingIssueCorrelationQuery
              | LogsQuery
              | LogAttributesQuery
              | LogValuesQuery
              | ExperimentFunnelsQuery
              | ExperimentTrendsQuery
              | CalendarHeatmapQuery
              | RecordingsQuery
              | TracesQuery
              | TraceQuery
              | TraceNeighborsQuery
              | VectorSearchQuery
              | UsageMetricsQuery
              | EndpointsUsageOverviewQuery
              | EndpointsUsageTableQuery
              | EndpointsUsageTrendsQuery
            )
          | null
        )
      | undefined;
    tags?: QueryLogTags | undefined;
    variables?: (Record<string, unknown> | null) | undefined;
    version?: (number | null) | undefined;
  };
  export type HogQLAutocomplete = {
    endPosition: number;
    filters?: HogQLFilters | undefined;
    globals?: (Record<string, unknown> | null) | undefined;
    kind?: "HogQLAutocomplete" | undefined;
    language: HogLanguage;
    modifiers?: HogQLQueryModifiers | undefined;
    query: string;
    response?: HogQLAutocompleteResponse | undefined;
    sourceQuery?:
      | (
          | (
              | EventsNode
              | ActionsNode
              | PersonsNode
              | EventsQuery
              | SessionsQuery
              | ActorsQuery
              | GroupsQuery
              | InsightActorsQuery
              | InsightActorsQueryOptions
              | SessionsTimelineQuery
              | HogQuery
              | HogQLQuery
              | HogQLMetadata
              | HogQLAutocomplete
              | RevenueAnalyticsGrossRevenueQuery
              | RevenueAnalyticsMetricsQuery
              | RevenueAnalyticsMRRQuery
              | RevenueAnalyticsOverviewQuery
              | RevenueAnalyticsTopCustomersQuery
              | MarketingAnalyticsTableQuery
              | MarketingAnalyticsAggregatedQuery
              | NonIntegratedConversionsTableQuery
              | WebOverviewQuery
              | WebStatsTableQuery
              | WebExternalClicksTableQuery
              | WebGoalsQuery
              | WebVitalsQuery
              | WebVitalsPathBreakdownQuery
              | WebPageURLSearchQuery
              | WebTrendsQuery
              | WebAnalyticsExternalSummaryQuery
              | SessionAttributionExplorerQuery
              | RevenueExampleEventsQuery
              | RevenueExampleDataWarehouseTablesQuery
              | ErrorTrackingQuery
              | ErrorTrackingSimilarIssuesQuery
              | ErrorTrackingBreakdownsQuery
              | ErrorTrackingIssueCorrelationQuery
              | LogsQuery
              | LogAttributesQuery
              | LogValuesQuery
              | ExperimentFunnelsQuery
              | ExperimentTrendsQuery
              | CalendarHeatmapQuery
              | RecordingsQuery
              | TracesQuery
              | TraceQuery
              | TraceNeighborsQuery
              | VectorSearchQuery
              | UsageMetricsQuery
              | EndpointsUsageOverviewQuery
              | EndpointsUsageTableQuery
              | EndpointsUsageTrendsQuery
            )
          | null
        )
      | undefined;
    startPosition: number;
    tags?: QueryLogTags | undefined;
    version?: (number | null) | undefined;
  };
  export type Insight = {
    id: number;
    short_id: string;
    name?: (string | null) | undefined;
    derived_name?: (string | null) | undefined;
    query?: (Record<string, unknown> | null) | undefined;
    order?: (number | null) | undefined;
    deleted?: boolean | undefined;
    dashboards?: Array<number> | undefined;
    dashboard_tiles: Array<DashboardTileBasic>;
    last_refresh: string;
    cache_target_age: string;
    next_allowed_client_refresh: string;
    result: string;
    hasMore: string;
    columns: string;
    created_at: string | null;
    created_by: UserBasic & unknown;
    description?: (string | null) | undefined;
    updated_at: string;
    tags?: Array<unknown> | undefined;
    favorited?: boolean | undefined;
    last_modified_at: string;
    last_modified_by: UserBasic & unknown;
    is_sample: boolean;
    effective_restriction_level: EffectiveRestrictionLevelEnum & unknown;
    effective_privilege_level: EffectivePrivilegeLevelEnum & unknown;
    user_access_level: string | null;
    timezone: string;
    is_cached: string;
    query_status: string;
    hogql: string;
    types: string;
    resolved_date_range: string;
    _create_in_folder?: string | undefined;
    alerts: string;
    last_viewed_at: string;
  };
  export type InsightVariableTypeEnum = "String" | "Number" | "Boolean" | "List" | "Date";
  export type InsightVariable = {
    id: string;
    name: string;
    type: InsightVariableTypeEnum;
    default_value?: (unknown | null) | undefined;
    created_by: number | null;
    created_at: string;
    code_name: string | null;
    values?: (unknown | null) | undefined;
  };
  export type RETENTION = Partial<{
    hideLineGraph: boolean | null;
    hideSizeColumn: boolean | null;
    useSmallLayout: boolean | null;
  }>;
  export type VizSpecificOptions = Partial<{ ActionsPie: ActionsPie; RETENTION: RETENTION }>;
  export type InsightVizNode = {
    embedded?: (boolean | null) | undefined;
    full?: (boolean | null) | undefined;
    hidePersonsModal?: (boolean | null) | undefined;
    hideTooltipOnScroll?: (boolean | null) | undefined;
    kind?: "InsightVizNode" | undefined;
    showCorrelationTable?: (boolean | null) | undefined;
    showFilters?: (boolean | null) | undefined;
    showHeader?: (boolean | null) | undefined;
    showLastComputation?: (boolean | null) | undefined;
    showLastComputationRefresh?: (boolean | null) | undefined;
    showResults?: (boolean | null) | undefined;
    showTable?: (boolean | null) | undefined;
    source:
      | TrendsQuery
      | FunnelsQuery
      | RetentionQuery
      | PathsQuery
      | StickinessQuery
      | LifecycleQuery
      | WebStatsTableQuery
      | WebOverviewQuery;
    suppressSessionAnalysisWarning?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
    vizSpecificOptions?: VizSpecificOptions | undefined;
  };
  export type InterestingNote = { text: string; line_refs: string };
  export type LLMPrompt = {
    id: string;
    name: string;
    prompt: unknown;
    version: number;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
    deleted?: boolean | undefined;
  };
  export type LLMProviderKeyStateEnum = "unknown" | "ok" | "invalid" | "error";
  export type LLMProviderKey = {
    id: string;
    provider: ProviderEnum;
    name: string;
    state: LLMProviderKeyStateEnum & unknown;
    error_message: string | null;
    api_key?: string | undefined;
    api_key_masked: string;
    set_as_active?: boolean | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    last_used_at: string | null;
  };
  export type LiveDebuggerBreakpoint = {
    id: string;
    repository?: (string | null) | undefined;
    filename: string;
    line_number: number;
    enabled?: boolean | undefined;
    condition?: (string | null) | undefined;
    created_at: string;
    updated_at: string;
  };
  export type LocalEvaluationResponse = {
    flags: Array<MinimalFeatureFlag>;
    group_type_mapping: Record<string, string>;
    cohorts: Record<string, unknown>;
  };
  export type MembershipLevelEnum = 1 | 8 | 15;
  export type Message = {
    content: string | null;
    conversation: string;
    contextual_tools?: Record<string, unknown> | undefined;
    ui_context?: unknown | undefined;
    billing_context?: unknown | undefined;
    trace_id: string;
    session_id?: string | undefined;
    agent_mode?: AgentModeEnum | undefined;
    resume_payload?: (unknown | null) | undefined;
  };
  export type MessageMinimal = { content: string };
  export type MinimalPerson = {
    id: number;
    name: string;
    distinct_ids: string;
    properties?: unknown | undefined;
    created_at: string;
    uuid: string;
  };
  export type MyFlagsResponse = { feature_flag: MinimalFeatureFlag; value: unknown };
  export type Notebook = {
    id: string;
    short_id: string;
    title?: (string | null) | undefined;
    content?: (unknown | null) | undefined;
    text_content?: (string | null) | undefined;
    version?: number | undefined;
    deleted?: boolean | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    last_modified_at: string;
    last_modified_by: UserBasic & unknown;
    user_access_level: string | null;
    _create_in_folder?: string | undefined;
  };
  export type NotebookMinimal = {
    id: string;
    short_id: string;
    title: string | null;
    deleted: boolean;
    created_at: string;
    created_by: UserBasic & unknown;
    last_modified_at: string;
    last_modified_by: UserBasic & unknown;
    user_access_level: string | null;
    _create_in_folder?: string | undefined;
  };
  export type OperatorEnum =
    | "exact"
    | "is_not"
    | "icontains"
    | "not_icontains"
    | "regex"
    | "not_regex"
    | "gt"
    | "lt"
    | "gte"
    | "lte"
    | "is_set"
    | "is_not_set"
    | "is_date_exact"
    | "is_date_after"
    | "is_date_before"
    | "in"
    | "not_in";
  export type PluginsAccessLevelEnum = 0 | 3 | 6 | 9;
  export type Organization = {
    id: string;
    name: string;
    slug: string;
    logo_media_id?: (string | null) | undefined;
    created_at: string;
    updated_at: string;
    membership_level: (MembershipLevelEnum & (unknown | null)) | null;
    plugins_access_level: PluginsAccessLevelEnum & unknown;
    teams: Array<Record<string, unknown>>;
    projects: Array<Record<string, unknown>>;
    available_product_features: Array<unknown> | null;
    is_member_join_email_enabled?: boolean | undefined;
    metadata: string;
    customer_id: string | null;
    enforce_2fa?: (boolean | null) | undefined;
    members_can_invite?: (boolean | null) | undefined;
    members_can_use_personal_api_keys?: boolean | undefined;
    allow_publicly_shared_resources?: boolean | undefined;
    member_count: string;
    is_ai_data_processing_approved?: (boolean | null) | undefined;
    default_experiment_stats_method?: ((DefaultExperimentStatsMethodEnum | BlankEnum | NullEnum) | null) | undefined;
    default_anonymize_ips?: boolean | undefined;
    default_role_id?: (string | null) | undefined;
    is_active: boolean | null;
    is_not_active_reason: string | null;
  };
  export type OrganizationBasic = {
    id: string;
    name: string;
    slug: string;
    logo_media_id: string | null;
    membership_level: (MembershipLevelEnum & (unknown | null)) | null;
    members_can_use_personal_api_keys?: boolean | undefined;
    is_active?: (boolean | null) | undefined;
    is_not_active_reason?: (string | null) | undefined;
  };
  export type OrganizationDomain = {
    id: string;
    domain: string;
    is_verified: boolean;
    verified_at: string | null;
    verification_challenge: string;
    jit_provisioning_enabled?: boolean | undefined;
    sso_enforcement?: string | undefined;
    has_saml: boolean;
    saml_entity_id?: (string | null) | undefined;
    saml_acs_url?: (string | null) | undefined;
    saml_x509_cert?: (string | null) | undefined;
    has_scim: boolean;
    scim_enabled?: boolean | undefined;
    scim_base_url: string | null;
    scim_bearer_token: string | null;
  };
  export type OrganizationIntegrationKindEnum = "vercel";
  export type OrganizationIntegration = {
    id: string;
    kind: OrganizationIntegrationKindEnum & unknown;
    integration_id: string | null;
    config: unknown;
    created_at: string;
    updated_at: string;
    created_by: UserBasic & unknown;
  };
  export type OrganizationMembershipLevel = 1 | 8 | 15;
  export type OrganizationInvite = {
    id: string;
    target_email: string;
    first_name?: string | undefined;
    emailing_attempt_made: boolean;
    level?: (OrganizationMembershipLevel & unknown) | undefined;
    is_expired: boolean;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
    message?: (string | null) | undefined;
    private_project_access?: (unknown | null) | undefined;
    send_email?: boolean | undefined;
    combine_pending_invites?: boolean | undefined;
  };
  export type OrganizationMember = {
    id: string;
    user: UserBasic & unknown;
    level?: (OrganizationMembershipLevel & unknown) | undefined;
    joined_at: string;
    updated_at: string;
    is_2fa_enabled: boolean;
    has_social_auth: boolean;
    last_login: string;
  };
  export type OriginProductEnum =
    | "error_tracking"
    | "eval_clusters"
    | "user_created"
    | "support_queue"
    | "session_summaries";
  export type PaginatedActionList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Action>;
  };
  export type PaginatedActivityLogList = Array<ActivityLog>;
  export type PaginatedAlertList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Alert>;
  };
  export type PaginatedAnnotationList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Annotation>;
  };
  export type PaginatedBatchExportBackfillList = {
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<BatchExportBackfill>;
  };
  export type PaginatedBatchExportList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<BatchExport>;
  };
  export type PaginatedBatchExportRunList = {
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<BatchExportRun>;
  };
  export type PaginatedClickhouseEventList = Partial<{ next: string | null; results: Array<ClickhouseEvent> }>;
  export type PaginatedCohortList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Cohort>;
  };
  export type PaginatedConversationList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Conversation>;
  };
  export type PaginatedCustomerProfileConfigList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<CustomerProfileConfig>;
  };
  export type PaginatedDashboardBasicList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<DashboardBasic>;
  };
  export type PaginatedDashboardTemplateList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<DashboardTemplate>;
  };
  export type PaginatedDataColorThemeList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<DataColorTheme>;
  };
  export type PaginatedDataWarehouseSavedQueryMinimalList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<DataWarehouseSavedQueryMinimal>;
  };
  export type PaginatedDatasetItemList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<DatasetItem>;
  };
  export type PaginatedDatasetList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Dataset>;
  };
  export type PaginatedDesktopRecordingList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<DesktopRecording>;
  };
  export type PaginatedEarlyAccessFeatureList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<EarlyAccessFeature>;
  };
  export type PaginatedEnterpriseEventDefinitionList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<EnterpriseEventDefinition>;
  };
  export type PaginatedEnterprisePropertyDefinitionList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<EnterprisePropertyDefinition>;
  };
  export type PaginatedErrorTrackingAssignmentRuleList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ErrorTrackingAssignmentRule>;
  };
  export type PaginatedErrorTrackingAutoCaptureControlsList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ErrorTrackingAutoCaptureControls>;
  };
  export type PaginatedErrorTrackingFingerprintList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ErrorTrackingFingerprint>;
  };
  export type PaginatedErrorTrackingGroupingRuleList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ErrorTrackingGroupingRule>;
  };
  export type PaginatedErrorTrackingReleaseList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ErrorTrackingRelease>;
  };
  export type PaginatedErrorTrackingSuppressionRuleList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ErrorTrackingSuppressionRule>;
  };
  export type PaginatedErrorTrackingSymbolSetList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ErrorTrackingSymbolSet>;
  };
  export type PaginatedEvaluationList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Evaluation>;
  };
  export type PaginatedExperimentHoldoutList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ExperimentHoldout>;
  };
  export type PaginatedExperimentList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Experiment>;
  };
  export type PaginatedExperimentSavedMetricList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ExperimentSavedMetric>;
  };
  export type PaginatedExportedAssetList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ExportedAsset>;
  };
  export type PaginatedExternalDataSourceSerializersList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ExternalDataSourceSerializers>;
  };
  export type PaginatedFeatureFlagList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<FeatureFlag>;
  };
  export type PaginatedFileSystemList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<FileSystem>;
  };
  export type PaginatedFileSystemShortcutList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<FileSystemShortcut>;
  };
  export type PaginatedGroupList = {
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Group>;
  };
  export type PaginatedGroupUsageMetricList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<GroupUsageMetric>;
  };
  export type PaginatedHogFunctionMinimalList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<HogFunctionMinimal>;
  };
  export type PaginatedInsightList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Insight>;
  };
  export type PaginatedInsightVariableList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<InsightVariable>;
  };
  export type PaginatedIntegrationList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Integration>;
  };
  export type PaginatedLLMPromptList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<LLMPrompt>;
  };
  export type PaginatedLLMProviderKeyList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<LLMProviderKey>;
  };
  export type PaginatedLiveDebuggerBreakpointList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<LiveDebuggerBreakpoint>;
  };
  export type PaginatedNotebookMinimalList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<NotebookMinimal>;
  };
  export type PaginatedOrganizationDomainList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<OrganizationDomain>;
  };
  export type PaginatedOrganizationIntegrationList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<OrganizationIntegration>;
  };
  export type PaginatedOrganizationInviteList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<OrganizationInvite>;
  };
  export type PaginatedOrganizationList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Organization>;
  };
  export type PaginatedOrganizationMemberList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<OrganizationMember>;
  };
  export type PersistedFolderTypeEnum = "home" | "pinned" | "custom_products";
  export type PersistedFolder = {
    id: string;
    type: PersistedFolderTypeEnum;
    protocol?: string | undefined;
    path?: string | undefined;
    created_at: string;
    updated_at: string;
  };
  export type PaginatedPersistedFolderList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<PersistedFolder>;
  };
  export type PaginatedPersonList = Partial<{
    next: string | null;
    previous: string | null;
    count: number;
    results: Array<Person>;
  }>;
  export type PluginLogEntrySourceEnum = "SYSTEM" | "PLUGIN" | "CONSOLE";
  export type PluginLogEntryTypeEnum = "DEBUG" | "LOG" | "INFO" | "WARN" | "ERROR";
  export type PluginLogEntry = {
    id: string;
    team_id: number;
    plugin_id: number;
    plugin_config_id: number;
    timestamp: string;
    source: PluginLogEntrySourceEnum;
    type: PluginLogEntryTypeEnum;
    message: string;
    instance_id: string;
  };
  export type PaginatedPluginLogEntryList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<PluginLogEntry>;
  };
  export type ProductTour = {
    id: string;
    name: string;
    description?: string | undefined;
    internal_targeting_flag: MinimalFeatureFlag & unknown;
    linked_flag: MinimalFeatureFlag & unknown;
    targeting_flag_filters: Record<string, unknown> | null;
    content?: unknown | undefined;
    auto_launch?: boolean | undefined;
    start_date?: (string | null) | undefined;
    end_date?: (string | null) | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    updated_at: string;
    archived?: boolean | undefined;
  };
  export type PaginatedProductTourList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ProductTour>;
  };
  export type ProjectBackwardCompatBasic = {
    id: number;
    uuid: string;
    organization: string;
    api_token: string;
    name: string;
    completed_snippet_onboarding: boolean;
    has_completed_onboarding_for: unknown | null;
    ingested_event: boolean;
    is_demo: boolean;
    timezone: TimezoneEnum & unknown;
    access_control: boolean;
  };
  export type PaginatedProjectBackwardCompatBasicList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ProjectBackwardCompatBasic>;
  };
  export type ProxyRecordStatusEnum =
    | "waiting"
    | "issuing"
    | "valid"
    | "warning"
    | "erroring"
    | "deleting"
    | "timed_out";
  export type ProxyRecord = {
    id: string;
    domain: string;
    target_cname: string;
    status: ProxyRecordStatusEnum & unknown;
    message: string | null;
    created_at: string;
    updated_at: string;
    created_by: number | null;
  };
  export type PaginatedProxyRecordList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ProxyRecord>;
  };
  export type Role = {
    id: string;
    name: string;
    created_at: string;
    created_by: UserBasic & unknown;
    members: string;
    is_default: string;
  };
  export type PaginatedRoleList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Role>;
  };
  export type RoleMembership = {
    id: string;
    role_id: string;
    organization_member: OrganizationMember & unknown;
    user: UserBasic & unknown;
    joined_at: string;
    updated_at: string;
    user_uuid: string;
  };
  export type PaginatedRoleMembershipList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<RoleMembership>;
  };
  export type SessionGroupSummaryMinimal = {
    id: string;
    title: string;
    session_count: number;
    created_at: string;
    created_by: UserBasic & unknown;
  };
  export type PaginatedSessionGroupSummaryMinimalList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<SessionGroupSummaryMinimal>;
  };
  export type SessionRecording = {
    id: string;
    distinct_id: string | null;
    viewed: boolean;
    viewers: Array<string>;
    recording_duration: number;
    active_seconds: number | null;
    inactive_seconds: number | null;
    start_time: string | null;
    end_time: string | null;
    click_count: number | null;
    keypress_count: number | null;
    mouse_activity_count: number | null;
    console_log_count: number | null;
    console_warn_count: number | null;
    console_error_count: number | null;
    start_url: string | null;
    person?: MinimalPerson | undefined;
    retention_period_days: number | null;
    expiry_time: string;
    recording_ttl: string;
    snapshot_source: string | null;
    snapshot_library: string | null;
    ongoing: boolean;
    activity_score: number | null;
    external_references: Array<Record<string, unknown>>;
  };
  export type PaginatedSessionRecordingList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<SessionRecording>;
  };
  export type SessionRecordingPlaylistTypeEnum = "collection" | "filters";
  export type SessionRecordingPlaylist = {
    id: number;
    short_id: string;
    name?: (string | null) | undefined;
    derived_name?: (string | null) | undefined;
    description?: string | undefined;
    pinned?: boolean | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    deleted?: boolean | undefined;
    filters?: unknown | undefined;
    last_modified_at: string;
    last_modified_by: UserBasic & unknown;
    recordings_counts: Record<string, Record<string, unknown>>;
    type: (SessionRecordingPlaylistTypeEnum | NullEnum) | null;
    is_synthetic: boolean;
    _create_in_folder?: string | undefined;
  };
  export type PaginatedSessionRecordingPlaylistList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<SessionRecordingPlaylist>;
  };
  export type SignalReportStatusEnum = "potential" | "candidate" | "in_progress" | "ready" | "failed";
  export type SignalReport = {
    id: string;
    title: string | null;
    summary: string | null;
    status: SignalReportStatusEnum & unknown;
    total_weight: number;
    signal_count: number;
    relevant_user_count: number | null;
    created_at: string;
    updated_at: string;
    artefact_count: number;
  };
  export type PaginatedSignalReportList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<SignalReport>;
  };
  export type TargetTypeEnum = "email" | "slack" | "webhook";
  export type Subscription = {
    id: number;
    dashboard?: (number | null) | undefined;
    insight?: (number | null) | undefined;
    target_type: TargetTypeEnum;
    target_value: string;
    frequency: FrequencyEnum;
    interval?: number | undefined;
    byweekday?: (Array<ByweekdayEnum> | null) | undefined;
    bysetpos?: (number | null) | undefined;
    count?: (number | null) | undefined;
    start_date: string;
    until_date?: (string | null) | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    deleted?: boolean | undefined;
    title?: (string | null) | undefined;
    summary: string;
    next_delivery_date: string | null;
    invite_message?: (string | null) | undefined;
  };
  export type PaginatedSubscriptionList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Subscription>;
  };
  export type SurveyType = "popover" | "widget" | "external_survey" | "api";
  export type ResponseSamplingIntervalTypeEnum = "day" | "week" | "month";
  export type Survey = {
    id: string;
    name: string;
    description?: string | undefined;
    type: SurveyType;
    schedule?: (string | null) | undefined;
    linked_flag: MinimalFeatureFlag & unknown;
    linked_flag_id?: (number | null) | undefined;
    linked_insight_id?: (number | null) | undefined;
    targeting_flag: MinimalFeatureFlag & unknown;
    internal_targeting_flag: MinimalFeatureFlag & unknown;
    questions?: (unknown | null) | undefined;
    conditions: string;
    appearance?: (unknown | null) | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    start_date?: (string | null) | undefined;
    end_date?: (string | null) | undefined;
    archived?: boolean | undefined;
    responses_limit?: (number | null) | undefined;
    feature_flag_keys: Array<unknown>;
    iteration_count?: (number | null) | undefined;
    iteration_frequency_days?: (number | null) | undefined;
    iteration_start_dates?: (Array<string | null> | null) | undefined;
    current_iteration?: (number | null) | undefined;
    current_iteration_start_date?: (string | null) | undefined;
    response_sampling_start_date?: (string | null) | undefined;
    response_sampling_interval_type?: ((ResponseSamplingIntervalTypeEnum | BlankEnum | NullEnum) | null) | undefined;
    response_sampling_interval?: (number | null) | undefined;
    response_sampling_limit?: (number | null) | undefined;
    response_sampling_daily_limits?: (unknown | null) | undefined;
    enable_partial_responses?: (boolean | null) | undefined;
    enable_iframe_embedding?: (boolean | null) | undefined;
    user_access_level: string | null;
  };
  export type PaginatedSurveyList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Survey>;
  };
  export type TableFormatEnum = "CSV" | "CSVWithNames" | "Parquet" | "JSONEachRow" | "Delta" | "DeltaS3Wrapper";
  export type SimpleExternalDataSourceSerializers = {
    id: string;
    created_at: string;
    created_by: number | null;
    status: string;
    source_type: SourceTypeEnum & unknown;
  };
  export type Table = {
    id: string;
    deleted?: (boolean | null) | undefined;
    name: string;
    format: TableFormatEnum;
    created_by: UserBasic & unknown;
    created_at: string;
    url_pattern: string;
    credential: Credential;
    columns: string;
    external_data_source: SimpleExternalDataSourceSerializers & unknown;
    external_schema: string;
  };
  export type PaginatedTableList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Table>;
  };
  export type PaginatedTaskList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Task>;
  };
  export type TaskRunDetailStatusEnum = "not_started" | "queued" | "in_progress" | "completed" | "failed" | "cancelled";
  export type TaskRunArtifactResponse = {
    name: string;
    type: string;
    size?: number | undefined;
    content_type?: string | undefined;
    storage_path: string;
    uploaded_at: string;
  };
  export type TaskRunDetail = {
    id: string;
    task: string;
    stage?: (string | null) | undefined;
    branch?: (string | null) | undefined;
    status?: TaskRunDetailStatusEnum | undefined;
    environment?: EnvironmentEnum | undefined;
    log_url: string | null;
    error_message?: (string | null) | undefined;
    output?: (unknown | null) | undefined;
    state?: unknown | undefined;
    artifacts: Array<TaskRunArtifactResponse>;
    created_at: string;
    updated_at: string;
    completed_at: string | null;
  };
  export type PaginatedTaskRunDetailList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<TaskRunDetail>;
  };
  export type TeamBasic = {
    id: number;
    uuid: string;
    organization: string;
    project_id: number;
    api_token: string;
    name: string;
    completed_snippet_onboarding: boolean;
    has_completed_onboarding_for: unknown | null;
    ingested_event: boolean;
    is_demo: boolean;
    timezone: TimezoneEnum & unknown;
    access_control: boolean;
  };
  export type PaginatedTeamBasicList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<TeamBasic>;
  };
  export type ThresholdWithAlert = {
    id: string;
    created_at: string;
    name?: string | undefined;
    configuration: InsightThreshold;
    alerts: Array<Alert>;
  };
  export type PaginatedThresholdWithAlertList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<ThresholdWithAlert>;
  };
  export type TicketStatusEnum = "new" | "open" | "pending" | "on_hold" | "resolved";
  export type PriorityEnum = "low" | "medium" | "high";
  export type TicketAssignment = { id: string; type: string };
  export type TicketPerson = {
    id: string;
    name: string;
    distinct_ids: Array<string>;
    properties: Record<string, unknown>;
    created_at: string;
    is_identified: boolean;
  };
  export type Ticket = {
    id: string;
    ticket_number: number;
    channel_source: ChannelSourceEnum & unknown;
    distinct_id: string;
    status?: TicketStatusEnum | undefined;
    priority?: ((PriorityEnum | BlankEnum | NullEnum) | null) | undefined;
    assignee: TicketAssignment & unknown;
    anonymous_traits?: unknown | undefined;
    ai_resolved?: boolean | undefined;
    escalation_reason?: (string | null) | undefined;
    created_at: string;
    updated_at: string;
    message_count: number;
    last_message_at: string | null;
    last_message_text: string | null;
    unread_team_count: number;
    session_id: string | null;
    session_context: unknown;
    person: (TicketPerson & (unknown | null)) | null;
  };
  export type PaginatedTicketList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<Ticket>;
  };
  export type UserInterview = {
    id: string;
    created_by: UserBasic & unknown;
    created_at: string;
    interviewee_emails?: Array<string> | undefined;
    transcript: string;
    summary?: string | undefined;
    audio: string;
  };
  export type PaginatedUserInterviewList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<UserInterview>;
  };
  export type ToolbarModeEnum = "disabled" | "toolbar";
  export type ScenePersonalisationBasic = { scene: string; dashboard?: (number | null) | undefined };
  export type ThemeModeEnum = "light" | "dark" | "system";
  export type ShortcutPositionEnum = "above" | "below" | "hidden";
  export type User = {
    date_joined: string;
    uuid: string;
    distinct_id: string | null;
    first_name?: string | undefined;
    last_name?: string | undefined;
    email: string;
    pending_email: string | null;
    is_email_verified: boolean | null;
    notification_settings?: Record<string, unknown> | undefined;
    anonymize_data?: (boolean | null) | undefined;
    allow_impersonation?: (boolean | null) | undefined;
    toolbar_mode?: ((ToolbarModeEnum | BlankEnum | NullEnum) | null) | undefined;
    has_password: boolean;
    id: number;
    is_staff?: boolean | undefined;
    is_impersonated: boolean | null;
    is_impersonated_until: string | null;
    is_impersonated_read_only: boolean | null;
    sensitive_session_expires_at: string | null;
    team: TeamBasic & unknown;
    organization: Organization & unknown;
    organizations: Array<OrganizationBasic>;
    set_current_organization?: string | undefined;
    set_current_team?: string | undefined;
    password: string;
    current_password?: string | undefined;
    events_column_config?: unknown | undefined;
    is_2fa_enabled: boolean;
    has_social_auth: boolean;
    has_sso_enforcement: boolean;
    has_seen_product_intro_for?: (unknown | null) | undefined;
    scene_personalisation: Array<ScenePersonalisationBasic>;
    theme_mode?: ((ThemeModeEnum | BlankEnum | NullEnum) | null) | undefined;
    hedgehog_config?: (unknown | null) | undefined;
    allow_sidebar_suggestions?: (boolean | null) | undefined;
    shortcut_position?: ((ShortcutPositionEnum | BlankEnum | NullEnum) | null) | undefined;
    role_at_organization?: RoleAtOrganizationEnum | undefined;
    passkeys_enabled_for_2fa?: (boolean | null) | undefined;
  };
  export type PaginatedUserList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<User>;
  };
  export type WebExperimentsAPI = {
    id: number;
    name: string;
    created_at?: string | undefined;
    feature_flag_key: string;
    variants: unknown;
  };
  export type PaginatedWebExperimentsAPIList = {
    count: number;
    next?: (string | null) | undefined;
    previous?: (string | null) | undefined;
    results: Array<WebExperimentsAPI>;
  };
  export type PatchedAction = Partial<{
    id: number;
    name: string | null;
    description: string;
    tags: Array<unknown>;
    post_to_slack: boolean;
    slack_message_format: string;
    steps: Array<ActionStepJSON>;
    created_at: string;
    created_by: UserBasic & unknown;
    deleted: boolean;
    is_calculating: boolean;
    last_calculated_at: string;
    team_id: number;
    is_action: boolean;
    bytecode_error: string | null;
    pinned_at: string | null;
    creation_context: string;
    _create_in_folder: string;
    user_access_level: string | null;
  }>;
  export type PatchedAddPersonsToStaticCohortRequest = Partial<{ person_ids: Array<string> }>;
  export type PatchedAlert = Partial<{
    id: string;
    created_by: UserBasic & unknown;
    created_at: string;
    insight: number;
    name: string;
    subscribed_users: Array<number>;
    threshold: Threshold;
    condition: (AlertCondition & (unknown | null)) | null;
    state: State66aEnum & unknown;
    enabled: boolean;
    last_notified_at: string | null;
    last_checked_at: string | null;
    next_check_at: string | null;
    checks: Array<AlertCheck>;
    config: (TrendsAlertConfig & (unknown | null)) | null;
    calculation_interval: (CalculationIntervalEnum | BlankEnum | NullEnum) | null;
    snoozed_until: string | null;
    skip_weekend: boolean | null;
  }>;
  export type PatchedAnnotation = Partial<{
    id: number;
    content: string | null;
    date_marker: string | null;
    creation_type: CreationTypeEnum;
    dashboard_item: number | null;
    dashboard_id: number | null;
    dashboard_name: string | null;
    insight_short_id: string | null;
    insight_name: string | null;
    insight_derived_name: string | null;
    created_by: UserBasic & unknown;
    created_at: string | null;
    updated_at: string;
    deleted: boolean;
    scope: AnnotationScopeEnum;
  }>;
  export type PatchedBatchExport = Partial<{
    id: string;
    team_id: number;
    name: string;
    model: (ModelEnum | BlankEnum | NullEnum) | null;
    destination: BatchExportDestination;
    interval: IntervalEnum;
    paused: boolean;
    created_at: string;
    last_updated_at: string;
    last_paused_at: string | null;
    start_at: string | null;
    end_at: string | null;
    latest_runs: Array<BatchExportRun>;
    hogql_query: string;
    schema: unknown | null;
    filters: unknown | null;
    timezone: (TimezoneEnum | NullEnum) | null;
    offset_day: number | null;
    offset_hour: number | null;
  }>;
  export type PatchedCohort = Partial<{
    id: number;
    name: string | null;
    description: string;
    groups: unknown;
    deleted: boolean;
    filters: unknown | null;
    query: unknown | null;
    version: number | null;
    pending_version: number | null;
    is_calculating: boolean;
    created_by: UserBasic & unknown;
    created_at: string | null;
    last_calculation: string | null;
    errors_calculating: number;
    last_error_message: string | null;
    count: number | null;
    is_static: boolean;
    cohort_type: (CohortTypeEnum | BlankEnum | NullEnum) | null;
    experiment_set: Array<number>;
    _create_in_folder: string;
    _create_static_person_ids: Array<string>;
  }>;
  export type PatchedConversation = Partial<{
    id: string;
    status: ConversationStatusEnum & unknown;
    title: string | null;
    user: UserBasic & unknown;
    created_at: string | null;
    updated_at: string | null;
    type: ConversationTypeEnum & unknown;
    is_internal: boolean | null;
    slack_thread_key: string | null;
    slack_workspace_domain: string | null;
    messages: Array<Record<string, unknown>>;
    has_unsupported_content: boolean;
    agent_mode: string | null;
    pending_approvals: Array<Record<string, unknown>>;
  }>;
  export type PatchedCustomerProfileConfig = Partial<{
    id: string;
    scope: CustomerProfileConfigScopeEnum;
    content: unknown | null;
    sidebar: unknown | null;
    created_at: string;
    updated_at: string | null;
  }>;
  export type PatchedDashboard = Partial<{
    id: number;
    name: string | null;
    description: string;
    pinned: boolean;
    created_at: string;
    created_by: UserBasic & unknown;
    last_accessed_at: string | null;
    last_viewed_at: string | null;
    is_shared: boolean;
    deleted: boolean;
    creation_mode: CreationModeEnum & unknown;
    filters: Record<string, unknown>;
    variables: Record<string, unknown> | null;
    breakdown_colors: unknown;
    data_color_theme_id: number | null;
    tags: Array<unknown>;
    restriction_level: DashboardRestrictionLevel & unknown;
    effective_restriction_level: EffectiveRestrictionLevelEnum & unknown;
    effective_privilege_level: EffectivePrivilegeLevelEnum & unknown;
    user_access_level: string | null;
    access_control_version: string;
    last_refresh: string | null;
    persisted_filters: Record<string, unknown> | null;
    persisted_variables: Record<string, unknown> | null;
    team_id: number;
    tiles: Array<Record<string, unknown>> | null;
    use_template: string;
    use_dashboard: number | null;
    delete_insights: boolean;
    _create_in_folder: string;
  }>;
  export type PatchedDashboardTemplate = Partial<{
    id: string;
    template_name: string | null;
    dashboard_description: string | null;
    dashboard_filters: unknown | null;
    tags: Array<string> | null;
    tiles: unknown | null;
    variables: unknown | null;
    deleted: boolean | null;
    created_at: string | null;
    created_by: number | null;
    image_url: string | null;
    team_id: number | null;
    scope: (DashboardTemplateScopeEnum | BlankEnum | NullEnum) | null;
    availability_contexts: Array<string> | null;
  }>;
  export type PatchedDataColorTheme = Partial<{
    id: number;
    name: string;
    colors: unknown;
    is_global: string;
    created_at: string | null;
    created_by: UserBasic & unknown;
  }>;
  export type PatchedDataWarehouseSavedQuery = Partial<{
    id: string;
    deleted: boolean | null;
    name: string;
    query: unknown | null;
    created_by: UserBasic & unknown;
    created_at: string;
    sync_frequency: string;
    columns: string;
    status: (StatusD5cEnum | NullEnum) | null;
    last_run_at: string | null;
    managed_viewset_kind: string;
    latest_error: string | null;
    edited_history_id: string | null;
    latest_history_id: string;
    soft_update: boolean | null;
    is_materialized: boolean | null;
    origin: (OriginEnum | NullEnum) | null;
  }>;
  export type PatchedDataset = Partial<{
    id: string;
    name: string;
    description: string | null;
    metadata: unknown | null;
    created_at: string;
    updated_at: string | null;
    deleted: boolean | null;
    created_by: UserBasic & unknown;
    team: number;
  }>;
  export type PatchedDatasetItem = Partial<{
    id: string;
    dataset: string;
    input: unknown | null;
    output: unknown | null;
    metadata: unknown | null;
    ref_trace_id: string | null;
    ref_timestamp: string | null;
    ref_source_id: string | null;
    deleted: boolean | null;
    created_at: string;
    updated_at: string | null;
    created_by: UserBasic & unknown;
    team: number;
  }>;
  export type PatchedDesktopRecording = Partial<{
    id: string;
    team: number;
    created_by: number | null;
    sdk_upload_id: string;
    recall_recording_id: string | null;
    platform: Platform9aaEnum;
    meeting_title: string | null;
    meeting_url: string | null;
    duration_seconds: number | null;
    status: Status292Enum;
    notes: string | null;
    error_message: string | null;
    video_url: string | null;
    video_size_bytes: number | null;
    participants: Array<string>;
    transcript_text: string;
    transcript_segments: Array<TranscriptSegment>;
    summary: string | null;
    extracted_tasks: Array<Task>;
    tasks_generated_at: string | null;
    summary_generated_at: string | null;
    started_at: string;
    completed_at: string | null;
    created_at: string;
    updated_at: string;
  }>;
  export type PatchedEarlyAccessFeature = Partial<{
    id: string;
    feature_flag: MinimalFeatureFlag & unknown;
    name: string;
    description: string;
    stage: StageEnum;
    documentation_url: string;
    payload: string;
    created_at: string;
  }>;
  export type PatchedEnterpriseEventDefinition = Partial<{
    id: string;
    name: string;
    owner: number | null;
    description: string | null;
    tags: Array<unknown>;
    created_at: string | null;
    updated_at: string;
    updated_by: UserBasic & unknown;
    last_seen_at: string | null;
    last_updated_at: string;
    verified: boolean;
    verified_at: string | null;
    verified_by: UserBasic & unknown;
    hidden: boolean | null;
    is_action: boolean;
    action_id: number;
    is_calculating: boolean;
    last_calculated_at: string;
    created_by: UserBasic & unknown;
    post_to_slack: boolean;
    default_columns: Array<string>;
  }>;
  export type PatchedEnterprisePropertyDefinition = Partial<{
    id: string;
    name: string;
    description: string | null;
    tags: Array<unknown>;
    is_numerical: boolean;
    updated_at: string;
    updated_by: UserBasic & unknown;
    is_seen_on_filtered_events: boolean | null;
    property_type: (PropertyTypeEnum | BlankEnum | NullEnum) | null;
    verified: boolean;
    verified_at: string | null;
    verified_by: UserBasic & unknown;
    hidden: boolean | null;
  }>;
  export type PatchedErrorTrackingAssignmentRule = Partial<{
    id: string;
    filters: unknown;
    assignee: string;
    order_key: number;
    disabled_data: unknown | null;
  }>;
  export type PatchedErrorTrackingAutoCaptureControls = Partial<{
    id: string;
    library: LibraryEnum & unknown;
    match_type: MatchTypeEnum;
    sample_rate: string;
    linked_feature_flag: unknown | null;
    event_triggers: Array<string | null> | null;
    url_triggers: Array<unknown | null> | null;
    url_blocklist: Array<unknown | null> | null;
  }>;
  export type PatchedErrorTrackingGroupingRule = Partial<{
    id: string;
    filters: unknown;
    assignee: string;
    order_key: number;
    disabled_data: unknown | null;
  }>;
  export type PatchedErrorTrackingRelease = Partial<{
    id: string;
    hash_id: string;
    team_id: number;
    created_at: string;
    metadata: unknown | null;
    version: string;
    project: string;
  }>;
  export type PatchedErrorTrackingSuppressionRule = Partial<{ id: string; filters: unknown; order_key: number }>;
  export type PatchedErrorTrackingSymbolSet = Partial<{
    id: string;
    ref: string;
    team_id: number;
    created_at: string;
    last_used: string | null;
    storage_ptr: string | null;
    failure_reason: string | null;
    release: string;
  }>;
  export type PatchedEvaluation = Partial<{
    id: string;
    name: string;
    description: string;
    enabled: boolean;
    evaluation_type: EvaluationTypeEnum;
    evaluation_config: unknown;
    output_type: OutputTypeEnum;
    output_config: unknown;
    conditions: unknown;
    model_configuration: (ModelConfiguration & (unknown | null)) | null;
    created_at: string;
    updated_at: string;
    created_by: UserBasic & unknown;
    deleted: boolean;
  }>;
  export type PatchedExperiment = Partial<{
    id: number;
    name: string;
    description: string | null;
    start_date: string | null;
    end_date: string | null;
    feature_flag_key: string;
    feature_flag: MinimalFeatureFlag & unknown;
    holdout: ExperimentHoldout & unknown;
    holdout_id: number | null;
    exposure_cohort: number | null;
    parameters: unknown | null;
    secondary_metrics: unknown | null;
    saved_metrics: Array<ExperimentToSavedMetric>;
    saved_metrics_ids: Array<unknown> | null;
    filters: unknown;
    archived: boolean;
    deleted: boolean | null;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
    type: (ExperimentTypeEnum | BlankEnum | NullEnum) | null;
    exposure_criteria: unknown | null;
    metrics: unknown | null;
    metrics_secondary: unknown | null;
    stats_config: unknown | null;
    scheduling_config: unknown | null;
    _create_in_folder: string;
    conclusion: (ConclusionEnum | BlankEnum | NullEnum) | null;
    conclusion_comment: string | null;
    primary_metrics_ordered_uuids: unknown | null;
    secondary_metrics_ordered_uuids: unknown | null;
    user_access_level: string | null;
  }>;
  export type PatchedExperimentHoldout = Partial<{
    id: number;
    name: string;
    description: string | null;
    filters: unknown;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
  }>;
  export type PatchedExperimentSavedMetric = Partial<{
    id: number;
    name: string;
    description: string | null;
    query: unknown;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
    tags: Array<unknown>;
    user_access_level: string | null;
  }>;
  export type PatchedExternalDataSourceSerializers = Partial<{
    id: string;
    created_at: string;
    created_by: string | null;
    status: string;
    client_secret: string;
    account_id: string;
    source_type: SourceTypeEnum & unknown;
    latest_error: string;
    prefix: string | null;
    description: string | null;
    last_run_at: string;
    schemas: string;
    job_inputs: unknown | null;
    revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfig & unknown;
    user_access_level: string | null;
  }>;
  export type PatchedFeatureFlag = Partial<{
    id: number;
    name: string;
    key: string;
    filters: Record<string, unknown>;
    deleted: boolean;
    active: boolean;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string | null;
    version: number;
    last_modified_by: UserBasic & unknown;
    ensure_experience_continuity: boolean | null;
    experiment_set: string;
    surveys: Record<string, unknown>;
    features: Record<string, unknown>;
    rollback_conditions: unknown | null;
    performed_rollback: boolean | null;
    can_edit: boolean;
    tags: Array<unknown>;
    evaluation_tags: Array<unknown>;
    usage_dashboard: number;
    analytics_dashboards: Array<number>;
    has_enriched_analytics: boolean | null;
    user_access_level: string | null;
    creation_context: FeatureFlagCreationContextEnum & unknown;
    is_remote_configuration: boolean | null;
    has_encrypted_payloads: boolean | null;
    status: string;
    evaluation_runtime: (EvaluationRuntimeEnum | BlankEnum | NullEnum) | null;
    bucketing_identifier: (BucketingIdentifierEnum | BlankEnum | NullEnum) | null;
    last_called_at: string | null;
    _create_in_folder: string;
    _should_create_usage_dashboard: boolean;
  }>;
  export type PatchedFileSystem = Partial<{
    id: string;
    path: string;
    depth: number | null;
    type: string;
    ref: string | null;
    href: string | null;
    meta: unknown | null;
    shortcut: boolean | null;
    created_at: string;
    last_viewed_at: string | null;
  }>;
  export type PatchedFileSystemShortcut = Partial<{
    id: string;
    path: string;
    type: string;
    ref: string | null;
    href: string | null;
    created_at: string;
  }>;
  export type PatchedGroupType = Partial<{
    group_type: string;
    group_type_index: number;
    name_singular: string | null;
    name_plural: string | null;
    detail_dashboard: number | null;
    default_columns: Array<string> | null;
    created_at: string | null;
  }>;
  export type PatchedGroupUsageMetric = Partial<{
    id: string;
    name: string;
    format: GroupUsageMetricFormatEnum;
    interval: number;
    display: DisplayEnum;
    filters: unknown;
  }>;
  export type PatchedHogFunction = Partial<{
    id: string;
    type: (HogFunctionTypeEnum | NullEnum) | null;
    name: string | null;
    description: string;
    created_at: string;
    created_by: UserBasic & unknown;
    updated_at: string;
    enabled: boolean;
    deleted: boolean;
    hog: string;
    bytecode: unknown | null;
    transpiled: string | null;
    inputs_schema: Array<InputsSchemaItem>;
    inputs: Record<string, unknown>;
    filters: HogFunctionFilters;
    masking: (HogFunctionMasking & (unknown | null)) | null;
    mappings: Array<Mappings> | null;
    icon_url: string | null;
    template: HogFunctionTemplate & unknown;
    template_id: string | null;
    status: (HogFunctionStatus & (unknown | null)) | null;
    execution_order: number | null;
    _create_in_folder: string;
    batch_export_id: string | null;
  }>;
  export type PatchedInsight = Partial<{
    id: number;
    short_id: string;
    name: string | null;
    derived_name: string | null;
    query: Record<string, unknown> | null;
    order: number | null;
    deleted: boolean;
    dashboards: Array<number>;
    dashboard_tiles: Array<DashboardTileBasic>;
    last_refresh: string;
    cache_target_age: string;
    next_allowed_client_refresh: string;
    result: string;
    hasMore: string;
    columns: string;
    created_at: string | null;
    created_by: UserBasic & unknown;
    description: string | null;
    updated_at: string;
    tags: Array<unknown>;
    favorited: boolean;
    last_modified_at: string;
    last_modified_by: UserBasic & unknown;
    is_sample: boolean;
    effective_restriction_level: EffectiveRestrictionLevelEnum & unknown;
    effective_privilege_level: EffectivePrivilegeLevelEnum & unknown;
    user_access_level: string | null;
    timezone: string;
    is_cached: string;
    query_status: string;
    hogql: string;
    types: string;
    resolved_date_range: string;
    _create_in_folder: string;
    alerts: string;
    last_viewed_at: string;
  }>;
  export type PatchedInsightVariable = Partial<{
    id: string;
    name: string;
    type: InsightVariableTypeEnum;
    default_value: unknown | null;
    created_by: number | null;
    created_at: string;
    code_name: string | null;
    values: unknown | null;
  }>;
  export type PatchedIntegration = Partial<{
    id: number;
    kind: IntegrationKindEnum;
    config: unknown;
    created_at: string;
    created_by: UserBasic & unknown;
    errors: string;
    display_name: string;
  }>;
  export type PatchedLLMPrompt = Partial<{
    id: string;
    name: string;
    prompt: unknown;
    version: number;
    created_by: UserBasic & unknown;
    created_at: string;
    updated_at: string;
    deleted: boolean;
  }>;
  export type PatchedLLMProviderKey = Partial<{
    id: string;
    provider: ProviderEnum;
    name: string;
    state: LLMProviderKeyStateEnum & unknown;
    error_message: string | null;
    api_key: string;
    api_key_masked: string;
    set_as_active: boolean;
    created_at: string;
    created_by: UserBasic & unknown;
    last_used_at: string | null;
  }>;
  export type PatchedLiveDebuggerBreakpoint = Partial<{
    id: string;
    repository: string | null;
    filename: string;
    line_number: number;
    enabled: boolean;
    condition: string | null;
    created_at: string;
    updated_at: string;
  }>;
  export type PatchedNotebook = Partial<{
    id: string;
    short_id: string;
    title: string | null;
    content: unknown | null;
    text_content: string | null;
    version: number;
    deleted: boolean;
    created_at: string;
    created_by: UserBasic & unknown;
    last_modified_at: string;
    last_modified_by: UserBasic & unknown;
    user_access_level: string | null;
    _create_in_folder: string;
  }>;
  export type PatchedOrganization = Partial<{
    id: string;
    name: string;
    slug: string;
    logo_media_id: string | null;
    created_at: string;
    updated_at: string;
    membership_level: (MembershipLevelEnum & (unknown | null)) | null;
    plugins_access_level: PluginsAccessLevelEnum & unknown;
    teams: Array<Record<string, unknown>>;
    projects: Array<Record<string, unknown>>;
    available_product_features: Array<unknown> | null;
    is_member_join_email_enabled: boolean;
    metadata: string;
    customer_id: string | null;
    enforce_2fa: boolean | null;
    members_can_invite: boolean | null;
    members_can_use_personal_api_keys: boolean;
    allow_publicly_shared_resources: boolean;
    member_count: string;
    is_ai_data_processing_approved: boolean | null;
    default_experiment_stats_method: (DefaultExperimentStatsMethodEnum | BlankEnum | NullEnum) | null;
    default_anonymize_ips: boolean;
    default_role_id: string | null;
    is_active: boolean | null;
    is_not_active_reason: string | null;
  }>;
  export type PatchedOrganizationDomain = Partial<{
    id: string;
    domain: string;
    is_verified: boolean;
    verified_at: string | null;
    verification_challenge: string;
    jit_provisioning_enabled: boolean;
    sso_enforcement: string;
    has_saml: boolean;
    saml_entity_id: string | null;
    saml_acs_url: string | null;
    saml_x509_cert: string | null;
    has_scim: boolean;
    scim_enabled: boolean;
    scim_base_url: string | null;
    scim_bearer_token: string | null;
  }>;
  export type PatchedOrganizationMember = Partial<{
    id: string;
    user: UserBasic & unknown;
    level: OrganizationMembershipLevel & unknown;
    joined_at: string;
    updated_at: string;
    is_2fa_enabled: boolean;
    has_social_auth: boolean;
    last_login: string;
  }>;
  export type PatchedPersistedFolder = Partial<{
    id: string;
    type: PersistedFolderTypeEnum;
    protocol: string;
    path: string;
    created_at: string;
    updated_at: string;
  }>;
  export type PatchedPerson = Partial<{
    id: number;
    name: string;
    distinct_ids: Array<string>;
    properties: unknown;
    created_at: string;
    uuid: string;
  }>;
  export type PinnedSceneTab = Partial<{
    id: string;
    pathname: string;
    search: string;
    hash: string;
    title: string;
    customTitle: string | null;
    iconType: string;
    sceneId: string | null;
    sceneKey: string | null;
    sceneParams: unknown;
    pinned: boolean;
  }>;
  export type PatchedPinnedSceneTabs = Partial<{
    tabs: Array<PinnedSceneTab>;
    homepage: (PinnedSceneTab & (unknown | null)) | null;
  }>;
  export type ProductTourSerializerCreateUpdateOnlyCreationContextEnum = "app" | "toolbar";
  export type PatchedProductTourSerializerCreateUpdateOnly = Partial<{
    id: string;
    name: string;
    description: string;
    internal_targeting_flag: MinimalFeatureFlag & unknown;
    linked_flag: MinimalFeatureFlag & unknown;
    linked_flag_id: number | null;
    targeting_flag_filters: unknown | null;
    content: unknown;
    auto_launch: boolean;
    start_date: string | null;
    end_date: string | null;
    created_at: string;
    created_by: UserBasic & unknown;
    updated_at: string;
    archived: boolean;
    creation_context: ProductTourSerializerCreateUpdateOnlyCreationContextEnum & unknown;
  }>;
  export type WeekStartDayEnum = 0 | 1;
  export type PatchedProjectBackwardCompat = Partial<{
    id: number;
    organization: string;
    name: string;
    product_description: string | null;
    created_at: string;
    effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null;
    has_group_types: boolean;
    group_types: Array<Record<string, unknown>>;
    live_events_token: string | null;
    updated_at: string;
    uuid: string;
    api_token: string;
    app_urls: Array<string | null>;
    slack_incoming_webhook: string | null;
    anonymize_ips: boolean;
    completed_snippet_onboarding: boolean;
    ingested_event: boolean;
    test_account_filters: unknown;
    test_account_filters_default_checked: boolean | null;
    path_cleaning_filters: unknown | null;
    is_demo: boolean;
    timezone: TimezoneEnum;
    data_attributes: unknown;
    person_display_name_properties: Array<string> | null;
    correlation_config: unknown | null;
    autocapture_opt_out: boolean | null;
    autocapture_exceptions_opt_in: boolean | null;
    autocapture_web_vitals_opt_in: boolean | null;
    autocapture_web_vitals_allowed_metrics: unknown | null;
    autocapture_exceptions_errors_to_ignore: unknown | null;
    capture_console_log_opt_in: boolean | null;
    capture_performance_opt_in: boolean | null;
    session_recording_opt_in: boolean;
    session_recording_sample_rate: string | null;
    session_recording_minimum_duration_milliseconds: number | null;
    session_recording_linked_flag: unknown | null;
    session_recording_network_payload_capture_config: unknown | null;
    session_recording_masking_config: unknown | null;
    session_replay_config: unknown | null;
    survey_config: unknown | null;
    access_control: boolean;
    week_start_day: (WeekStartDayEnum | NullEnum) | null;
    primary_dashboard: number | null;
    live_events_columns: Array<string> | null;
    recording_domains: Array<string | null> | null;
    person_on_events_querying_enabled: string;
    inject_web_apps: boolean | null;
    extra_settings: unknown | null;
    modifiers: unknown | null;
    default_modifiers: string;
    has_completed_onboarding_for: unknown | null;
    surveys_opt_in: boolean | null;
    heatmaps_opt_in: boolean | null;
    product_intents: string;
    flags_persistence_default: boolean | null;
    secret_api_token: string | null;
    secret_api_token_backup: string | null;
    receive_org_level_activity_logs: boolean | null;
    business_model: (BusinessModelEnum | BlankEnum | NullEnum) | null;
    conversations_enabled: boolean | null;
    conversations_settings: unknown | null;
    logs_settings: unknown | null;
  }>;
  export type PatchedProxyRecord = Partial<{
    id: string;
    domain: string;
    target_cname: string;
    status: ProxyRecordStatusEnum & unknown;
    message: string | null;
    created_at: string;
    updated_at: string;
    created_by: number | null;
  }>;
  export type PatchedRemovePersonRequest = Partial<{ person_id: string }>;
  export type PatchedRole = Partial<{
    id: string;
    name: string;
    created_at: string;
    created_by: UserBasic & unknown;
    members: string;
    is_default: string;
  }>;
  export type PatchedSessionGroupSummary = Partial<{
    id: string;
    title: string;
    session_ids: Array<string>;
    summary: unknown;
    extra_summary_context: unknown | null;
    run_metadata: unknown | null;
    created_at: string;
    created_by: UserBasic & unknown;
    team: number;
  }>;
  export type PatchedSessionRecording = Partial<{
    id: string;
    distinct_id: string | null;
    viewed: boolean;
    viewers: Array<string>;
    recording_duration: number;
    active_seconds: number | null;
    inactive_seconds: number | null;
    start_time: string | null;
    end_time: string | null;
    click_count: number | null;
    keypress_count: number | null;
    mouse_activity_count: number | null;
    console_log_count: number | null;
    console_warn_count: number | null;
    console_error_count: number | null;
    start_url: string | null;
    person: MinimalPerson;
    retention_period_days: number | null;
    expiry_time: string;
    recording_ttl: string;
    snapshot_source: string | null;
    snapshot_library: string | null;
    ongoing: boolean;
    activity_score: number | null;
    external_references: Array<Record<string, unknown>>;
  }>;
  export type PatchedSessionRecordingPlaylist = Partial<{
    id: number;
    short_id: string;
    name: string | null;
    derived_name: string | null;
    description: string;
    pinned: boolean;
    created_at: string;
    created_by: UserBasic & unknown;
    deleted: boolean;
    filters: unknown;
    last_modified_at: string;
    last_modified_by: UserBasic & unknown;
    recordings_counts: Record<string, Record<string, unknown>>;
    type: (SessionRecordingPlaylistTypeEnum | NullEnum) | null;
    is_synthetic: boolean;
    _create_in_folder: string;
  }>;
  export type PatchedSubscription = Partial<{
    id: number;
    dashboard: number | null;
    insight: number | null;
    target_type: TargetTypeEnum;
    target_value: string;
    frequency: FrequencyEnum;
    interval: number;
    byweekday: Array<ByweekdayEnum> | null;
    bysetpos: number | null;
    count: number | null;
    start_date: string;
    until_date: string | null;
    created_at: string;
    created_by: UserBasic & unknown;
    deleted: boolean;
    title: string | null;
    summary: string;
    next_delivery_date: string | null;
    invite_message: string | null;
  }>;
  export type PatchedSurveySerializerCreateUpdateOnly = Partial<{
    id: string;
    name: string;
    description: string;
    type: SurveyType;
    schedule: string | null;
    linked_flag: MinimalFeatureFlag & unknown;
    linked_flag_id: number | null;
    linked_insight_id: number | null;
    targeting_flag_id: number;
    targeting_flag: MinimalFeatureFlag & unknown;
    internal_targeting_flag: MinimalFeatureFlag & unknown;
    targeting_flag_filters: unknown | null;
    remove_targeting_flag: boolean | null;
    questions: unknown | null;
    conditions: unknown | null;
    appearance: unknown | null;
    created_at: string;
    created_by: UserBasic & unknown;
    start_date: string | null;
    end_date: string | null;
    archived: boolean;
    responses_limit: number | null;
    iteration_count: number | null;
    iteration_frequency_days: number | null;
    iteration_start_dates: Array<string | null> | null;
    current_iteration: number | null;
    current_iteration_start_date: string | null;
    response_sampling_start_date: string | null;
    response_sampling_interval_type: (ResponseSamplingIntervalTypeEnum | BlankEnum | NullEnum) | null;
    response_sampling_interval: number | null;
    response_sampling_limit: number | null;
    response_sampling_daily_limits: unknown | null;
    enable_partial_responses: boolean | null;
    enable_iframe_embedding: boolean | null;
    _create_in_folder: string;
  }>;
  export type PatchedTable = Partial<{
    id: string;
    deleted: boolean | null;
    name: string;
    format: TableFormatEnum;
    created_by: UserBasic & unknown;
    created_at: string;
    url_pattern: string;
    credential: Credential;
    columns: string;
    external_data_source: SimpleExternalDataSourceSerializers & unknown;
    external_schema: string;
  }>;
  export type PatchedTask = Partial<{
    id: string;
    task_number: number | null;
    slug: string;
    title: string;
    description: string;
    origin_product: OriginProductEnum;
    repository: string | null;
    github_integration: number | null;
    json_schema: unknown | null;
    latest_run: string;
    created_at: string;
    updated_at: string;
    created_by: UserBasic & unknown;
  }>;
  export type TaskRunUpdateStatusEnum = "not_started" | "queued" | "in_progress" | "completed" | "failed" | "cancelled";
  export type PatchedTaskRunUpdate = Partial<{
    status: TaskRunUpdateStatusEnum;
    branch: string | null;
    stage: string | null;
    output: unknown | null;
    state: unknown;
    error_message: string | null;
  }>;
  export type SessionRecordingRetentionPeriodEnum = "30d" | "90d" | "1y" | "5y";
  export type TeamRevenueAnalyticsConfig = Partial<{
    base_currency: BaseCurrencyEnum;
    events: unknown;
    goals: unknown;
    filter_test_accounts: boolean;
  }>;
  export type TeamMarketingAnalyticsConfig = Partial<{
    sources_map: unknown;
    conversion_goals: unknown;
    attribution_window_days: number;
    attribution_mode: AttributionModeEnum;
    campaign_name_mappings: unknown;
    custom_source_mappings: unknown;
    campaign_field_preferences: unknown;
  }>;
  export type TeamCustomerAnalyticsConfig = Partial<{
    activity_event: unknown;
    signup_pageview_event: unknown;
    signup_event: unknown;
    subscription_event: unknown;
    payment_event: unknown;
  }>;
  export type PatchedTeam = Partial<{
    id: number;
    uuid: string;
    name: string;
    access_control: boolean;
    organization: string;
    project_id: number;
    api_token: string;
    secret_api_token: string | null;
    secret_api_token_backup: string | null;
    created_at: string;
    updated_at: string;
    ingested_event: boolean;
    default_modifiers: Record<string, unknown>;
    person_on_events_querying_enabled: boolean;
    user_access_level: string | null;
    app_urls: Array<string | null>;
    slack_incoming_webhook: string | null;
    anonymize_ips: boolean;
    completed_snippet_onboarding: boolean;
    test_account_filters: unknown;
    test_account_filters_default_checked: boolean | null;
    path_cleaning_filters: unknown | null;
    is_demo: boolean;
    timezone: TimezoneEnum;
    data_attributes: unknown;
    person_display_name_properties: Array<string> | null;
    correlation_config: unknown | null;
    autocapture_opt_out: boolean | null;
    autocapture_exceptions_opt_in: boolean | null;
    autocapture_web_vitals_opt_in: boolean | null;
    autocapture_web_vitals_allowed_metrics: unknown | null;
    autocapture_exceptions_errors_to_ignore: unknown | null;
    capture_console_log_opt_in: boolean | null;
    logs_settings: unknown | null;
    capture_performance_opt_in: boolean | null;
    session_recording_opt_in: boolean;
    session_recording_sample_rate: string | null;
    session_recording_minimum_duration_milliseconds: number | null;
    session_recording_linked_flag: unknown | null;
    session_recording_network_payload_capture_config: unknown | null;
    session_recording_masking_config: unknown | null;
    session_recording_url_trigger_config: Array<unknown | null> | null;
    session_recording_url_blocklist_config: Array<unknown | null> | null;
    session_recording_event_trigger_config: Array<string | null> | null;
    session_recording_trigger_match_type_config: string | null;
    session_recording_retention_period: SessionRecordingRetentionPeriodEnum;
    session_replay_config: unknown | null;
    survey_config: unknown | null;
    week_start_day: (WeekStartDayEnum | NullEnum) | null;
    primary_dashboard: number | null;
    live_events_columns: Array<string> | null;
    recording_domains: Array<string | null> | null;
    cookieless_server_hash_mode: (CookielessServerHashModeEnum | NullEnum) | null;
    human_friendly_comparison_periods: boolean | null;
    inject_web_apps: boolean | null;
    extra_settings: unknown | null;
    modifiers: unknown | null;
    has_completed_onboarding_for: unknown | null;
    surveys_opt_in: boolean | null;
    heatmaps_opt_in: boolean | null;
    flags_persistence_default: boolean | null;
    feature_flag_confirmation_enabled: boolean | null;
    feature_flag_confirmation_message: string | null;
    default_evaluation_contexts_enabled: boolean | null;
    require_evaluation_contexts: boolean | null;
    capture_dead_clicks: boolean | null;
    default_data_theme: number | null;
    revenue_analytics_config: TeamRevenueAnalyticsConfig;
    marketing_analytics_config: TeamMarketingAnalyticsConfig;
    customer_analytics_config: TeamCustomerAnalyticsConfig;
    onboarding_tasks: unknown | null;
    base_currency: BaseCurrencyEnum & unknown;
    web_analytics_pre_aggregated_tables_enabled: boolean | null;
    experiment_recalculation_time: string | null;
    default_experiment_confidence_level: string | null;
    default_experiment_stats_method: (DefaultExperimentStatsMethodEnum | BlankEnum | NullEnum) | null;
    receive_org_level_activity_logs: boolean | null;
    business_model: (BusinessModelEnum | BlankEnum | NullEnum) | null;
    conversations_enabled: boolean | null;
    conversations_settings: unknown | null;
    proactive_tasks_enabled: boolean | null;
    effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null;
    has_group_types: boolean;
    group_types: Array<Record<string, unknown>>;
    live_events_token: string | null;
    product_intents: string;
    managed_viewsets: string;
  }>;
  export type PatchedTicket = Partial<{
    id: string;
    ticket_number: number;
    channel_source: ChannelSourceEnum & unknown;
    distinct_id: string;
    status: TicketStatusEnum;
    priority: (PriorityEnum | BlankEnum | NullEnum) | null;
    assignee: TicketAssignment & unknown;
    anonymous_traits: unknown;
    ai_resolved: boolean;
    escalation_reason: string | null;
    created_at: string;
    updated_at: string;
    message_count: number;
    last_message_at: string | null;
    last_message_text: string | null;
    unread_team_count: number;
    session_id: string | null;
    session_context: unknown;
    person: (TicketPerson & (unknown | null)) | null;
  }>;
  export type PatchedUser = Partial<{
    date_joined: string;
    uuid: string;
    distinct_id: string | null;
    first_name: string;
    last_name: string;
    email: string;
    pending_email: string | null;
    is_email_verified: boolean | null;
    notification_settings: Record<string, unknown>;
    anonymize_data: boolean | null;
    allow_impersonation: boolean | null;
    toolbar_mode: (ToolbarModeEnum | BlankEnum | NullEnum) | null;
    has_password: boolean;
    id: number;
    is_staff: boolean;
    is_impersonated: boolean | null;
    is_impersonated_until: string | null;
    is_impersonated_read_only: boolean | null;
    sensitive_session_expires_at: string | null;
    team: TeamBasic & unknown;
    organization: Organization & unknown;
    organizations: Array<OrganizationBasic>;
    set_current_organization: string;
    set_current_team: string;
    password: string;
    current_password: string;
    events_column_config: unknown;
    is_2fa_enabled: boolean;
    has_social_auth: boolean;
    has_sso_enforcement: boolean;
    has_seen_product_intro_for: unknown | null;
    scene_personalisation: Array<ScenePersonalisationBasic>;
    theme_mode: (ThemeModeEnum | BlankEnum | NullEnum) | null;
    hedgehog_config: unknown | null;
    allow_sidebar_suggestions: boolean | null;
    shortcut_position: (ShortcutPositionEnum | BlankEnum | NullEnum) | null;
    role_at_organization: RoleAtOrganizationEnum;
    passkeys_enabled_for_2fa: boolean | null;
  }>;
  export type PatchedUserInterview = Partial<{
    id: string;
    created_by: UserBasic & unknown;
    created_at: string;
    interviewee_emails: Array<string>;
    transcript: string;
    summary: string;
    audio: string;
  }>;
  export type PatchedWebExperimentsAPI = Partial<{
    id: number;
    name: string;
    created_at: string;
    feature_flag_key: string;
    variants: unknown;
  }>;
  export type PinnedSceneTabs = Partial<{
    tabs: Array<PinnedSceneTab>;
    homepage: (PinnedSceneTab & (unknown | null)) | null;
  }>;
  export type ProductTourSerializerCreateUpdateOnly = {
    id: string;
    name: string;
    description?: string | undefined;
    internal_targeting_flag: MinimalFeatureFlag & unknown;
    linked_flag: MinimalFeatureFlag & unknown;
    linked_flag_id?: (number | null) | undefined;
    targeting_flag_filters?: (unknown | null) | undefined;
    content?: unknown | undefined;
    auto_launch?: boolean | undefined;
    start_date?: (string | null) | undefined;
    end_date?: (string | null) | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    updated_at: string;
    archived?: boolean | undefined;
    creation_context?: (ProductTourSerializerCreateUpdateOnlyCreationContextEnum & unknown) | undefined;
  };
  export type ProjectBackwardCompat = {
    id: number;
    organization: string;
    name?: string | undefined;
    product_description?: (string | null) | undefined;
    created_at: string;
    effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null;
    has_group_types: boolean;
    group_types: Array<Record<string, unknown>>;
    live_events_token: string | null;
    updated_at: string;
    uuid: string;
    api_token: string;
    app_urls?: Array<string | null> | undefined;
    slack_incoming_webhook?: (string | null) | undefined;
    anonymize_ips?: boolean | undefined;
    completed_snippet_onboarding?: boolean | undefined;
    ingested_event: boolean;
    test_account_filters?: unknown | undefined;
    test_account_filters_default_checked?: (boolean | null) | undefined;
    path_cleaning_filters?: (unknown | null) | undefined;
    is_demo?: boolean | undefined;
    timezone?: TimezoneEnum | undefined;
    data_attributes?: unknown | undefined;
    person_display_name_properties?: (Array<string> | null) | undefined;
    correlation_config?: (unknown | null) | undefined;
    autocapture_opt_out?: (boolean | null) | undefined;
    autocapture_exceptions_opt_in?: (boolean | null) | undefined;
    autocapture_web_vitals_opt_in?: (boolean | null) | undefined;
    autocapture_web_vitals_allowed_metrics?: (unknown | null) | undefined;
    autocapture_exceptions_errors_to_ignore?: (unknown | null) | undefined;
    capture_console_log_opt_in?: (boolean | null) | undefined;
    capture_performance_opt_in?: (boolean | null) | undefined;
    session_recording_opt_in?: boolean | undefined;
    session_recording_sample_rate?: (string | null) | undefined;
    session_recording_minimum_duration_milliseconds?: (number | null) | undefined;
    session_recording_linked_flag?: (unknown | null) | undefined;
    session_recording_network_payload_capture_config?: (unknown | null) | undefined;
    session_recording_masking_config?: (unknown | null) | undefined;
    session_replay_config?: (unknown | null) | undefined;
    survey_config?: (unknown | null) | undefined;
    access_control?: boolean | undefined;
    week_start_day?: ((WeekStartDayEnum | NullEnum) | null) | undefined;
    primary_dashboard?: (number | null) | undefined;
    live_events_columns?: (Array<string> | null) | undefined;
    recording_domains?: (Array<string | null> | null) | undefined;
    person_on_events_querying_enabled: string;
    inject_web_apps?: (boolean | null) | undefined;
    extra_settings?: (unknown | null) | undefined;
    modifiers?: (unknown | null) | undefined;
    default_modifiers: string;
    has_completed_onboarding_for?: (unknown | null) | undefined;
    surveys_opt_in?: (boolean | null) | undefined;
    heatmaps_opt_in?: (boolean | null) | undefined;
    product_intents: string;
    flags_persistence_default?: (boolean | null) | undefined;
    secret_api_token: string | null;
    secret_api_token_backup: string | null;
    receive_org_level_activity_logs?: (boolean | null) | undefined;
    business_model?: ((BusinessModelEnum | BlankEnum | NullEnum) | null) | undefined;
    conversations_enabled?: (boolean | null) | undefined;
    conversations_settings?: (unknown | null) | undefined;
    logs_settings?: (unknown | null) | undefined;
  };
  export type PropertyItemTypeEnum =
    | "event"
    | "event_metadata"
    | "feature"
    | "person"
    | "cohort"
    | "element"
    | "static-cohort"
    | "dynamic-cohort"
    | "precalculated-cohort"
    | "group"
    | "recording"
    | "log_entry"
    | "behavioral"
    | "session"
    | "hogql"
    | "data_warehouse"
    | "data_warehouse_person_property"
    | "error_tracking_issue"
    | "log"
    | "log_attribute"
    | "log_resource_attribute"
    | "revenue_analytics"
    | "flag"
    | "workflow_variable";
  export type PropertyItem = {
    key: string;
    value: string;
    operator?: ((OperatorEnum | BlankEnum | NullEnum) | null) | undefined;
    type?: (PropertyItemTypeEnum | BlankEnum) | undefined;
  };
  export type Property = { type?: (PropertyTypeEnum & unknown) | undefined; values: Array<PropertyItem> };
  export type SavedInsightNode = {
    allowSorting?: (boolean | null) | undefined;
    context?: DataTableNodeViewPropsContext | undefined;
    contextKey?: (string | null) | undefined;
    defaultColumns?: (Array<string> | null) | undefined;
    embedded?: (boolean | null) | undefined;
    expandable?: (boolean | null) | undefined;
    full?: (boolean | null) | undefined;
    hidePersonsModal?: (boolean | null) | undefined;
    hideTooltipOnScroll?: (boolean | null) | undefined;
    kind?: "SavedInsightNode" | undefined;
    propertiesViaUrl?: (boolean | null) | undefined;
    shortId: string;
    showActions?: (boolean | null) | undefined;
    showColumnConfigurator?: (boolean | null) | undefined;
    showCorrelationTable?: (boolean | null) | undefined;
    showCount?: (boolean | null) | undefined;
    showDateRange?: (boolean | null) | undefined;
    showElapsedTime?: (boolean | null) | undefined;
    showEventFilter?: (boolean | null) | undefined;
    showEventsFilter?: (boolean | null) | undefined;
    showExport?: (boolean | null) | undefined;
    showFilters?: (boolean | null) | undefined;
    showHeader?: (boolean | null) | undefined;
    showHogQLEditor?: (boolean | null) | undefined;
    showLastComputation?: (boolean | null) | undefined;
    showLastComputationRefresh?: (boolean | null) | undefined;
    showOpenEditorButton?: (boolean | null) | undefined;
    showPersistentColumnConfigurator?: (boolean | null) | undefined;
    showPropertyFilter?: ((boolean | Array<TaxonomicFilterGroupType>) | null) | undefined;
    showRecordingColumn?: (boolean | null) | undefined;
    showReload?: (boolean | null) | undefined;
    showResults?: (boolean | null) | undefined;
    showResultsTable?: (boolean | null) | undefined;
    showSavedFilters?: (boolean | null) | undefined;
    showSavedQueries?: (boolean | null) | undefined;
    showSearch?: (boolean | null) | undefined;
    showSourceQueryOptions?: (boolean | null) | undefined;
    showTable?: (boolean | null) | undefined;
    showTableViews?: (boolean | null) | undefined;
    showTestAccountFilters?: (boolean | null) | undefined;
    showTimings?: (boolean | null) | undefined;
    suppressSessionAnalysisWarning?: (boolean | null) | undefined;
    version?: (number | null) | undefined;
    vizSpecificOptions?: VizSpecificOptions | undefined;
  };
  export type SuggestedQuestionsQueryResponse = { questions: Array<string> };
  export type SuggestedQuestionsQuery = Partial<{
    kind: "SuggestedQuestionsQuery";
    modifiers: HogQLQueryModifiers;
    response: SuggestedQuestionsQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type TeamTaxonomyItem = { count: number; event: string };
  export type TeamTaxonomyQueryResponse = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<TeamTaxonomyItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type TeamTaxonomyQuery = Partial<{
    kind: "TeamTaxonomyQuery";
    modifiers: HogQLQueryModifiers;
    response: TeamTaxonomyQueryResponse;
    tags: QueryLogTags;
    version: number | null;
  }>;
  export type RefreshType =
    | "async"
    | "async_except_on_cache_miss"
    | "blocking"
    | "force_async"
    | "force_blocking"
    | "force_cache"
    | "lazy_async";
  export type QueryRequest = {
    async?: (boolean | null) | undefined;
    client_query_id?: (string | null) | undefined;
    filters_override?: DashboardFilter | undefined;
    name?: (string | null) | undefined;
    query:
      | EventsNode
      | ActionsNode
      | PersonsNode
      | DataWarehouseNode
      | EventsQuery
      | SessionsQuery
      | ActorsQuery
      | GroupsQuery
      | InsightActorsQuery
      | InsightActorsQueryOptions
      | SessionsTimelineQuery
      | HogQuery
      | HogQLQuery
      | HogQLMetadata
      | HogQLAutocomplete
      | HogQLASTQuery
      | SessionAttributionExplorerQuery
      | RevenueExampleEventsQuery
      | RevenueExampleDataWarehouseTablesQuery
      | ErrorTrackingQuery
      | ErrorTrackingSimilarIssuesQuery
      | ErrorTrackingBreakdownsQuery
      | ErrorTrackingIssueCorrelationQuery
      | ExperimentFunnelsQuery
      | ExperimentTrendsQuery
      | ExperimentQuery
      | ExperimentExposureQuery
      | DocumentSimilarityQuery
      | WebOverviewQuery
      | WebStatsTableQuery
      | WebExternalClicksTableQuery
      | WebGoalsQuery
      | WebVitalsQuery
      | WebVitalsPathBreakdownQuery
      | WebPageURLSearchQuery
      | WebAnalyticsExternalSummaryQuery
      | RevenueAnalyticsGrossRevenueQuery
      | RevenueAnalyticsMetricsQuery
      | RevenueAnalyticsMRRQuery
      | RevenueAnalyticsOverviewQuery
      | RevenueAnalyticsTopCustomersQuery
      | MarketingAnalyticsTableQuery
      | MarketingAnalyticsAggregatedQuery
      | NonIntegratedConversionsTableQuery
      | DataVisualizationNode
      | DataTableNode
      | SavedInsightNode
      | InsightVizNode
      | TrendsQuery
      | FunnelsQuery
      | RetentionQuery
      | PathsQuery
      | StickinessQuery
      | LifecycleQuery
      | FunnelCorrelationQuery
      | DatabaseSchemaQuery
      | LogsQuery
      | LogAttributesQuery
      | LogValuesQuery
      | SuggestedQuestionsQuery
      | TeamTaxonomyQuery
      | EventTaxonomyQuery
      | ActorsPropertyTaxonomyQuery
      | TracesQuery
      | TraceQuery
      | TraceNeighborsQuery
      | VectorSearchQuery
      | UsageMetricsQuery
      | EndpointsUsageOverviewQuery
      | EndpointsUsageTableQuery
      | EndpointsUsageTrendsQuery;
    refresh?: RefreshType | undefined;
    variables_override?: (Record<string, Record<string, unknown>> | null) | undefined;
  };
  export type QueryResponseAlternative1 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type QueryResponseAlternative3 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit: number;
    missing_actors_count?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<string> | null) | undefined;
  };
  export type QueryResponseAlternative4 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    kind?: "GroupsQuery" | undefined;
    limit: number;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type QueryResponseAlternative5 = Partial<{
    breakdown: Array<BreakdownItem> | null;
    breakdowns: Array<MultipleBreakdownOptions> | null;
    compare: Array<CompareItem> | null;
    day: Array<DayItem> | null;
    interval: Array<IntervalItem> | null;
    series: Array<Series> | null;
    status: Array<StatusItem> | null;
  }>;
  export type QueryResponseAlternative6 = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<TimelineEntry>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative7 = {
    bytecode?: (Array<unknown> | null) | undefined;
    coloredBytecode?: (Array<unknown> | null) | undefined;
    results: unknown;
    stdout?: (string | null) | undefined;
  };
  export type QueryResponseAlternative8 = {
    clickhouse?: (string | null) | undefined;
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    explain?: (Array<string> | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    metadata?: HogQLMetadataResponse | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query?: (string | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative9 = {
    ch_table_names?: (Array<string> | null) | undefined;
    errors: Array<HogQLNotice>;
    isUsingIndices?: QueryIndexUsage | undefined;
    isValid?: (boolean | null) | undefined;
    notices: Array<HogQLNotice>;
    query?: (string | null) | undefined;
    table_names?: (Array<string> | null) | undefined;
    warnings: Array<HogQLNotice>;
  };
  export type QueryResponseAlternative10 = {
    incomplete_list: boolean;
    suggestions: Array<AutocompleteCompletionItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative11 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative14 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<ErrorTrackingIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative15 = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<SimilarIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative16 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Record<string, unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative17 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<ErrorTrackingCorrelatedIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative18 = {
    credible_intervals: Record<string, Array<number>>;
    expected_loss: number;
    funnels_query?: FunnelsQuery | undefined;
    insight: Array<Array<Record<string, unknown>>>;
    kind?: "ExperimentFunnelsQuery" | undefined;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantFunnelsBaseStats>;
  };
  export type QueryResponseAlternative19 = {
    count_query?: TrendsQuery | undefined;
    credible_intervals: Record<string, Array<number>>;
    exposure_query?: TrendsQuery | undefined;
    insight: Array<Record<string, unknown>>;
    kind?: "ExperimentTrendsQuery" | undefined;
    p_value: number;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantTrendsBaseStats>;
  };
  export type QueryResponseAlternative20 = Partial<{
    baseline: ExperimentStatsBaseValidated;
    breakdown_results: Array<ExperimentBreakdownResult> | null;
    clickhouse_sql: string | null;
    credible_intervals: Record<string, Array<number>> | null;
    hogql: string | null;
    insight: Array<Record<string, unknown>> | null;
    kind: "ExperimentQuery";
    metric: (ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric) | null;
    p_value: number | null;
    probability: Record<string, number> | null;
    significance_code: ExperimentSignificanceCode;
    significant: boolean | null;
    stats_version: number | null;
    variant_results: (Array<ExperimentVariantResultFrequentist> | Array<ExperimentVariantResultBayesian>) | null;
    variants: (Array<ExperimentVariantTrendsBaseStats> | Array<ExperimentVariantFunnelsBaseStats>) | null;
  }>;
  export type QueryResponseAlternative21 = {
    date_range: DateRange;
    kind?: "ExperimentExposureQuery" | undefined;
    sample_ratio_mismatch?: SampleRatioMismatch | undefined;
    timeseries: Array<ExperimentExposureTimeSeries>;
    total_exposures: Record<string, number>;
  };
  export type QueryResponseAlternative22 = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<EmbeddingDistance>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative23 = {
    dateFrom?: (string | null) | undefined;
    dateTo?: (string | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebOverviewItem>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type QueryResponseAlternative24 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type QueryResponseAlternative25 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative27 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebVitalsPathBreakdownResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative28 = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<PageURL>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative29 = {
    data: Record<string, unknown>;
    error?: ExternalQueryError | undefined;
    status: ExternalQueryStatus;
  };
  export type QueryResponseAlternative30 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative31 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative32 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsMRRQueryResultItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative33 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsOverviewItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative34 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative35 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative36 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Record<string, unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative37 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative38 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type QueryResponseAlternative39 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit: number;
    missing_actors_count?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<string> | null) | undefined;
  };
  export type QueryResponseAlternative40 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    kind?: "GroupsQuery" | undefined;
    limit: number;
    modifiers?: HogQLQueryModifiers | undefined;
    offset: number;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type QueryResponseAlternative41 = {
    clickhouse?: (string | null) | undefined;
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    explain?: (Array<string> | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    metadata?: HogQLMetadataResponse | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query?: (string | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative42 = {
    dateFrom?: (string | null) | undefined;
    dateTo?: (string | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebOverviewItem>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type QueryResponseAlternative43 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
    usedPreAggregatedTables?: (boolean | null) | undefined;
  };
  export type QueryResponseAlternative44 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative46 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<WebVitalsPathBreakdownResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative47 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative48 = {
    columns: Array<unknown>;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql: string;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types: Array<string>;
  };
  export type QueryResponseAlternative49 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative50 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative51 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsMRRQueryResultItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative52 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RevenueAnalyticsOverviewItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative53 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative54 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative56 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative57 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Record<string, unknown>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative58 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Array<MarketingAnalyticsItem>>;
    samplingRate?: SamplingRate | undefined;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative59 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<ErrorTrackingIssue>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative61 = {
    credible_intervals: Record<string, Array<number>>;
    expected_loss: number;
    funnels_query?: FunnelsQuery | undefined;
    insight: Array<Array<Record<string, unknown>>>;
    kind?: "ExperimentFunnelsQuery" | undefined;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantFunnelsBaseStats>;
  };
  export type QueryResponseAlternative62 = {
    count_query?: TrendsQuery | undefined;
    credible_intervals: Record<string, Array<number>>;
    exposure_query?: TrendsQuery | undefined;
    insight: Array<Record<string, unknown>>;
    kind?: "ExperimentTrendsQuery" | undefined;
    p_value: number;
    probability: Record<string, number>;
    significance_code: ExperimentSignificanceCode;
    significant: boolean;
    stats_version?: (number | null) | undefined;
    variants: Array<ExperimentVariantTrendsBaseStats>;
  };
  export type QueryResponseAlternative63 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<LLMTrace>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative64 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative65 = {
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative66 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative67 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<RetentionResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative68 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<PathsLink>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative69 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative71 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: FunnelCorrelationResult;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative72 = { joins: Array<DataWarehouseViewLink>; tables: Record<string, unknown> };
  export type QueryResponseAlternative73 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    nextCursor?: (string | null) | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: unknown;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative74 = {
    count: number;
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative75 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<LogValueResult>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative76 = { questions: Array<string> };
  export type QueryResponseAlternative77 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<TeamTaxonomyItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative78 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<EventTaxonomyItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative79 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: ActorsPropertyTaxonomyResponse | Array<ActorsPropertyTaxonomyResponse>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative80 = {
    columns?: (Array<string> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<LLMTrace>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative82 = Partial<{
    newerTimestamp: string | null;
    newerTraceId: string | null;
    olderTimestamp: string | null;
    olderTraceId: string | null;
    timings: Array<QueryTiming> | null;
  }>;
  export type QueryResponseAlternative83 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<VectorSearchResponseItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative84 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<UsageMetric>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative85 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<EndpointsUsageOverviewItem>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative86 = {
    columns?: (Array<unknown> | null) | undefined;
    error?: (string | null) | undefined;
    hasMore?: (boolean | null) | undefined;
    hogql?: (string | null) | undefined;
    limit?: (number | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    offset?: (number | null) | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<unknown>;
    timings?: (Array<QueryTiming> | null) | undefined;
    types?: (Array<unknown> | null) | undefined;
  };
  export type QueryResponseAlternative87 = {
    error?: (string | null) | undefined;
    hogql?: (string | null) | undefined;
    modifiers?: HogQLQueryModifiers | undefined;
    query_status?: QueryStatus | undefined;
    resolved_date_range?: ResolvedDateRangeResponse | undefined;
    results: Array<Record<string, unknown>>;
    timings?: (Array<QueryTiming> | null) | undefined;
  };
  export type QueryResponseAlternative =
    | Record<string, unknown>
    | QueryResponseAlternative1
    | QueryResponseAlternative3
    | QueryResponseAlternative4
    | QueryResponseAlternative5
    | QueryResponseAlternative6
    | QueryResponseAlternative7
    | QueryResponseAlternative8
    | QueryResponseAlternative9
    | QueryResponseAlternative10
    | QueryResponseAlternative11
    | QueryResponseAlternative14
    | QueryResponseAlternative15
    | QueryResponseAlternative16
    | QueryResponseAlternative17
    | QueryResponseAlternative18
    | QueryResponseAlternative19
    | QueryResponseAlternative20
    | QueryResponseAlternative21
    | QueryResponseAlternative22
    | QueryResponseAlternative23
    | QueryResponseAlternative24
    | QueryResponseAlternative25
    | QueryResponseAlternative27
    | QueryResponseAlternative28
    | QueryResponseAlternative29
    | QueryResponseAlternative30
    | QueryResponseAlternative31
    | QueryResponseAlternative32
    | QueryResponseAlternative33
    | QueryResponseAlternative34
    | QueryResponseAlternative35
    | QueryResponseAlternative36
    | QueryResponseAlternative37
    | unknown
    | QueryResponseAlternative38
    | QueryResponseAlternative39
    | QueryResponseAlternative40
    | QueryResponseAlternative41
    | QueryResponseAlternative42
    | QueryResponseAlternative43
    | QueryResponseAlternative44
    | QueryResponseAlternative46
    | QueryResponseAlternative47
    | QueryResponseAlternative48
    | QueryResponseAlternative49
    | QueryResponseAlternative50
    | QueryResponseAlternative51
    | QueryResponseAlternative52
    | QueryResponseAlternative53
    | QueryResponseAlternative54
    | QueryResponseAlternative56
    | QueryResponseAlternative57
    | QueryResponseAlternative58
    | QueryResponseAlternative59
    | QueryResponseAlternative61
    | QueryResponseAlternative62
    | QueryResponseAlternative63
    | QueryResponseAlternative64
    | QueryResponseAlternative65
    | QueryResponseAlternative66
    | QueryResponseAlternative67
    | QueryResponseAlternative68
    | QueryResponseAlternative69
    | QueryResponseAlternative71
    | QueryResponseAlternative72
    | QueryResponseAlternative73
    | QueryResponseAlternative74
    | QueryResponseAlternative75
    | QueryResponseAlternative76
    | QueryResponseAlternative77
    | QueryResponseAlternative78
    | QueryResponseAlternative79
    | QueryResponseAlternative80
    | QueryResponseAlternative82
    | QueryResponseAlternative83
    | QueryResponseAlternative84
    | QueryResponseAlternative85
    | QueryResponseAlternative86
    | QueryResponseAlternative87;
  export type QueryStatusResponse = { query_status: QueryStatus };
  export type QueryUpgradeRequest = {
    query:
      | EventsNode
      | ActionsNode
      | PersonsNode
      | DataWarehouseNode
      | EventsQuery
      | SessionsQuery
      | ActorsQuery
      | GroupsQuery
      | InsightActorsQuery
      | InsightActorsQueryOptions
      | SessionsTimelineQuery
      | HogQuery
      | HogQLQuery
      | HogQLMetadata
      | HogQLAutocomplete
      | HogQLASTQuery
      | SessionAttributionExplorerQuery
      | RevenueExampleEventsQuery
      | RevenueExampleDataWarehouseTablesQuery
      | ErrorTrackingQuery
      | ErrorTrackingSimilarIssuesQuery
      | ErrorTrackingBreakdownsQuery
      | ErrorTrackingIssueCorrelationQuery
      | ExperimentFunnelsQuery
      | ExperimentTrendsQuery
      | ExperimentQuery
      | ExperimentExposureQuery
      | DocumentSimilarityQuery
      | WebOverviewQuery
      | WebStatsTableQuery
      | WebExternalClicksTableQuery
      | WebGoalsQuery
      | WebVitalsQuery
      | WebVitalsPathBreakdownQuery
      | WebPageURLSearchQuery
      | WebAnalyticsExternalSummaryQuery
      | RevenueAnalyticsGrossRevenueQuery
      | RevenueAnalyticsMetricsQuery
      | RevenueAnalyticsMRRQuery
      | RevenueAnalyticsOverviewQuery
      | RevenueAnalyticsTopCustomersQuery
      | MarketingAnalyticsTableQuery
      | MarketingAnalyticsAggregatedQuery
      | NonIntegratedConversionsTableQuery
      | DataVisualizationNode
      | DataTableNode
      | SavedInsightNode
      | InsightVizNode
      | TrendsQuery
      | FunnelsQuery
      | RetentionQuery
      | PathsQuery
      | StickinessQuery
      | LifecycleQuery
      | FunnelCorrelationQuery
      | DatabaseSchemaQuery
      | LogsQuery
      | LogAttributesQuery
      | LogValuesQuery
      | SuggestedQuestionsQuery
      | TeamTaxonomyQuery
      | EventTaxonomyQuery
      | ActorsPropertyTaxonomyQuery
      | TracesQuery
      | TraceQuery
      | TraceNeighborsQuery
      | VectorSearchQuery
      | UsageMetricsQuery
      | EndpointsUsageOverviewQuery
      | EndpointsUsageTableQuery
      | EndpointsUsageTrendsQuery;
  };
  export type QueryUpgradeResponse = {
    query:
      | EventsNode
      | ActionsNode
      | PersonsNode
      | DataWarehouseNode
      | EventsQuery
      | SessionsQuery
      | ActorsQuery
      | GroupsQuery
      | InsightActorsQuery
      | InsightActorsQueryOptions
      | SessionsTimelineQuery
      | HogQuery
      | HogQLQuery
      | HogQLMetadata
      | HogQLAutocomplete
      | HogQLASTQuery
      | SessionAttributionExplorerQuery
      | RevenueExampleEventsQuery
      | RevenueExampleDataWarehouseTablesQuery
      | ErrorTrackingQuery
      | ErrorTrackingSimilarIssuesQuery
      | ErrorTrackingBreakdownsQuery
      | ErrorTrackingIssueCorrelationQuery
      | ExperimentFunnelsQuery
      | ExperimentTrendsQuery
      | ExperimentQuery
      | ExperimentExposureQuery
      | DocumentSimilarityQuery
      | WebOverviewQuery
      | WebStatsTableQuery
      | WebExternalClicksTableQuery
      | WebGoalsQuery
      | WebVitalsQuery
      | WebVitalsPathBreakdownQuery
      | WebPageURLSearchQuery
      | WebAnalyticsExternalSummaryQuery
      | RevenueAnalyticsGrossRevenueQuery
      | RevenueAnalyticsMetricsQuery
      | RevenueAnalyticsMRRQuery
      | RevenueAnalyticsOverviewQuery
      | RevenueAnalyticsTopCustomersQuery
      | MarketingAnalyticsTableQuery
      | MarketingAnalyticsAggregatedQuery
      | NonIntegratedConversionsTableQuery
      | DataVisualizationNode
      | DataTableNode
      | SavedInsightNode
      | InsightVizNode
      | TrendsQuery
      | FunnelsQuery
      | RetentionQuery
      | PathsQuery
      | StickinessQuery
      | LifecycleQuery
      | FunnelCorrelationQuery
      | DatabaseSchemaQuery
      | LogsQuery
      | LogAttributesQuery
      | LogValuesQuery
      | SuggestedQuestionsQuery
      | TeamTaxonomyQuery
      | EventTaxonomyQuery
      | ActorsPropertyTaxonomyQuery
      | TracesQuery
      | TraceQuery
      | TraceNeighborsQuery
      | VectorSearchQuery
      | UsageMetricsQuery
      | EndpointsUsageOverviewQuery
      | EndpointsUsageTableQuery
      | EndpointsUsageTrendsQuery;
  };
  export type SessionGroupSummary = {
    id: string;
    title: string;
    session_ids: Array<string>;
    summary: unknown;
    extra_summary_context: unknown | null;
    run_metadata: unknown | null;
    created_at: string;
    created_by: UserBasic & unknown;
    team: number;
  };
  export type SessionSummaries = { session_ids: Array<string>; focus_area?: string | undefined };
  export type SharingConfiguration = {
    created_at: string;
    enabled?: boolean | undefined;
    access_token: string | null;
    settings?: (unknown | null) | undefined;
    password_required?: boolean | undefined;
    share_passwords: string;
  };
  export type SummaryBullet = { text: string; line_refs: string };
  export type StructuredSummary = {
    title: string;
    flow_diagram: string;
    summary_bullets: Array<SummaryBullet>;
    interesting_notes: Array<InterestingNote>;
  };
  export type SummarizeTypeEnum = "trace" | "event";
  export type SummarizeRequest = {
    summarize_type: SummarizeTypeEnum;
    mode?: (ModeEnum & unknown) | undefined;
    data: unknown;
    force_refresh?: boolean | undefined;
    model?: (string | null) | undefined;
  };
  export type SummarizeResponse = { summary: StructuredSummary; text_repr: string; metadata?: unknown | undefined };
  export type SurveySerializerCreateUpdateOnly = {
    id: string;
    name: string;
    description?: string | undefined;
    type: SurveyType;
    schedule?: (string | null) | undefined;
    linked_flag: MinimalFeatureFlag & unknown;
    linked_flag_id?: (number | null) | undefined;
    linked_insight_id?: (number | null) | undefined;
    targeting_flag_id?: number | undefined;
    targeting_flag: MinimalFeatureFlag & unknown;
    internal_targeting_flag: MinimalFeatureFlag & unknown;
    targeting_flag_filters?: (unknown | null) | undefined;
    remove_targeting_flag?: (boolean | null) | undefined;
    questions?: (unknown | null) | undefined;
    conditions?: (unknown | null) | undefined;
    appearance?: (unknown | null) | undefined;
    created_at: string;
    created_by: UserBasic & unknown;
    start_date?: (string | null) | undefined;
    end_date?: (string | null) | undefined;
    archived?: boolean | undefined;
    responses_limit?: (number | null) | undefined;
    iteration_count?: (number | null) | undefined;
    iteration_frequency_days?: (number | null) | undefined;
    iteration_start_dates?: (Array<string | null> | null) | undefined;
    current_iteration?: (number | null) | undefined;
    current_iteration_start_date?: (string | null) | undefined;
    response_sampling_start_date?: (string | null) | undefined;
    response_sampling_interval_type?: ((ResponseSamplingIntervalTypeEnum | BlankEnum | NullEnum) | null) | undefined;
    response_sampling_interval?: (number | null) | undefined;
    response_sampling_limit?: (number | null) | undefined;
    response_sampling_daily_limits?: (unknown | null) | undefined;
    enable_partial_responses?: (boolean | null) | undefined;
    enable_iframe_embedding?: (boolean | null) | undefined;
    _create_in_folder?: string | undefined;
  };
  export type TaskRunAppendLogRequest = { entries: Array<Record<string, unknown>> };
  export type TaskRunArtifactPresignRequest = { storage_path: string };
  export type TaskRunArtifactPresignResponse = { url: string; expires_in: number };
  export type TaskRunArtifactUploadTypeEnum = "plan" | "context" | "reference" | "output" | "artifact";
  export type TaskRunArtifactUpload = {
    name: string;
    type: TaskRunArtifactUploadTypeEnum;
    content: string;
    content_type?: string | undefined;
  };
  export type TaskRunArtifactsUploadRequest = { artifacts: Array<TaskRunArtifactUpload> };
  export type TaskRunArtifactsUploadResponse = { artifacts: Array<TaskRunArtifactResponse> };
  export type Team = {
    id: number;
    uuid: string;
    name?: string | undefined;
    access_control?: boolean | undefined;
    organization: string;
    project_id: number;
    api_token: string;
    secret_api_token: string | null;
    secret_api_token_backup: string | null;
    created_at: string;
    updated_at: string;
    ingested_event: boolean;
    default_modifiers: Record<string, unknown>;
    person_on_events_querying_enabled: boolean;
    user_access_level: string | null;
    app_urls?: Array<string | null> | undefined;
    slack_incoming_webhook?: (string | null) | undefined;
    anonymize_ips?: boolean | undefined;
    completed_snippet_onboarding?: boolean | undefined;
    test_account_filters?: unknown | undefined;
    test_account_filters_default_checked?: (boolean | null) | undefined;
    path_cleaning_filters?: (unknown | null) | undefined;
    is_demo?: boolean | undefined;
    timezone?: TimezoneEnum | undefined;
    data_attributes?: unknown | undefined;
    person_display_name_properties?: (Array<string> | null) | undefined;
    correlation_config?: (unknown | null) | undefined;
    autocapture_opt_out?: (boolean | null) | undefined;
    autocapture_exceptions_opt_in?: (boolean | null) | undefined;
    autocapture_web_vitals_opt_in?: (boolean | null) | undefined;
    autocapture_web_vitals_allowed_metrics?: (unknown | null) | undefined;
    autocapture_exceptions_errors_to_ignore?: (unknown | null) | undefined;
    capture_console_log_opt_in?: (boolean | null) | undefined;
    logs_settings?: (unknown | null) | undefined;
    capture_performance_opt_in?: (boolean | null) | undefined;
    session_recording_opt_in?: boolean | undefined;
    session_recording_sample_rate?: (string | null) | undefined;
    session_recording_minimum_duration_milliseconds?: (number | null) | undefined;
    session_recording_linked_flag?: (unknown | null) | undefined;
    session_recording_network_payload_capture_config?: (unknown | null) | undefined;
    session_recording_masking_config?: (unknown | null) | undefined;
    session_recording_url_trigger_config?: (Array<unknown | null> | null) | undefined;
    session_recording_url_blocklist_config?: (Array<unknown | null> | null) | undefined;
    session_recording_event_trigger_config?: (Array<string | null> | null) | undefined;
    session_recording_trigger_match_type_config?: (string | null) | undefined;
    session_recording_retention_period?: SessionRecordingRetentionPeriodEnum | undefined;
    session_replay_config?: (unknown | null) | undefined;
    survey_config?: (unknown | null) | undefined;
    week_start_day?: ((WeekStartDayEnum | NullEnum) | null) | undefined;
    primary_dashboard?: (number | null) | undefined;
    live_events_columns?: (Array<string> | null) | undefined;
    recording_domains?: (Array<string | null> | null) | undefined;
    cookieless_server_hash_mode?: ((CookielessServerHashModeEnum | NullEnum) | null) | undefined;
    human_friendly_comparison_periods?: (boolean | null) | undefined;
    inject_web_apps?: (boolean | null) | undefined;
    extra_settings?: (unknown | null) | undefined;
    modifiers?: (unknown | null) | undefined;
    has_completed_onboarding_for?: (unknown | null) | undefined;
    surveys_opt_in?: (boolean | null) | undefined;
    heatmaps_opt_in?: (boolean | null) | undefined;
    flags_persistence_default?: (boolean | null) | undefined;
    feature_flag_confirmation_enabled?: (boolean | null) | undefined;
    feature_flag_confirmation_message?: (string | null) | undefined;
    default_evaluation_contexts_enabled?: (boolean | null) | undefined;
    require_evaluation_contexts?: (boolean | null) | undefined;
    capture_dead_clicks?: (boolean | null) | undefined;
    default_data_theme?: (number | null) | undefined;
    revenue_analytics_config?: TeamRevenueAnalyticsConfig | undefined;
    marketing_analytics_config?: TeamMarketingAnalyticsConfig | undefined;
    customer_analytics_config?: TeamCustomerAnalyticsConfig | undefined;
    onboarding_tasks?: (unknown | null) | undefined;
    base_currency?: (BaseCurrencyEnum & unknown) | undefined;
    web_analytics_pre_aggregated_tables_enabled?: (boolean | null) | undefined;
    experiment_recalculation_time?: (string | null) | undefined;
    default_experiment_confidence_level?: (string | null) | undefined;
    default_experiment_stats_method?: ((DefaultExperimentStatsMethodEnum | BlankEnum | NullEnum) | null) | undefined;
    receive_org_level_activity_logs?: (boolean | null) | undefined;
    business_model?: ((BusinessModelEnum | BlankEnum | NullEnum) | null) | undefined;
    conversations_enabled?: (boolean | null) | undefined;
    conversations_settings?: (unknown | null) | undefined;
    proactive_tasks_enabled?: (boolean | null) | undefined;
    effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null;
    has_group_types: boolean;
    group_types: Array<Record<string, unknown>>;
    live_events_token: string | null;
    product_intents: string;
    managed_viewsets: string;
  };
  export type TextReprMetadata = {
    event_type?: string | undefined;
    event_id?: string | undefined;
    trace_id?: string | undefined;
    rendering: string;
    char_count: number;
    truncated: boolean;
    error?: string | undefined;
  };
  export type TextReprOptions = Partial<{
    max_length: number;
    truncated: boolean;
    truncate_buffer: number;
    include_markers: boolean;
    collapsed: boolean;
    include_metadata: boolean;
    include_hierarchy: boolean;
    max_depth: number;
    tools_collapse_threshold: number;
    include_line_numbers: boolean;
  }>;
  export type TextReprRequest = { event_type: EventTypeEnum; data: unknown; options?: TextReprOptions | undefined };
  export type TextReprResponse = { text: string; metadata: TextReprMetadata };
  export type WebAnalyticsBreakdownResponse = { next?: (string | null) | undefined; results: Array<unknown> };
  export type WebAnalyticsOverviewResponse = {
    visitors: number;
    views: number;
    sessions: number;
    bounce_rate: number;
    session_duration: number;
  };

  // </Schemas>
}

export namespace Endpoints {
  // <Endpoints>

  export type get_Alerts_list = {
    method: "GET";
    path: "/api/environments/{project_id}/alerts/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedAlertList };
  };
  export type post_Alerts_create = {
    method: "POST";
    path: "/api/environments/{project_id}/alerts/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Alert;
    };
    responses: { 201: Schemas.Alert };
  };
  export type get_Alerts_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Alert };
  };
  export type put_Alerts_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Alert;
    };
    responses: { 200: Schemas.Alert };
  };
  export type patch_Alerts_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedAlert;
    };
    responses: { 200: Schemas.Alert };
  };
  export type delete_Alerts_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_App_metrics_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/app_metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_App_metrics_error_details_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/app_metrics/{id}/error_details/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_App_metrics_historical_exports_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/";
    requestFormat: "json";
    parameters: {
      path: { plugin_config_id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_App_metrics_historical_exports_retrieve_2 = {
    method: "GET";
    path: "/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; plugin_config_id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_list = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedBatchExportList };
  };
  export type post_Batch_exports_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 201: Schemas.BatchExport };
  };
  export type get_Batch_exports_backfills_list = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ cursor: string; ordering: string }>;
      path: { batch_export_id: string; project_id: string };
    };
    responses: { 200: Schemas.PaginatedBatchExportBackfillList };
  };
  export type post_Batch_exports_backfills_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; project_id: string };

      body: Schemas.BatchExportBackfill;
    };
    responses: { 201: Schemas.BatchExportBackfill };
  };
  export type get_Batch_exports_backfills_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };
    };
    responses: { 200: Schemas.BatchExportBackfill };
  };
  export type post_Batch_exports_backfills_cancel_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };

      body: Schemas.BatchExportBackfill;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_runs_list = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ cursor: string; ordering: string }>;
      path: { batch_export_id: string; project_id: string };
    };
    responses: { 200: Schemas.PaginatedBatchExportRunList };
  };
  export type get_Batch_exports_runs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };
    };
    responses: { 200: Schemas.BatchExportRun };
  };
  export type post_Batch_exports_runs_cancel_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };

      body: Schemas.BatchExportRun;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_runs_logs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_runs_retry_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };

      body: Schemas.BatchExportRun;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type put_Batch_exports_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type patch_Batch_exports_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedBatchExport;
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type delete_Batch_exports_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Batch_exports_logs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_pause_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/{id}/pause/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_run_test_step_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/{id}/run_test_step/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_unpause_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/{id}/unpause/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_run_test_step_new_create = {
    method: "POST";
    path: "/api/environments/{project_id}/batch_exports/run_test_step_new/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_test_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/batch_exports/test/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Conversations_list = {
    method: "GET";
    path: "/api/environments/{project_id}/conversations/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedConversationList };
  };
  export type post_Conversations_create = {
    method: "POST";
    path: "/api/environments/{project_id}/conversations/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Message;
    };
    responses: { 201: Schemas.Message };
  };
  export type get_Conversations_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/conversations/{conversation}/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string };
    };
    responses: { 200: Schemas.Conversation };
  };
  export type post_Conversations_append_message_create = {
    method: "POST";
    path: "/api/environments/{project_id}/conversations/{conversation}/append_message/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string };

      body: Schemas.MessageMinimal;
    };
    responses: { 200: Schemas.MessageMinimal };
  };
  export type patch_Conversations_cancel_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/conversations/{conversation}/cancel/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string };

      body: Schemas.PatchedConversation;
    };
    responses: { 200: Schemas.Conversation };
  };
  export type get_Conversations_queue_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/conversations/{conversation}/queue/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string };
    };
    responses: { 200: Schemas.Conversation };
  };
  export type post_Conversations_queue_create = {
    method: "POST";
    path: "/api/environments/{project_id}/conversations/{conversation}/queue/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string };

      body: Schemas.Conversation;
    };
    responses: { 200: Schemas.Conversation };
  };
  export type patch_Conversations_queue_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/conversations/{conversation}/queue/{queue_id}/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string; queue_id: string };

      body: Schemas.PatchedConversation;
    };
    responses: { 200: Schemas.Conversation };
  };
  export type delete_Conversations_queue_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/conversations/{conversation}/queue/{queue_id}/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string; queue_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Conversations_queue_clear_create = {
    method: "POST";
    path: "/api/environments/{project_id}/conversations/{conversation}/queue/clear/";
    requestFormat: "json";
    parameters: {
      path: { conversation: string; project_id: string };

      body: Schemas.Conversation;
    };
    responses: { 200: Schemas.Conversation };
  };
  export type get_Customer_profile_configs_list = {
    method: "GET";
    path: "/api/environments/{project_id}/customer_profile_configs/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedCustomerProfileConfigList };
  };
  export type post_Customer_profile_configs_create = {
    method: "POST";
    path: "/api/environments/{project_id}/customer_profile_configs/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.CustomerProfileConfig;
    };
    responses: { 201: Schemas.CustomerProfileConfig };
  };
  export type get_Customer_profile_configs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/customer_profile_configs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.CustomerProfileConfig };
  };
  export type put_Customer_profile_configs_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/customer_profile_configs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.CustomerProfileConfig;
    };
    responses: { 200: Schemas.CustomerProfileConfig };
  };
  export type patch_Customer_profile_configs_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/customer_profile_configs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedCustomerProfileConfig;
    };
    responses: { 200: Schemas.CustomerProfileConfig };
  };
  export type delete_Customer_profile_configs_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/customer_profile_configs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Dashboards_list = {
    method: "GET";
    path: "/api/environments/{project_id}/dashboards/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt"; limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDashboardBasicList };
  };
  export type post_Dashboards_create = {
    method: "POST";
    path: "/api/environments/{project_id}/dashboards/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 201: Schemas.Dashboard };
  };
  export type get_Dashboards_collaborators_list = {
    method: "GET";
    path: "/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };
    };
    responses: { 200: Array<Schemas.DashboardCollaborator> };
  };
  export type post_Dashboards_collaborators_create = {
    method: "POST";
    path: "/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };

      body: Schemas.DashboardCollaborator;
    };
    responses: { 201: Schemas.DashboardCollaborator };
  };
  export type delete_Dashboards_collaborators_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string; user__uuid: string };
    };
    responses: { 204: unknown };
  };
  export type get_Dashboards_sharing_list = {
    method: "GET";
    path: "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };
    };
    responses: { 200: Array<Schemas.SharingConfiguration> };
  };
  export type post_Dashboards_sharing_passwords_create = {
    method: "POST";
    path: "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type delete_Dashboards_sharing_passwords_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; password_id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Dashboards_sharing_refresh_create = {
    method: "POST";
    path: "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/refresh/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type get_Dashboards_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Dashboard };
  };
  export type put_Dashboards_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 200: Schemas.Dashboard };
  };
  export type patch_Dashboards_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedDashboard;
    };
    responses: { 200: Schemas.Dashboard };
  };
  export type delete_Dashboards_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type patch_Dashboards_move_tile_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/dashboards/{id}/move_tile/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedDashboard;
    };
    responses: { 200: unknown };
  };
  export type get_Dashboards_stream_tiles_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/dashboards/{id}/stream_tiles/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Dashboards_create_from_template_json_create = {
    method: "POST";
    path: "/api/environments/{project_id}/dashboards/create_from_template_json/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 200: unknown };
  };
  export type post_Dashboards_create_unlisted_dashboard_create = {
    method: "POST";
    path: "/api/environments/{project_id}/dashboards/create_unlisted_dashboard/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 200: unknown };
  };
  export type get_Data_color_themes_list = {
    method: "GET";
    path: "/api/environments/{project_id}/data_color_themes/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDataColorThemeList };
  };
  export type post_Data_color_themes_create = {
    method: "POST";
    path: "/api/environments/{project_id}/data_color_themes/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DataColorTheme;
    };
    responses: { 201: Schemas.DataColorTheme };
  };
  export type get_Data_color_themes_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.DataColorTheme };
  };
  export type put_Data_color_themes_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.DataColorTheme;
    };
    responses: { 200: Schemas.DataColorTheme };
  };
  export type patch_Data_color_themes_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedDataColorTheme;
    };
    responses: { 200: Schemas.DataColorTheme };
  };
  export type delete_Data_color_themes_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Dataset_items_list = {
    method: "GET";
    path: "/api/environments/{project_id}/dataset_items/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ dataset: string; limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDatasetItemList };
  };
  export type post_Dataset_items_create = {
    method: "POST";
    path: "/api/environments/{project_id}/dataset_items/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DatasetItem;
    };
    responses: { 201: Schemas.DatasetItem };
  };
  export type get_Dataset_items_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DatasetItem };
  };
  export type put_Dataset_items_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DatasetItem;
    };
    responses: { 200: Schemas.DatasetItem };
  };
  export type patch_Dataset_items_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDatasetItem;
    };
    responses: { 200: Schemas.DatasetItem };
  };
  export type delete_Dataset_items_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Datasets_list = {
    method: "GET";
    path: "/api/environments/{project_id}/datasets/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        id__in: Array<string>;
        limit: number;
        offset: number;
        order_by: Array<"-created_at" | "-updated_at" | "created_at" | "updated_at">;
        search: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDatasetList };
  };
  export type post_Datasets_create = {
    method: "POST";
    path: "/api/environments/{project_id}/datasets/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Dataset;
    };
    responses: { 201: Schemas.Dataset };
  };
  export type get_Datasets_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Dataset };
  };
  export type put_Datasets_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Dataset;
    };
    responses: { 200: Schemas.Dataset };
  };
  export type patch_Datasets_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDataset;
    };
    responses: { 200: Schemas.Dataset };
  };
  export type delete_Datasets_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Desktop_recordings_list = {
    method: "GET";
    path: "/api/environments/{project_id}/desktop_recordings/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDesktopRecordingList };
  };
  export type post_Desktop_recordings_create = {
    method: "POST";
    path: "/api/environments/{project_id}/desktop_recordings/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.CreateRecordingRequest;
    };
    responses: { 201: Schemas.CreateRecordingResponse };
  };
  export type get_Desktop_recordings_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/desktop_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DesktopRecording };
  };
  export type put_Desktop_recordings_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/desktop_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DesktopRecording;
    };
    responses: { 200: Schemas.DesktopRecording };
  };
  export type patch_Desktop_recordings_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/desktop_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDesktopRecording;
    };
    responses: { 200: Schemas.DesktopRecording };
  };
  export type delete_Desktop_recordings_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/desktop_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Desktop_recordings_append_segments_create = {
    method: "POST";
    path: "/api/environments/{project_id}/desktop_recordings/{id}/append_segments/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.AppendSegments;
    };
    responses: { 200: Schemas.DesktopRecording };
  };
  export type get_Endpoints_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/endpoints/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Endpoints_create = {
    method: "POST";
    path: "/api/environments/{project_id}/endpoints/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.EndpointRequest;
    };
    responses: { 201: unknown };
  };
  export type get_Endpoints_retrieve_2 = {
    method: "GET";
    path: "/api/environments/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type put_Endpoints_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };

      body: Schemas.EndpointRequest;
    };
    responses: { 200: unknown };
  };
  export type patch_Endpoints_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type delete_Endpoints_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Endpoints_materialization_status_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/endpoints/{name}/materialization_status/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Endpoints_openapi_json_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/endpoints/{name}/openapi.json/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Endpoints_run_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/endpoints/{name}/run/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Endpoints_run_create = {
    method: "POST";
    path: "/api/environments/{project_id}/endpoints/{name}/run/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };

      body: Schemas.EndpointRunRequest;
    };
    responses: { 200: unknown };
  };
  export type get_Endpoints_versions_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/endpoints/{name}/versions/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Endpoints_last_execution_times_create = {
    method: "POST";
    path: "/api/environments/{project_id}/endpoints/last_execution_times/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.EndpointLastExecutionTimesRequest;
    };
    responses: { 200: Schemas.QueryStatusResponse };
  };
  export type get_Error_tracking_assignment_rules_list = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/assignment_rules/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingAssignmentRuleList };
  };
  export type post_Error_tracking_assignment_rules_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/assignment_rules/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingAssignmentRule;
    };
    responses: { 201: Schemas.ErrorTrackingAssignmentRule };
  };
  export type get_Error_tracking_assignment_rules_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingAssignmentRule };
  };
  export type put_Error_tracking_assignment_rules_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingAssignmentRule;
    };
    responses: { 200: Schemas.ErrorTrackingAssignmentRule };
  };
  export type patch_Error_tracking_assignment_rules_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingAssignmentRule;
    };
    responses: { 200: Schemas.ErrorTrackingAssignmentRule };
  };
  export type delete_Error_tracking_assignment_rules_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type patch_Error_tracking_assignment_rules_reorder_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/assignment_rules/reorder/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PatchedErrorTrackingAssignmentRule;
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_autocapture_controls_list = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/autocapture_controls/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingAutoCaptureControlsList };
  };
  export type post_Error_tracking_autocapture_controls_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/autocapture_controls/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingAutoCaptureControls;
    };
    responses: { 201: Schemas.ErrorTrackingAutoCaptureControls };
  };
  export type get_Error_tracking_autocapture_controls_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingAutoCaptureControls };
  };
  export type put_Error_tracking_autocapture_controls_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingAutoCaptureControls;
    };
    responses: { 200: Schemas.ErrorTrackingAutoCaptureControls };
  };
  export type patch_Error_tracking_autocapture_controls_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingAutoCaptureControls;
    };
    responses: { 200: Schemas.ErrorTrackingAutoCaptureControls };
  };
  export type delete_Error_tracking_autocapture_controls_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Error_tracking_fingerprints_list = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/fingerprints/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingFingerprintList };
  };
  export type get_Error_tracking_fingerprints_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/fingerprints/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingFingerprint };
  };
  export type delete_Error_tracking_fingerprints_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/error_tracking/fingerprints/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Error_tracking_git_provider_file_links_resolve_github_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/git-provider-file-links/resolve_github/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_git_provider_file_links_resolve_gitlab_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/git-provider-file-links/resolve_gitlab/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_grouping_rules_list = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/grouping_rules/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingGroupingRuleList };
  };
  export type post_Error_tracking_grouping_rules_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/grouping_rules/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingGroupingRule;
    };
    responses: { 201: Schemas.ErrorTrackingGroupingRule };
  };
  export type get_Error_tracking_grouping_rules_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingGroupingRule };
  };
  export type put_Error_tracking_grouping_rules_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingGroupingRule;
    };
    responses: { 200: Schemas.ErrorTrackingGroupingRule };
  };
  export type patch_Error_tracking_grouping_rules_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingGroupingRule;
    };
    responses: { 200: Schemas.ErrorTrackingGroupingRule };
  };
  export type delete_Error_tracking_grouping_rules_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type patch_Error_tracking_grouping_rules_reorder_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/grouping_rules/reorder/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PatchedErrorTrackingGroupingRule;
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_releases_list = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/releases/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingReleaseList };
  };
  export type post_Error_tracking_releases_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/releases/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingRelease;
    };
    responses: { 201: Schemas.ErrorTrackingRelease };
  };
  export type get_Error_tracking_releases_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingRelease };
  };
  export type put_Error_tracking_releases_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingRelease;
    };
    responses: { 200: Schemas.ErrorTrackingRelease };
  };
  export type patch_Error_tracking_releases_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingRelease;
    };
    responses: { 200: Schemas.ErrorTrackingRelease };
  };
  export type delete_Error_tracking_releases_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Error_tracking_releases_hash_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/releases/hash/{hash_id}/";
    requestFormat: "json";
    parameters: {
      path: { hash_id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_suppression_rules_list = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/suppression_rules/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingSuppressionRuleList };
  };
  export type post_Error_tracking_suppression_rules_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/suppression_rules/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSuppressionRule;
    };
    responses: { 201: Schemas.ErrorTrackingSuppressionRule };
  };
  export type get_Error_tracking_suppression_rules_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingSuppressionRule };
  };
  export type put_Error_tracking_suppression_rules_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingSuppressionRule;
    };
    responses: { 200: Schemas.ErrorTrackingSuppressionRule };
  };
  export type patch_Error_tracking_suppression_rules_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingSuppressionRule;
    };
    responses: { 200: Schemas.ErrorTrackingSuppressionRule };
  };
  export type delete_Error_tracking_suppression_rules_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type patch_Error_tracking_suppression_rules_reorder_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/suppression_rules/reorder/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PatchedErrorTrackingSuppressionRule;
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_symbol_sets_list = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingSymbolSetList };
  };
  export type post_Error_tracking_symbol_sets_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/";
    requestFormat: "form-data";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 201: Schemas.ErrorTrackingSymbolSet };
  };
  export type get_Error_tracking_symbol_sets_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingSymbolSet };
  };
  export type put_Error_tracking_symbol_sets_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "form-data";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: Schemas.ErrorTrackingSymbolSet };
  };
  export type patch_Error_tracking_symbol_sets_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "form-data";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingSymbolSet;
    };
    responses: { 200: Schemas.ErrorTrackingSymbolSet };
  };
  export type delete_Error_tracking_symbol_sets_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type put_Error_tracking_symbol_sets_finish_upload_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/finish_upload/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type post_Error_tracking_symbol_sets_bulk_finish_upload_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/bulk_finish_upload/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type post_Error_tracking_symbol_sets_bulk_start_upload_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/bulk_start_upload/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type post_Error_tracking_symbol_sets_start_upload_create = {
    method: "POST";
    path: "/api/environments/{project_id}/error_tracking/symbol_sets/start_upload/";
    requestFormat: "form-data";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type post_Evaluation_runs_create = {
    method: "POST";
    path: "/api/environments/{project_id}/evaluation_runs/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 201: unknown };
  };
  export type get_Evaluations_list = {
    method: "GET";
    path: "/api/environments/{project_id}/evaluations/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        enabled: boolean;
        id__in: Array<string>;
        limit: number;
        offset: number;
        order_by: Array<"-created_at" | "-name" | "-updated_at" | "created_at" | "name" | "updated_at">;
        search: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedEvaluationList };
  };
  export type post_Evaluations_create = {
    method: "POST";
    path: "/api/environments/{project_id}/evaluations/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Evaluation;
    };
    responses: { 201: Schemas.Evaluation };
  };
  export type get_Evaluations_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/evaluations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Evaluation };
  };
  export type put_Evaluations_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/evaluations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Evaluation;
    };
    responses: { 200: Schemas.Evaluation };
  };
  export type patch_Evaluations_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/evaluations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedEvaluation;
    };
    responses: { 200: Schemas.Evaluation };
  };
  export type delete_Evaluations_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/evaluations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Events_list = {
    method: "GET";
    path: "/api/environments/{project_id}/events/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        after: string;
        before: string;
        distinct_id: number;
        event: string;
        format: "csv" | "json";
        limit: number;
        offset: number;
        person_id: number;
        properties: Array<Schemas.Property>;
        select: Array<string>;
        where: Array<string>;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedClickhouseEventList };
  };
  export type get_Events_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/events/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ClickhouseEvent };
  };
  export type get_Events_values_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/events/values/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Exports_list = {
    method: "GET";
    path: "/api/environments/{project_id}/exports/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedExportedAssetList };
  };
  export type post_Exports_create = {
    method: "POST";
    path: "/api/environments/{project_id}/exports/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExportedAsset;
    };
    responses: { 201: Schemas.ExportedAsset };
  };
  export type get_Exports_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.ExportedAsset };
  };
  export type get_Exports_content_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/exports/{id}/content/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_External_data_sources_list = {
    method: "GET";
    path: "/api/environments/{project_id}/external_data_sources/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedExternalDataSourceSerializersList };
  };
  export type post_External_data_sources_create = {
    method: "POST";
    path: "/api/environments/{project_id}/external_data_sources/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 201: Schemas.ExternalDataSourceSerializers };
  };
  export type get_External_data_sources_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ExternalDataSourceSerializers };
  };
  export type put_External_data_sources_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: Schemas.ExternalDataSourceSerializers };
  };
  export type patch_External_data_sources_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedExternalDataSourceSerializers;
    };
    responses: { 200: Schemas.ExternalDataSourceSerializers };
  };
  export type delete_External_data_sources_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_External_data_sources_jobs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/external_data_sources/{id}/jobs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_External_data_sources_reload_create = {
    method: "POST";
    path: "/api/environments/{project_id}/external_data_sources/{id}/reload/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type patch_External_data_sources_revenue_analytics_config_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/external_data_sources/{id}/revenue_analytics_config/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type post_External_data_sources_database_schema_create = {
    method: "POST";
    path: "/api/environments/{project_id}/external_data_sources/database_schema/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type post_External_data_sources_source_prefix_create = {
    method: "POST";
    path: "/api/environments/{project_id}/external_data_sources/source_prefix/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type get_External_data_sources_wizard_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/external_data_sources/wizard/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_File_system_list = {
    method: "GET";
    path: "/api/environments/{project_id}/file_system/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedFileSystemList };
  };
  export type post_File_system_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 201: Schemas.FileSystem };
  };
  export type get_File_system_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.FileSystem };
  };
  export type put_File_system_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: Schemas.FileSystem };
  };
  export type patch_File_system_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedFileSystem;
    };
    responses: { 200: Schemas.FileSystem };
  };
  export type delete_File_system_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_File_system_count_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system/{id}/count/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_link_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system/{id}/link/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_move_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system/{id}/move/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_count_by_path_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system/count_by_path/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type get_File_system_log_view_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/file_system/log_view/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_File_system_log_view_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system/log_view/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_undo_delete_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system/undo_delete/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type get_File_system_unfiled_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/file_system/unfiled/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_File_system_shortcut_list = {
    method: "GET";
    path: "/api/environments/{project_id}/file_system_shortcut/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedFileSystemShortcutList };
  };
  export type post_File_system_shortcut_create = {
    method: "POST";
    path: "/api/environments/{project_id}/file_system_shortcut/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystemShortcut;
    };
    responses: { 201: Schemas.FileSystemShortcut };
  };
  export type get_File_system_shortcut_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.FileSystemShortcut };
  };
  export type put_File_system_shortcut_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystemShortcut;
    };
    responses: { 200: Schemas.FileSystemShortcut };
  };
  export type patch_File_system_shortcut_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedFileSystemShortcut;
    };
    responses: { 200: Schemas.FileSystemShortcut };
  };
  export type delete_File_system_shortcut_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Groups_list = {
    method: "GET";
    path: "/api/environments/{project_id}/groups/";
    requestFormat: "json";
    parameters: {
      query: { cursor?: string | undefined; group_type_index: number; search: string };
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedGroupList };
  };
  export type post_Groups_create = {
    method: "POST";
    path: "/api/environments/{project_id}/groups/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.CreateGroup;
    };
    responses: { 201: Schemas.Group };
  };
  export type get_Groups_activity_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/groups/activity/";
    requestFormat: "json";
    parameters: {
      query: { group_type_index: number; id: string };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Groups_delete_property_create = {
    method: "POST";
    path: "/api/environments/{project_id}/groups/delete_property/";
    requestFormat: "json";
    parameters: {
      query: { group_key: string; group_type_index: number };
      path: { project_id: string };

      body: Schemas.Group;
    };
    responses: { 200: unknown };
  };
  export type get_Groups_find_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/groups/find/";
    requestFormat: "json";
    parameters: {
      query: { group_key: string; group_type_index: number };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Groups_property_definitions_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/groups/property_definitions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Groups_property_values_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/groups/property_values/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Groups_related_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/groups/related/";
    requestFormat: "json";
    parameters: {
      query: { group_type_index: number; id: string };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Groups_update_property_create = {
    method: "POST";
    path: "/api/environments/{project_id}/groups/update_property/";
    requestFormat: "json";
    parameters: {
      query: { group_key: string; group_type_index: number };
      path: { project_id: string };

      body: Schemas.Group;
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_list = {
    method: "GET";
    path: "/api/environments/{project_id}/hog_functions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        created_at: string;
        created_by: number;
        enabled: boolean;
        id: string;
        limit: number;
        offset: number;
        search: string;
        type: Array<string>;
        updated_at: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedHogFunctionMinimalList };
  };
  export type post_Hog_functions_create = {
    method: "POST";
    path: "/api/environments/{project_id}/hog_functions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 201: Schemas.HogFunction };
  };
  export type get_Hog_functions_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.HogFunction };
  };
  export type put_Hog_functions_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 200: Schemas.HogFunction };
  };
  export type patch_Hog_functions_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedHogFunction;
    };
    responses: { 200: Schemas.HogFunction };
  };
  export type delete_Hog_functions_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type post_Hog_functions_enable_backfills_create = {
    method: "POST";
    path: "/api/environments/{project_id}/hog_functions/{id}/enable_backfills/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 200: unknown };
  };
  export type post_Hog_functions_invocations_create = {
    method: "POST";
    path: "/api/environments/{project_id}/hog_functions/{id}/invocations/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_logs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/hog_functions/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_metrics_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/hog_functions/{id}/metrics/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_metrics_totals_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/hog_functions/{id}/metrics/totals/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_icon_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/hog_functions/icon/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_icons_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/hog_functions/icons/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Hog_functions_rearrange_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/hog_functions/rearrange/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PatchedHogFunction;
    };
    responses: { 200: unknown };
  };
  export type get_Insight_variables_list = {
    method: "GET";
    path: "/api/environments/{project_id}/insight_variables/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ page: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedInsightVariableList };
  };
  export type post_Insight_variables_create = {
    method: "POST";
    path: "/api/environments/{project_id}/insight_variables/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.InsightVariable;
    };
    responses: { 201: Schemas.InsightVariable };
  };
  export type get_Insight_variables_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.InsightVariable };
  };
  export type put_Insight_variables_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.InsightVariable;
    };
    responses: { 200: Schemas.InsightVariable };
  };
  export type patch_Insight_variables_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedInsightVariable;
    };
    responses: { 200: Schemas.InsightVariable };
  };
  export type delete_Insight_variables_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Insights_list = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        basic: boolean;
        format: "csv" | "json";
        limit: number;
        offset: number;
        refresh:
          | "async"
          | "async_except_on_cache_miss"
          | "blocking"
          | "force_async"
          | "force_blocking"
          | "force_cache"
          | "lazy_async";
        short_id: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedInsightList };
  };
  export type post_Insights_create = {
    method: "POST";
    path: "/api/environments/{project_id}/insights/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Insight;
    };
    responses: { 201: Schemas.Insight };
  };
  export type get_Insights_sharing_list = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/{insight_id}/sharing/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; project_id: string };
    };
    responses: { 200: Array<Schemas.SharingConfiguration> };
  };
  export type post_Insights_sharing_passwords_create = {
    method: "POST";
    path: "/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type delete_Insights_sharing_passwords_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; password_id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Insights_sharing_refresh_create = {
    method: "POST";
    path: "/api/environments/{project_id}/insights/{insight_id}/sharing/refresh/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type get_Insights_thresholds_list = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/{insight_id}/thresholds/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { insight_id: number; project_id: string };
    };
    responses: { 200: Schemas.PaginatedThresholdWithAlertList };
  };
  export type get_Insights_thresholds_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/{insight_id}/thresholds/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; insight_id: number; project_id: string };
    };
    responses: { 200: Schemas.ThresholdWithAlert };
  };
  export type get_Insights_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        format: "csv" | "json";
        from_dashboard: number;
        refresh:
          | "async"
          | "async_except_on_cache_miss"
          | "blocking"
          | "force_async"
          | "force_blocking"
          | "force_cache"
          | "lazy_async";
      }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Insight };
  };
  export type put_Insights_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: Schemas.Insight };
  };
  export type patch_Insights_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedInsight;
    };
    responses: { 200: Schemas.Insight };
  };
  export type delete_Insights_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Insights_activity_retrieve_2 = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/{id}/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Insights_analyze_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/{id}/analyze/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Insights_suggestions_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/{id}/suggestions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Insights_suggestions_create = {
    method: "POST";
    path: "/api/environments/{project_id}/insights/{id}/suggestions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: unknown };
  };
  export type get_Insights_activity_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Insights_cancel_create = {
    method: "POST";
    path: "/api/environments/{project_id}/insights/cancel/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: unknown };
  };
  export type get_Insights_my_last_viewed_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/insights/my_last_viewed/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Insights_viewed_create = {
    method: "POST";
    path: "/api/environments/{project_id}/insights/viewed/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_list = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedIntegrationList };
  };
  export type post_Integrations_create = {
    method: "POST";
    path: "/api/environments/{project_id}/integrations/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Integration;
    };
    responses: { 201: Schemas.Integration };
  };
  export type get_Integrations_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Integration };
  };
  export type delete_Integrations_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/integrations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Integrations_channels_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/channels/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_clickup_lists_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/clickup_lists/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_clickup_spaces_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/clickup_spaces/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_clickup_workspaces_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/clickup_workspaces/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Integrations_email_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/integrations/{id}/email/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedIntegration;
    };
    responses: { 200: Schemas.Integration };
  };
  export type post_Integrations_email_verify_create = {
    method: "POST";
    path: "/api/environments/{project_id}/integrations/{id}/email/verify/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Integration;
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_github_repos_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/github_repos/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_google_accessible_accounts_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/google_accessible_accounts/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_google_conversion_actions_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/google_conversion_actions/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_jira_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/jira_projects/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_linear_teams_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/linear_teams/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_linkedin_ads_accounts_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/linkedin_ads_accounts/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_linkedin_ads_conversion_rules_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/linkedin_ads_conversion_rules/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_twilio_phone_numbers_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/{id}/twilio_phone_numbers/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_authorize_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/integrations/authorize/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Llm_analytics_evaluation_config_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_analytics/evaluation_config/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Llm_analytics_evaluation_config_set_active_key_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/evaluation_config/set_active_key/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Llm_analytics_evaluation_summary_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/evaluation_summary/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.EvaluationSummaryRequest;
    };
    responses: {
      200: Schemas.EvaluationSummaryResponse;
      400: Record<string, unknown>;
      403: Record<string, unknown>;
      404: Record<string, unknown>;
      500: Record<string, unknown>;
    };
  };
  export type get_Llm_analytics_models_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_analytics/models/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Llm_analytics_provider_key_validations_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/provider_key_validations/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 201: unknown };
  };
  export type get_Llm_analytics_provider_keys_list = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedLLMProviderKeyList };
  };
  export type post_Llm_analytics_provider_keys_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.LLMProviderKey;
    };
    responses: { 201: Schemas.LLMProviderKey };
  };
  export type get_Llm_analytics_provider_keys_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.LLMProviderKey };
  };
  export type put_Llm_analytics_provider_keys_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.LLMProviderKey;
    };
    responses: { 200: Schemas.LLMProviderKey };
  };
  export type patch_Llm_analytics_provider_keys_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedLLMProviderKey;
    };
    responses: { 200: Schemas.LLMProviderKey };
  };
  export type delete_Llm_analytics_provider_keys_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Llm_analytics_provider_keys_dependent_configs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/dependent_configs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.LLMProviderKey };
  };
  export type post_Llm_analytics_provider_keys_validate_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/validate/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.LLMProviderKey;
    };
    responses: { 200: Schemas.LLMProviderKey };
  };
  export type post_Llm_analytics_summarization_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/summarization/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.SummarizeRequest;
    };
    responses: {
      200: Schemas.SummarizeResponse;
      400: Record<string, unknown>;
      403: Record<string, unknown>;
      500: Record<string, unknown>;
    };
  };
  export type post_Llm_analytics_summarization_batch_check_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/summarization/batch_check/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.BatchCheckRequest;
    };
    responses: { 200: Schemas.BatchCheckResponse; 400: Record<string, unknown>; 403: Record<string, unknown> };
  };
  export type post_Llm_analytics_text_repr_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/text_repr/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.TextReprRequest;
    };
    responses: {
      200: Schemas.TextReprResponse;
      400: Record<string, unknown>;
      500: Record<string, unknown>;
      503: Record<string, unknown>;
    };
  };
  export type post_Llm_analytics_translate_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_analytics/translate/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 201: unknown };
  };
  export type get_Llm_prompts_list = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_prompts/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedLLMPromptList };
  };
  export type post_Llm_prompts_create = {
    method: "POST";
    path: "/api/environments/{project_id}/llm_prompts/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.LLMPrompt;
    };
    responses: { 201: Schemas.LLMPrompt };
  };
  export type get_Llm_prompts_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_prompts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.LLMPrompt };
  };
  export type put_Llm_prompts_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/llm_prompts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.LLMPrompt;
    };
    responses: { 200: Schemas.LLMPrompt };
  };
  export type patch_Llm_prompts_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/llm_prompts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedLLMPrompt;
    };
    responses: { 200: Schemas.LLMPrompt };
  };
  export type delete_Llm_prompts_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/llm_prompts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Llm_prompts_name_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/llm_prompts/name/{prompt_name}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; prompt_name: string };
    };
    responses: { 200: Schemas.LLMPrompt };
  };
  export type get_Logs_attributes_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/logs/attributes/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Logs_explainLogWithAI_create = {
    method: "POST";
    path: "/api/environments/{project_id}/logs/explainLogWithAI/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExplainRequest;
    };
    responses: { 201: Schemas.ExplainRequest };
  };
  export type post_Logs_export_create = {
    method: "POST";
    path: "/api/environments/{project_id}/logs/export/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Logs_has_logs_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/logs/has_logs/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Logs_query_create = {
    method: "POST";
    path: "/api/environments/{project_id}/logs/query/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Logs_sparkline_create = {
    method: "POST";
    path: "/api/environments/{project_id}/logs/sparkline/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Logs_values_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/logs/values/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Max_tools_create_and_query_insight_create = {
    method: "POST";
    path: "/api/environments/{project_id}/max_tools/create_and_query_insight/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Mcp_tools_create = {
    method: "POST";
    path: "/api/environments/{project_id}/mcp_tools/{tool_name}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; tool_name: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persisted_folder_list = {
    method: "GET";
    path: "/api/environments/{project_id}/persisted_folder/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedPersistedFolderList };
  };
  export type post_Persisted_folder_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persisted_folder/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PersistedFolder;
    };
    responses: { 201: Schemas.PersistedFolder };
  };
  export type get_Persisted_folder_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.PersistedFolder };
  };
  export type put_Persisted_folder_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PersistedFolder;
    };
    responses: { 200: Schemas.PersistedFolder };
  };
  export type patch_Persisted_folder_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedPersistedFolder;
    };
    responses: { 200: Schemas.PersistedFolder };
  };
  export type delete_Persisted_folder_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Persons_list = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        distinct_id: string;
        email: string;
        format: "csv" | "json";
        limit: number;
        offset: number;
        properties: Array<Schemas.Property>;
        search: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedPersonList };
  };
  export type get_Persons_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Person };
  };
  export type put_Persons_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/persons/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: Schemas.Person };
  };
  export type patch_Persons_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/persons/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedPerson;
    };
    responses: { 200: Schemas.Person };
  };
  export type get_Persons_activity_retrieve_2 = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/{id}/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_delete_property_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persons/{id}/delete_property/";
    requestFormat: "json";
    parameters: {
      query: { $unset: string; format?: ("csv" | "json") | undefined };
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_properties_timeline_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/{id}/properties_timeline/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_split_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persons/{id}/split/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type post_Persons_update_property_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persons/{id}/update_property/";
    requestFormat: "json";
    parameters: {
      query: { format?: ("csv" | "json") | undefined; key: string; value: unknown };
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_activity_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_bulk_delete_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persons/bulk_delete/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        delete_events: boolean;
        delete_recordings: boolean;
        distinct_ids: Record<string, unknown>;
        format: "csv" | "json";
        ids: Record<string, unknown>;
        keep_person: boolean;
      }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_cohorts_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/cohorts/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persons_funnel_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/funnel/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_funnel_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persons/funnel/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_funnel_correlation_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/funnel/correlation/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_funnel_correlation_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persons/funnel/correlation/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_lifecycle_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/lifecycle/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_reset_person_distinct_id_create = {
    method: "POST";
    path: "/api/environments/{project_id}/persons/reset_person_distinct_id/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_stickiness_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/stickiness/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persons_trends_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/trends/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persons_values_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/persons/values/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Plugin_configs_logs_list = {
    method: "GET";
    path: "/api/environments/{project_id}/plugin_configs/{plugin_config_id}/logs/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { plugin_config_id: string; project_id: string };
    };
    responses: { 200: Schemas.PaginatedPluginLogEntryList };
  };
  export type post_Query_create = {
    method: "POST";
    path: "/api/environments/{project_id}/query/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.QueryRequest;
    };
    responses: { 200: Schemas.QueryResponseAlternative };
  };
  export type get_Query_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/query/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.QueryStatusResponse };
  };
  export type delete_Query_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/query/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Query_log_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/query/{id}/log/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Record<string, unknown> };
  };
  export type post_Query_check_auth_for_async_create = {
    method: "POST";
    path: "/api/environments/{project_id}/query/check_auth_for_async/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Query_draft_sql_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/query/draft_sql/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Query_upgrade_create = {
    method: "POST";
    path: "/api/environments/{project_id}/query/upgrade/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.QueryUpgradeRequest;
    };
    responses: { 200: Schemas.QueryUpgradeResponse };
  };
  export type get_Session_recording_playlists_list = {
    method: "GET";
    path: "/api/environments/{project_id}/session_recording_playlists/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ created_by: number; limit: number; offset: number; short_id: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSessionRecordingPlaylistList };
  };
  export type post_Session_recording_playlists_create = {
    method: "POST";
    path: "/api/environments/{project_id}/session_recording_playlists/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.SessionRecordingPlaylist;
    };
    responses: { 201: Schemas.SessionRecordingPlaylist };
  };
  export type get_Session_recording_playlists_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: Schemas.SessionRecordingPlaylist };
  };
  export type put_Session_recording_playlists_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.SessionRecordingPlaylist;
    };
    responses: { 200: Schemas.SessionRecordingPlaylist };
  };
  export type patch_Session_recording_playlists_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.PatchedSessionRecordingPlaylist;
    };
    responses: { 200: Schemas.SessionRecordingPlaylist };
  };
  export type delete_Session_recording_playlists_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Session_recording_playlists_recordings_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Session_recording_playlists_recordings_create = {
    method: "POST";
    path: "/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; session_recording_id: string; short_id: string };

      body: Schemas.SessionRecordingPlaylist;
    };
    responses: { 200: unknown };
  };
  export type delete_Session_recording_playlists_recordings_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; session_recording_id: string; short_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Session_recordings_list = {
    method: "GET";
    path: "/api/environments/{project_id}/session_recordings/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSessionRecordingList };
  };
  export type get_Session_recordings_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.SessionRecording };
  };
  export type put_Session_recordings_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.SessionRecording;
    };
    responses: { 200: Schemas.SessionRecording };
  };
  export type patch_Session_recordings_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedSessionRecording;
    };
    responses: { 200: Schemas.SessionRecording };
  };
  export type delete_Session_recordings_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Session_recordings_sharing_list = {
    method: "GET";
    path: "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; recording_id: string };
    };
    responses: { 200: Array<Schemas.SharingConfiguration> };
  };
  export type post_Session_recordings_sharing_passwords_create = {
    method: "POST";
    path: "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; recording_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type delete_Session_recordings_sharing_passwords_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/";
    requestFormat: "json";
    parameters: {
      path: { password_id: string; project_id: string; recording_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Session_recordings_sharing_refresh_create = {
    method: "POST";
    path: "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/refresh/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; recording_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type post_Create_session_summaries = {
    method: "POST";
    path: "/api/environments/{project_id}/session_summaries/create_session_summaries/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.SessionSummaries;
    };
    responses: { 200: Schemas.SessionSummaries };
  };
  export type post_Create_session_summaries_individually = {
    method: "POST";
    path: "/api/environments/{project_id}/session_summaries/create_session_summaries_individually/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.SessionSummaries;
    };
    responses: { 200: Schemas.SessionSummaries };
  };
  export type get_Sessions_property_definitions_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/sessions/property_definitions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Sessions_values_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/sessions/values/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Subscriptions_list = {
    method: "GET";
    path: "/api/environments/{project_id}/subscriptions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSubscriptionList };
  };
  export type post_Subscriptions_create = {
    method: "POST";
    path: "/api/environments/{project_id}/subscriptions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Subscription;
    };
    responses: { 201: Schemas.Subscription };
  };
  export type get_Subscriptions_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Subscription };
  };
  export type put_Subscriptions_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Subscription;
    };
    responses: { 200: Schemas.Subscription };
  };
  export type patch_Subscriptions_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedSubscription;
    };
    responses: { 200: Schemas.Subscription };
  };
  export type delete_Subscriptions_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_User_interviews_list = {
    method: "GET";
    path: "/api/environments/{project_id}/user_interviews/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedUserInterviewList };
  };
  export type post_User_interviews_create = {
    method: "POST";
    path: "/api/environments/{project_id}/user_interviews/";
    requestFormat: "form-data";
    parameters: {
      path: { project_id: string };

      body: Schemas.UserInterview;
    };
    responses: { 201: Schemas.UserInterview };
  };
  export type get_User_interviews_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/user_interviews/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.UserInterview };
  };
  export type put_User_interviews_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/user_interviews/{id}/";
    requestFormat: "form-data";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.UserInterview;
    };
    responses: { 200: Schemas.UserInterview };
  };
  export type patch_User_interviews_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/user_interviews/{id}/";
    requestFormat: "form-data";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedUserInterview;
    };
    responses: { 200: Schemas.UserInterview };
  };
  export type delete_User_interviews_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/user_interviews/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Warehouse_saved_queries_list = {
    method: "GET";
    path: "/api/environments/{project_id}/warehouse_saved_queries/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ page: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDataWarehouseSavedQueryMinimalList };
  };
  export type post_Warehouse_saved_queries_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 201: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_saved_queries_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type put_Warehouse_saved_queries_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type patch_Warehouse_saved_queries_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type delete_Warehouse_saved_queries_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Warehouse_saved_queries_activity_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/activity/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_ancestors_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/ancestors/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_cancel_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/cancel/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_saved_queries_dependencies_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/dependencies/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_descendants_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/descendants/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_materialize_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/materialize/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_revert_materialization_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/revert_materialization/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_run_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/run/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_saved_queries_run_history_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/warehouse_saved_queries/{id}/run_history/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_resume_schedules_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_saved_queries/resume_schedules/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_tables_list = {
    method: "GET";
    path: "/api/environments/{project_id}/warehouse_tables/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedTableList };
  };
  export type post_Warehouse_tables_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_tables/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Table;
    };
    responses: { 201: Schemas.Table };
  };
  export type get_Warehouse_tables_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Table };
  };
  export type put_Warehouse_tables_update = {
    method: "PUT";
    path: "/api/environments/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: Schemas.Table };
  };
  export type patch_Warehouse_tables_partial_update = {
    method: "PATCH";
    path: "/api/environments/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedTable;
    };
    responses: { 200: Schemas.Table };
  };
  export type delete_Warehouse_tables_destroy = {
    method: "DELETE";
    path: "/api/environments/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Warehouse_tables_refresh_schema_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_tables/{id}/refresh_schema/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: unknown };
  };
  export type post_Warehouse_tables_update_schema_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_tables/{id}/update_schema/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: unknown };
  };
  export type post_Warehouse_tables_file_create = {
    method: "POST";
    path: "/api/environments/{project_id}/warehouse_tables/file/";
    requestFormat: "form-data";
    parameters: {
      path: { project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: unknown };
  };
  export type get_Web_vitals_retrieve = {
    method: "GET";
    path: "/api/environments/{project_id}/web_vitals/";
    requestFormat: "json";
    parameters: {
      query: { pathname: string };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_List = {
    method: "GET";
    path: "/api/organizations/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
    };
    responses: { 200: Schemas.PaginatedOrganizationList };
  };
  export type post_Create = {
    method: "POST";
    path: "/api/organizations/";
    requestFormat: "json";
    parameters: {
      body: Schemas.Organization;
    };
    responses: { 201: Schemas.Organization };
  };
  export type get_Retrieve = {
    method: "GET";
    path: "/api/organizations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string };
    };
    responses: { 200: Schemas.Organization };
  };
  export type put_Update = {
    method: "PUT";
    path: "/api/organizations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string };

      body: Schemas.Organization;
    };
    responses: { 200: Schemas.Organization };
  };
  export type patch_Partial_update = {
    method: "PATCH";
    path: "/api/organizations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string };

      body: Schemas.PatchedOrganization;
    };
    responses: { 200: Schemas.Organization };
  };
  export type delete_Destroy = {
    method: "DELETE";
    path: "/api/organizations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Batch_exports_list_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/batch_exports/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedBatchExportList };
  };
  export type post_Batch_exports_create_2 = {
    method: "POST";
    path: "/api/organizations/{organization_id}/batch_exports/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 201: Schemas.BatchExport };
  };
  export type get_Batch_exports_retrieve_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type put_Batch_exports_update_2 = {
    method: "PUT";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type patch_Batch_exports_partial_update_2 = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.PatchedBatchExport;
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type delete_Batch_exports_destroy_2 = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Batch_exports_logs_retrieve_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_pause_create_2 = {
    method: "POST";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/pause/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_run_test_step_create_2 = {
    method: "POST";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/run_test_step/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_unpause_create_2 = {
    method: "POST";
    path: "/api/organizations/{organization_id}/batch_exports/{id}/unpause/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_run_test_step_new_create_2 = {
    method: "POST";
    path: "/api/organizations/{organization_id}/batch_exports/run_test_step_new/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_test_retrieve_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/batch_exports/test/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Domains_list = {
    method: "GET";
    path: "/api/organizations/{organization_id}/domains/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedOrganizationDomainList };
  };
  export type post_Domains_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/domains/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.OrganizationDomain;
    };
    responses: { 201: Schemas.OrganizationDomain };
  };
  export type get_Domains_retrieve = {
    method: "GET";
    path: "/api/organizations/{organization_id}/domains/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 200: Schemas.OrganizationDomain };
  };
  export type put_Domains_update = {
    method: "PUT";
    path: "/api/organizations/{organization_id}/domains/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.OrganizationDomain;
    };
    responses: { 200: Schemas.OrganizationDomain };
  };
  export type patch_Domains_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/domains/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.PatchedOrganizationDomain;
    };
    responses: { 200: Schemas.OrganizationDomain };
  };
  export type delete_Domains_destroy = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/domains/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Domains_scim_token_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/domains/{id}/scim/token/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.OrganizationDomain;
    };
    responses: { 200: unknown };
  };
  export type post_Domains_verify_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/domains/{id}/verify/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.OrganizationDomain;
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_list_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/integrations/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedOrganizationIntegrationList };
  };
  export type get_Integrations_retrieve_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/integrations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 200: Schemas.OrganizationIntegration };
  };
  export type get_Invites_list = {
    method: "GET";
    path: "/api/organizations/{organization_id}/invites/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedOrganizationInviteList };
  };
  export type post_Invites_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/invites/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.OrganizationInvite;
    };
    responses: { 201: Schemas.OrganizationInvite };
  };
  export type delete_Invites_destroy = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/invites/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Invites_bulk_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/invites/bulk/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.OrganizationInvite;
    };
    responses: { 200: unknown };
  };
  export type get_Members_list = {
    method: "GET";
    path: "/api/organizations/{organization_id}/members/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedOrganizationMemberList };
  };
  export type put_Members_update = {
    method: "PUT";
    path: "/api/organizations/{organization_id}/members/{user__uuid}/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string; user__uuid: string };

      body: Schemas.OrganizationMember;
    };
    responses: { 200: Schemas.OrganizationMember };
  };
  export type patch_Members_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/members/{user__uuid}/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string; user__uuid: string };

      body: Schemas.PatchedOrganizationMember;
    };
    responses: { 200: Schemas.OrganizationMember };
  };
  export type delete_Members_destroy = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/members/{user__uuid}/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string; user__uuid: string };
    };
    responses: { 204: unknown };
  };
  export type get_Members_scoped_api_keys_retrieve = {
    method: "GET";
    path: "/api/organizations/{organization_id}/members/{user__uuid}/scoped_api_keys/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string; user__uuid: string };
    };
    responses: { 200: Schemas.OrganizationMember };
  };
  export type get_List_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/projects/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedProjectBackwardCompatBasicList };
  };
  export type post_Create_2 = {
    method: "POST";
    path: "/api/organizations/{organization_id}/projects/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.ProjectBackwardCompat;
    };
    responses: { 201: Schemas.ProjectBackwardCompat };
  };
  export type get_Retrieve_2 = {
    method: "GET";
    path: "/api/organizations/{organization_id}/projects/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type put_Update_2 = {
    method: "PUT";
    path: "/api/organizations/{organization_id}/projects/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.ProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type patch_Partial_update_2 = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/projects/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.PatchedProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type delete_Destroy_2 = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/projects/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Activity_retrieve = {
    method: "GET";
    path: "/api/organizations/{organization_id}/projects/{id}/activity/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type patch_Add_product_intent_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/projects/{id}/add_product_intent/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.PatchedProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type post_Change_organization_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/projects/{id}/change_organization/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.ProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type patch_Complete_product_onboarding_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/projects/{id}/complete_product_onboarding/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.PatchedProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type patch_Delete_secret_token_backup_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/projects/{id}/delete_secret_token_backup/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.PatchedProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type post_Generate_conversations_public_token_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/projects/{id}/generate_conversations_public_token/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.ProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type get_Is_generating_demo_data_retrieve = {
    method: "GET";
    path: "/api/organizations/{organization_id}/projects/{id}/is_generating_demo_data/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type patch_Reset_token_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/projects/{id}/reset_token/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.PatchedProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type patch_Rotate_secret_token_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/projects/{id}/rotate_secret_token/";
    requestFormat: "json";
    parameters: {
      path: { id: number; organization_id: string };

      body: Schemas.PatchedProjectBackwardCompat;
    };
    responses: { 200: Schemas.ProjectBackwardCompat };
  };
  export type get_Proxy_records_list = {
    method: "GET";
    path: "/api/organizations/{organization_id}/proxy_records/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedProxyRecordList };
  };
  export type post_Proxy_records_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/proxy_records/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.ProxyRecord;
    };
    responses: { 201: Schemas.ProxyRecord };
  };
  export type get_Proxy_records_retrieve = {
    method: "GET";
    path: "/api/organizations/{organization_id}/proxy_records/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 200: Schemas.ProxyRecord };
  };
  export type put_Proxy_records_update = {
    method: "PUT";
    path: "/api/organizations/{organization_id}/proxy_records/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.ProxyRecord;
    };
    responses: { 200: Schemas.ProxyRecord };
  };
  export type patch_Proxy_records_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/proxy_records/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.PatchedProxyRecord;
    };
    responses: { 200: Schemas.ProxyRecord };
  };
  export type delete_Proxy_records_destroy = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/proxy_records/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Roles_list = {
    method: "GET";
    path: "/api/organizations/{organization_id}/roles/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string };
    };
    responses: { 200: Schemas.PaginatedRoleList };
  };
  export type post_Roles_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/roles/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string };

      body: Schemas.Role;
    };
    responses: { 201: Schemas.Role };
  };
  export type get_Roles_retrieve = {
    method: "GET";
    path: "/api/organizations/{organization_id}/roles/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 200: Schemas.Role };
  };
  export type put_Roles_update = {
    method: "PUT";
    path: "/api/organizations/{organization_id}/roles/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.Role;
    };
    responses: { 200: Schemas.Role };
  };
  export type patch_Roles_partial_update = {
    method: "PATCH";
    path: "/api/organizations/{organization_id}/roles/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };

      body: Schemas.PatchedRole;
    };
    responses: { 200: Schemas.Role };
  };
  export type delete_Roles_destroy = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/roles/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Roles_role_memberships_list = {
    method: "GET";
    path: "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { organization_id: string; role_id: string };
    };
    responses: { 200: Schemas.PaginatedRoleMembershipList };
  };
  export type post_Roles_role_memberships_create = {
    method: "POST";
    path: "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/";
    requestFormat: "json";
    parameters: {
      path: { organization_id: string; role_id: string };

      body: Schemas.RoleMembership;
    };
    responses: { 201: Schemas.RoleMembership };
  };
  export type get_Roles_role_memberships_retrieve = {
    method: "GET";
    path: "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string; role_id: string };
    };
    responses: { 200: Schemas.RoleMembership };
  };
  export type delete_Roles_role_memberships_destroy = {
    method: "DELETE";
    path: "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; organization_id: string; role_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Actions_list = {
    method: "GET";
    path: "/api/projects/{project_id}/actions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json"; limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedActionList };
  };
  export type post_Actions_create = {
    method: "POST";
    path: "/api/projects/{project_id}/actions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Action;
    };
    responses: { 201: Schemas.Action };
  };
  export type get_Actions_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/actions/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Action };
  };
  export type put_Actions_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/actions/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Action;
    };
    responses: { 200: Schemas.Action };
  };
  export type patch_Actions_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/actions/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedAction;
    };
    responses: { 200: Schemas.Action };
  };
  export type delete_Actions_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/actions/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Activity_log_list = {
    method: "GET";
    path: "/api/projects/{project_id}/activity_log/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedActivityLogList };
  };
  export type get_Advanced_activity_logs_list = {
    method: "GET";
    path: "/api/projects/{project_id}/advanced_activity_logs/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedActivityLogList };
  };
  export type get_Advanced_activity_logs_available_filters_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/advanced_activity_logs/available_filters/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: Schemas.ActivityLog };
  };
  export type post_Advanced_activity_logs_export_create = {
    method: "POST";
    path: "/api/projects/{project_id}/advanced_activity_logs/export/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ActivityLog;
    };
    responses: { 200: Schemas.ActivityLog };
  };
  export type get_Alerts_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/alerts/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedAlertList };
  };
  export type post_Alerts_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/alerts/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Alert;
    };
    responses: { 201: Schemas.Alert };
  };
  export type get_Alerts_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Alert };
  };
  export type put_Alerts_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Alert;
    };
    responses: { 200: Schemas.Alert };
  };
  export type patch_Alerts_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedAlert;
    };
    responses: { 200: Schemas.Alert };
  };
  export type delete_Alerts_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/alerts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Annotations_list = {
    method: "GET";
    path: "/api/projects/{project_id}/annotations/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedAnnotationList };
  };
  export type post_Annotations_create = {
    method: "POST";
    path: "/api/projects/{project_id}/annotations/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Annotation;
    };
    responses: { 201: Schemas.Annotation };
  };
  export type get_Annotations_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/annotations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Annotation };
  };
  export type put_Annotations_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/annotations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Annotation;
    };
    responses: { 200: Schemas.Annotation };
  };
  export type patch_Annotations_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/annotations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedAnnotation;
    };
    responses: { 200: Schemas.Annotation };
  };
  export type delete_Annotations_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/annotations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_App_metrics_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/app_metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_App_metrics_error_details_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/app_metrics/{id}/error_details/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_App_metrics_historical_exports_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/";
    requestFormat: "json";
    parameters: {
      path: { plugin_config_id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_App_metrics_historical_exports_retrieve_4 = {
    method: "GET";
    path: "/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; plugin_config_id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_list_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedBatchExportList };
  };
  export type post_Batch_exports_create_3 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 201: Schemas.BatchExport };
  };
  export type get_Batch_exports_backfills_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ cursor: string; ordering: string }>;
      path: { batch_export_id: string; project_id: string };
    };
    responses: { 200: Schemas.PaginatedBatchExportBackfillList };
  };
  export type post_Batch_exports_backfills_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; project_id: string };

      body: Schemas.BatchExportBackfill;
    };
    responses: { 201: Schemas.BatchExportBackfill };
  };
  export type get_Batch_exports_backfills_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };
    };
    responses: { 200: Schemas.BatchExportBackfill };
  };
  export type post_Batch_exports_backfills_cancel_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };

      body: Schemas.BatchExportBackfill;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_runs_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ cursor: string; ordering: string }>;
      path: { batch_export_id: string; project_id: string };
    };
    responses: { 200: Schemas.PaginatedBatchExportRunList };
  };
  export type get_Batch_exports_runs_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };
    };
    responses: { 200: Schemas.BatchExportRun };
  };
  export type post_Batch_exports_runs_cancel_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };

      body: Schemas.BatchExportRun;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_runs_logs_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_runs_retry_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/";
    requestFormat: "json";
    parameters: {
      path: { batch_export_id: string; id: string; project_id: string };

      body: Schemas.BatchExportRun;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type put_Batch_exports_update_3 = {
    method: "PUT";
    path: "/api/projects/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type patch_Batch_exports_partial_update_3 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedBatchExport;
    };
    responses: { 200: Schemas.BatchExport };
  };
  export type delete_Batch_exports_destroy_3 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/batch_exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Batch_exports_logs_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_pause_create_3 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/{id}/pause/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_run_test_step_create_3 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/{id}/run_test_step/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_unpause_create_3 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/{id}/unpause/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type post_Batch_exports_run_test_step_new_create_3 = {
    method: "POST";
    path: "/api/projects/{project_id}/batch_exports/run_test_step_new/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.BatchExport;
    };
    responses: { 200: unknown };
  };
  export type get_Batch_exports_test_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/batch_exports/test/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Cohorts_list = {
    method: "GET";
    path: "/api/projects/{project_id}/cohorts/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedCohortList };
  };
  export type post_Cohorts_create = {
    method: "POST";
    path: "/api/projects/{project_id}/cohorts/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Cohort;
    };
    responses: { 201: Schemas.Cohort };
  };
  export type get_Cohorts_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/cohorts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Cohort };
  };
  export type put_Cohorts_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/cohorts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Cohort;
    };
    responses: { 200: Schemas.Cohort };
  };
  export type patch_Cohorts_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/cohorts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedCohort;
    };
    responses: { 200: Schemas.Cohort };
  };
  export type delete_Cohorts_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/cohorts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Cohorts_activity_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/cohorts/{id}/activity/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Cohorts_add_persons_to_static_cohort_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/cohorts/{id}/add_persons_to_static_cohort/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedAddPersonsToStaticCohortRequest;
    };
    responses: { 200: unknown };
  };
  export type get_Cohorts_calculation_history_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/cohorts/{id}/calculation_history/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Cohorts_persons_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/cohorts/{id}/persons/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Cohorts_remove_person_from_static_cohort_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/cohorts/{id}/remove_person_from_static_cohort/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedRemovePersonRequest;
    };
    responses: { 200: unknown };
  };
  export type get_Cohorts_activity_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/cohorts/activity/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Conversations_tickets_list = {
    method: "GET";
    path: "/api/projects/{project_id}/conversations/tickets/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedTicketList };
  };
  export type post_Conversations_tickets_create = {
    method: "POST";
    path: "/api/projects/{project_id}/conversations/tickets/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Ticket;
    };
    responses: { 201: Schemas.Ticket };
  };
  export type get_Conversations_tickets_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/conversations/tickets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Ticket };
  };
  export type put_Conversations_tickets_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/conversations/tickets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Ticket;
    };
    responses: { 200: Schemas.Ticket };
  };
  export type patch_Conversations_tickets_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/conversations/tickets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedTicket;
    };
    responses: { 200: Schemas.Ticket };
  };
  export type delete_Conversations_tickets_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/conversations/tickets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Conversations_tickets_unread_count_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/conversations/tickets/unread_count/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: Schemas.Ticket };
  };
  export type get_Dashboard_templates_list = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboard_templates/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDashboardTemplateList };
  };
  export type post_Dashboard_templates_create = {
    method: "POST";
    path: "/api/projects/{project_id}/dashboard_templates/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DashboardTemplate;
    };
    responses: { 201: Schemas.DashboardTemplate };
  };
  export type get_Dashboard_templates_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboard_templates/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DashboardTemplate };
  };
  export type put_Dashboard_templates_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/dashboard_templates/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DashboardTemplate;
    };
    responses: { 200: Schemas.DashboardTemplate };
  };
  export type patch_Dashboard_templates_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/dashboard_templates/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDashboardTemplate;
    };
    responses: { 200: Schemas.DashboardTemplate };
  };
  export type delete_Dashboard_templates_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/dashboard_templates/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Dashboard_templates_json_schema_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboard_templates/json_schema/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Dashboards_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboards/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt"; limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDashboardBasicList };
  };
  export type post_Dashboards_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/dashboards/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 201: Schemas.Dashboard };
  };
  export type get_Dashboards_collaborators_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };
    };
    responses: { 200: Array<Schemas.DashboardCollaborator> };
  };
  export type post_Dashboards_collaborators_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };

      body: Schemas.DashboardCollaborator;
    };
    responses: { 201: Schemas.DashboardCollaborator };
  };
  export type delete_Dashboards_collaborators_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string; user__uuid: string };
    };
    responses: { 204: unknown };
  };
  export type get_Dashboards_sharing_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };
    };
    responses: { 200: Array<Schemas.SharingConfiguration> };
  };
  export type post_Dashboards_sharing_passwords_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type delete_Dashboards_sharing_passwords_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; password_id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Dashboards_sharing_refresh_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/refresh/";
    requestFormat: "json";
    parameters: {
      path: { dashboard_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type get_Dashboards_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Dashboard };
  };
  export type put_Dashboards_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 200: Schemas.Dashboard };
  };
  export type patch_Dashboards_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedDashboard;
    };
    responses: { 200: Schemas.Dashboard };
  };
  export type delete_Dashboards_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/dashboards/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type patch_Dashboards_move_tile_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/dashboards/{id}/move_tile/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedDashboard;
    };
    responses: { 200: unknown };
  };
  export type get_Dashboards_stream_tiles_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/dashboards/{id}/stream_tiles/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Dashboards_create_from_template_json_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/dashboards/create_from_template_json/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 200: unknown };
  };
  export type post_Dashboards_create_unlisted_dashboard_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/dashboards/create_unlisted_dashboard/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "json" | "txt" }>;
      path: { project_id: string };

      body: Schemas.Dashboard;
    };
    responses: { 200: unknown };
  };
  export type get_Data_color_themes_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/data_color_themes/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDataColorThemeList };
  };
  export type post_Data_color_themes_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/data_color_themes/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DataColorTheme;
    };
    responses: { 201: Schemas.DataColorTheme };
  };
  export type get_Data_color_themes_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.DataColorTheme };
  };
  export type put_Data_color_themes_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.DataColorTheme;
    };
    responses: { 200: Schemas.DataColorTheme };
  };
  export type patch_Data_color_themes_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedDataColorTheme;
    };
    responses: { 200: Schemas.DataColorTheme };
  };
  export type delete_Data_color_themes_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/data_color_themes/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Dataset_items_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/dataset_items/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ dataset: string; limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDatasetItemList };
  };
  export type post_Dataset_items_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/dataset_items/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DatasetItem;
    };
    responses: { 201: Schemas.DatasetItem };
  };
  export type get_Dataset_items_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DatasetItem };
  };
  export type put_Dataset_items_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DatasetItem;
    };
    responses: { 200: Schemas.DatasetItem };
  };
  export type patch_Dataset_items_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDatasetItem;
    };
    responses: { 200: Schemas.DatasetItem };
  };
  export type delete_Dataset_items_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/dataset_items/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Datasets_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/datasets/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        id__in: Array<string>;
        limit: number;
        offset: number;
        order_by: Array<"-created_at" | "-updated_at" | "created_at" | "updated_at">;
        search: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDatasetList };
  };
  export type post_Datasets_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/datasets/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Dataset;
    };
    responses: { 201: Schemas.Dataset };
  };
  export type get_Datasets_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Dataset };
  };
  export type put_Datasets_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Dataset;
    };
    responses: { 200: Schemas.Dataset };
  };
  export type patch_Datasets_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDataset;
    };
    responses: { 200: Schemas.Dataset };
  };
  export type delete_Datasets_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/datasets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Early_access_feature_list = {
    method: "GET";
    path: "/api/projects/{project_id}/early_access_feature/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedEarlyAccessFeatureList };
  };
  export type post_Early_access_feature_create = {
    method: "POST";
    path: "/api/projects/{project_id}/early_access_feature/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.EarlyAccessFeatureSerializerCreateOnly;
    };
    responses: { 201: Schemas.EarlyAccessFeatureSerializerCreateOnly };
  };
  export type get_Early_access_feature_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/early_access_feature/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.EarlyAccessFeature };
  };
  export type put_Early_access_feature_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/early_access_feature/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.EarlyAccessFeature;
    };
    responses: { 200: Schemas.EarlyAccessFeature };
  };
  export type patch_Early_access_feature_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/early_access_feature/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedEarlyAccessFeature;
    };
    responses: { 200: Schemas.EarlyAccessFeature };
  };
  export type delete_Early_access_feature_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/early_access_feature/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Endpoints_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/endpoints/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Endpoints_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/endpoints/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.EndpointRequest;
    };
    responses: { 201: unknown };
  };
  export type get_Endpoints_retrieve_4 = {
    method: "GET";
    path: "/api/projects/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type put_Endpoints_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };

      body: Schemas.EndpointRequest;
    };
    responses: { 200: unknown };
  };
  export type patch_Endpoints_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type delete_Endpoints_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/endpoints/{name}/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Endpoints_materialization_status_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/endpoints/{name}/materialization_status/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Endpoints_openapi_json_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/endpoints/{name}/openapi.json/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Endpoints_run_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/endpoints/{name}/run/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Endpoints_run_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/endpoints/{name}/run/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };

      body: Schemas.EndpointRunRequest;
    };
    responses: { 200: unknown };
  };
  export type get_Endpoints_versions_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/endpoints/{name}/versions/";
    requestFormat: "json";
    parameters: {
      path: { name: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Endpoints_last_execution_times_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/endpoints/last_execution_times/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.EndpointLastExecutionTimesRequest;
    };
    responses: { 200: Schemas.QueryStatusResponse };
  };
  export type get_List_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/environments/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedTeamBasicList };
  };
  export type post_Create_3 = {
    method: "POST";
    path: "/api/projects/{project_id}/environments/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Team;
    };
    responses: { 201: Schemas.Team };
  };
  export type get_Retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/environments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Team };
  };
  export type put_Update_3 = {
    method: "PUT";
    path: "/api/projects/{project_id}/environments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Team;
    };
    responses: { 200: Schemas.Team };
  };
  export type patch_Partial_update_3 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/environments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedTeam;
    };
    responses: { 200: Schemas.Team };
  };
  export type delete_Destroy_3 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/environments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Activity_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/environments/{id}/activity/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Add_product_intent_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/environments/{id}/add_product_intent/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedTeam;
    };
    responses: { 200: unknown };
  };
  export type patch_Complete_product_onboarding_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/environments/{id}/complete_product_onboarding/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedTeam;
    };
    responses: { 200: unknown };
  };
  export type get_Default_evaluation_tags_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/environments/{id}/default_evaluation_tags/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Default_evaluation_tags_create = {
    method: "POST";
    path: "/api/projects/{project_id}/environments/{id}/default_evaluation_tags/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Team;
    };
    responses: { 200: unknown };
  };
  export type delete_Default_evaluation_tags_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/environments/{id}/default_evaluation_tags/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type patch_Delete_secret_token_backup_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/environments/{id}/delete_secret_token_backup/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedTeam;
    };
    responses: { 200: unknown };
  };
  export type get_Event_ingestion_restrictions_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/environments/{id}/event_ingestion_restrictions/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Generate_conversations_public_token_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/environments/{id}/generate_conversations_public_token/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Team;
    };
    responses: { 200: unknown };
  };
  export type get_Is_generating_demo_data_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/environments/{id}/is_generating_demo_data/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Reset_token_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/environments/{id}/reset_token/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedTeam;
    };
    responses: { 200: unknown };
  };
  export type patch_Rotate_secret_token_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/environments/{id}/rotate_secret_token/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedTeam;
    };
    responses: { 200: unknown };
  };
  export type get_Settings_as_of_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/environments/{id}/settings_as_of/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_releases_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/error_tracking/releases/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingReleaseList };
  };
  export type post_Error_tracking_releases_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/error_tracking/releases/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingRelease;
    };
    responses: { 201: Schemas.ErrorTrackingRelease };
  };
  export type get_Error_tracking_releases_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingRelease };
  };
  export type put_Error_tracking_releases_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingRelease;
    };
    responses: { 200: Schemas.ErrorTrackingRelease };
  };
  export type patch_Error_tracking_releases_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingRelease;
    };
    responses: { 200: Schemas.ErrorTrackingRelease };
  };
  export type delete_Error_tracking_releases_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/error_tracking/releases/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Error_tracking_releases_hash_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/error_tracking/releases/hash/{hash_id}/";
    requestFormat: "json";
    parameters: {
      path: { hash_id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Error_tracking_symbol_sets_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedErrorTrackingSymbolSetList };
  };
  export type post_Error_tracking_symbol_sets_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/";
    requestFormat: "form-data";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 201: Schemas.ErrorTrackingSymbolSet };
  };
  export type get_Error_tracking_symbol_sets_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ErrorTrackingSymbolSet };
  };
  export type put_Error_tracking_symbol_sets_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "form-data";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: Schemas.ErrorTrackingSymbolSet };
  };
  export type patch_Error_tracking_symbol_sets_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "form-data";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedErrorTrackingSymbolSet;
    };
    responses: { 200: Schemas.ErrorTrackingSymbolSet };
  };
  export type delete_Error_tracking_symbol_sets_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type put_Error_tracking_symbol_sets_finish_upload_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/finish_upload/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type post_Error_tracking_symbol_sets_bulk_finish_upload_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/bulk_finish_upload/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type post_Error_tracking_symbol_sets_bulk_start_upload_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/bulk_start_upload/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type post_Error_tracking_symbol_sets_start_upload_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/error_tracking/symbol_sets/start_upload/";
    requestFormat: "form-data";
    parameters: {
      path: { project_id: string };

      body: Schemas.ErrorTrackingSymbolSet;
    };
    responses: { 200: unknown };
  };
  export type get_Event_definitions_list = {
    method: "GET";
    path: "/api/projects/{project_id}/event_definitions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedEnterpriseEventDefinitionList };
  };
  export type post_Event_definitions_create = {
    method: "POST";
    path: "/api/projects/{project_id}/event_definitions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.EnterpriseEventDefinition;
    };
    responses: { 201: Schemas.EnterpriseEventDefinition };
  };
  export type get_Event_definitions_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/event_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.EnterpriseEventDefinition };
  };
  export type put_Event_definitions_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/event_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.EnterpriseEventDefinition;
    };
    responses: { 200: Schemas.EnterpriseEventDefinition };
  };
  export type patch_Event_definitions_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/event_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedEnterpriseEventDefinition;
    };
    responses: { 200: Schemas.EnterpriseEventDefinition };
  };
  export type delete_Event_definitions_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/event_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Event_definitions_metrics_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/event_definitions/{id}/metrics/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Event_definitions_by_name_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/event_definitions/by_name/";
    requestFormat: "json";
    parameters: {
      query: { name: string };
      path: { project_id: string };
    };
    responses: { 200: Schemas.EventDefinition };
  };
  export type get_Event_definitions_golang_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/event_definitions/golang/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Event_definitions_python_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/event_definitions/python/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Event_definitions_typescript_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/event_definitions/typescript/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Events_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/events/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        after: string;
        before: string;
        distinct_id: number;
        event: string;
        format: "csv" | "json";
        limit: number;
        offset: number;
        person_id: number;
        properties: Array<Schemas.Property>;
        select: Array<string>;
        where: Array<string>;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedClickhouseEventList };
  };
  export type get_Events_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/events/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ClickhouseEvent };
  };
  export type get_Events_values_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/events/values/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Experiment_holdouts_list = {
    method: "GET";
    path: "/api/projects/{project_id}/experiment_holdouts/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedExperimentHoldoutList };
  };
  export type post_Experiment_holdouts_create = {
    method: "POST";
    path: "/api/projects/{project_id}/experiment_holdouts/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExperimentHoldout;
    };
    responses: { 201: Schemas.ExperimentHoldout };
  };
  export type get_Experiment_holdouts_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/experiment_holdouts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.ExperimentHoldout };
  };
  export type put_Experiment_holdouts_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/experiment_holdouts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.ExperimentHoldout;
    };
    responses: { 200: Schemas.ExperimentHoldout };
  };
  export type patch_Experiment_holdouts_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/experiment_holdouts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedExperimentHoldout;
    };
    responses: { 200: Schemas.ExperimentHoldout };
  };
  export type delete_Experiment_holdouts_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/experiment_holdouts/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Experiment_saved_metrics_list = {
    method: "GET";
    path: "/api/projects/{project_id}/experiment_saved_metrics/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedExperimentSavedMetricList };
  };
  export type post_Experiment_saved_metrics_create = {
    method: "POST";
    path: "/api/projects/{project_id}/experiment_saved_metrics/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExperimentSavedMetric;
    };
    responses: { 201: Schemas.ExperimentSavedMetric };
  };
  export type get_Experiment_saved_metrics_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/experiment_saved_metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.ExperimentSavedMetric };
  };
  export type put_Experiment_saved_metrics_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/experiment_saved_metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.ExperimentSavedMetric;
    };
    responses: { 200: Schemas.ExperimentSavedMetric };
  };
  export type patch_Experiment_saved_metrics_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/experiment_saved_metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedExperimentSavedMetric;
    };
    responses: { 200: Schemas.ExperimentSavedMetric };
  };
  export type delete_Experiment_saved_metrics_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/experiment_saved_metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Experiments_list = {
    method: "GET";
    path: "/api/projects/{project_id}/experiments/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedExperimentList };
  };
  export type post_Experiments_create = {
    method: "POST";
    path: "/api/projects/{project_id}/experiments/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Experiment;
    };
    responses: { 201: Schemas.Experiment };
  };
  export type get_Experiments_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Experiment };
  };
  export type put_Experiments_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Experiment;
    };
    responses: { 200: Schemas.Experiment };
  };
  export type patch_Experiments_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedExperiment;
    };
    responses: { 200: Schemas.Experiment };
  };
  export type delete_Experiments_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type post_Experiments_create_exposure_cohort_for_experiment_create = {
    method: "POST";
    path: "/api/projects/{project_id}/experiments/{id}/create_exposure_cohort_for_experiment/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Experiment;
    };
    responses: { 200: unknown };
  };
  export type post_Experiments_duplicate_create = {
    method: "POST";
    path: "/api/projects/{project_id}/experiments/{id}/duplicate/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Experiment;
    };
    responses: { 200: unknown };
  };
  export type post_Experiments_recalculate_timeseries_create = {
    method: "POST";
    path: "/api/projects/{project_id}/experiments/{id}/recalculate_timeseries/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Experiment;
    };
    responses: { 200: unknown };
  };
  export type get_Experiments_timeseries_results_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/experiments/{id}/timeseries_results/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Experiments_eligible_feature_flags_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/experiments/eligible_feature_flags/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Experiments_requires_flag_implementation_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/experiments/requires_flag_implementation/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Experiments_stats_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/experiments/stats/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Exports_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/exports/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedExportedAssetList };
  };
  export type post_Exports_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/exports/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExportedAsset;
    };
    responses: { 201: Schemas.ExportedAsset };
  };
  export type get_Exports_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/exports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.ExportedAsset };
  };
  export type get_Exports_content_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/exports/{id}/content/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_External_data_sources_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/external_data_sources/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedExternalDataSourceSerializersList };
  };
  export type post_External_data_sources_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/external_data_sources/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 201: Schemas.ExternalDataSourceSerializers };
  };
  export type get_External_data_sources_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ExternalDataSourceSerializers };
  };
  export type put_External_data_sources_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: Schemas.ExternalDataSourceSerializers };
  };
  export type patch_External_data_sources_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedExternalDataSourceSerializers;
    };
    responses: { 200: Schemas.ExternalDataSourceSerializers };
  };
  export type delete_External_data_sources_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/external_data_sources/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_External_data_sources_jobs_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/external_data_sources/{id}/jobs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_External_data_sources_reload_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/external_data_sources/{id}/reload/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type patch_External_data_sources_revenue_analytics_config_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/external_data_sources/{id}/revenue_analytics_config/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type post_External_data_sources_database_schema_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/external_data_sources/database_schema/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type post_External_data_sources_source_prefix_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/external_data_sources/source_prefix/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ExternalDataSourceSerializers;
    };
    responses: { 200: unknown };
  };
  export type get_External_data_sources_wizard_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/external_data_sources/wizard/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Feature_flags_list = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        active: "STALE" | "false" | "true";
        created_by_id: string;
        evaluation_runtime: "both" | "client" | "server";
        excluded_properties: string;
        has_evaluation_tags: "false" | "true";
        limit: number;
        offset: number;
        search: string;
        tags: string;
        type: "boolean" | "experiment" | "multivariant";
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedFeatureFlagList };
  };
  export type post_Feature_flags_create = {
    method: "POST";
    path: "/api/projects/{project_id}/feature_flags/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FeatureFlag;
    };
    responses: { 201: Schemas.FeatureFlag };
  };
  export type get_Feature_flags_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.FeatureFlag };
  };
  export type put_Feature_flags_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/feature_flags/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.FeatureFlag;
    };
    responses: { 200: Schemas.FeatureFlag };
  };
  export type patch_Feature_flags_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/feature_flags/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedFeatureFlag;
    };
    responses: { 200: Schemas.FeatureFlag };
  };
  export type delete_Feature_flags_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/feature_flags/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Feature_flags_activity_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/{id}/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; page: number }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.ActivityLogPaginatedResponse; 404: unknown };
  };
  export type post_Feature_flags_create_static_cohort_for_flag_create = {
    method: "POST";
    path: "/api/projects/{project_id}/feature_flags/{id}/create_static_cohort_for_flag/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.FeatureFlag;
    };
    responses: { 200: unknown };
  };
  export type post_Feature_flags_dashboard_create = {
    method: "POST";
    path: "/api/projects/{project_id}/feature_flags/{id}/dashboard/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.FeatureFlag;
    };
    responses: { 200: unknown };
  };
  export type get_Feature_flags_dependent_flags_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/{id}/dependent_flags/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Feature_flags_enrich_usage_dashboard_create = {
    method: "POST";
    path: "/api/projects/{project_id}/feature_flags/{id}/enrich_usage_dashboard/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.FeatureFlag;
    };
    responses: { 200: unknown };
  };
  export type get_Feature_flags_remote_config_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/{id}/remote_config/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Feature_flags_status_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/{id}/status/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Feature_flags_activity_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; page: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.ActivityLogPaginatedResponse };
  };
  export type post_Feature_flags_bulk_keys_create = {
    method: "POST";
    path: "/api/projects/{project_id}/feature_flags/bulk_keys/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FeatureFlag;
    };
    responses: { 200: unknown };
  };
  export type get_Feature_flags_evaluation_reasons_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/evaluation_reasons/";
    requestFormat: "json";
    parameters: {
      query: { distinct_id: string; groups?: string | undefined };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Feature_flags_local_evaluation_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/local_evaluation/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ send_cohorts: boolean | null }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.LocalEvaluationResponse; 402: Record<string, unknown>; 500: Record<string, unknown> };
  };
  export type get_Feature_flags_my_flags_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/feature_flags/my_flags/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ groups: string }>;
      path: { project_id: string };
    };
    responses: { 200: Array<Schemas.MyFlagsResponse> };
  };
  export type post_Feature_flags_user_blast_radius_create = {
    method: "POST";
    path: "/api/projects/{project_id}/feature_flags/user_blast_radius/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FeatureFlag;
    };
    responses: { 200: unknown };
  };
  export type get_File_system_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/file_system/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedFileSystemList };
  };
  export type post_File_system_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 201: Schemas.FileSystem };
  };
  export type get_File_system_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.FileSystem };
  };
  export type put_File_system_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: Schemas.FileSystem };
  };
  export type patch_File_system_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedFileSystem;
    };
    responses: { 200: Schemas.FileSystem };
  };
  export type delete_File_system_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/file_system/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_File_system_count_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system/{id}/count/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_link_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system/{id}/link/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_move_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system/{id}/move/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_count_by_path_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system/count_by_path/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type get_File_system_log_view_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/file_system/log_view/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_File_system_log_view_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system/log_view/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type post_File_system_undo_delete_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system/undo_delete/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystem;
    };
    responses: { 200: unknown };
  };
  export type get_File_system_unfiled_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/file_system/unfiled/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_File_system_shortcut_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/file_system_shortcut/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedFileSystemShortcutList };
  };
  export type post_File_system_shortcut_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/file_system_shortcut/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.FileSystemShortcut;
    };
    responses: { 201: Schemas.FileSystemShortcut };
  };
  export type get_File_system_shortcut_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.FileSystemShortcut };
  };
  export type put_File_system_shortcut_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.FileSystemShortcut;
    };
    responses: { 200: Schemas.FileSystemShortcut };
  };
  export type patch_File_system_shortcut_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedFileSystemShortcut;
    };
    responses: { 200: Schemas.FileSystemShortcut };
  };
  export type delete_File_system_shortcut_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/file_system_shortcut/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Flag_value_values_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/flag_value/values/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ key: string }>;
      path: { project_id: string };
    };
    responses: { 200: Array<Record<string, unknown>>; 400: Record<string, unknown>; 404: Record<string, unknown> };
  };
  export type get_Groups_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/groups/";
    requestFormat: "json";
    parameters: {
      query: { cursor?: string | undefined; group_type_index: number; search: string };
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedGroupList };
  };
  export type post_Groups_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/groups/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.CreateGroup;
    };
    responses: { 201: Schemas.Group };
  };
  export type get_Groups_activity_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/groups/activity/";
    requestFormat: "json";
    parameters: {
      query: { group_type_index: number; id: string };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Groups_delete_property_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/groups/delete_property/";
    requestFormat: "json";
    parameters: {
      query: { group_key: string; group_type_index: number };
      path: { project_id: string };

      body: Schemas.Group;
    };
    responses: { 200: unknown };
  };
  export type get_Groups_find_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/groups/find/";
    requestFormat: "json";
    parameters: {
      query: { group_key: string; group_type_index: number };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Groups_property_definitions_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/groups/property_definitions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Groups_property_values_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/groups/property_values/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Groups_related_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/groups/related/";
    requestFormat: "json";
    parameters: {
      query: { group_type_index: number; id: string };
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Groups_update_property_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/groups/update_property/";
    requestFormat: "json";
    parameters: {
      query: { group_key: string; group_type_index: number };
      path: { project_id: string };

      body: Schemas.Group;
    };
    responses: { 200: unknown };
  };
  export type get_Groups_types_list = {
    method: "GET";
    path: "/api/projects/{project_id}/groups_types/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: Array<Schemas.GroupType> };
  };
  export type delete_Groups_types_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/groups_types/{group_type_index}/";
    requestFormat: "json";
    parameters: {
      path: { group_type_index: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Groups_types_metrics_list = {
    method: "GET";
    path: "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { group_type_index: number; project_id: string };
    };
    responses: { 200: Schemas.PaginatedGroupUsageMetricList };
  };
  export type post_Groups_types_metrics_create = {
    method: "POST";
    path: "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/";
    requestFormat: "json";
    parameters: {
      path: { group_type_index: number; project_id: string };

      body: Schemas.GroupUsageMetric;
    };
    responses: { 201: Schemas.GroupUsageMetric };
  };
  export type get_Groups_types_metrics_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { group_type_index: number; id: string; project_id: string };
    };
    responses: { 200: Schemas.GroupUsageMetric };
  };
  export type put_Groups_types_metrics_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { group_type_index: number; id: string; project_id: string };

      body: Schemas.GroupUsageMetric;
    };
    responses: { 200: Schemas.GroupUsageMetric };
  };
  export type patch_Groups_types_metrics_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { group_type_index: number; id: string; project_id: string };

      body: Schemas.PatchedGroupUsageMetric;
    };
    responses: { 200: Schemas.GroupUsageMetric };
  };
  export type delete_Groups_types_metrics_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/";
    requestFormat: "json";
    parameters: {
      path: { group_type_index: number; id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type put_Groups_types_create_detail_dashboard_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/groups_types/create_detail_dashboard/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.GroupType;
    };
    responses: { 200: unknown };
  };
  export type put_Groups_types_set_default_columns_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/groups_types/set_default_columns/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.GroupType;
    };
    responses: { 200: unknown };
  };
  export type patch_Groups_types_update_metadata_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/groups_types/update_metadata/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PatchedGroupType;
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/hog_functions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        created_at: string;
        created_by: number;
        enabled: boolean;
        id: string;
        limit: number;
        offset: number;
        search: string;
        type: Array<string>;
        updated_at: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedHogFunctionMinimalList };
  };
  export type post_Hog_functions_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/hog_functions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 201: Schemas.HogFunction };
  };
  export type get_Hog_functions_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.HogFunction };
  };
  export type put_Hog_functions_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 200: Schemas.HogFunction };
  };
  export type patch_Hog_functions_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedHogFunction;
    };
    responses: { 200: Schemas.HogFunction };
  };
  export type delete_Hog_functions_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/hog_functions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type post_Hog_functions_enable_backfills_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/hog_functions/{id}/enable_backfills/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 200: unknown };
  };
  export type post_Hog_functions_invocations_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/hog_functions/{id}/invocations/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.HogFunction;
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_logs_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/hog_functions/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_metrics_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/hog_functions/{id}/metrics/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_metrics_totals_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/hog_functions/{id}/metrics/totals/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_icon_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/hog_functions/icon/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Hog_functions_icons_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/hog_functions/icons/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Hog_functions_rearrange_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/hog_functions/rearrange/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PatchedHogFunction;
    };
    responses: { 200: unknown };
  };
  export type get_Insight_variables_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insight_variables/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ page: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedInsightVariableList };
  };
  export type post_Insight_variables_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/insight_variables/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.InsightVariable;
    };
    responses: { 201: Schemas.InsightVariable };
  };
  export type get_Insight_variables_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.InsightVariable };
  };
  export type put_Insight_variables_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.InsightVariable;
    };
    responses: { 200: Schemas.InsightVariable };
  };
  export type patch_Insight_variables_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedInsightVariable;
    };
    responses: { 200: Schemas.InsightVariable };
  };
  export type delete_Insight_variables_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/insight_variables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Insights_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        basic: boolean;
        format: "csv" | "json";
        limit: number;
        offset: number;
        refresh:
          | "async"
          | "async_except_on_cache_miss"
          | "blocking"
          | "force_async"
          | "force_blocking"
          | "force_cache"
          | "lazy_async";
        short_id: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedInsightList };
  };
  export type post_Insights_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/insights/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Insight;
    };
    responses: { 201: Schemas.Insight };
  };
  export type get_Insights_sharing_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/{insight_id}/sharing/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; project_id: string };
    };
    responses: { 200: Array<Schemas.SharingConfiguration> };
  };
  export type post_Insights_sharing_passwords_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type delete_Insights_sharing_passwords_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; password_id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Insights_sharing_refresh_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/insights/{insight_id}/sharing/refresh/";
    requestFormat: "json";
    parameters: {
      path: { insight_id: number; project_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type get_Insights_thresholds_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/{insight_id}/thresholds/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { insight_id: number; project_id: string };
    };
    responses: { 200: Schemas.PaginatedThresholdWithAlertList };
  };
  export type get_Insights_thresholds_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/{insight_id}/thresholds/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; insight_id: number; project_id: string };
    };
    responses: { 200: Schemas.ThresholdWithAlert };
  };
  export type get_Insights_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        format: "csv" | "json";
        from_dashboard: number;
        refresh:
          | "async"
          | "async_except_on_cache_miss"
          | "blocking"
          | "force_async"
          | "force_blocking"
          | "force_cache"
          | "lazy_async";
      }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Insight };
  };
  export type put_Insights_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: Schemas.Insight };
  };
  export type patch_Insights_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedInsight;
    };
    responses: { 200: Schemas.Insight };
  };
  export type delete_Insights_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/insights/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Insights_activity_retrieve_4 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/{id}/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Insights_analyze_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/{id}/analyze/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Insights_suggestions_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/{id}/suggestions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Insights_suggestions_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/insights/{id}/suggestions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: unknown };
  };
  export type get_Insights_activity_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Insights_cancel_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/insights/cancel/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: unknown };
  };
  export type get_Insights_my_last_viewed_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/insights/my_last_viewed/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Insights_viewed_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/insights/viewed/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Insight;
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_list_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedIntegrationList };
  };
  export type post_Integrations_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/integrations/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Integration;
    };
    responses: { 201: Schemas.Integration };
  };
  export type get_Integrations_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Integration };
  };
  export type delete_Integrations_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/integrations/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Integrations_channels_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/channels/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_clickup_lists_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/clickup_lists/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_clickup_spaces_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/clickup_spaces/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_clickup_workspaces_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/clickup_workspaces/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Integrations_email_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/integrations/{id}/email/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedIntegration;
    };
    responses: { 200: Schemas.Integration };
  };
  export type post_Integrations_email_verify_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/integrations/{id}/email/verify/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Integration;
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_github_repos_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/github_repos/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_google_accessible_accounts_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/google_accessible_accounts/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_google_conversion_actions_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/google_conversion_actions/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_jira_projects_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/jira_projects/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_linear_teams_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/linear_teams/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_linkedin_ads_accounts_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/linkedin_ads_accounts/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_linkedin_ads_conversion_rules_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/linkedin_ads_conversion_rules/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_twilio_phone_numbers_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/{id}/twilio_phone_numbers/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Integrations_authorize_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/integrations/authorize/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Live_debugger_breakpoints_list = {
    method: "GET";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ filename: string; limit: number; offset: number; repository: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedLiveDebuggerBreakpointList };
  };
  export type post_Live_debugger_breakpoints_create = {
    method: "POST";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.LiveDebuggerBreakpoint;
    };
    responses: { 201: Schemas.LiveDebuggerBreakpoint };
  };
  export type get_Live_debugger_breakpoints_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.LiveDebuggerBreakpoint };
  };
  export type put_Live_debugger_breakpoints_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.LiveDebuggerBreakpoint;
    };
    responses: { 200: Schemas.LiveDebuggerBreakpoint };
  };
  export type patch_Live_debugger_breakpoints_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedLiveDebuggerBreakpoint;
    };
    responses: { 200: Schemas.LiveDebuggerBreakpoint };
  };
  export type delete_Live_debugger_breakpoints_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Live_debugger_breakpoints_active_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/active/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ enabled: boolean; filename: string; repository: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.ActiveBreakpointsResponse; 400: unknown; 401: unknown };
  };
  export type get_Live_debugger_breakpoints_breakpoint_hits_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/live_debugger_breakpoints/breakpoint_hits/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ breakpoint_ids: string; limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.BreakpointHitsResponse; 400: unknown };
  };
  export type get_Logs_attributes_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/logs/attributes/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Logs_export_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/logs/export/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Logs_has_logs_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/logs/has_logs/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Logs_query_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/logs/query/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Logs_sparkline_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/logs/sparkline/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Logs_values_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/logs/values/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Notebooks_list = {
    method: "GET";
    path: "/api/projects/{project_id}/notebooks/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        contains: string;
        created_by: string;
        date_from: string;
        date_to: string;
        limit: number;
        offset: number;
        user: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedNotebookMinimalList };
  };
  export type post_Notebooks_create = {
    method: "POST";
    path: "/api/projects/{project_id}/notebooks/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Notebook;
    };
    responses: { 201: Schemas.Notebook };
  };
  export type get_Notebooks_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/notebooks/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: Schemas.Notebook };
  };
  export type put_Notebooks_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/notebooks/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.Notebook;
    };
    responses: { 200: Schemas.Notebook };
  };
  export type patch_Notebooks_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/notebooks/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.PatchedNotebook;
    };
    responses: { 200: Schemas.Notebook };
  };
  export type delete_Notebooks_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/notebooks/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Notebooks_activity_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/notebooks/{short_id}/activity/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Notebooks_kernel_config_create = {
    method: "POST";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/config/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.Notebook;
    };
    responses: { 200: unknown };
  };
  export type get_Notebooks_kernel_dataframe_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/dataframe/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Notebooks_kernel_execute_create = {
    method: "POST";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/execute/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.Notebook;
    };
    responses: { 200: unknown };
  };
  export type post_Notebooks_kernel_execute_stream_create = {
    method: "POST";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/execute/stream/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.Notebook;
    };
    responses: { 200: unknown };
  };
  export type post_Notebooks_kernel_restart_create = {
    method: "POST";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/restart/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.Notebook;
    };
    responses: { 200: unknown };
  };
  export type post_Notebooks_kernel_start_create = {
    method: "POST";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/start/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.Notebook;
    };
    responses: { 200: unknown };
  };
  export type get_Notebooks_kernel_status_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/status/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Notebooks_kernel_stop_create = {
    method: "POST";
    path: "/api/projects/{project_id}/notebooks/{short_id}/kernel/stop/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.Notebook;
    };
    responses: { 200: unknown };
  };
  export type get_Notebooks_activity_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/notebooks/activity/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Notebooks_recording_comments_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/notebooks/recording_comments/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persisted_folder_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persisted_folder/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedPersistedFolderList };
  };
  export type post_Persisted_folder_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persisted_folder/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.PersistedFolder;
    };
    responses: { 201: Schemas.PersistedFolder };
  };
  export type get_Persisted_folder_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.PersistedFolder };
  };
  export type put_Persisted_folder_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PersistedFolder;
    };
    responses: { 200: Schemas.PersistedFolder };
  };
  export type patch_Persisted_folder_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedPersistedFolder;
    };
    responses: { 200: Schemas.PersistedFolder };
  };
  export type delete_Persisted_folder_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/persisted_folder/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Persons_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        distinct_id: string;
        email: string;
        format: "csv" | "json";
        limit: number;
        offset: number;
        properties: Array<Schemas.Property>;
        search: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedPersonList };
  };
  export type get_Persons_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Person };
  };
  export type put_Persons_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/persons/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: Schemas.Person };
  };
  export type patch_Persons_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/persons/{id}/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.PatchedPerson;
    };
    responses: { 200: Schemas.Person };
  };
  export type get_Persons_activity_retrieve_4 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/{id}/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_delete_property_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persons/{id}/delete_property/";
    requestFormat: "json";
    parameters: {
      query: { $unset: string; format?: ("csv" | "json") | undefined };
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_properties_timeline_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/{id}/properties_timeline/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_split_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persons/{id}/split/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type post_Persons_update_property_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persons/{id}/update_property/";
    requestFormat: "json";
    parameters: {
      query: { format?: ("csv" | "json") | undefined; key: string; value: unknown };
      path: { id: number; project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_activity_retrieve_3 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/activity/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_bulk_delete_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persons/bulk_delete/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        delete_events: boolean;
        delete_recordings: boolean;
        distinct_ids: Record<string, unknown>;
        format: "csv" | "json";
        ids: Record<string, unknown>;
        keep_person: boolean;
      }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_cohorts_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/cohorts/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persons_funnel_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/funnel/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_funnel_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persons/funnel/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_funnel_correlation_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/funnel/correlation/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_funnel_correlation_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persons/funnel/correlation/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_lifecycle_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/lifecycle/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Persons_reset_person_distinct_id_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/persons/reset_person_distinct_id/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };

      body: Schemas.Person;
    };
    responses: { 200: unknown };
  };
  export type get_Persons_stickiness_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/stickiness/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persons_trends_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/trends/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Persons_values_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/persons/values/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ format: "csv" | "json" }>;
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Plugin_configs_logs_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/plugin_configs/{plugin_config_id}/logs/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { plugin_config_id: string; project_id: string };
    };
    responses: { 200: Schemas.PaginatedPluginLogEntryList };
  };
  export type get_Product_tours_list = {
    method: "GET";
    path: "/api/projects/{project_id}/product_tours/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedProductTourList };
  };
  export type post_Product_tours_create = {
    method: "POST";
    path: "/api/projects/{project_id}/product_tours/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ProductTourSerializerCreateUpdateOnly;
    };
    responses: { 201: Schemas.ProductTourSerializerCreateUpdateOnly };
  };
  export type get_Product_tours_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/product_tours/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.ProductTour };
  };
  export type put_Product_tours_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/product_tours/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.ProductTour;
    };
    responses: { 200: Schemas.ProductTour };
  };
  export type patch_Product_tours_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/product_tours/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedProductTourSerializerCreateUpdateOnly;
    };
    responses: { 200: Schemas.ProductTourSerializerCreateUpdateOnly };
  };
  export type delete_Product_tours_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/product_tours/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Product_tours_generate_create = {
    method: "POST";
    path: "/api/projects/{project_id}/product_tours/generate/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.ProductTourSerializerCreateUpdateOnly;
    };
    responses: { 200: Schemas.ProductTourSerializerCreateUpdateOnly };
  };
  export type get_Property_definitions_list = {
    method: "GET";
    path: "/api/projects/{project_id}/property_definitions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        event_names: string;
        exclude_core_properties: boolean;
        exclude_hidden: boolean;
        excluded_properties: string;
        filter_by_event_names: boolean | null;
        group_type_index: number;
        is_feature_flag: boolean | null;
        is_numerical: boolean | null;
        limit: number;
        offset: number;
        properties: string;
        search: string;
        type: "event" | "person" | "group" | "session";
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedEnterprisePropertyDefinitionList };
  };
  export type get_Property_definitions_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/property_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.EnterprisePropertyDefinition };
  };
  export type put_Property_definitions_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/property_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.EnterprisePropertyDefinition;
    };
    responses: { 200: Schemas.EnterprisePropertyDefinition };
  };
  export type patch_Property_definitions_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/property_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedEnterprisePropertyDefinition;
    };
    responses: { 200: Schemas.EnterprisePropertyDefinition };
  };
  export type delete_Property_definitions_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/property_definitions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Property_definitions_seen_together_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/property_definitions/seen_together/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Query_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/query/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.QueryRequest;
    };
    responses: { 200: Schemas.QueryResponseAlternative };
  };
  export type get_Query_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/query/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.QueryStatusResponse };
  };
  export type delete_Query_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/query/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Query_log_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/query/{id}/log/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Record<string, unknown> };
  };
  export type post_Query_check_auth_for_async_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/query/check_auth_for_async/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Query_draft_sql_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/query/draft_sql/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Query_upgrade_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/query/upgrade/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.QueryUpgradeRequest;
    };
    responses: { 200: Schemas.QueryUpgradeResponse };
  };
  export type get_Session_group_summaries_list = {
    method: "GET";
    path: "/api/projects/{project_id}/session_group_summaries/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSessionGroupSummaryMinimalList };
  };
  export type post_Session_group_summaries_create = {
    method: "POST";
    path: "/api/projects/{project_id}/session_group_summaries/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.SessionGroupSummary;
    };
    responses: { 201: Schemas.SessionGroupSummary };
  };
  export type get_Session_group_summaries_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/session_group_summaries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.SessionGroupSummary };
  };
  export type put_Session_group_summaries_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/session_group_summaries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.SessionGroupSummary;
    };
    responses: { 200: Schemas.SessionGroupSummary };
  };
  export type patch_Session_group_summaries_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/session_group_summaries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedSessionGroupSummary;
    };
    responses: { 200: Schemas.SessionGroupSummary };
  };
  export type delete_Session_group_summaries_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/session_group_summaries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Session_recording_playlists_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/session_recording_playlists/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ created_by: number; limit: number; offset: number; short_id: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSessionRecordingPlaylistList };
  };
  export type post_Session_recording_playlists_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/session_recording_playlists/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.SessionRecordingPlaylist;
    };
    responses: { 201: Schemas.SessionRecordingPlaylist };
  };
  export type get_Session_recording_playlists_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: Schemas.SessionRecordingPlaylist };
  };
  export type put_Session_recording_playlists_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.SessionRecordingPlaylist;
    };
    responses: { 200: Schemas.SessionRecordingPlaylist };
  };
  export type patch_Session_recording_playlists_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };

      body: Schemas.PatchedSessionRecordingPlaylist;
    };
    responses: { 200: Schemas.SessionRecordingPlaylist };
  };
  export type delete_Session_recording_playlists_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/session_recording_playlists/{short_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Session_recording_playlists_recordings_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; short_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Session_recording_playlists_recordings_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; session_recording_id: string; short_id: string };

      body: Schemas.SessionRecordingPlaylist;
    };
    responses: { 200: unknown };
  };
  export type delete_Session_recording_playlists_recordings_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; session_recording_id: string; short_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Session_recordings_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/session_recordings/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSessionRecordingList };
  };
  export type get_Session_recordings_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.SessionRecording };
  };
  export type put_Session_recordings_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.SessionRecording;
    };
    responses: { 200: Schemas.SessionRecording };
  };
  export type patch_Session_recordings_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedSessionRecording;
    };
    responses: { 200: Schemas.SessionRecording };
  };
  export type delete_Session_recordings_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/session_recordings/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Session_recordings_sharing_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; recording_id: string };
    };
    responses: { 200: Array<Schemas.SharingConfiguration> };
  };
  export type post_Session_recordings_sharing_passwords_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; recording_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type delete_Session_recordings_sharing_passwords_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/";
    requestFormat: "json";
    parameters: {
      path: { password_id: string; project_id: string; recording_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Session_recordings_sharing_refresh_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/refresh/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; recording_id: string };

      body: Schemas.SharingConfiguration;
    };
    responses: { 200: Schemas.SharingConfiguration };
  };
  export type get_Sessions_property_definitions_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/sessions/property_definitions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Sessions_values_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/sessions/values/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Signal_reports_list = {
    method: "GET";
    path: "/api/projects/{project_id}/signal_reports/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSignalReportList };
  };
  export type get_Signal_reports_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/signal_reports/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.SignalReport };
  };
  export type get_Signal_reports_artefacts_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/signal_reports/{id}/artefacts/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown; 404: unknown };
  };
  export type get_Subscriptions_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/subscriptions/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSubscriptionList };
  };
  export type post_Subscriptions_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/subscriptions/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Subscription;
    };
    responses: { 201: Schemas.Subscription };
  };
  export type get_Subscriptions_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.Subscription };
  };
  export type put_Subscriptions_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.Subscription;
    };
    responses: { 200: Schemas.Subscription };
  };
  export type patch_Subscriptions_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedSubscription;
    };
    responses: { 200: Schemas.Subscription };
  };
  export type delete_Subscriptions_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/subscriptions/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 405: unknown };
  };
  export type get_Surveys_list = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedSurveyList };
  };
  export type post_Surveys_create = {
    method: "POST";
    path: "/api/projects/{project_id}/surveys/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.SurveySerializerCreateUpdateOnly;
    };
    responses: { 201: Schemas.SurveySerializerCreateUpdateOnly };
  };
  export type get_Surveys_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Survey };
  };
  export type put_Surveys_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/surveys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Survey;
    };
    responses: { 200: Schemas.Survey };
  };
  export type patch_Surveys_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/surveys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedSurveySerializerCreateUpdateOnly;
    };
    responses: { 200: Schemas.SurveySerializerCreateUpdateOnly };
  };
  export type delete_Surveys_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/surveys/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Surveys_activity_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/{id}/activity/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Surveys_archived_response_uuids_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/{id}/archived-response-uuids/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Surveys_duplicate_to_projects_create = {
    method: "POST";
    path: "/api/projects/{project_id}/surveys/{id}/duplicate_to_projects/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.SurveySerializerCreateUpdateOnly;
    };
    responses: { 200: unknown };
  };
  export type post_Surveys_responses_archive_create = {
    method: "POST";
    path: "/api/projects/{project_id}/surveys/{id}/responses/{response_uuid}/archive/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; response_uuid: string };

      body: Schemas.SurveySerializerCreateUpdateOnly;
    };
    responses: { 200: unknown };
  };
  export type post_Surveys_responses_unarchive_create = {
    method: "POST";
    path: "/api/projects/{project_id}/surveys/{id}/responses/{response_uuid}/unarchive/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; response_uuid: string };

      body: Schemas.SurveySerializerCreateUpdateOnly;
    };
    responses: { 200: unknown };
  };
  export type get_Surveys_stats_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/{id}/stats/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: unknown };
  };
  export type post_Surveys_summarize_responses_create = {
    method: "POST";
    path: "/api/projects/{project_id}/surveys/{id}/summarize_responses/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.SurveySerializerCreateUpdateOnly;
    };
    responses: { 200: unknown };
  };
  export type post_Surveys_summary_headline_create = {
    method: "POST";
    path: "/api/projects/{project_id}/surveys/{id}/summary_headline/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.SurveySerializerCreateUpdateOnly;
    };
    responses: { 200: unknown };
  };
  export type get_Surveys_activity_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/activity/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Surveys_responses_count_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/responses_count/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Surveys_stats_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/surveys/stats/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown };
  };
  export type get_Tasks_list = {
    method: "GET";
    path: "/api/projects/{project_id}/tasks/";
    requestFormat: "json";
    parameters: {
      query: Partial<{
        created_by: number;
        limit: number;
        offset: number;
        organization: string;
        origin_product: string;
        repository: string;
        stage: string;
      }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedTaskList };
  };
  export type post_Tasks_create = {
    method: "POST";
    path: "/api/projects/{project_id}/tasks/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Task;
    };
    responses: { 201: Schemas.Task };
  };
  export type get_Tasks_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/tasks/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Task };
  };
  export type put_Tasks_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/tasks/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Task;
    };
    responses: { 200: Schemas.Task };
  };
  export type patch_Tasks_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/tasks/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedTask;
    };
    responses: { 200: Schemas.Task };
  };
  export type delete_Tasks_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/tasks/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Tasks_run_create = {
    method: "POST";
    path: "/api/projects/{project_id}/tasks/{id}/run/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Task; 404: unknown };
  };
  export type get_Tasks_runs_list = {
    method: "GET";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string; task_id: string };
    };
    responses: { 200: Schemas.PaginatedTaskRunDetailList };
  };
  export type post_Tasks_runs_create = {
    method: "POST";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string; task_id: string };
    };
    responses: { 201: Schemas.TaskRunDetail };
  };
  export type get_Tasks_runs_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; task_id: string };
    };
    responses: { 200: Schemas.TaskRunDetail };
  };
  export type patch_Tasks_runs_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; task_id: string };

      body: Schemas.PatchedTaskRunUpdate;
    };
    responses: { 200: Schemas.TaskRunDetail; 400: Schemas.ErrorResponse; 404: unknown };
  };
  export type post_Tasks_runs_append_log_create = {
    method: "POST";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/append_log/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; task_id: string };

      body: Schemas.TaskRunAppendLogRequest;
    };
    responses: { 200: Schemas.TaskRunDetail; 400: Schemas.ErrorResponse; 404: unknown };
  };
  export type post_Tasks_runs_artifacts_create = {
    method: "POST";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/artifacts/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; task_id: string };

      body: Schemas.TaskRunArtifactsUploadRequest;
    };
    responses: { 200: Schemas.TaskRunArtifactsUploadResponse; 400: Schemas.ErrorResponse; 404: unknown };
  };
  export type post_Tasks_runs_artifacts_presign_create = {
    method: "POST";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/artifacts/presign/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; task_id: string };

      body: Schemas.TaskRunArtifactPresignRequest;
    };
    responses: { 200: Schemas.TaskRunArtifactPresignResponse; 400: Schemas.ErrorResponse; 404: unknown };
  };
  export type get_Tasks_runs_logs_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/logs/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; task_id: string };
    };
    responses: { 200: unknown; 404: unknown };
  };
  export type patch_Tasks_runs_set_output_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/set_output/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string; task_id: string };
    };
    responses: { 200: Schemas.TaskRunDetail; 404: unknown };
  };
  export type post_Tasks_cluster_video_segments_create = {
    method: "POST";
    path: "/api/projects/{project_id}/tasks/cluster_video_segments/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
    };
    responses: { 200: unknown; 500: unknown };
  };
  export type get_Warehouse_saved_queries_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/warehouse_saved_queries/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ page: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedDataWarehouseSavedQueryMinimalList };
  };
  export type post_Warehouse_saved_queries_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 201: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_saved_queries_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type put_Warehouse_saved_queries_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type patch_Warehouse_saved_queries_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedDataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type delete_Warehouse_saved_queries_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_Warehouse_saved_queries_activity_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/activity/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_ancestors_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/ancestors/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_cancel_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/cancel/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_saved_queries_dependencies_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/dependencies/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_descendants_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/descendants/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_materialize_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/materialize/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_revert_materialization_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/revert_materialization/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_run_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/run/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_saved_queries_run_history_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/warehouse_saved_queries/{id}/run_history/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type post_Warehouse_saved_queries_resume_schedules_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_saved_queries/resume_schedules/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.DataWarehouseSavedQuery;
    };
    responses: { 200: Schemas.DataWarehouseSavedQuery };
  };
  export type get_Warehouse_tables_list_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/warehouse_tables/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number; search: string }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedTableList };
  };
  export type post_Warehouse_tables_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_tables/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.Table;
    };
    responses: { 201: Schemas.Table };
  };
  export type get_Warehouse_tables_retrieve_2 = {
    method: "GET";
    path: "/api/projects/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: Schemas.Table };
  };
  export type put_Warehouse_tables_update_2 = {
    method: "PUT";
    path: "/api/projects/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: Schemas.Table };
  };
  export type patch_Warehouse_tables_partial_update_2 = {
    method: "PATCH";
    path: "/api/projects/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.PatchedTable;
    };
    responses: { 200: Schemas.Table };
  };
  export type delete_Warehouse_tables_destroy_2 = {
    method: "DELETE";
    path: "/api/projects/{project_id}/warehouse_tables/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Warehouse_tables_refresh_schema_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_tables/{id}/refresh_schema/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: unknown };
  };
  export type post_Warehouse_tables_update_schema_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_tables/{id}/update_schema/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: unknown };
  };
  export type post_Warehouse_tables_file_create_2 = {
    method: "POST";
    path: "/api/projects/{project_id}/warehouse_tables/file/";
    requestFormat: "form-data";
    parameters: {
      path: { project_id: string };

      body: Schemas.Table;
    };
    responses: { 200: unknown };
  };
  export type get_Web_analytics_breakdown_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/web_analytics/breakdown/";
    requestFormat: "json";
    parameters: {
      query: {
        apply_path_cleaning?: boolean | undefined;
        breakdown_by:
          | "DeviceType"
          | "Browser"
          | "OS"
          | "Viewport"
          | "InitialReferringDomain"
          | "InitialUTMSource"
          | "InitialUTMMedium"
          | "InitialUTMCampaign"
          | "InitialUTMTerm"
          | "InitialUTMContent"
          | "Country"
          | "Region"
          | "City"
          | "InitialPage"
          | "Page"
          | "ExitPage"
          | "InitialChannelType";
        date_from: string;
        date_to: string;
        filter_test_accounts?: boolean | undefined;
        host?: (string | null) | undefined;
        limit?: number | undefined;
        offset?: number | undefined;
      };
      path: { project_id: string };
    };
    responses: { 200: Schemas.WebAnalyticsBreakdownResponse };
  };
  export type get_Web_analytics_overview_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/web_analytics/overview/";
    requestFormat: "json";
    parameters: {
      query: {
        date_from: string;
        date_to: string;
        filter_test_accounts?: boolean | undefined;
        host?: (string | null) | undefined;
      };
      path: { project_id: string };
    };
    responses: { 200: Schemas.WebAnalyticsOverviewResponse };
  };
  export type get_Web_experiments_list = {
    method: "GET";
    path: "/api/projects/{project_id}/web_experiments/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: Schemas.PaginatedWebExperimentsAPIList };
  };
  export type post_Web_experiments_create = {
    method: "POST";
    path: "/api/projects/{project_id}/web_experiments/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };

      body: Schemas.WebExperimentsAPI;
    };
    responses: { 201: Schemas.WebExperimentsAPI };
  };
  export type get_Web_experiments_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/web_experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 200: Schemas.WebExperimentsAPI };
  };
  export type put_Web_experiments_update = {
    method: "PUT";
    path: "/api/projects/{project_id}/web_experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.WebExperimentsAPI;
    };
    responses: { 200: Schemas.WebExperimentsAPI };
  };
  export type patch_Web_experiments_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/web_experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };

      body: Schemas.PatchedWebExperimentsAPI;
    };
    responses: { 200: Schemas.WebExperimentsAPI };
  };
  export type delete_Web_experiments_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/web_experiments/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: number; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type get_User_home_settings_retrieve = {
    method: "GET";
    path: "/api/user_home_settings/{uuid}/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };
    };
    responses: { 200: Schemas.PinnedSceneTabs };
  };
  export type patch_User_home_settings_partial_update = {
    method: "PATCH";
    path: "/api/user_home_settings/{uuid}/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.PatchedPinnedSceneTabs;
    };
    responses: { 200: Schemas.PinnedSceneTabs };
  };
  export type get_Users_list = {
    method: "GET";
    path: "/api/users/";
    requestFormat: "json";
    parameters: {
      query: Partial<{ email: string; is_staff: boolean; limit: number; offset: number }>;
    };
    responses: { 200: Schemas.PaginatedUserList };
  };
  export type get_Users_retrieve = {
    method: "GET";
    path: "/api/users/{uuid}/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };
    };
    responses: { 200: Schemas.User };
  };
  export type put_Users_update = {
    method: "PUT";
    path: "/api/users/{uuid}/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.User;
    };
    responses: { 200: Schemas.User };
  };
  export type patch_Users_partial_update = {
    method: "PATCH";
    path: "/api/users/{uuid}/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.PatchedUser;
    };
    responses: { 200: Schemas.User };
  };
  export type delete_Users_destroy = {
    method: "DELETE";
    path: "/api/users/{uuid}/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };
    };
    responses: { 204: unknown };
  };
  export type get_Users_hedgehog_config_retrieve = {
    method: "GET";
    path: "/api/users/{uuid}/hedgehog_config/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };
    };
    responses: { 200: unknown };
  };
  export type patch_Users_hedgehog_config_partial_update = {
    method: "PATCH";
    path: "/api/users/{uuid}/hedgehog_config/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.PatchedUser;
    };
    responses: { 200: unknown };
  };
  export type post_Users_scene_personalisation_create = {
    method: "POST";
    path: "/api/users/{uuid}/scene_personalisation/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.User;
    };
    responses: { 200: unknown };
  };
  export type get_Users_start_2fa_setup_retrieve = {
    method: "GET";
    path: "/api/users/{uuid}/start_2fa_setup/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };
    };
    responses: { 200: unknown };
  };
  export type post_Users_two_factor_backup_codes_create = {
    method: "POST";
    path: "/api/users/{uuid}/two_factor_backup_codes/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.User;
    };
    responses: { 200: unknown };
  };
  export type post_Users_two_factor_disable_create = {
    method: "POST";
    path: "/api/users/{uuid}/two_factor_disable/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.User;
    };
    responses: { 200: unknown };
  };
  export type get_Users_two_factor_start_setup_retrieve = {
    method: "GET";
    path: "/api/users/{uuid}/two_factor_start_setup/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };
    };
    responses: { 200: unknown };
  };
  export type get_Users_two_factor_status_retrieve = {
    method: "GET";
    path: "/api/users/{uuid}/two_factor_status/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };
    };
    responses: { 200: unknown };
  };
  export type post_Users_two_factor_validate_create = {
    method: "POST";
    path: "/api/users/{uuid}/two_factor_validate/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.User;
    };
    responses: { 200: unknown };
  };
  export type post_Users_validate_2fa_create = {
    method: "POST";
    path: "/api/users/{uuid}/validate_2fa/";
    requestFormat: "json";
    parameters: {
      path: { uuid: string };

      body: Schemas.User;
    };
    responses: { 200: unknown };
  };
  export type patch_Users_cancel_email_change_request_partial_update = {
    method: "PATCH";
    path: "/api/users/cancel_email_change_request/";
    requestFormat: "json";
    parameters: {
      body: Schemas.PatchedUser;
    };
    responses: { 200: unknown };
  };
  export type post_Users_request_email_verification_create = {
    method: "POST";
    path: "/api/users/request_email_verification/";
    requestFormat: "json";
    parameters: {
      body: Schemas.User;
    };
    responses: { 200: unknown };
  };
  export type post_Users_verify_email_create = {
    method: "POST";
    path: "/api/users/verify_email/";
    requestFormat: "json";
    parameters: {
      body: Schemas.User;
    };
    responses: { 200: unknown };
  };

  // </Endpoints>
}

// <EndpointByMethod>
export type EndpointByMethod = {
  get: {
    "/api/environments/{project_id}/alerts/": Endpoints.get_Alerts_list;
    "/api/environments/{project_id}/alerts/{id}/": Endpoints.get_Alerts_retrieve;
    "/api/environments/{project_id}/app_metrics/{id}/": Endpoints.get_App_metrics_retrieve;
    "/api/environments/{project_id}/app_metrics/{id}/error_details/": Endpoints.get_App_metrics_error_details_retrieve;
    "/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/": Endpoints.get_App_metrics_historical_exports_retrieve;
    "/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/": Endpoints.get_App_metrics_historical_exports_retrieve_2;
    "/api/environments/{project_id}/batch_exports/": Endpoints.get_Batch_exports_list;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/": Endpoints.get_Batch_exports_backfills_list;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/": Endpoints.get_Batch_exports_backfills_retrieve;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/": Endpoints.get_Batch_exports_runs_list;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/": Endpoints.get_Batch_exports_runs_retrieve;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/": Endpoints.get_Batch_exports_runs_logs_retrieve;
    "/api/environments/{project_id}/batch_exports/{id}/": Endpoints.get_Batch_exports_retrieve;
    "/api/environments/{project_id}/batch_exports/{id}/logs/": Endpoints.get_Batch_exports_logs_retrieve;
    "/api/environments/{project_id}/batch_exports/test/": Endpoints.get_Batch_exports_test_retrieve;
    "/api/environments/{project_id}/conversations/": Endpoints.get_Conversations_list;
    "/api/environments/{project_id}/conversations/{conversation}/": Endpoints.get_Conversations_retrieve;
    "/api/environments/{project_id}/conversations/{conversation}/queue/": Endpoints.get_Conversations_queue_retrieve;
    "/api/environments/{project_id}/customer_profile_configs/": Endpoints.get_Customer_profile_configs_list;
    "/api/environments/{project_id}/customer_profile_configs/{id}/": Endpoints.get_Customer_profile_configs_retrieve;
    "/api/environments/{project_id}/dashboards/": Endpoints.get_Dashboards_list;
    "/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/": Endpoints.get_Dashboards_collaborators_list;
    "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/": Endpoints.get_Dashboards_sharing_list;
    "/api/environments/{project_id}/dashboards/{id}/": Endpoints.get_Dashboards_retrieve;
    "/api/environments/{project_id}/dashboards/{id}/stream_tiles/": Endpoints.get_Dashboards_stream_tiles_retrieve;
    "/api/environments/{project_id}/data_color_themes/": Endpoints.get_Data_color_themes_list;
    "/api/environments/{project_id}/data_color_themes/{id}/": Endpoints.get_Data_color_themes_retrieve;
    "/api/environments/{project_id}/dataset_items/": Endpoints.get_Dataset_items_list;
    "/api/environments/{project_id}/dataset_items/{id}/": Endpoints.get_Dataset_items_retrieve;
    "/api/environments/{project_id}/datasets/": Endpoints.get_Datasets_list;
    "/api/environments/{project_id}/datasets/{id}/": Endpoints.get_Datasets_retrieve;
    "/api/environments/{project_id}/desktop_recordings/": Endpoints.get_Desktop_recordings_list;
    "/api/environments/{project_id}/desktop_recordings/{id}/": Endpoints.get_Desktop_recordings_retrieve;
    "/api/environments/{project_id}/endpoints/": Endpoints.get_Endpoints_retrieve;
    "/api/environments/{project_id}/endpoints/{name}/": Endpoints.get_Endpoints_retrieve_2;
    "/api/environments/{project_id}/endpoints/{name}/materialization_status/": Endpoints.get_Endpoints_materialization_status_retrieve;
    "/api/environments/{project_id}/endpoints/{name}/openapi.json/": Endpoints.get_Endpoints_openapi_json_retrieve;
    "/api/environments/{project_id}/endpoints/{name}/run/": Endpoints.get_Endpoints_run_retrieve;
    "/api/environments/{project_id}/endpoints/{name}/versions/": Endpoints.get_Endpoints_versions_retrieve;
    "/api/environments/{project_id}/error_tracking/assignment_rules/": Endpoints.get_Error_tracking_assignment_rules_list;
    "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/": Endpoints.get_Error_tracking_assignment_rules_retrieve;
    "/api/environments/{project_id}/error_tracking/autocapture_controls/": Endpoints.get_Error_tracking_autocapture_controls_list;
    "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/": Endpoints.get_Error_tracking_autocapture_controls_retrieve;
    "/api/environments/{project_id}/error_tracking/fingerprints/": Endpoints.get_Error_tracking_fingerprints_list;
    "/api/environments/{project_id}/error_tracking/fingerprints/{id}/": Endpoints.get_Error_tracking_fingerprints_retrieve;
    "/api/environments/{project_id}/error_tracking/git-provider-file-links/resolve_github/": Endpoints.get_Error_tracking_git_provider_file_links_resolve_github_retrieve;
    "/api/environments/{project_id}/error_tracking/git-provider-file-links/resolve_gitlab/": Endpoints.get_Error_tracking_git_provider_file_links_resolve_gitlab_retrieve;
    "/api/environments/{project_id}/error_tracking/grouping_rules/": Endpoints.get_Error_tracking_grouping_rules_list;
    "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/": Endpoints.get_Error_tracking_grouping_rules_retrieve;
    "/api/environments/{project_id}/error_tracking/releases/": Endpoints.get_Error_tracking_releases_list;
    "/api/environments/{project_id}/error_tracking/releases/{id}/": Endpoints.get_Error_tracking_releases_retrieve;
    "/api/environments/{project_id}/error_tracking/releases/hash/{hash_id}/": Endpoints.get_Error_tracking_releases_hash_retrieve;
    "/api/environments/{project_id}/error_tracking/suppression_rules/": Endpoints.get_Error_tracking_suppression_rules_list;
    "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/": Endpoints.get_Error_tracking_suppression_rules_retrieve;
    "/api/environments/{project_id}/error_tracking/symbol_sets/": Endpoints.get_Error_tracking_symbol_sets_list;
    "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.get_Error_tracking_symbol_sets_retrieve;
    "/api/environments/{project_id}/evaluations/": Endpoints.get_Evaluations_list;
    "/api/environments/{project_id}/evaluations/{id}/": Endpoints.get_Evaluations_retrieve;
    "/api/environments/{project_id}/events/": Endpoints.get_Events_list;
    "/api/environments/{project_id}/events/{id}/": Endpoints.get_Events_retrieve;
    "/api/environments/{project_id}/events/values/": Endpoints.get_Events_values_retrieve;
    "/api/environments/{project_id}/exports/": Endpoints.get_Exports_list;
    "/api/environments/{project_id}/exports/{id}/": Endpoints.get_Exports_retrieve;
    "/api/environments/{project_id}/exports/{id}/content/": Endpoints.get_Exports_content_retrieve;
    "/api/environments/{project_id}/external_data_sources/": Endpoints.get_External_data_sources_list;
    "/api/environments/{project_id}/external_data_sources/{id}/": Endpoints.get_External_data_sources_retrieve;
    "/api/environments/{project_id}/external_data_sources/{id}/jobs/": Endpoints.get_External_data_sources_jobs_retrieve;
    "/api/environments/{project_id}/external_data_sources/wizard/": Endpoints.get_External_data_sources_wizard_retrieve;
    "/api/environments/{project_id}/file_system/": Endpoints.get_File_system_list;
    "/api/environments/{project_id}/file_system/{id}/": Endpoints.get_File_system_retrieve;
    "/api/environments/{project_id}/file_system/log_view/": Endpoints.get_File_system_log_view_retrieve;
    "/api/environments/{project_id}/file_system/unfiled/": Endpoints.get_File_system_unfiled_retrieve;
    "/api/environments/{project_id}/file_system_shortcut/": Endpoints.get_File_system_shortcut_list;
    "/api/environments/{project_id}/file_system_shortcut/{id}/": Endpoints.get_File_system_shortcut_retrieve;
    "/api/environments/{project_id}/groups/": Endpoints.get_Groups_list;
    "/api/environments/{project_id}/groups/activity/": Endpoints.get_Groups_activity_retrieve;
    "/api/environments/{project_id}/groups/find/": Endpoints.get_Groups_find_retrieve;
    "/api/environments/{project_id}/groups/property_definitions/": Endpoints.get_Groups_property_definitions_retrieve;
    "/api/environments/{project_id}/groups/property_values/": Endpoints.get_Groups_property_values_retrieve;
    "/api/environments/{project_id}/groups/related/": Endpoints.get_Groups_related_retrieve;
    "/api/environments/{project_id}/hog_functions/": Endpoints.get_Hog_functions_list;
    "/api/environments/{project_id}/hog_functions/{id}/": Endpoints.get_Hog_functions_retrieve;
    "/api/environments/{project_id}/hog_functions/{id}/logs/": Endpoints.get_Hog_functions_logs_retrieve;
    "/api/environments/{project_id}/hog_functions/{id}/metrics/": Endpoints.get_Hog_functions_metrics_retrieve;
    "/api/environments/{project_id}/hog_functions/{id}/metrics/totals/": Endpoints.get_Hog_functions_metrics_totals_retrieve;
    "/api/environments/{project_id}/hog_functions/icon/": Endpoints.get_Hog_functions_icon_retrieve;
    "/api/environments/{project_id}/hog_functions/icons/": Endpoints.get_Hog_functions_icons_retrieve;
    "/api/environments/{project_id}/insight_variables/": Endpoints.get_Insight_variables_list;
    "/api/environments/{project_id}/insight_variables/{id}/": Endpoints.get_Insight_variables_retrieve;
    "/api/environments/{project_id}/insights/": Endpoints.get_Insights_list;
    "/api/environments/{project_id}/insights/{insight_id}/sharing/": Endpoints.get_Insights_sharing_list;
    "/api/environments/{project_id}/insights/{insight_id}/thresholds/": Endpoints.get_Insights_thresholds_list;
    "/api/environments/{project_id}/insights/{insight_id}/thresholds/{id}/": Endpoints.get_Insights_thresholds_retrieve;
    "/api/environments/{project_id}/insights/{id}/": Endpoints.get_Insights_retrieve;
    "/api/environments/{project_id}/insights/{id}/activity/": Endpoints.get_Insights_activity_retrieve_2;
    "/api/environments/{project_id}/insights/{id}/analyze/": Endpoints.get_Insights_analyze_retrieve;
    "/api/environments/{project_id}/insights/{id}/suggestions/": Endpoints.get_Insights_suggestions_retrieve;
    "/api/environments/{project_id}/insights/activity/": Endpoints.get_Insights_activity_retrieve;
    "/api/environments/{project_id}/insights/my_last_viewed/": Endpoints.get_Insights_my_last_viewed_retrieve;
    "/api/environments/{project_id}/integrations/": Endpoints.get_Integrations_list;
    "/api/environments/{project_id}/integrations/{id}/": Endpoints.get_Integrations_retrieve;
    "/api/environments/{project_id}/integrations/{id}/channels/": Endpoints.get_Integrations_channels_retrieve;
    "/api/environments/{project_id}/integrations/{id}/clickup_lists/": Endpoints.get_Integrations_clickup_lists_retrieve;
    "/api/environments/{project_id}/integrations/{id}/clickup_spaces/": Endpoints.get_Integrations_clickup_spaces_retrieve;
    "/api/environments/{project_id}/integrations/{id}/clickup_workspaces/": Endpoints.get_Integrations_clickup_workspaces_retrieve;
    "/api/environments/{project_id}/integrations/{id}/github_repos/": Endpoints.get_Integrations_github_repos_retrieve;
    "/api/environments/{project_id}/integrations/{id}/google_accessible_accounts/": Endpoints.get_Integrations_google_accessible_accounts_retrieve;
    "/api/environments/{project_id}/integrations/{id}/google_conversion_actions/": Endpoints.get_Integrations_google_conversion_actions_retrieve;
    "/api/environments/{project_id}/integrations/{id}/jira_projects/": Endpoints.get_Integrations_jira_retrieve;
    "/api/environments/{project_id}/integrations/{id}/linear_teams/": Endpoints.get_Integrations_linear_teams_retrieve;
    "/api/environments/{project_id}/integrations/{id}/linkedin_ads_accounts/": Endpoints.get_Integrations_linkedin_ads_accounts_retrieve;
    "/api/environments/{project_id}/integrations/{id}/linkedin_ads_conversion_rules/": Endpoints.get_Integrations_linkedin_ads_conversion_rules_retrieve;
    "/api/environments/{project_id}/integrations/{id}/twilio_phone_numbers/": Endpoints.get_Integrations_twilio_phone_numbers_retrieve;
    "/api/environments/{project_id}/integrations/authorize/": Endpoints.get_Integrations_authorize_retrieve;
    "/api/environments/{project_id}/llm_analytics/evaluation_config/": Endpoints.get_Llm_analytics_evaluation_config_retrieve;
    "/api/environments/{project_id}/llm_analytics/models/": Endpoints.get_Llm_analytics_models_retrieve;
    "/api/environments/{project_id}/llm_analytics/provider_keys/": Endpoints.get_Llm_analytics_provider_keys_list;
    "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/": Endpoints.get_Llm_analytics_provider_keys_retrieve;
    "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/dependent_configs/": Endpoints.get_Llm_analytics_provider_keys_dependent_configs_retrieve;
    "/api/environments/{project_id}/llm_prompts/": Endpoints.get_Llm_prompts_list;
    "/api/environments/{project_id}/llm_prompts/{id}/": Endpoints.get_Llm_prompts_retrieve;
    "/api/environments/{project_id}/llm_prompts/name/{prompt_name}/": Endpoints.get_Llm_prompts_name_retrieve;
    "/api/environments/{project_id}/logs/attributes/": Endpoints.get_Logs_attributes_retrieve;
    "/api/environments/{project_id}/logs/has_logs/": Endpoints.get_Logs_has_logs_retrieve;
    "/api/environments/{project_id}/logs/values/": Endpoints.get_Logs_values_retrieve;
    "/api/environments/{project_id}/persisted_folder/": Endpoints.get_Persisted_folder_list;
    "/api/environments/{project_id}/persisted_folder/{id}/": Endpoints.get_Persisted_folder_retrieve;
    "/api/environments/{project_id}/persons/": Endpoints.get_Persons_list;
    "/api/environments/{project_id}/persons/{id}/": Endpoints.get_Persons_retrieve;
    "/api/environments/{project_id}/persons/{id}/activity/": Endpoints.get_Persons_activity_retrieve_2;
    "/api/environments/{project_id}/persons/{id}/properties_timeline/": Endpoints.get_Persons_properties_timeline_retrieve;
    "/api/environments/{project_id}/persons/activity/": Endpoints.get_Persons_activity_retrieve;
    "/api/environments/{project_id}/persons/cohorts/": Endpoints.get_Persons_cohorts_retrieve;
    "/api/environments/{project_id}/persons/funnel/": Endpoints.get_Persons_funnel_retrieve;
    "/api/environments/{project_id}/persons/funnel/correlation/": Endpoints.get_Persons_funnel_correlation_retrieve;
    "/api/environments/{project_id}/persons/lifecycle/": Endpoints.get_Persons_lifecycle_retrieve;
    "/api/environments/{project_id}/persons/stickiness/": Endpoints.get_Persons_stickiness_retrieve;
    "/api/environments/{project_id}/persons/trends/": Endpoints.get_Persons_trends_retrieve;
    "/api/environments/{project_id}/persons/values/": Endpoints.get_Persons_values_retrieve;
    "/api/environments/{project_id}/plugin_configs/{plugin_config_id}/logs/": Endpoints.get_Plugin_configs_logs_list;
    "/api/environments/{project_id}/query/{id}/": Endpoints.get_Query_retrieve;
    "/api/environments/{project_id}/query/{id}/log/": Endpoints.get_Query_log_retrieve;
    "/api/environments/{project_id}/query/draft_sql/": Endpoints.get_Query_draft_sql_retrieve;
    "/api/environments/{project_id}/session_recording_playlists/": Endpoints.get_Session_recording_playlists_list;
    "/api/environments/{project_id}/session_recording_playlists/{short_id}/": Endpoints.get_Session_recording_playlists_retrieve;
    "/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/": Endpoints.get_Session_recording_playlists_recordings_retrieve;
    "/api/environments/{project_id}/session_recordings/": Endpoints.get_Session_recordings_list;
    "/api/environments/{project_id}/session_recordings/{id}/": Endpoints.get_Session_recordings_retrieve;
    "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/": Endpoints.get_Session_recordings_sharing_list;
    "/api/environments/{project_id}/sessions/property_definitions/": Endpoints.get_Sessions_property_definitions_retrieve;
    "/api/environments/{project_id}/sessions/values/": Endpoints.get_Sessions_values_retrieve;
    "/api/environments/{project_id}/subscriptions/": Endpoints.get_Subscriptions_list;
    "/api/environments/{project_id}/subscriptions/{id}/": Endpoints.get_Subscriptions_retrieve;
    "/api/environments/{project_id}/user_interviews/": Endpoints.get_User_interviews_list;
    "/api/environments/{project_id}/user_interviews/{id}/": Endpoints.get_User_interviews_retrieve;
    "/api/environments/{project_id}/warehouse_saved_queries/": Endpoints.get_Warehouse_saved_queries_list;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/": Endpoints.get_Warehouse_saved_queries_retrieve;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/activity/": Endpoints.get_Warehouse_saved_queries_activity_retrieve;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/dependencies/": Endpoints.get_Warehouse_saved_queries_dependencies_retrieve;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/run_history/": Endpoints.get_Warehouse_saved_queries_run_history_retrieve;
    "/api/environments/{project_id}/warehouse_tables/": Endpoints.get_Warehouse_tables_list;
    "/api/environments/{project_id}/warehouse_tables/{id}/": Endpoints.get_Warehouse_tables_retrieve;
    "/api/environments/{project_id}/web_vitals/": Endpoints.get_Web_vitals_retrieve;
    "/api/organizations/": Endpoints.get_List;
    "/api/organizations/{id}/": Endpoints.get_Retrieve;
    "/api/organizations/{organization_id}/batch_exports/": Endpoints.get_Batch_exports_list_2;
    "/api/organizations/{organization_id}/batch_exports/{id}/": Endpoints.get_Batch_exports_retrieve_2;
    "/api/organizations/{organization_id}/batch_exports/{id}/logs/": Endpoints.get_Batch_exports_logs_retrieve_2;
    "/api/organizations/{organization_id}/batch_exports/test/": Endpoints.get_Batch_exports_test_retrieve_2;
    "/api/organizations/{organization_id}/domains/": Endpoints.get_Domains_list;
    "/api/organizations/{organization_id}/domains/{id}/": Endpoints.get_Domains_retrieve;
    "/api/organizations/{organization_id}/integrations/": Endpoints.get_Integrations_list_2;
    "/api/organizations/{organization_id}/integrations/{id}/": Endpoints.get_Integrations_retrieve_2;
    "/api/organizations/{organization_id}/invites/": Endpoints.get_Invites_list;
    "/api/organizations/{organization_id}/members/": Endpoints.get_Members_list;
    "/api/organizations/{organization_id}/members/{user__uuid}/scoped_api_keys/": Endpoints.get_Members_scoped_api_keys_retrieve;
    "/api/organizations/{organization_id}/projects/": Endpoints.get_List_2;
    "/api/organizations/{organization_id}/projects/{id}/": Endpoints.get_Retrieve_2;
    "/api/organizations/{organization_id}/projects/{id}/activity/": Endpoints.get_Activity_retrieve;
    "/api/organizations/{organization_id}/projects/{id}/is_generating_demo_data/": Endpoints.get_Is_generating_demo_data_retrieve;
    "/api/organizations/{organization_id}/proxy_records/": Endpoints.get_Proxy_records_list;
    "/api/organizations/{organization_id}/proxy_records/{id}/": Endpoints.get_Proxy_records_retrieve;
    "/api/organizations/{organization_id}/roles/": Endpoints.get_Roles_list;
    "/api/organizations/{organization_id}/roles/{id}/": Endpoints.get_Roles_retrieve;
    "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/": Endpoints.get_Roles_role_memberships_list;
    "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/{id}/": Endpoints.get_Roles_role_memberships_retrieve;
    "/api/projects/{project_id}/actions/": Endpoints.get_Actions_list;
    "/api/projects/{project_id}/actions/{id}/": Endpoints.get_Actions_retrieve;
    "/api/projects/{project_id}/activity_log/": Endpoints.get_Activity_log_list;
    "/api/projects/{project_id}/advanced_activity_logs/": Endpoints.get_Advanced_activity_logs_list;
    "/api/projects/{project_id}/advanced_activity_logs/available_filters/": Endpoints.get_Advanced_activity_logs_available_filters_retrieve;
    "/api/projects/{project_id}/alerts/": Endpoints.get_Alerts_list_2;
    "/api/projects/{project_id}/alerts/{id}/": Endpoints.get_Alerts_retrieve_2;
    "/api/projects/{project_id}/annotations/": Endpoints.get_Annotations_list;
    "/api/projects/{project_id}/annotations/{id}/": Endpoints.get_Annotations_retrieve;
    "/api/projects/{project_id}/app_metrics/{id}/": Endpoints.get_App_metrics_retrieve_2;
    "/api/projects/{project_id}/app_metrics/{id}/error_details/": Endpoints.get_App_metrics_error_details_retrieve_2;
    "/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/": Endpoints.get_App_metrics_historical_exports_retrieve_3;
    "/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/": Endpoints.get_App_metrics_historical_exports_retrieve_4;
    "/api/projects/{project_id}/batch_exports/": Endpoints.get_Batch_exports_list_3;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/": Endpoints.get_Batch_exports_backfills_list_2;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/": Endpoints.get_Batch_exports_backfills_retrieve_2;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/": Endpoints.get_Batch_exports_runs_list_2;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/": Endpoints.get_Batch_exports_runs_retrieve_2;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/": Endpoints.get_Batch_exports_runs_logs_retrieve_2;
    "/api/projects/{project_id}/batch_exports/{id}/": Endpoints.get_Batch_exports_retrieve_3;
    "/api/projects/{project_id}/batch_exports/{id}/logs/": Endpoints.get_Batch_exports_logs_retrieve_3;
    "/api/projects/{project_id}/batch_exports/test/": Endpoints.get_Batch_exports_test_retrieve_3;
    "/api/projects/{project_id}/cohorts/": Endpoints.get_Cohorts_list;
    "/api/projects/{project_id}/cohorts/{id}/": Endpoints.get_Cohorts_retrieve;
    "/api/projects/{project_id}/cohorts/{id}/activity/": Endpoints.get_Cohorts_activity_retrieve_2;
    "/api/projects/{project_id}/cohorts/{id}/calculation_history/": Endpoints.get_Cohorts_calculation_history_retrieve;
    "/api/projects/{project_id}/cohorts/{id}/persons/": Endpoints.get_Cohorts_persons_retrieve;
    "/api/projects/{project_id}/cohorts/activity/": Endpoints.get_Cohorts_activity_retrieve;
    "/api/projects/{project_id}/conversations/tickets/": Endpoints.get_Conversations_tickets_list;
    "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.get_Conversations_tickets_retrieve;
    "/api/projects/{project_id}/conversations/tickets/unread_count/": Endpoints.get_Conversations_tickets_unread_count_retrieve;
    "/api/projects/{project_id}/dashboard_templates/": Endpoints.get_Dashboard_templates_list;
    "/api/projects/{project_id}/dashboard_templates/{id}/": Endpoints.get_Dashboard_templates_retrieve;
    "/api/projects/{project_id}/dashboard_templates/json_schema/": Endpoints.get_Dashboard_templates_json_schema_retrieve;
    "/api/projects/{project_id}/dashboards/": Endpoints.get_Dashboards_list_2;
    "/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/": Endpoints.get_Dashboards_collaborators_list_2;
    "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/": Endpoints.get_Dashboards_sharing_list_2;
    "/api/projects/{project_id}/dashboards/{id}/": Endpoints.get_Dashboards_retrieve_2;
    "/api/projects/{project_id}/dashboards/{id}/stream_tiles/": Endpoints.get_Dashboards_stream_tiles_retrieve_2;
    "/api/projects/{project_id}/data_color_themes/": Endpoints.get_Data_color_themes_list_2;
    "/api/projects/{project_id}/data_color_themes/{id}/": Endpoints.get_Data_color_themes_retrieve_2;
    "/api/projects/{project_id}/dataset_items/": Endpoints.get_Dataset_items_list_2;
    "/api/projects/{project_id}/dataset_items/{id}/": Endpoints.get_Dataset_items_retrieve_2;
    "/api/projects/{project_id}/datasets/": Endpoints.get_Datasets_list_2;
    "/api/projects/{project_id}/datasets/{id}/": Endpoints.get_Datasets_retrieve_2;
    "/api/projects/{project_id}/early_access_feature/": Endpoints.get_Early_access_feature_list;
    "/api/projects/{project_id}/early_access_feature/{id}/": Endpoints.get_Early_access_feature_retrieve;
    "/api/projects/{project_id}/endpoints/": Endpoints.get_Endpoints_retrieve_3;
    "/api/projects/{project_id}/endpoints/{name}/": Endpoints.get_Endpoints_retrieve_4;
    "/api/projects/{project_id}/endpoints/{name}/materialization_status/": Endpoints.get_Endpoints_materialization_status_retrieve_2;
    "/api/projects/{project_id}/endpoints/{name}/openapi.json/": Endpoints.get_Endpoints_openapi_json_retrieve_2;
    "/api/projects/{project_id}/endpoints/{name}/run/": Endpoints.get_Endpoints_run_retrieve_2;
    "/api/projects/{project_id}/endpoints/{name}/versions/": Endpoints.get_Endpoints_versions_retrieve_2;
    "/api/projects/{project_id}/environments/": Endpoints.get_List_3;
    "/api/projects/{project_id}/environments/{id}/": Endpoints.get_Retrieve_3;
    "/api/projects/{project_id}/environments/{id}/activity/": Endpoints.get_Activity_retrieve_2;
    "/api/projects/{project_id}/environments/{id}/default_evaluation_tags/": Endpoints.get_Default_evaluation_tags_retrieve;
    "/api/projects/{project_id}/environments/{id}/event_ingestion_restrictions/": Endpoints.get_Event_ingestion_restrictions_retrieve;
    "/api/projects/{project_id}/environments/{id}/is_generating_demo_data/": Endpoints.get_Is_generating_demo_data_retrieve_2;
    "/api/projects/{project_id}/environments/{id}/settings_as_of/": Endpoints.get_Settings_as_of_retrieve;
    "/api/projects/{project_id}/error_tracking/releases/": Endpoints.get_Error_tracking_releases_list_2;
    "/api/projects/{project_id}/error_tracking/releases/{id}/": Endpoints.get_Error_tracking_releases_retrieve_2;
    "/api/projects/{project_id}/error_tracking/releases/hash/{hash_id}/": Endpoints.get_Error_tracking_releases_hash_retrieve_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/": Endpoints.get_Error_tracking_symbol_sets_list_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.get_Error_tracking_symbol_sets_retrieve_2;
    "/api/projects/{project_id}/event_definitions/": Endpoints.get_Event_definitions_list;
    "/api/projects/{project_id}/event_definitions/{id}/": Endpoints.get_Event_definitions_retrieve;
    "/api/projects/{project_id}/event_definitions/{id}/metrics/": Endpoints.get_Event_definitions_metrics_retrieve;
    "/api/projects/{project_id}/event_definitions/by_name/": Endpoints.get_Event_definitions_by_name_retrieve;
    "/api/projects/{project_id}/event_definitions/golang/": Endpoints.get_Event_definitions_golang_retrieve;
    "/api/projects/{project_id}/event_definitions/python/": Endpoints.get_Event_definitions_python_retrieve;
    "/api/projects/{project_id}/event_definitions/typescript/": Endpoints.get_Event_definitions_typescript_retrieve;
    "/api/projects/{project_id}/events/": Endpoints.get_Events_list_2;
    "/api/projects/{project_id}/events/{id}/": Endpoints.get_Events_retrieve_2;
    "/api/projects/{project_id}/events/values/": Endpoints.get_Events_values_retrieve_2;
    "/api/projects/{project_id}/experiment_holdouts/": Endpoints.get_Experiment_holdouts_list;
    "/api/projects/{project_id}/experiment_holdouts/{id}/": Endpoints.get_Experiment_holdouts_retrieve;
    "/api/projects/{project_id}/experiment_saved_metrics/": Endpoints.get_Experiment_saved_metrics_list;
    "/api/projects/{project_id}/experiment_saved_metrics/{id}/": Endpoints.get_Experiment_saved_metrics_retrieve;
    "/api/projects/{project_id}/experiments/": Endpoints.get_Experiments_list;
    "/api/projects/{project_id}/experiments/{id}/": Endpoints.get_Experiments_retrieve;
    "/api/projects/{project_id}/experiments/{id}/timeseries_results/": Endpoints.get_Experiments_timeseries_results_retrieve;
    "/api/projects/{project_id}/experiments/eligible_feature_flags/": Endpoints.get_Experiments_eligible_feature_flags_retrieve;
    "/api/projects/{project_id}/experiments/requires_flag_implementation/": Endpoints.get_Experiments_requires_flag_implementation_retrieve;
    "/api/projects/{project_id}/experiments/stats/": Endpoints.get_Experiments_stats_retrieve;
    "/api/projects/{project_id}/exports/": Endpoints.get_Exports_list_2;
    "/api/projects/{project_id}/exports/{id}/": Endpoints.get_Exports_retrieve_2;
    "/api/projects/{project_id}/exports/{id}/content/": Endpoints.get_Exports_content_retrieve_2;
    "/api/projects/{project_id}/external_data_sources/": Endpoints.get_External_data_sources_list_2;
    "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.get_External_data_sources_retrieve_2;
    "/api/projects/{project_id}/external_data_sources/{id}/jobs/": Endpoints.get_External_data_sources_jobs_retrieve_2;
    "/api/projects/{project_id}/external_data_sources/wizard/": Endpoints.get_External_data_sources_wizard_retrieve_2;
    "/api/projects/{project_id}/feature_flags/": Endpoints.get_Feature_flags_list;
    "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.get_Feature_flags_retrieve;
    "/api/projects/{project_id}/feature_flags/{id}/activity/": Endpoints.get_Feature_flags_activity_retrieve_2;
    "/api/projects/{project_id}/feature_flags/{id}/dependent_flags/": Endpoints.get_Feature_flags_dependent_flags_retrieve;
    "/api/projects/{project_id}/feature_flags/{id}/remote_config/": Endpoints.get_Feature_flags_remote_config_retrieve;
    "/api/projects/{project_id}/feature_flags/{id}/status/": Endpoints.get_Feature_flags_status_retrieve;
    "/api/projects/{project_id}/feature_flags/activity/": Endpoints.get_Feature_flags_activity_retrieve;
    "/api/projects/{project_id}/feature_flags/evaluation_reasons/": Endpoints.get_Feature_flags_evaluation_reasons_retrieve;
    "/api/projects/{project_id}/feature_flags/local_evaluation/": Endpoints.get_Feature_flags_local_evaluation_retrieve;
    "/api/projects/{project_id}/feature_flags/my_flags/": Endpoints.get_Feature_flags_my_flags_retrieve;
    "/api/projects/{project_id}/file_system/": Endpoints.get_File_system_list_2;
    "/api/projects/{project_id}/file_system/{id}/": Endpoints.get_File_system_retrieve_2;
    "/api/projects/{project_id}/file_system/log_view/": Endpoints.get_File_system_log_view_retrieve_2;
    "/api/projects/{project_id}/file_system/unfiled/": Endpoints.get_File_system_unfiled_retrieve_2;
    "/api/projects/{project_id}/file_system_shortcut/": Endpoints.get_File_system_shortcut_list_2;
    "/api/projects/{project_id}/file_system_shortcut/{id}/": Endpoints.get_File_system_shortcut_retrieve_2;
    "/api/projects/{project_id}/flag_value/values/": Endpoints.get_Flag_value_values_retrieve;
    "/api/projects/{project_id}/groups/": Endpoints.get_Groups_list_2;
    "/api/projects/{project_id}/groups/activity/": Endpoints.get_Groups_activity_retrieve_2;
    "/api/projects/{project_id}/groups/find/": Endpoints.get_Groups_find_retrieve_2;
    "/api/projects/{project_id}/groups/property_definitions/": Endpoints.get_Groups_property_definitions_retrieve_2;
    "/api/projects/{project_id}/groups/property_values/": Endpoints.get_Groups_property_values_retrieve_2;
    "/api/projects/{project_id}/groups/related/": Endpoints.get_Groups_related_retrieve_2;
    "/api/projects/{project_id}/groups_types/": Endpoints.get_Groups_types_list;
    "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/": Endpoints.get_Groups_types_metrics_list;
    "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/": Endpoints.get_Groups_types_metrics_retrieve;
    "/api/projects/{project_id}/hog_functions/": Endpoints.get_Hog_functions_list_2;
    "/api/projects/{project_id}/hog_functions/{id}/": Endpoints.get_Hog_functions_retrieve_2;
    "/api/projects/{project_id}/hog_functions/{id}/logs/": Endpoints.get_Hog_functions_logs_retrieve_2;
    "/api/projects/{project_id}/hog_functions/{id}/metrics/": Endpoints.get_Hog_functions_metrics_retrieve_2;
    "/api/projects/{project_id}/hog_functions/{id}/metrics/totals/": Endpoints.get_Hog_functions_metrics_totals_retrieve_2;
    "/api/projects/{project_id}/hog_functions/icon/": Endpoints.get_Hog_functions_icon_retrieve_2;
    "/api/projects/{project_id}/hog_functions/icons/": Endpoints.get_Hog_functions_icons_retrieve_2;
    "/api/projects/{project_id}/insight_variables/": Endpoints.get_Insight_variables_list_2;
    "/api/projects/{project_id}/insight_variables/{id}/": Endpoints.get_Insight_variables_retrieve_2;
    "/api/projects/{project_id}/insights/": Endpoints.get_Insights_list_2;
    "/api/projects/{project_id}/insights/{insight_id}/sharing/": Endpoints.get_Insights_sharing_list_2;
    "/api/projects/{project_id}/insights/{insight_id}/thresholds/": Endpoints.get_Insights_thresholds_list_2;
    "/api/projects/{project_id}/insights/{insight_id}/thresholds/{id}/": Endpoints.get_Insights_thresholds_retrieve_2;
    "/api/projects/{project_id}/insights/{id}/": Endpoints.get_Insights_retrieve_2;
    "/api/projects/{project_id}/insights/{id}/activity/": Endpoints.get_Insights_activity_retrieve_4;
    "/api/projects/{project_id}/insights/{id}/analyze/": Endpoints.get_Insights_analyze_retrieve_2;
    "/api/projects/{project_id}/insights/{id}/suggestions/": Endpoints.get_Insights_suggestions_retrieve_2;
    "/api/projects/{project_id}/insights/activity/": Endpoints.get_Insights_activity_retrieve_3;
    "/api/projects/{project_id}/insights/my_last_viewed/": Endpoints.get_Insights_my_last_viewed_retrieve_2;
    "/api/projects/{project_id}/integrations/": Endpoints.get_Integrations_list_3;
    "/api/projects/{project_id}/integrations/{id}/": Endpoints.get_Integrations_retrieve_3;
    "/api/projects/{project_id}/integrations/{id}/channels/": Endpoints.get_Integrations_channels_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/clickup_lists/": Endpoints.get_Integrations_clickup_lists_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/clickup_spaces/": Endpoints.get_Integrations_clickup_spaces_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/clickup_workspaces/": Endpoints.get_Integrations_clickup_workspaces_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/github_repos/": Endpoints.get_Integrations_github_repos_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/google_accessible_accounts/": Endpoints.get_Integrations_google_accessible_accounts_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/google_conversion_actions/": Endpoints.get_Integrations_google_conversion_actions_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/jira_projects/": Endpoints.get_Integrations_jira_projects_retrieve;
    "/api/projects/{project_id}/integrations/{id}/linear_teams/": Endpoints.get_Integrations_linear_teams_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/linkedin_ads_accounts/": Endpoints.get_Integrations_linkedin_ads_accounts_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/linkedin_ads_conversion_rules/": Endpoints.get_Integrations_linkedin_ads_conversion_rules_retrieve_2;
    "/api/projects/{project_id}/integrations/{id}/twilio_phone_numbers/": Endpoints.get_Integrations_twilio_phone_numbers_retrieve_2;
    "/api/projects/{project_id}/integrations/authorize/": Endpoints.get_Integrations_authorize_retrieve_2;
    "/api/projects/{project_id}/live_debugger_breakpoints/": Endpoints.get_Live_debugger_breakpoints_list;
    "/api/projects/{project_id}/live_debugger_breakpoints/{id}/": Endpoints.get_Live_debugger_breakpoints_retrieve;
    "/api/projects/{project_id}/live_debugger_breakpoints/active/": Endpoints.get_Live_debugger_breakpoints_active_retrieve;
    "/api/projects/{project_id}/live_debugger_breakpoints/breakpoint_hits/": Endpoints.get_Live_debugger_breakpoints_breakpoint_hits_retrieve;
    "/api/projects/{project_id}/logs/attributes/": Endpoints.get_Logs_attributes_retrieve_2;
    "/api/projects/{project_id}/logs/has_logs/": Endpoints.get_Logs_has_logs_retrieve_2;
    "/api/projects/{project_id}/logs/values/": Endpoints.get_Logs_values_retrieve_2;
    "/api/projects/{project_id}/notebooks/": Endpoints.get_Notebooks_list;
    "/api/projects/{project_id}/notebooks/{short_id}/": Endpoints.get_Notebooks_retrieve;
    "/api/projects/{project_id}/notebooks/{short_id}/activity/": Endpoints.get_Notebooks_activity_retrieve_2;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/dataframe/": Endpoints.get_Notebooks_kernel_dataframe_retrieve;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/status/": Endpoints.get_Notebooks_kernel_status_retrieve;
    "/api/projects/{project_id}/notebooks/activity/": Endpoints.get_Notebooks_activity_retrieve;
    "/api/projects/{project_id}/notebooks/recording_comments/": Endpoints.get_Notebooks_recording_comments_retrieve;
    "/api/projects/{project_id}/persisted_folder/": Endpoints.get_Persisted_folder_list_2;
    "/api/projects/{project_id}/persisted_folder/{id}/": Endpoints.get_Persisted_folder_retrieve_2;
    "/api/projects/{project_id}/persons/": Endpoints.get_Persons_list_2;
    "/api/projects/{project_id}/persons/{id}/": Endpoints.get_Persons_retrieve_2;
    "/api/projects/{project_id}/persons/{id}/activity/": Endpoints.get_Persons_activity_retrieve_4;
    "/api/projects/{project_id}/persons/{id}/properties_timeline/": Endpoints.get_Persons_properties_timeline_retrieve_2;
    "/api/projects/{project_id}/persons/activity/": Endpoints.get_Persons_activity_retrieve_3;
    "/api/projects/{project_id}/persons/cohorts/": Endpoints.get_Persons_cohorts_retrieve_2;
    "/api/projects/{project_id}/persons/funnel/": Endpoints.get_Persons_funnel_retrieve_2;
    "/api/projects/{project_id}/persons/funnel/correlation/": Endpoints.get_Persons_funnel_correlation_retrieve_2;
    "/api/projects/{project_id}/persons/lifecycle/": Endpoints.get_Persons_lifecycle_retrieve_2;
    "/api/projects/{project_id}/persons/stickiness/": Endpoints.get_Persons_stickiness_retrieve_2;
    "/api/projects/{project_id}/persons/trends/": Endpoints.get_Persons_trends_retrieve_2;
    "/api/projects/{project_id}/persons/values/": Endpoints.get_Persons_values_retrieve_2;
    "/api/projects/{project_id}/plugin_configs/{plugin_config_id}/logs/": Endpoints.get_Plugin_configs_logs_list_2;
    "/api/projects/{project_id}/product_tours/": Endpoints.get_Product_tours_list;
    "/api/projects/{project_id}/product_tours/{id}/": Endpoints.get_Product_tours_retrieve;
    "/api/projects/{project_id}/property_definitions/": Endpoints.get_Property_definitions_list;
    "/api/projects/{project_id}/property_definitions/{id}/": Endpoints.get_Property_definitions_retrieve;
    "/api/projects/{project_id}/property_definitions/seen_together/": Endpoints.get_Property_definitions_seen_together_retrieve;
    "/api/projects/{project_id}/query/{id}/": Endpoints.get_Query_retrieve_2;
    "/api/projects/{project_id}/query/{id}/log/": Endpoints.get_Query_log_retrieve_2;
    "/api/projects/{project_id}/query/draft_sql/": Endpoints.get_Query_draft_sql_retrieve_2;
    "/api/projects/{project_id}/session_group_summaries/": Endpoints.get_Session_group_summaries_list;
    "/api/projects/{project_id}/session_group_summaries/{id}/": Endpoints.get_Session_group_summaries_retrieve;
    "/api/projects/{project_id}/session_recording_playlists/": Endpoints.get_Session_recording_playlists_list_2;
    "/api/projects/{project_id}/session_recording_playlists/{short_id}/": Endpoints.get_Session_recording_playlists_retrieve_2;
    "/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/": Endpoints.get_Session_recording_playlists_recordings_retrieve_2;
    "/api/projects/{project_id}/session_recordings/": Endpoints.get_Session_recordings_list_2;
    "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.get_Session_recordings_retrieve_2;
    "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/": Endpoints.get_Session_recordings_sharing_list_2;
    "/api/projects/{project_id}/sessions/property_definitions/": Endpoints.get_Sessions_property_definitions_retrieve_2;
    "/api/projects/{project_id}/sessions/values/": Endpoints.get_Sessions_values_retrieve_2;
    "/api/projects/{project_id}/signal_reports/": Endpoints.get_Signal_reports_list;
    "/api/projects/{project_id}/signal_reports/{id}/": Endpoints.get_Signal_reports_retrieve;
    "/api/projects/{project_id}/signal_reports/{id}/artefacts/": Endpoints.get_Signal_reports_artefacts_retrieve;
    "/api/projects/{project_id}/subscriptions/": Endpoints.get_Subscriptions_list_2;
    "/api/projects/{project_id}/subscriptions/{id}/": Endpoints.get_Subscriptions_retrieve_2;
    "/api/projects/{project_id}/surveys/": Endpoints.get_Surveys_list;
    "/api/projects/{project_id}/surveys/{id}/": Endpoints.get_Surveys_retrieve;
    "/api/projects/{project_id}/surveys/{id}/activity/": Endpoints.get_Surveys_activity_retrieve_2;
    "/api/projects/{project_id}/surveys/{id}/archived-response-uuids/": Endpoints.get_Surveys_archived_response_uuids_retrieve;
    "/api/projects/{project_id}/surveys/{id}/stats/": Endpoints.get_Surveys_stats_retrieve_2;
    "/api/projects/{project_id}/surveys/activity/": Endpoints.get_Surveys_activity_retrieve;
    "/api/projects/{project_id}/surveys/responses_count/": Endpoints.get_Surveys_responses_count_retrieve;
    "/api/projects/{project_id}/surveys/stats/": Endpoints.get_Surveys_stats_retrieve;
    "/api/projects/{project_id}/tasks/": Endpoints.get_Tasks_list;
    "/api/projects/{project_id}/tasks/{id}/": Endpoints.get_Tasks_retrieve;
    "/api/projects/{project_id}/tasks/{task_id}/runs/": Endpoints.get_Tasks_runs_list;
    "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/": Endpoints.get_Tasks_runs_retrieve;
    "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/logs/": Endpoints.get_Tasks_runs_logs_retrieve;
    "/api/projects/{project_id}/warehouse_saved_queries/": Endpoints.get_Warehouse_saved_queries_list_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/": Endpoints.get_Warehouse_saved_queries_retrieve_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/activity/": Endpoints.get_Warehouse_saved_queries_activity_retrieve_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/dependencies/": Endpoints.get_Warehouse_saved_queries_dependencies_retrieve_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/run_history/": Endpoints.get_Warehouse_saved_queries_run_history_retrieve_2;
    "/api/projects/{project_id}/warehouse_tables/": Endpoints.get_Warehouse_tables_list_2;
    "/api/projects/{project_id}/warehouse_tables/{id}/": Endpoints.get_Warehouse_tables_retrieve_2;
    "/api/projects/{project_id}/web_analytics/breakdown/": Endpoints.get_Web_analytics_breakdown_retrieve;
    "/api/projects/{project_id}/web_analytics/overview/": Endpoints.get_Web_analytics_overview_retrieve;
    "/api/projects/{project_id}/web_experiments/": Endpoints.get_Web_experiments_list;
    "/api/projects/{project_id}/web_experiments/{id}/": Endpoints.get_Web_experiments_retrieve;
    "/api/user_home_settings/{uuid}/": Endpoints.get_User_home_settings_retrieve;
    "/api/users/": Endpoints.get_Users_list;
    "/api/users/{uuid}/": Endpoints.get_Users_retrieve;
    "/api/users/{uuid}/hedgehog_config/": Endpoints.get_Users_hedgehog_config_retrieve;
    "/api/users/{uuid}/start_2fa_setup/": Endpoints.get_Users_start_2fa_setup_retrieve;
    "/api/users/{uuid}/two_factor_start_setup/": Endpoints.get_Users_two_factor_start_setup_retrieve;
    "/api/users/{uuid}/two_factor_status/": Endpoints.get_Users_two_factor_status_retrieve;
  };
  post: {
    "/api/environments/{project_id}/alerts/": Endpoints.post_Alerts_create;
    "/api/environments/{project_id}/batch_exports/": Endpoints.post_Batch_exports_create;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/": Endpoints.post_Batch_exports_backfills_create;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/": Endpoints.post_Batch_exports_backfills_cancel_create;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/": Endpoints.post_Batch_exports_runs_cancel_create;
    "/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/": Endpoints.post_Batch_exports_runs_retry_create;
    "/api/environments/{project_id}/batch_exports/{id}/pause/": Endpoints.post_Batch_exports_pause_create;
    "/api/environments/{project_id}/batch_exports/{id}/run_test_step/": Endpoints.post_Batch_exports_run_test_step_create;
    "/api/environments/{project_id}/batch_exports/{id}/unpause/": Endpoints.post_Batch_exports_unpause_create;
    "/api/environments/{project_id}/batch_exports/run_test_step_new/": Endpoints.post_Batch_exports_run_test_step_new_create;
    "/api/environments/{project_id}/conversations/": Endpoints.post_Conversations_create;
    "/api/environments/{project_id}/conversations/{conversation}/append_message/": Endpoints.post_Conversations_append_message_create;
    "/api/environments/{project_id}/conversations/{conversation}/queue/": Endpoints.post_Conversations_queue_create;
    "/api/environments/{project_id}/conversations/{conversation}/queue/clear/": Endpoints.post_Conversations_queue_clear_create;
    "/api/environments/{project_id}/customer_profile_configs/": Endpoints.post_Customer_profile_configs_create;
    "/api/environments/{project_id}/dashboards/": Endpoints.post_Dashboards_create;
    "/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/": Endpoints.post_Dashboards_collaborators_create;
    "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/": Endpoints.post_Dashboards_sharing_passwords_create;
    "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/refresh/": Endpoints.post_Dashboards_sharing_refresh_create;
    "/api/environments/{project_id}/dashboards/create_from_template_json/": Endpoints.post_Dashboards_create_from_template_json_create;
    "/api/environments/{project_id}/dashboards/create_unlisted_dashboard/": Endpoints.post_Dashboards_create_unlisted_dashboard_create;
    "/api/environments/{project_id}/data_color_themes/": Endpoints.post_Data_color_themes_create;
    "/api/environments/{project_id}/dataset_items/": Endpoints.post_Dataset_items_create;
    "/api/environments/{project_id}/datasets/": Endpoints.post_Datasets_create;
    "/api/environments/{project_id}/desktop_recordings/": Endpoints.post_Desktop_recordings_create;
    "/api/environments/{project_id}/desktop_recordings/{id}/append_segments/": Endpoints.post_Desktop_recordings_append_segments_create;
    "/api/environments/{project_id}/endpoints/": Endpoints.post_Endpoints_create;
    "/api/environments/{project_id}/endpoints/{name}/run/": Endpoints.post_Endpoints_run_create;
    "/api/environments/{project_id}/endpoints/last_execution_times/": Endpoints.post_Endpoints_last_execution_times_create;
    "/api/environments/{project_id}/error_tracking/assignment_rules/": Endpoints.post_Error_tracking_assignment_rules_create;
    "/api/environments/{project_id}/error_tracking/autocapture_controls/": Endpoints.post_Error_tracking_autocapture_controls_create;
    "/api/environments/{project_id}/error_tracking/grouping_rules/": Endpoints.post_Error_tracking_grouping_rules_create;
    "/api/environments/{project_id}/error_tracking/releases/": Endpoints.post_Error_tracking_releases_create;
    "/api/environments/{project_id}/error_tracking/suppression_rules/": Endpoints.post_Error_tracking_suppression_rules_create;
    "/api/environments/{project_id}/error_tracking/symbol_sets/": Endpoints.post_Error_tracking_symbol_sets_create;
    "/api/environments/{project_id}/error_tracking/symbol_sets/bulk_finish_upload/": Endpoints.post_Error_tracking_symbol_sets_bulk_finish_upload_create;
    "/api/environments/{project_id}/error_tracking/symbol_sets/bulk_start_upload/": Endpoints.post_Error_tracking_symbol_sets_bulk_start_upload_create;
    "/api/environments/{project_id}/error_tracking/symbol_sets/start_upload/": Endpoints.post_Error_tracking_symbol_sets_start_upload_create;
    "/api/environments/{project_id}/evaluation_runs/": Endpoints.post_Evaluation_runs_create;
    "/api/environments/{project_id}/evaluations/": Endpoints.post_Evaluations_create;
    "/api/environments/{project_id}/exports/": Endpoints.post_Exports_create;
    "/api/environments/{project_id}/external_data_sources/": Endpoints.post_External_data_sources_create;
    "/api/environments/{project_id}/external_data_sources/{id}/reload/": Endpoints.post_External_data_sources_reload_create;
    "/api/environments/{project_id}/external_data_sources/database_schema/": Endpoints.post_External_data_sources_database_schema_create;
    "/api/environments/{project_id}/external_data_sources/source_prefix/": Endpoints.post_External_data_sources_source_prefix_create;
    "/api/environments/{project_id}/file_system/": Endpoints.post_File_system_create;
    "/api/environments/{project_id}/file_system/{id}/count/": Endpoints.post_File_system_count_create;
    "/api/environments/{project_id}/file_system/{id}/link/": Endpoints.post_File_system_link_create;
    "/api/environments/{project_id}/file_system/{id}/move/": Endpoints.post_File_system_move_create;
    "/api/environments/{project_id}/file_system/count_by_path/": Endpoints.post_File_system_count_by_path_create;
    "/api/environments/{project_id}/file_system/log_view/": Endpoints.post_File_system_log_view_create;
    "/api/environments/{project_id}/file_system/undo_delete/": Endpoints.post_File_system_undo_delete_create;
    "/api/environments/{project_id}/file_system_shortcut/": Endpoints.post_File_system_shortcut_create;
    "/api/environments/{project_id}/groups/": Endpoints.post_Groups_create;
    "/api/environments/{project_id}/groups/delete_property/": Endpoints.post_Groups_delete_property_create;
    "/api/environments/{project_id}/groups/update_property/": Endpoints.post_Groups_update_property_create;
    "/api/environments/{project_id}/hog_functions/": Endpoints.post_Hog_functions_create;
    "/api/environments/{project_id}/hog_functions/{id}/enable_backfills/": Endpoints.post_Hog_functions_enable_backfills_create;
    "/api/environments/{project_id}/hog_functions/{id}/invocations/": Endpoints.post_Hog_functions_invocations_create;
    "/api/environments/{project_id}/insight_variables/": Endpoints.post_Insight_variables_create;
    "/api/environments/{project_id}/insights/": Endpoints.post_Insights_create;
    "/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/": Endpoints.post_Insights_sharing_passwords_create;
    "/api/environments/{project_id}/insights/{insight_id}/sharing/refresh/": Endpoints.post_Insights_sharing_refresh_create;
    "/api/environments/{project_id}/insights/{id}/suggestions/": Endpoints.post_Insights_suggestions_create;
    "/api/environments/{project_id}/insights/cancel/": Endpoints.post_Insights_cancel_create;
    "/api/environments/{project_id}/insights/viewed/": Endpoints.post_Insights_viewed_create;
    "/api/environments/{project_id}/integrations/": Endpoints.post_Integrations_create;
    "/api/environments/{project_id}/integrations/{id}/email/verify/": Endpoints.post_Integrations_email_verify_create;
    "/api/environments/{project_id}/llm_analytics/evaluation_config/set_active_key/": Endpoints.post_Llm_analytics_evaluation_config_set_active_key_create;
    "/api/environments/{project_id}/llm_analytics/evaluation_summary/": Endpoints.post_Llm_analytics_evaluation_summary_create;
    "/api/environments/{project_id}/llm_analytics/provider_key_validations/": Endpoints.post_Llm_analytics_provider_key_validations_create;
    "/api/environments/{project_id}/llm_analytics/provider_keys/": Endpoints.post_Llm_analytics_provider_keys_create;
    "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/validate/": Endpoints.post_Llm_analytics_provider_keys_validate_create;
    "/api/environments/{project_id}/llm_analytics/summarization/": Endpoints.post_Llm_analytics_summarization_create;
    "/api/environments/{project_id}/llm_analytics/summarization/batch_check/": Endpoints.post_Llm_analytics_summarization_batch_check_create;
    "/api/environments/{project_id}/llm_analytics/text_repr/": Endpoints.post_Llm_analytics_text_repr_create;
    "/api/environments/{project_id}/llm_analytics/translate/": Endpoints.post_Llm_analytics_translate_create;
    "/api/environments/{project_id}/llm_prompts/": Endpoints.post_Llm_prompts_create;
    "/api/environments/{project_id}/logs/explainLogWithAI/": Endpoints.post_Logs_explainLogWithAI_create;
    "/api/environments/{project_id}/logs/export/": Endpoints.post_Logs_export_create;
    "/api/environments/{project_id}/logs/query/": Endpoints.post_Logs_query_create;
    "/api/environments/{project_id}/logs/sparkline/": Endpoints.post_Logs_sparkline_create;
    "/api/environments/{project_id}/max_tools/create_and_query_insight/": Endpoints.post_Max_tools_create_and_query_insight_create;
    "/api/environments/{project_id}/mcp_tools/{tool_name}/": Endpoints.post_Mcp_tools_create;
    "/api/environments/{project_id}/persisted_folder/": Endpoints.post_Persisted_folder_create;
    "/api/environments/{project_id}/persons/{id}/delete_property/": Endpoints.post_Persons_delete_property_create;
    "/api/environments/{project_id}/persons/{id}/split/": Endpoints.post_Persons_split_create;
    "/api/environments/{project_id}/persons/{id}/update_property/": Endpoints.post_Persons_update_property_create;
    "/api/environments/{project_id}/persons/bulk_delete/": Endpoints.post_Persons_bulk_delete_create;
    "/api/environments/{project_id}/persons/funnel/": Endpoints.post_Persons_funnel_create;
    "/api/environments/{project_id}/persons/funnel/correlation/": Endpoints.post_Persons_funnel_correlation_create;
    "/api/environments/{project_id}/persons/reset_person_distinct_id/": Endpoints.post_Persons_reset_person_distinct_id_create;
    "/api/environments/{project_id}/query/": Endpoints.post_Query_create;
    "/api/environments/{project_id}/query/check_auth_for_async/": Endpoints.post_Query_check_auth_for_async_create;
    "/api/environments/{project_id}/query/upgrade/": Endpoints.post_Query_upgrade_create;
    "/api/environments/{project_id}/session_recording_playlists/": Endpoints.post_Session_recording_playlists_create;
    "/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/": Endpoints.post_Session_recording_playlists_recordings_create;
    "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/": Endpoints.post_Session_recordings_sharing_passwords_create;
    "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/refresh/": Endpoints.post_Session_recordings_sharing_refresh_create;
    "/api/environments/{project_id}/session_summaries/create_session_summaries/": Endpoints.post_Create_session_summaries;
    "/api/environments/{project_id}/session_summaries/create_session_summaries_individually/": Endpoints.post_Create_session_summaries_individually;
    "/api/environments/{project_id}/subscriptions/": Endpoints.post_Subscriptions_create;
    "/api/environments/{project_id}/user_interviews/": Endpoints.post_User_interviews_create;
    "/api/environments/{project_id}/warehouse_saved_queries/": Endpoints.post_Warehouse_saved_queries_create;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/ancestors/": Endpoints.post_Warehouse_saved_queries_ancestors_create;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/cancel/": Endpoints.post_Warehouse_saved_queries_cancel_create;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/descendants/": Endpoints.post_Warehouse_saved_queries_descendants_create;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/materialize/": Endpoints.post_Warehouse_saved_queries_materialize_create;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/revert_materialization/": Endpoints.post_Warehouse_saved_queries_revert_materialization_create;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/run/": Endpoints.post_Warehouse_saved_queries_run_create;
    "/api/environments/{project_id}/warehouse_saved_queries/resume_schedules/": Endpoints.post_Warehouse_saved_queries_resume_schedules_create;
    "/api/environments/{project_id}/warehouse_tables/": Endpoints.post_Warehouse_tables_create;
    "/api/environments/{project_id}/warehouse_tables/{id}/refresh_schema/": Endpoints.post_Warehouse_tables_refresh_schema_create;
    "/api/environments/{project_id}/warehouse_tables/{id}/update_schema/": Endpoints.post_Warehouse_tables_update_schema_create;
    "/api/environments/{project_id}/warehouse_tables/file/": Endpoints.post_Warehouse_tables_file_create;
    "/api/organizations/": Endpoints.post_Create;
    "/api/organizations/{organization_id}/batch_exports/": Endpoints.post_Batch_exports_create_2;
    "/api/organizations/{organization_id}/batch_exports/{id}/pause/": Endpoints.post_Batch_exports_pause_create_2;
    "/api/organizations/{organization_id}/batch_exports/{id}/run_test_step/": Endpoints.post_Batch_exports_run_test_step_create_2;
    "/api/organizations/{organization_id}/batch_exports/{id}/unpause/": Endpoints.post_Batch_exports_unpause_create_2;
    "/api/organizations/{organization_id}/batch_exports/run_test_step_new/": Endpoints.post_Batch_exports_run_test_step_new_create_2;
    "/api/organizations/{organization_id}/domains/": Endpoints.post_Domains_create;
    "/api/organizations/{organization_id}/domains/{id}/scim/token/": Endpoints.post_Domains_scim_token_create;
    "/api/organizations/{organization_id}/domains/{id}/verify/": Endpoints.post_Domains_verify_create;
    "/api/organizations/{organization_id}/invites/": Endpoints.post_Invites_create;
    "/api/organizations/{organization_id}/invites/bulk/": Endpoints.post_Invites_bulk_create;
    "/api/organizations/{organization_id}/projects/": Endpoints.post_Create_2;
    "/api/organizations/{organization_id}/projects/{id}/change_organization/": Endpoints.post_Change_organization_create;
    "/api/organizations/{organization_id}/projects/{id}/generate_conversations_public_token/": Endpoints.post_Generate_conversations_public_token_create;
    "/api/organizations/{organization_id}/proxy_records/": Endpoints.post_Proxy_records_create;
    "/api/organizations/{organization_id}/roles/": Endpoints.post_Roles_create;
    "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/": Endpoints.post_Roles_role_memberships_create;
    "/api/projects/{project_id}/actions/": Endpoints.post_Actions_create;
    "/api/projects/{project_id}/advanced_activity_logs/export/": Endpoints.post_Advanced_activity_logs_export_create;
    "/api/projects/{project_id}/alerts/": Endpoints.post_Alerts_create_2;
    "/api/projects/{project_id}/annotations/": Endpoints.post_Annotations_create;
    "/api/projects/{project_id}/batch_exports/": Endpoints.post_Batch_exports_create_3;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/": Endpoints.post_Batch_exports_backfills_create_2;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/": Endpoints.post_Batch_exports_backfills_cancel_create_2;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/": Endpoints.post_Batch_exports_runs_cancel_create_2;
    "/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/": Endpoints.post_Batch_exports_runs_retry_create_2;
    "/api/projects/{project_id}/batch_exports/{id}/pause/": Endpoints.post_Batch_exports_pause_create_3;
    "/api/projects/{project_id}/batch_exports/{id}/run_test_step/": Endpoints.post_Batch_exports_run_test_step_create_3;
    "/api/projects/{project_id}/batch_exports/{id}/unpause/": Endpoints.post_Batch_exports_unpause_create_3;
    "/api/projects/{project_id}/batch_exports/run_test_step_new/": Endpoints.post_Batch_exports_run_test_step_new_create_3;
    "/api/projects/{project_id}/cohorts/": Endpoints.post_Cohorts_create;
    "/api/projects/{project_id}/conversations/tickets/": Endpoints.post_Conversations_tickets_create;
    "/api/projects/{project_id}/dashboard_templates/": Endpoints.post_Dashboard_templates_create;
    "/api/projects/{project_id}/dashboards/": Endpoints.post_Dashboards_create_2;
    "/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/": Endpoints.post_Dashboards_collaborators_create_2;
    "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/": Endpoints.post_Dashboards_sharing_passwords_create_2;
    "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/refresh/": Endpoints.post_Dashboards_sharing_refresh_create_2;
    "/api/projects/{project_id}/dashboards/create_from_template_json/": Endpoints.post_Dashboards_create_from_template_json_create_2;
    "/api/projects/{project_id}/dashboards/create_unlisted_dashboard/": Endpoints.post_Dashboards_create_unlisted_dashboard_create_2;
    "/api/projects/{project_id}/data_color_themes/": Endpoints.post_Data_color_themes_create_2;
    "/api/projects/{project_id}/dataset_items/": Endpoints.post_Dataset_items_create_2;
    "/api/projects/{project_id}/datasets/": Endpoints.post_Datasets_create_2;
    "/api/projects/{project_id}/early_access_feature/": Endpoints.post_Early_access_feature_create;
    "/api/projects/{project_id}/endpoints/": Endpoints.post_Endpoints_create_2;
    "/api/projects/{project_id}/endpoints/{name}/run/": Endpoints.post_Endpoints_run_create_2;
    "/api/projects/{project_id}/endpoints/last_execution_times/": Endpoints.post_Endpoints_last_execution_times_create_2;
    "/api/projects/{project_id}/environments/": Endpoints.post_Create_3;
    "/api/projects/{project_id}/environments/{id}/default_evaluation_tags/": Endpoints.post_Default_evaluation_tags_create;
    "/api/projects/{project_id}/environments/{id}/generate_conversations_public_token/": Endpoints.post_Generate_conversations_public_token_create_2;
    "/api/projects/{project_id}/error_tracking/releases/": Endpoints.post_Error_tracking_releases_create_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/": Endpoints.post_Error_tracking_symbol_sets_create_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/bulk_finish_upload/": Endpoints.post_Error_tracking_symbol_sets_bulk_finish_upload_create_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/bulk_start_upload/": Endpoints.post_Error_tracking_symbol_sets_bulk_start_upload_create_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/start_upload/": Endpoints.post_Error_tracking_symbol_sets_start_upload_create_2;
    "/api/projects/{project_id}/event_definitions/": Endpoints.post_Event_definitions_create;
    "/api/projects/{project_id}/experiment_holdouts/": Endpoints.post_Experiment_holdouts_create;
    "/api/projects/{project_id}/experiment_saved_metrics/": Endpoints.post_Experiment_saved_metrics_create;
    "/api/projects/{project_id}/experiments/": Endpoints.post_Experiments_create;
    "/api/projects/{project_id}/experiments/{id}/create_exposure_cohort_for_experiment/": Endpoints.post_Experiments_create_exposure_cohort_for_experiment_create;
    "/api/projects/{project_id}/experiments/{id}/duplicate/": Endpoints.post_Experiments_duplicate_create;
    "/api/projects/{project_id}/experiments/{id}/recalculate_timeseries/": Endpoints.post_Experiments_recalculate_timeseries_create;
    "/api/projects/{project_id}/exports/": Endpoints.post_Exports_create_2;
    "/api/projects/{project_id}/external_data_sources/": Endpoints.post_External_data_sources_create_2;
    "/api/projects/{project_id}/external_data_sources/{id}/reload/": Endpoints.post_External_data_sources_reload_create_2;
    "/api/projects/{project_id}/external_data_sources/database_schema/": Endpoints.post_External_data_sources_database_schema_create_2;
    "/api/projects/{project_id}/external_data_sources/source_prefix/": Endpoints.post_External_data_sources_source_prefix_create_2;
    "/api/projects/{project_id}/feature_flags/": Endpoints.post_Feature_flags_create;
    "/api/projects/{project_id}/feature_flags/{id}/create_static_cohort_for_flag/": Endpoints.post_Feature_flags_create_static_cohort_for_flag_create;
    "/api/projects/{project_id}/feature_flags/{id}/dashboard/": Endpoints.post_Feature_flags_dashboard_create;
    "/api/projects/{project_id}/feature_flags/{id}/enrich_usage_dashboard/": Endpoints.post_Feature_flags_enrich_usage_dashboard_create;
    "/api/projects/{project_id}/feature_flags/bulk_keys/": Endpoints.post_Feature_flags_bulk_keys_create;
    "/api/projects/{project_id}/feature_flags/user_blast_radius/": Endpoints.post_Feature_flags_user_blast_radius_create;
    "/api/projects/{project_id}/file_system/": Endpoints.post_File_system_create_2;
    "/api/projects/{project_id}/file_system/{id}/count/": Endpoints.post_File_system_count_create_2;
    "/api/projects/{project_id}/file_system/{id}/link/": Endpoints.post_File_system_link_create_2;
    "/api/projects/{project_id}/file_system/{id}/move/": Endpoints.post_File_system_move_create_2;
    "/api/projects/{project_id}/file_system/count_by_path/": Endpoints.post_File_system_count_by_path_create_2;
    "/api/projects/{project_id}/file_system/log_view/": Endpoints.post_File_system_log_view_create_2;
    "/api/projects/{project_id}/file_system/undo_delete/": Endpoints.post_File_system_undo_delete_create_2;
    "/api/projects/{project_id}/file_system_shortcut/": Endpoints.post_File_system_shortcut_create_2;
    "/api/projects/{project_id}/groups/": Endpoints.post_Groups_create_2;
    "/api/projects/{project_id}/groups/delete_property/": Endpoints.post_Groups_delete_property_create_2;
    "/api/projects/{project_id}/groups/update_property/": Endpoints.post_Groups_update_property_create_2;
    "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/": Endpoints.post_Groups_types_metrics_create;
    "/api/projects/{project_id}/hog_functions/": Endpoints.post_Hog_functions_create_2;
    "/api/projects/{project_id}/hog_functions/{id}/enable_backfills/": Endpoints.post_Hog_functions_enable_backfills_create_2;
    "/api/projects/{project_id}/hog_functions/{id}/invocations/": Endpoints.post_Hog_functions_invocations_create_2;
    "/api/projects/{project_id}/insight_variables/": Endpoints.post_Insight_variables_create_2;
    "/api/projects/{project_id}/insights/": Endpoints.post_Insights_create_2;
    "/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/": Endpoints.post_Insights_sharing_passwords_create_2;
    "/api/projects/{project_id}/insights/{insight_id}/sharing/refresh/": Endpoints.post_Insights_sharing_refresh_create_2;
    "/api/projects/{project_id}/insights/{id}/suggestions/": Endpoints.post_Insights_suggestions_create_2;
    "/api/projects/{project_id}/insights/cancel/": Endpoints.post_Insights_cancel_create_2;
    "/api/projects/{project_id}/insights/viewed/": Endpoints.post_Insights_viewed_create_2;
    "/api/projects/{project_id}/integrations/": Endpoints.post_Integrations_create_2;
    "/api/projects/{project_id}/integrations/{id}/email/verify/": Endpoints.post_Integrations_email_verify_create_2;
    "/api/projects/{project_id}/live_debugger_breakpoints/": Endpoints.post_Live_debugger_breakpoints_create;
    "/api/projects/{project_id}/logs/export/": Endpoints.post_Logs_export_create_2;
    "/api/projects/{project_id}/logs/query/": Endpoints.post_Logs_query_create_2;
    "/api/projects/{project_id}/logs/sparkline/": Endpoints.post_Logs_sparkline_create_2;
    "/api/projects/{project_id}/notebooks/": Endpoints.post_Notebooks_create;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/config/": Endpoints.post_Notebooks_kernel_config_create;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/execute/": Endpoints.post_Notebooks_kernel_execute_create;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/execute/stream/": Endpoints.post_Notebooks_kernel_execute_stream_create;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/restart/": Endpoints.post_Notebooks_kernel_restart_create;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/start/": Endpoints.post_Notebooks_kernel_start_create;
    "/api/projects/{project_id}/notebooks/{short_id}/kernel/stop/": Endpoints.post_Notebooks_kernel_stop_create;
    "/api/projects/{project_id}/persisted_folder/": Endpoints.post_Persisted_folder_create_2;
    "/api/projects/{project_id}/persons/{id}/delete_property/": Endpoints.post_Persons_delete_property_create_2;
    "/api/projects/{project_id}/persons/{id}/split/": Endpoints.post_Persons_split_create_2;
    "/api/projects/{project_id}/persons/{id}/update_property/": Endpoints.post_Persons_update_property_create_2;
    "/api/projects/{project_id}/persons/bulk_delete/": Endpoints.post_Persons_bulk_delete_create_2;
    "/api/projects/{project_id}/persons/funnel/": Endpoints.post_Persons_funnel_create_2;
    "/api/projects/{project_id}/persons/funnel/correlation/": Endpoints.post_Persons_funnel_correlation_create_2;
    "/api/projects/{project_id}/persons/reset_person_distinct_id/": Endpoints.post_Persons_reset_person_distinct_id_create_2;
    "/api/projects/{project_id}/product_tours/": Endpoints.post_Product_tours_create;
    "/api/projects/{project_id}/product_tours/generate/": Endpoints.post_Product_tours_generate_create;
    "/api/projects/{project_id}/query/": Endpoints.post_Query_create_2;
    "/api/projects/{project_id}/query/check_auth_for_async/": Endpoints.post_Query_check_auth_for_async_create_2;
    "/api/projects/{project_id}/query/upgrade/": Endpoints.post_Query_upgrade_create_2;
    "/api/projects/{project_id}/session_group_summaries/": Endpoints.post_Session_group_summaries_create;
    "/api/projects/{project_id}/session_recording_playlists/": Endpoints.post_Session_recording_playlists_create_2;
    "/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/": Endpoints.post_Session_recording_playlists_recordings_create_2;
    "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/": Endpoints.post_Session_recordings_sharing_passwords_create_2;
    "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/refresh/": Endpoints.post_Session_recordings_sharing_refresh_create_2;
    "/api/projects/{project_id}/subscriptions/": Endpoints.post_Subscriptions_create_2;
    "/api/projects/{project_id}/surveys/": Endpoints.post_Surveys_create;
    "/api/projects/{project_id}/surveys/{id}/duplicate_to_projects/": Endpoints.post_Surveys_duplicate_to_projects_create;
    "/api/projects/{project_id}/surveys/{id}/responses/{response_uuid}/archive/": Endpoints.post_Surveys_responses_archive_create;
    "/api/projects/{project_id}/surveys/{id}/responses/{response_uuid}/unarchive/": Endpoints.post_Surveys_responses_unarchive_create;
    "/api/projects/{project_id}/surveys/{id}/summarize_responses/": Endpoints.post_Surveys_summarize_responses_create;
    "/api/projects/{project_id}/surveys/{id}/summary_headline/": Endpoints.post_Surveys_summary_headline_create;
    "/api/projects/{project_id}/tasks/": Endpoints.post_Tasks_create;
    "/api/projects/{project_id}/tasks/{id}/run/": Endpoints.post_Tasks_run_create;
    "/api/projects/{project_id}/tasks/{task_id}/runs/": Endpoints.post_Tasks_runs_create;
    "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/append_log/": Endpoints.post_Tasks_runs_append_log_create;
    "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/artifacts/": Endpoints.post_Tasks_runs_artifacts_create;
    "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/artifacts/presign/": Endpoints.post_Tasks_runs_artifacts_presign_create;
    "/api/projects/{project_id}/tasks/cluster_video_segments/": Endpoints.post_Tasks_cluster_video_segments_create;
    "/api/projects/{project_id}/warehouse_saved_queries/": Endpoints.post_Warehouse_saved_queries_create_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/ancestors/": Endpoints.post_Warehouse_saved_queries_ancestors_create_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/cancel/": Endpoints.post_Warehouse_saved_queries_cancel_create_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/descendants/": Endpoints.post_Warehouse_saved_queries_descendants_create_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/materialize/": Endpoints.post_Warehouse_saved_queries_materialize_create_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/revert_materialization/": Endpoints.post_Warehouse_saved_queries_revert_materialization_create_2;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/run/": Endpoints.post_Warehouse_saved_queries_run_create_2;
    "/api/projects/{project_id}/warehouse_saved_queries/resume_schedules/": Endpoints.post_Warehouse_saved_queries_resume_schedules_create_2;
    "/api/projects/{project_id}/warehouse_tables/": Endpoints.post_Warehouse_tables_create_2;
    "/api/projects/{project_id}/warehouse_tables/{id}/refresh_schema/": Endpoints.post_Warehouse_tables_refresh_schema_create_2;
    "/api/projects/{project_id}/warehouse_tables/{id}/update_schema/": Endpoints.post_Warehouse_tables_update_schema_create_2;
    "/api/projects/{project_id}/warehouse_tables/file/": Endpoints.post_Warehouse_tables_file_create_2;
    "/api/projects/{project_id}/web_experiments/": Endpoints.post_Web_experiments_create;
    "/api/users/{uuid}/scene_personalisation/": Endpoints.post_Users_scene_personalisation_create;
    "/api/users/{uuid}/two_factor_backup_codes/": Endpoints.post_Users_two_factor_backup_codes_create;
    "/api/users/{uuid}/two_factor_disable/": Endpoints.post_Users_two_factor_disable_create;
    "/api/users/{uuid}/two_factor_validate/": Endpoints.post_Users_two_factor_validate_create;
    "/api/users/{uuid}/validate_2fa/": Endpoints.post_Users_validate_2fa_create;
    "/api/users/request_email_verification/": Endpoints.post_Users_request_email_verification_create;
    "/api/users/verify_email/": Endpoints.post_Users_verify_email_create;
  };
  put: {
    "/api/environments/{project_id}/alerts/{id}/": Endpoints.put_Alerts_update;
    "/api/environments/{project_id}/batch_exports/{id}/": Endpoints.put_Batch_exports_update;
    "/api/environments/{project_id}/customer_profile_configs/{id}/": Endpoints.put_Customer_profile_configs_update;
    "/api/environments/{project_id}/dashboards/{id}/": Endpoints.put_Dashboards_update;
    "/api/environments/{project_id}/data_color_themes/{id}/": Endpoints.put_Data_color_themes_update;
    "/api/environments/{project_id}/dataset_items/{id}/": Endpoints.put_Dataset_items_update;
    "/api/environments/{project_id}/datasets/{id}/": Endpoints.put_Datasets_update;
    "/api/environments/{project_id}/desktop_recordings/{id}/": Endpoints.put_Desktop_recordings_update;
    "/api/environments/{project_id}/endpoints/{name}/": Endpoints.put_Endpoints_update;
    "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/": Endpoints.put_Error_tracking_assignment_rules_update;
    "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/": Endpoints.put_Error_tracking_autocapture_controls_update;
    "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/": Endpoints.put_Error_tracking_grouping_rules_update;
    "/api/environments/{project_id}/error_tracking/releases/{id}/": Endpoints.put_Error_tracking_releases_update;
    "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/": Endpoints.put_Error_tracking_suppression_rules_update;
    "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.put_Error_tracking_symbol_sets_update;
    "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/finish_upload/": Endpoints.put_Error_tracking_symbol_sets_finish_upload_update;
    "/api/environments/{project_id}/evaluations/{id}/": Endpoints.put_Evaluations_update;
    "/api/environments/{project_id}/external_data_sources/{id}/": Endpoints.put_External_data_sources_update;
    "/api/environments/{project_id}/file_system/{id}/": Endpoints.put_File_system_update;
    "/api/environments/{project_id}/file_system_shortcut/{id}/": Endpoints.put_File_system_shortcut_update;
    "/api/environments/{project_id}/hog_functions/{id}/": Endpoints.put_Hog_functions_update;
    "/api/environments/{project_id}/insight_variables/{id}/": Endpoints.put_Insight_variables_update;
    "/api/environments/{project_id}/insights/{id}/": Endpoints.put_Insights_update;
    "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/": Endpoints.put_Llm_analytics_provider_keys_update;
    "/api/environments/{project_id}/llm_prompts/{id}/": Endpoints.put_Llm_prompts_update;
    "/api/environments/{project_id}/persisted_folder/{id}/": Endpoints.put_Persisted_folder_update;
    "/api/environments/{project_id}/persons/{id}/": Endpoints.put_Persons_update;
    "/api/environments/{project_id}/session_recording_playlists/{short_id}/": Endpoints.put_Session_recording_playlists_update;
    "/api/environments/{project_id}/session_recordings/{id}/": Endpoints.put_Session_recordings_update;
    "/api/environments/{project_id}/subscriptions/{id}/": Endpoints.put_Subscriptions_update;
    "/api/environments/{project_id}/user_interviews/{id}/": Endpoints.put_User_interviews_update;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/": Endpoints.put_Warehouse_saved_queries_update;
    "/api/environments/{project_id}/warehouse_tables/{id}/": Endpoints.put_Warehouse_tables_update;
    "/api/organizations/{id}/": Endpoints.put_Update;
    "/api/organizations/{organization_id}/batch_exports/{id}/": Endpoints.put_Batch_exports_update_2;
    "/api/organizations/{organization_id}/domains/{id}/": Endpoints.put_Domains_update;
    "/api/organizations/{organization_id}/members/{user__uuid}/": Endpoints.put_Members_update;
    "/api/organizations/{organization_id}/projects/{id}/": Endpoints.put_Update_2;
    "/api/organizations/{organization_id}/proxy_records/{id}/": Endpoints.put_Proxy_records_update;
    "/api/organizations/{organization_id}/roles/{id}/": Endpoints.put_Roles_update;
    "/api/projects/{project_id}/actions/{id}/": Endpoints.put_Actions_update;
    "/api/projects/{project_id}/alerts/{id}/": Endpoints.put_Alerts_update_2;
    "/api/projects/{project_id}/annotations/{id}/": Endpoints.put_Annotations_update;
    "/api/projects/{project_id}/batch_exports/{id}/": Endpoints.put_Batch_exports_update_3;
    "/api/projects/{project_id}/cohorts/{id}/": Endpoints.put_Cohorts_update;
    "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.put_Conversations_tickets_update;
    "/api/projects/{project_id}/dashboard_templates/{id}/": Endpoints.put_Dashboard_templates_update;
    "/api/projects/{project_id}/dashboards/{id}/": Endpoints.put_Dashboards_update_2;
    "/api/projects/{project_id}/data_color_themes/{id}/": Endpoints.put_Data_color_themes_update_2;
    "/api/projects/{project_id}/dataset_items/{id}/": Endpoints.put_Dataset_items_update_2;
    "/api/projects/{project_id}/datasets/{id}/": Endpoints.put_Datasets_update_2;
    "/api/projects/{project_id}/early_access_feature/{id}/": Endpoints.put_Early_access_feature_update;
    "/api/projects/{project_id}/endpoints/{name}/": Endpoints.put_Endpoints_update_2;
    "/api/projects/{project_id}/environments/{id}/": Endpoints.put_Update_3;
    "/api/projects/{project_id}/error_tracking/releases/{id}/": Endpoints.put_Error_tracking_releases_update_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.put_Error_tracking_symbol_sets_update_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/finish_upload/": Endpoints.put_Error_tracking_symbol_sets_finish_upload_update_2;
    "/api/projects/{project_id}/event_definitions/{id}/": Endpoints.put_Event_definitions_update;
    "/api/projects/{project_id}/experiment_holdouts/{id}/": Endpoints.put_Experiment_holdouts_update;
    "/api/projects/{project_id}/experiment_saved_metrics/{id}/": Endpoints.put_Experiment_saved_metrics_update;
    "/api/projects/{project_id}/experiments/{id}/": Endpoints.put_Experiments_update;
    "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.put_External_data_sources_update_2;
    "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.put_Feature_flags_update;
    "/api/projects/{project_id}/file_system/{id}/": Endpoints.put_File_system_update_2;
    "/api/projects/{project_id}/file_system_shortcut/{id}/": Endpoints.put_File_system_shortcut_update_2;
    "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/": Endpoints.put_Groups_types_metrics_update;
    "/api/projects/{project_id}/groups_types/create_detail_dashboard/": Endpoints.put_Groups_types_create_detail_dashboard_update;
    "/api/projects/{project_id}/groups_types/set_default_columns/": Endpoints.put_Groups_types_set_default_columns_update;
    "/api/projects/{project_id}/hog_functions/{id}/": Endpoints.put_Hog_functions_update_2;
    "/api/projects/{project_id}/insight_variables/{id}/": Endpoints.put_Insight_variables_update_2;
    "/api/projects/{project_id}/insights/{id}/": Endpoints.put_Insights_update_2;
    "/api/projects/{project_id}/live_debugger_breakpoints/{id}/": Endpoints.put_Live_debugger_breakpoints_update;
    "/api/projects/{project_id}/notebooks/{short_id}/": Endpoints.put_Notebooks_update;
    "/api/projects/{project_id}/persisted_folder/{id}/": Endpoints.put_Persisted_folder_update_2;
    "/api/projects/{project_id}/persons/{id}/": Endpoints.put_Persons_update_2;
    "/api/projects/{project_id}/product_tours/{id}/": Endpoints.put_Product_tours_update;
    "/api/projects/{project_id}/property_definitions/{id}/": Endpoints.put_Property_definitions_update;
    "/api/projects/{project_id}/session_group_summaries/{id}/": Endpoints.put_Session_group_summaries_update;
    "/api/projects/{project_id}/session_recording_playlists/{short_id}/": Endpoints.put_Session_recording_playlists_update_2;
    "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.put_Session_recordings_update_2;
    "/api/projects/{project_id}/subscriptions/{id}/": Endpoints.put_Subscriptions_update_2;
    "/api/projects/{project_id}/surveys/{id}/": Endpoints.put_Surveys_update;
    "/api/projects/{project_id}/tasks/{id}/": Endpoints.put_Tasks_update;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/": Endpoints.put_Warehouse_saved_queries_update_2;
    "/api/projects/{project_id}/warehouse_tables/{id}/": Endpoints.put_Warehouse_tables_update_2;
    "/api/projects/{project_id}/web_experiments/{id}/": Endpoints.put_Web_experiments_update;
    "/api/users/{uuid}/": Endpoints.put_Users_update;
  };
  patch: {
    "/api/environments/{project_id}/alerts/{id}/": Endpoints.patch_Alerts_partial_update;
    "/api/environments/{project_id}/batch_exports/{id}/": Endpoints.patch_Batch_exports_partial_update;
    "/api/environments/{project_id}/conversations/{conversation}/cancel/": Endpoints.patch_Conversations_cancel_partial_update;
    "/api/environments/{project_id}/conversations/{conversation}/queue/{queue_id}/": Endpoints.patch_Conversations_queue_partial_update;
    "/api/environments/{project_id}/customer_profile_configs/{id}/": Endpoints.patch_Customer_profile_configs_partial_update;
    "/api/environments/{project_id}/dashboards/{id}/": Endpoints.patch_Dashboards_partial_update;
    "/api/environments/{project_id}/dashboards/{id}/move_tile/": Endpoints.patch_Dashboards_move_tile_partial_update;
    "/api/environments/{project_id}/data_color_themes/{id}/": Endpoints.patch_Data_color_themes_partial_update;
    "/api/environments/{project_id}/dataset_items/{id}/": Endpoints.patch_Dataset_items_partial_update;
    "/api/environments/{project_id}/datasets/{id}/": Endpoints.patch_Datasets_partial_update;
    "/api/environments/{project_id}/desktop_recordings/{id}/": Endpoints.patch_Desktop_recordings_partial_update;
    "/api/environments/{project_id}/endpoints/{name}/": Endpoints.patch_Endpoints_partial_update;
    "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/": Endpoints.patch_Error_tracking_assignment_rules_partial_update;
    "/api/environments/{project_id}/error_tracking/assignment_rules/reorder/": Endpoints.patch_Error_tracking_assignment_rules_reorder_partial_update;
    "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/": Endpoints.patch_Error_tracking_autocapture_controls_partial_update;
    "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/": Endpoints.patch_Error_tracking_grouping_rules_partial_update;
    "/api/environments/{project_id}/error_tracking/grouping_rules/reorder/": Endpoints.patch_Error_tracking_grouping_rules_reorder_partial_update;
    "/api/environments/{project_id}/error_tracking/releases/{id}/": Endpoints.patch_Error_tracking_releases_partial_update;
    "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/": Endpoints.patch_Error_tracking_suppression_rules_partial_update;
    "/api/environments/{project_id}/error_tracking/suppression_rules/reorder/": Endpoints.patch_Error_tracking_suppression_rules_reorder_partial_update;
    "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.patch_Error_tracking_symbol_sets_partial_update;
    "/api/environments/{project_id}/evaluations/{id}/": Endpoints.patch_Evaluations_partial_update;
    "/api/environments/{project_id}/external_data_sources/{id}/": Endpoints.patch_External_data_sources_partial_update;
    "/api/environments/{project_id}/external_data_sources/{id}/revenue_analytics_config/": Endpoints.patch_External_data_sources_revenue_analytics_config_partial_update;
    "/api/environments/{project_id}/file_system/{id}/": Endpoints.patch_File_system_partial_update;
    "/api/environments/{project_id}/file_system_shortcut/{id}/": Endpoints.patch_File_system_shortcut_partial_update;
    "/api/environments/{project_id}/hog_functions/{id}/": Endpoints.patch_Hog_functions_partial_update;
    "/api/environments/{project_id}/hog_functions/rearrange/": Endpoints.patch_Hog_functions_rearrange_partial_update;
    "/api/environments/{project_id}/insight_variables/{id}/": Endpoints.patch_Insight_variables_partial_update;
    "/api/environments/{project_id}/insights/{id}/": Endpoints.patch_Insights_partial_update;
    "/api/environments/{project_id}/integrations/{id}/email/": Endpoints.patch_Integrations_email_partial_update;
    "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/": Endpoints.patch_Llm_analytics_provider_keys_partial_update;
    "/api/environments/{project_id}/llm_prompts/{id}/": Endpoints.patch_Llm_prompts_partial_update;
    "/api/environments/{project_id}/persisted_folder/{id}/": Endpoints.patch_Persisted_folder_partial_update;
    "/api/environments/{project_id}/persons/{id}/": Endpoints.patch_Persons_partial_update;
    "/api/environments/{project_id}/session_recording_playlists/{short_id}/": Endpoints.patch_Session_recording_playlists_partial_update;
    "/api/environments/{project_id}/session_recordings/{id}/": Endpoints.patch_Session_recordings_partial_update;
    "/api/environments/{project_id}/subscriptions/{id}/": Endpoints.patch_Subscriptions_partial_update;
    "/api/environments/{project_id}/user_interviews/{id}/": Endpoints.patch_User_interviews_partial_update;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/": Endpoints.patch_Warehouse_saved_queries_partial_update;
    "/api/environments/{project_id}/warehouse_tables/{id}/": Endpoints.patch_Warehouse_tables_partial_update;
    "/api/organizations/{id}/": Endpoints.patch_Partial_update;
    "/api/organizations/{organization_id}/batch_exports/{id}/": Endpoints.patch_Batch_exports_partial_update_2;
    "/api/organizations/{organization_id}/domains/{id}/": Endpoints.patch_Domains_partial_update;
    "/api/organizations/{organization_id}/members/{user__uuid}/": Endpoints.patch_Members_partial_update;
    "/api/organizations/{organization_id}/projects/{id}/": Endpoints.patch_Partial_update_2;
    "/api/organizations/{organization_id}/projects/{id}/add_product_intent/": Endpoints.patch_Add_product_intent_partial_update;
    "/api/organizations/{organization_id}/projects/{id}/complete_product_onboarding/": Endpoints.patch_Complete_product_onboarding_partial_update;
    "/api/organizations/{organization_id}/projects/{id}/delete_secret_token_backup/": Endpoints.patch_Delete_secret_token_backup_partial_update;
    "/api/organizations/{organization_id}/projects/{id}/reset_token/": Endpoints.patch_Reset_token_partial_update;
    "/api/organizations/{organization_id}/projects/{id}/rotate_secret_token/": Endpoints.patch_Rotate_secret_token_partial_update;
    "/api/organizations/{organization_id}/proxy_records/{id}/": Endpoints.patch_Proxy_records_partial_update;
    "/api/organizations/{organization_id}/roles/{id}/": Endpoints.patch_Roles_partial_update;
    "/api/projects/{project_id}/actions/{id}/": Endpoints.patch_Actions_partial_update;
    "/api/projects/{project_id}/alerts/{id}/": Endpoints.patch_Alerts_partial_update_2;
    "/api/projects/{project_id}/annotations/{id}/": Endpoints.patch_Annotations_partial_update;
    "/api/projects/{project_id}/batch_exports/{id}/": Endpoints.patch_Batch_exports_partial_update_3;
    "/api/projects/{project_id}/cohorts/{id}/": Endpoints.patch_Cohorts_partial_update;
    "/api/projects/{project_id}/cohorts/{id}/add_persons_to_static_cohort/": Endpoints.patch_Cohorts_add_persons_to_static_cohort_partial_update;
    "/api/projects/{project_id}/cohorts/{id}/remove_person_from_static_cohort/": Endpoints.patch_Cohorts_remove_person_from_static_cohort_partial_update;
    "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.patch_Conversations_tickets_partial_update;
    "/api/projects/{project_id}/dashboard_templates/{id}/": Endpoints.patch_Dashboard_templates_partial_update;
    "/api/projects/{project_id}/dashboards/{id}/": Endpoints.patch_Dashboards_partial_update_2;
    "/api/projects/{project_id}/dashboards/{id}/move_tile/": Endpoints.patch_Dashboards_move_tile_partial_update_2;
    "/api/projects/{project_id}/data_color_themes/{id}/": Endpoints.patch_Data_color_themes_partial_update_2;
    "/api/projects/{project_id}/dataset_items/{id}/": Endpoints.patch_Dataset_items_partial_update_2;
    "/api/projects/{project_id}/datasets/{id}/": Endpoints.patch_Datasets_partial_update_2;
    "/api/projects/{project_id}/early_access_feature/{id}/": Endpoints.patch_Early_access_feature_partial_update;
    "/api/projects/{project_id}/endpoints/{name}/": Endpoints.patch_Endpoints_partial_update_2;
    "/api/projects/{project_id}/environments/{id}/": Endpoints.patch_Partial_update_3;
    "/api/projects/{project_id}/environments/{id}/add_product_intent/": Endpoints.patch_Add_product_intent_partial_update_2;
    "/api/projects/{project_id}/environments/{id}/complete_product_onboarding/": Endpoints.patch_Complete_product_onboarding_partial_update_2;
    "/api/projects/{project_id}/environments/{id}/delete_secret_token_backup/": Endpoints.patch_Delete_secret_token_backup_partial_update_2;
    "/api/projects/{project_id}/environments/{id}/reset_token/": Endpoints.patch_Reset_token_partial_update_2;
    "/api/projects/{project_id}/environments/{id}/rotate_secret_token/": Endpoints.patch_Rotate_secret_token_partial_update_2;
    "/api/projects/{project_id}/error_tracking/releases/{id}/": Endpoints.patch_Error_tracking_releases_partial_update_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.patch_Error_tracking_symbol_sets_partial_update_2;
    "/api/projects/{project_id}/event_definitions/{id}/": Endpoints.patch_Event_definitions_partial_update;
    "/api/projects/{project_id}/experiment_holdouts/{id}/": Endpoints.patch_Experiment_holdouts_partial_update;
    "/api/projects/{project_id}/experiment_saved_metrics/{id}/": Endpoints.patch_Experiment_saved_metrics_partial_update;
    "/api/projects/{project_id}/experiments/{id}/": Endpoints.patch_Experiments_partial_update;
    "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.patch_External_data_sources_partial_update_2;
    "/api/projects/{project_id}/external_data_sources/{id}/revenue_analytics_config/": Endpoints.patch_External_data_sources_revenue_analytics_config_partial_update_2;
    "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.patch_Feature_flags_partial_update;
    "/api/projects/{project_id}/file_system/{id}/": Endpoints.patch_File_system_partial_update_2;
    "/api/projects/{project_id}/file_system_shortcut/{id}/": Endpoints.patch_File_system_shortcut_partial_update_2;
    "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/": Endpoints.patch_Groups_types_metrics_partial_update;
    "/api/projects/{project_id}/groups_types/update_metadata/": Endpoints.patch_Groups_types_update_metadata_partial_update;
    "/api/projects/{project_id}/hog_functions/{id}/": Endpoints.patch_Hog_functions_partial_update_2;
    "/api/projects/{project_id}/hog_functions/rearrange/": Endpoints.patch_Hog_functions_rearrange_partial_update_2;
    "/api/projects/{project_id}/insight_variables/{id}/": Endpoints.patch_Insight_variables_partial_update_2;
    "/api/projects/{project_id}/insights/{id}/": Endpoints.patch_Insights_partial_update_2;
    "/api/projects/{project_id}/integrations/{id}/email/": Endpoints.patch_Integrations_email_partial_update_2;
    "/api/projects/{project_id}/live_debugger_breakpoints/{id}/": Endpoints.patch_Live_debugger_breakpoints_partial_update;
    "/api/projects/{project_id}/notebooks/{short_id}/": Endpoints.patch_Notebooks_partial_update;
    "/api/projects/{project_id}/persisted_folder/{id}/": Endpoints.patch_Persisted_folder_partial_update_2;
    "/api/projects/{project_id}/persons/{id}/": Endpoints.patch_Persons_partial_update_2;
    "/api/projects/{project_id}/product_tours/{id}/": Endpoints.patch_Product_tours_partial_update;
    "/api/projects/{project_id}/property_definitions/{id}/": Endpoints.patch_Property_definitions_partial_update;
    "/api/projects/{project_id}/session_group_summaries/{id}/": Endpoints.patch_Session_group_summaries_partial_update;
    "/api/projects/{project_id}/session_recording_playlists/{short_id}/": Endpoints.patch_Session_recording_playlists_partial_update_2;
    "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.patch_Session_recordings_partial_update_2;
    "/api/projects/{project_id}/subscriptions/{id}/": Endpoints.patch_Subscriptions_partial_update_2;
    "/api/projects/{project_id}/surveys/{id}/": Endpoints.patch_Surveys_partial_update;
    "/api/projects/{project_id}/tasks/{id}/": Endpoints.patch_Tasks_partial_update;
    "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/": Endpoints.patch_Tasks_runs_partial_update;
    "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/set_output/": Endpoints.patch_Tasks_runs_set_output_partial_update;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/": Endpoints.patch_Warehouse_saved_queries_partial_update_2;
    "/api/projects/{project_id}/warehouse_tables/{id}/": Endpoints.patch_Warehouse_tables_partial_update_2;
    "/api/projects/{project_id}/web_experiments/{id}/": Endpoints.patch_Web_experiments_partial_update;
    "/api/user_home_settings/{uuid}/": Endpoints.patch_User_home_settings_partial_update;
    "/api/users/{uuid}/": Endpoints.patch_Users_partial_update;
    "/api/users/{uuid}/hedgehog_config/": Endpoints.patch_Users_hedgehog_config_partial_update;
    "/api/users/cancel_email_change_request/": Endpoints.patch_Users_cancel_email_change_request_partial_update;
  };
  delete: {
    "/api/environments/{project_id}/alerts/{id}/": Endpoints.delete_Alerts_destroy;
    "/api/environments/{project_id}/batch_exports/{id}/": Endpoints.delete_Batch_exports_destroy;
    "/api/environments/{project_id}/conversations/{conversation}/queue/{queue_id}/": Endpoints.delete_Conversations_queue_destroy;
    "/api/environments/{project_id}/customer_profile_configs/{id}/": Endpoints.delete_Customer_profile_configs_destroy;
    "/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/": Endpoints.delete_Dashboards_collaborators_destroy;
    "/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/": Endpoints.delete_Dashboards_sharing_passwords_destroy;
    "/api/environments/{project_id}/dashboards/{id}/": Endpoints.delete_Dashboards_destroy;
    "/api/environments/{project_id}/data_color_themes/{id}/": Endpoints.delete_Data_color_themes_destroy;
    "/api/environments/{project_id}/dataset_items/{id}/": Endpoints.delete_Dataset_items_destroy;
    "/api/environments/{project_id}/datasets/{id}/": Endpoints.delete_Datasets_destroy;
    "/api/environments/{project_id}/desktop_recordings/{id}/": Endpoints.delete_Desktop_recordings_destroy;
    "/api/environments/{project_id}/endpoints/{name}/": Endpoints.delete_Endpoints_destroy;
    "/api/environments/{project_id}/error_tracking/assignment_rules/{id}/": Endpoints.delete_Error_tracking_assignment_rules_destroy;
    "/api/environments/{project_id}/error_tracking/autocapture_controls/{id}/": Endpoints.delete_Error_tracking_autocapture_controls_destroy;
    "/api/environments/{project_id}/error_tracking/fingerprints/{id}/": Endpoints.delete_Error_tracking_fingerprints_destroy;
    "/api/environments/{project_id}/error_tracking/grouping_rules/{id}/": Endpoints.delete_Error_tracking_grouping_rules_destroy;
    "/api/environments/{project_id}/error_tracking/releases/{id}/": Endpoints.delete_Error_tracking_releases_destroy;
    "/api/environments/{project_id}/error_tracking/suppression_rules/{id}/": Endpoints.delete_Error_tracking_suppression_rules_destroy;
    "/api/environments/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.delete_Error_tracking_symbol_sets_destroy;
    "/api/environments/{project_id}/evaluations/{id}/": Endpoints.delete_Evaluations_destroy;
    "/api/environments/{project_id}/external_data_sources/{id}/": Endpoints.delete_External_data_sources_destroy;
    "/api/environments/{project_id}/file_system/{id}/": Endpoints.delete_File_system_destroy;
    "/api/environments/{project_id}/file_system_shortcut/{id}/": Endpoints.delete_File_system_shortcut_destroy;
    "/api/environments/{project_id}/hog_functions/{id}/": Endpoints.delete_Hog_functions_destroy;
    "/api/environments/{project_id}/insight_variables/{id}/": Endpoints.delete_Insight_variables_destroy;
    "/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/": Endpoints.delete_Insights_sharing_passwords_destroy;
    "/api/environments/{project_id}/insights/{id}/": Endpoints.delete_Insights_destroy;
    "/api/environments/{project_id}/integrations/{id}/": Endpoints.delete_Integrations_destroy;
    "/api/environments/{project_id}/llm_analytics/provider_keys/{id}/": Endpoints.delete_Llm_analytics_provider_keys_destroy;
    "/api/environments/{project_id}/llm_prompts/{id}/": Endpoints.delete_Llm_prompts_destroy;
    "/api/environments/{project_id}/persisted_folder/{id}/": Endpoints.delete_Persisted_folder_destroy;
    "/api/environments/{project_id}/query/{id}/": Endpoints.delete_Query_destroy;
    "/api/environments/{project_id}/session_recording_playlists/{short_id}/": Endpoints.delete_Session_recording_playlists_destroy;
    "/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/": Endpoints.delete_Session_recording_playlists_recordings_destroy;
    "/api/environments/{project_id}/session_recordings/{id}/": Endpoints.delete_Session_recordings_destroy;
    "/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/": Endpoints.delete_Session_recordings_sharing_passwords_destroy;
    "/api/environments/{project_id}/subscriptions/{id}/": Endpoints.delete_Subscriptions_destroy;
    "/api/environments/{project_id}/user_interviews/{id}/": Endpoints.delete_User_interviews_destroy;
    "/api/environments/{project_id}/warehouse_saved_queries/{id}/": Endpoints.delete_Warehouse_saved_queries_destroy;
    "/api/environments/{project_id}/warehouse_tables/{id}/": Endpoints.delete_Warehouse_tables_destroy;
    "/api/organizations/{id}/": Endpoints.delete_Destroy;
    "/api/organizations/{organization_id}/batch_exports/{id}/": Endpoints.delete_Batch_exports_destroy_2;
    "/api/organizations/{organization_id}/domains/{id}/": Endpoints.delete_Domains_destroy;
    "/api/organizations/{organization_id}/invites/{id}/": Endpoints.delete_Invites_destroy;
    "/api/organizations/{organization_id}/members/{user__uuid}/": Endpoints.delete_Members_destroy;
    "/api/organizations/{organization_id}/projects/{id}/": Endpoints.delete_Destroy_2;
    "/api/organizations/{organization_id}/proxy_records/{id}/": Endpoints.delete_Proxy_records_destroy;
    "/api/organizations/{organization_id}/roles/{id}/": Endpoints.delete_Roles_destroy;
    "/api/organizations/{organization_id}/roles/{role_id}/role_memberships/{id}/": Endpoints.delete_Roles_role_memberships_destroy;
    "/api/projects/{project_id}/actions/{id}/": Endpoints.delete_Actions_destroy;
    "/api/projects/{project_id}/alerts/{id}/": Endpoints.delete_Alerts_destroy_2;
    "/api/projects/{project_id}/annotations/{id}/": Endpoints.delete_Annotations_destroy;
    "/api/projects/{project_id}/batch_exports/{id}/": Endpoints.delete_Batch_exports_destroy_3;
    "/api/projects/{project_id}/cohorts/{id}/": Endpoints.delete_Cohorts_destroy;
    "/api/projects/{project_id}/conversations/tickets/{id}/": Endpoints.delete_Conversations_tickets_destroy;
    "/api/projects/{project_id}/dashboard_templates/{id}/": Endpoints.delete_Dashboard_templates_destroy;
    "/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/": Endpoints.delete_Dashboards_collaborators_destroy_2;
    "/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/": Endpoints.delete_Dashboards_sharing_passwords_destroy_2;
    "/api/projects/{project_id}/dashboards/{id}/": Endpoints.delete_Dashboards_destroy_2;
    "/api/projects/{project_id}/data_color_themes/{id}/": Endpoints.delete_Data_color_themes_destroy_2;
    "/api/projects/{project_id}/dataset_items/{id}/": Endpoints.delete_Dataset_items_destroy_2;
    "/api/projects/{project_id}/datasets/{id}/": Endpoints.delete_Datasets_destroy_2;
    "/api/projects/{project_id}/early_access_feature/{id}/": Endpoints.delete_Early_access_feature_destroy;
    "/api/projects/{project_id}/endpoints/{name}/": Endpoints.delete_Endpoints_destroy_2;
    "/api/projects/{project_id}/environments/{id}/": Endpoints.delete_Destroy_3;
    "/api/projects/{project_id}/environments/{id}/default_evaluation_tags/": Endpoints.delete_Default_evaluation_tags_destroy;
    "/api/projects/{project_id}/error_tracking/releases/{id}/": Endpoints.delete_Error_tracking_releases_destroy_2;
    "/api/projects/{project_id}/error_tracking/symbol_sets/{id}/": Endpoints.delete_Error_tracking_symbol_sets_destroy_2;
    "/api/projects/{project_id}/event_definitions/{id}/": Endpoints.delete_Event_definitions_destroy;
    "/api/projects/{project_id}/experiment_holdouts/{id}/": Endpoints.delete_Experiment_holdouts_destroy;
    "/api/projects/{project_id}/experiment_saved_metrics/{id}/": Endpoints.delete_Experiment_saved_metrics_destroy;
    "/api/projects/{project_id}/experiments/{id}/": Endpoints.delete_Experiments_destroy;
    "/api/projects/{project_id}/external_data_sources/{id}/": Endpoints.delete_External_data_sources_destroy_2;
    "/api/projects/{project_id}/feature_flags/{id}/": Endpoints.delete_Feature_flags_destroy;
    "/api/projects/{project_id}/file_system/{id}/": Endpoints.delete_File_system_destroy_2;
    "/api/projects/{project_id}/file_system_shortcut/{id}/": Endpoints.delete_File_system_shortcut_destroy_2;
    "/api/projects/{project_id}/groups_types/{group_type_index}/": Endpoints.delete_Groups_types_destroy;
    "/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/": Endpoints.delete_Groups_types_metrics_destroy;
    "/api/projects/{project_id}/hog_functions/{id}/": Endpoints.delete_Hog_functions_destroy_2;
    "/api/projects/{project_id}/insight_variables/{id}/": Endpoints.delete_Insight_variables_destroy_2;
    "/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/": Endpoints.delete_Insights_sharing_passwords_destroy_2;
    "/api/projects/{project_id}/insights/{id}/": Endpoints.delete_Insights_destroy_2;
    "/api/projects/{project_id}/integrations/{id}/": Endpoints.delete_Integrations_destroy_2;
    "/api/projects/{project_id}/live_debugger_breakpoints/{id}/": Endpoints.delete_Live_debugger_breakpoints_destroy;
    "/api/projects/{project_id}/notebooks/{short_id}/": Endpoints.delete_Notebooks_destroy;
    "/api/projects/{project_id}/persisted_folder/{id}/": Endpoints.delete_Persisted_folder_destroy_2;
    "/api/projects/{project_id}/product_tours/{id}/": Endpoints.delete_Product_tours_destroy;
    "/api/projects/{project_id}/property_definitions/{id}/": Endpoints.delete_Property_definitions_destroy;
    "/api/projects/{project_id}/query/{id}/": Endpoints.delete_Query_destroy_2;
    "/api/projects/{project_id}/session_group_summaries/{id}/": Endpoints.delete_Session_group_summaries_destroy;
    "/api/projects/{project_id}/session_recording_playlists/{short_id}/": Endpoints.delete_Session_recording_playlists_destroy_2;
    "/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/": Endpoints.delete_Session_recording_playlists_recordings_destroy_2;
    "/api/projects/{project_id}/session_recordings/{id}/": Endpoints.delete_Session_recordings_destroy_2;
    "/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/": Endpoints.delete_Session_recordings_sharing_passwords_destroy_2;
    "/api/projects/{project_id}/subscriptions/{id}/": Endpoints.delete_Subscriptions_destroy_2;
    "/api/projects/{project_id}/surveys/{id}/": Endpoints.delete_Surveys_destroy;
    "/api/projects/{project_id}/tasks/{id}/": Endpoints.delete_Tasks_destroy;
    "/api/projects/{project_id}/warehouse_saved_queries/{id}/": Endpoints.delete_Warehouse_saved_queries_destroy_2;
    "/api/projects/{project_id}/warehouse_tables/{id}/": Endpoints.delete_Warehouse_tables_destroy_2;
    "/api/projects/{project_id}/web_experiments/{id}/": Endpoints.delete_Web_experiments_destroy;
    "/api/users/{uuid}/": Endpoints.delete_Users_destroy;
  };
};

// </EndpointByMethod>

// <EndpointByMethod.Shorthands>
export type GetEndpoints = EndpointByMethod["get"];
export type PostEndpoints = EndpointByMethod["post"];
export type PutEndpoints = EndpointByMethod["put"];
export type PatchEndpoints = EndpointByMethod["patch"];
export type DeleteEndpoints = EndpointByMethod["delete"];
// </EndpointByMethod.Shorthands>

// <ApiClientTypes>
export type EndpointParameters = {
  body?: unknown;
  query?: Record<string, unknown>;
  header?: Record<string, unknown>;
  path?: Record<string, unknown>;
};

export type MutationMethod = "post" | "put" | "patch" | "delete";
export type Method = "get" | "head" | "options" | MutationMethod;

type RequestFormat = "json" | "form-data" | "form-url" | "binary" | "text";

export type DefaultEndpoint = {
  parameters?: EndpointParameters | undefined;
  responses?: Record<string, unknown>;
  responseHeaders?: Record<string, unknown>;
};

export type Endpoint<TConfig extends DefaultEndpoint = DefaultEndpoint> = {
  operationId: string;
  method: Method;
  path: string;
  requestFormat: RequestFormat;
  parameters?: TConfig["parameters"];
  meta: {
    alias: string;
    hasParameters: boolean;
    areParametersRequired: boolean;
  };
  responses?: TConfig["responses"];
  responseHeaders?: TConfig["responseHeaders"];
};

export interface Fetcher {
  decodePathParams?: (path: string, pathParams: Record<string, string>) => string;
  encodeSearchParams?: (searchParams: Record<string, unknown> | undefined) => URLSearchParams;
  //
  fetch: (input: {
    method: Method;
    url: URL;
    urlSearchParams?: URLSearchParams | undefined;
    parameters?: EndpointParameters | undefined;
    path: string;
    overrides?: RequestInit;
    throwOnStatusError?: boolean;
  }) => Promise<Response>;
  parseResponseData?: (response: Response) => Promise<unknown>;
}

export const successStatusCodes = [
  200, 201, 202, 203, 204, 205, 206, 207, 208, 226, 300, 301, 302, 303, 304, 305, 306, 307, 308,
] as const;
export type SuccessStatusCode = (typeof successStatusCodes)[number];

export const errorStatusCodes = [
  400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414, 415, 416, 417, 418, 421, 422, 423, 424,
  425, 426, 428, 429, 431, 451, 500, 501, 502, 503, 504, 505, 506, 507, 508, 510, 511,
] as const;
export type ErrorStatusCode = (typeof errorStatusCodes)[number];

// Taken from https://github.com/unjs/fetchdts/blob/ec4eaeab5d287116171fc1efd61f4a1ad34e4609/src/fetch.ts#L3
export interface TypedHeaders<TypedHeaderValues extends Record<string, string> | unknown>
  extends Omit<Headers, "append" | "delete" | "get" | "getSetCookie" | "has" | "set" | "forEach"> {
  /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/append) */
  append: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
    name: Name,
    value: Lowercase<Name> extends keyof TypedHeaderValues ? TypedHeaderValues[Lowercase<Name>] : string,
  ) => void;
  /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/delete) */
  delete: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(name: Name) => void;
  /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/get) */
  get: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
    name: Name,
  ) => (Lowercase<Name> extends keyof TypedHeaderValues ? TypedHeaderValues[Lowercase<Name>] : string) | null;
  /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/getSetCookie) */
  getSetCookie: () => string[];
  /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/has) */
  has: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(name: Name) => boolean;
  /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/set) */
  set: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
    name: Name,
    value: Lowercase<Name> extends keyof TypedHeaderValues ? TypedHeaderValues[Lowercase<Name>] : string,
  ) => void;
  forEach: (
    callbackfn: (
      value: TypedHeaderValues[keyof TypedHeaderValues] | (string & {}),
      key: Extract<keyof TypedHeaderValues, string> | (string & {}),
      parent: TypedHeaders<TypedHeaderValues>,
    ) => void,
    thisArg?: any,
  ) => void;
}

/** @see https://developer.mozilla.org/en-US/docs/Web/API/Response */
export interface TypedSuccessResponse<TSuccess, TStatusCode, THeaders>
  extends Omit<Response, "ok" | "status" | "json" | "headers"> {
  ok: true;
  status: TStatusCode;
  headers: never extends THeaders ? Headers : TypedHeaders<THeaders>;
  data: TSuccess;
  /** [MDN Reference](https://developer.mozilla.org/en-US/docs/Web/API/Response/json) */
  json: () => Promise<TSuccess>;
}

/** @see https://developer.mozilla.org/en-US/docs/Web/API/Response */
export interface TypedErrorResponse<TData, TStatusCode, THeaders>
  extends Omit<Response, "ok" | "status" | "json" | "headers"> {
  ok: false;
  status: TStatusCode;
  headers: never extends THeaders ? Headers : TypedHeaders<THeaders>;
  data: TData;
  /** [MDN Reference](https://developer.mozilla.org/en-US/docs/Web/API/Response/json) */
  json: () => Promise<TData>;
}

export type TypedApiResponse<TAllResponses extends Record<string | number, unknown> = {}, THeaders = {}> = {
  [K in keyof TAllResponses]: K extends string
    ? K extends `${infer TStatusCode extends number}`
      ? TStatusCode extends SuccessStatusCode
        ? TypedSuccessResponse<TAllResponses[K], TStatusCode, K extends keyof THeaders ? THeaders[K] : never>
        : TypedErrorResponse<TAllResponses[K], TStatusCode, K extends keyof THeaders ? THeaders[K] : never>
      : never
    : K extends number
      ? K extends SuccessStatusCode
        ? TypedSuccessResponse<TAllResponses[K], K, K extends keyof THeaders ? THeaders[K] : never>
        : TypedErrorResponse<TAllResponses[K], K, K extends keyof THeaders ? THeaders[K] : never>
      : never;
}[keyof TAllResponses];

export type SafeApiResponse<TEndpoint> = TEndpoint extends { responses: infer TResponses }
  ? TResponses extends Record<string, unknown>
    ? TypedApiResponse<TResponses, TEndpoint extends { responseHeaders: infer THeaders } ? THeaders : never>
    : never
  : never;

export type InferResponseByStatus<TEndpoint, TStatusCode> = Extract<
  SafeApiResponse<TEndpoint>,
  { status: TStatusCode }
>;

type RequiredKeys<T> = {
  [P in keyof T]-?: undefined extends T[P] ? never : P;
}[keyof T];

type MaybeOptionalArg<T> = RequiredKeys<T> extends never ? [config?: T] : [config: T];
type NotNever<T> = [T] extends [never] ? false : true;

// </ApiClientTypes>

// <TypedStatusError>
export class TypedStatusError<TData = unknown> extends Error {
  response: TypedErrorResponse<TData, ErrorStatusCode, unknown>;
  status: number;
  constructor(response: TypedErrorResponse<TData, ErrorStatusCode, unknown>) {
    super(`HTTP ${response.status}: ${response.statusText}`);
    this.name = "TypedStatusError";
    this.response = response;
    this.status = response.status;
  }
}
// </TypedStatusError>

// <ApiClient>
export class ApiClient {
  baseUrl: string = "";
  successStatusCodes = successStatusCodes;
  errorStatusCodes = errorStatusCodes;

  constructor(public fetcher: Fetcher) {}

  setBaseUrl(baseUrl: string) {
    this.baseUrl = baseUrl;
    return this;
  }

  /**
   * Replace path parameters in URL
   * Supports both OpenAPI format {param} and Express format :param
   */
  defaultDecodePathParams = (url: string, params: Record<string, string>): string => {
    return url
      .replace(/{(\w+)}/g, (_, key: string) => params[key] || `{${key}}`)
      .replace(/:([a-zA-Z0-9_]+)/g, (_, key: string) => params[key] || `:${key}`);
  };

  /** Uses URLSearchParams, skips null/undefined values */
  defaultEncodeSearchParams = (queryParams: Record<string, unknown> | undefined): URLSearchParams | undefined => {
    if (!queryParams) return;

    const searchParams = new URLSearchParams();
    Object.entries(queryParams).forEach(([key, value]) => {
      if (value != null) {
        // Skip null/undefined values
        if (Array.isArray(value)) {
          value.forEach((val) => val != null && searchParams.append(key, String(val)));
        } else {
          searchParams.append(key, String(value));
        }
      }
    });

    return searchParams;
  };

  defaultParseResponseData = async (response: Response): Promise<unknown> => {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.startsWith("text/")) {
      return await response.text();
    }

    if (contentType === "application/octet-stream") {
      return await response.arrayBuffer();
    }

    if (
      contentType.includes("application/json") ||
      (contentType.includes("application/") && contentType.includes("json")) ||
      contentType === "*/*"
    ) {
      try {
        return await response.json();
      } catch {
        return undefined;
      }
    }

    return;
  };

  // <ApiClient.get>
  get<Path extends keyof GetEndpoints, TEndpoint extends GetEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
    >
  ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>["data"]>;

  get<Path extends keyof GetEndpoints, TEndpoint extends GetEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
    >
  ): Promise<SafeApiResponse<TEndpoint>>;

  get<Path extends keyof GetEndpoints, _TEndpoint extends GetEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<any>
  ): Promise<any> {
    return this.request("get", path, ...params);
  }
  // </ApiClient.get>

  // <ApiClient.post>
  post<Path extends keyof PostEndpoints, TEndpoint extends PostEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
    >
  ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>["data"]>;

  post<Path extends keyof PostEndpoints, TEndpoint extends PostEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
    >
  ): Promise<SafeApiResponse<TEndpoint>>;

  post<Path extends keyof PostEndpoints, _TEndpoint extends PostEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<any>
  ): Promise<any> {
    return this.request("post", path, ...params);
  }
  // </ApiClient.post>

  // <ApiClient.put>
  put<Path extends keyof PutEndpoints, TEndpoint extends PutEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
    >
  ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>["data"]>;

  put<Path extends keyof PutEndpoints, TEndpoint extends PutEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
    >
  ): Promise<SafeApiResponse<TEndpoint>>;

  put<Path extends keyof PutEndpoints, _TEndpoint extends PutEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<any>
  ): Promise<any> {
    return this.request("put", path, ...params);
  }
  // </ApiClient.put>

  // <ApiClient.patch>
  patch<Path extends keyof PatchEndpoints, TEndpoint extends PatchEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
    >
  ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>["data"]>;

  patch<Path extends keyof PatchEndpoints, TEndpoint extends PatchEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
    >
  ): Promise<SafeApiResponse<TEndpoint>>;

  patch<Path extends keyof PatchEndpoints, _TEndpoint extends PatchEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<any>
  ): Promise<any> {
    return this.request("patch", path, ...params);
  }
  // </ApiClient.patch>

  // <ApiClient.delete>
  delete<Path extends keyof DeleteEndpoints, TEndpoint extends DeleteEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
    >
  ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>["data"]>;

  delete<Path extends keyof DeleteEndpoints, TEndpoint extends DeleteEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
    >
  ): Promise<SafeApiResponse<TEndpoint>>;

  delete<Path extends keyof DeleteEndpoints, _TEndpoint extends DeleteEndpoints[Path]>(
    path: Path,
    ...params: MaybeOptionalArg<any>
  ): Promise<any> {
    return this.request("delete", path, ...params);
  }
  // </ApiClient.delete>

  // <ApiClient.request>
  /**
   * Generic request method with full type-safety for any endpoint
   */
  request<
    TMethod extends keyof EndpointByMethod,
    TPath extends keyof EndpointByMethod[TMethod],
    TEndpoint extends EndpointByMethod[TMethod][TPath],
  >(
    method: TMethod,
    path: TPath,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
    >
  ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>["data"]>;

  request<
    TMethod extends keyof EndpointByMethod,
    TPath extends keyof EndpointByMethod[TMethod],
    TEndpoint extends EndpointByMethod[TMethod][TPath],
  >(
    method: TMethod,
    path: TPath,
    ...params: MaybeOptionalArg<
      TEndpoint extends { parameters: infer UParams }
        ? NotNever<UParams> extends true
          ? UParams & { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
          : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
    >
  ): Promise<SafeApiResponse<TEndpoint>>;

  request<
    TMethod extends keyof EndpointByMethod,
    TPath extends keyof EndpointByMethod[TMethod],
    TEndpoint extends EndpointByMethod[TMethod][TPath],
  >(method: TMethod, path: TPath, ...params: MaybeOptionalArg<any>): Promise<any> {
    const requestParams = params[0];
    const withResponse = requestParams?.withResponse;
    const {
      withResponse: _,
      throwOnStatusError = withResponse ? false : true,
      overrides,
      ...fetchParams
    } = requestParams || {};

    const parametersToSend: EndpointParameters = {};
    if (requestParams?.body !== undefined) (parametersToSend as any).body = requestParams.body;
    if (requestParams?.query !== undefined) (parametersToSend as any).query = requestParams.query;
    if (requestParams?.header !== undefined) (parametersToSend as any).header = requestParams.header;
    if (requestParams?.path !== undefined) (parametersToSend as any).path = requestParams.path;

    const resolvedPath = (this.fetcher.decodePathParams ?? this.defaultDecodePathParams)(
      this.baseUrl + (path as string),
      (parametersToSend.path ?? {}) as Record<string, string>,
    );
    const url = new URL(resolvedPath);
    const urlSearchParams = (this.fetcher.encodeSearchParams ?? this.defaultEncodeSearchParams)(parametersToSend.query);

    const promise = this.fetcher
      .fetch({
        method: method,
        path: path as string,
        url,
        urlSearchParams,
        parameters: Object.keys(fetchParams).length ? fetchParams : undefined,
        overrides,
        throwOnStatusError,
      })
      .then(async (response) => {
        const data = await (this.fetcher.parseResponseData ?? this.defaultParseResponseData)(response);
        const typedResponse = Object.assign(response, {
          data: data,
          json: () => Promise.resolve(data),
        }) as SafeApiResponse<TEndpoint>;

        if (throwOnStatusError && errorStatusCodes.includes(response.status as never)) {
          throw new TypedStatusError(typedResponse as never);
        }

        return withResponse ? typedResponse : data;
      });

    return promise as Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>["data"];
  }
  // </ApiClient.request>
}

export function createApiClient(fetcher: Fetcher, baseUrl?: string) {
  return new ApiClient(fetcher).setBaseUrl(baseUrl ?? "");
}

/**
 Example usage:
 const api = createApiClient((method, url, params) =>
   fetch(url, { method, body: JSON.stringify(params) }).then((res) => res.json()),
 );
 api.get("/users").then((users) => console.log(users));
 api.post("/users", { body: { name: "John" } }).then((user) => console.log(user));
 api.put("/users/:id", { path: { id: 1 }, body: { name: "John" } }).then((user) => console.log(user));

 // With error handling
 const result = await api.get("/users/{id}", { path: { id: "123" }, withResponse: true });
 if (result.ok) {
   // Access data directly
   const user = result.data;
   console.log(user);

   // Or use the json() method for compatibility
   const userFromJson = await result.json();
   console.log(userFromJson);
 } else {
   const error = result.data;
   console.error(`Error ${result.status}:`, error);
 }
*/

// </ApiClient>
