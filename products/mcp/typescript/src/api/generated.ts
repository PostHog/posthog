export namespace Schemas {
    // <Schemas>
    export type AIEventType =
        | '$ai_generation'
        | '$ai_embedding'
        | '$ai_span'
        | '$ai_trace'
        | '$ai_metric'
        | '$ai_feedback'
    export type UrlMatchingEnum = 'contains' | 'regex' | 'exact'
    export type NullEnum = null
    export type ActionStepJSON = Partial<{
        event: string | null
        properties: Array<Record<string, unknown>> | null
        selector: string | null
        tag_name: string | null
        text: string | null
        text_matching: (UrlMatchingEnum | NullEnum) | null
        href: string | null
        href_matching: (UrlMatchingEnum | NullEnum) | null
        url: string | null
        url_matching: (UrlMatchingEnum | NullEnum) | null
    }>
    export type RoleAtOrganizationEnum =
        | 'engineering'
        | 'data'
        | 'product'
        | 'founder'
        | 'leadership'
        | 'marketing'
        | 'sales'
        | 'other'
    export type BlankEnum = ''
    export type UserBasic = {
        id: number
        uuid: string
        distinct_id?: (string | null) | undefined
        first_name?: string | undefined
        last_name?: string | undefined
        email: string
        is_email_verified?: (boolean | null) | undefined
        hedgehog_config: Record<string, unknown> | null
        role_at_organization?: ((RoleAtOrganizationEnum | BlankEnum | NullEnum) | null) | undefined
    }
    export type Action = {
        id: number
        name?: (string | null) | undefined
        description?: string | undefined
        tags?: Array<unknown> | undefined
        post_to_slack?: boolean | undefined
        slack_message_format?: string | undefined
        steps?: Array<ActionStepJSON> | undefined
        created_at: string
        created_by: UserBasic & unknown
        deleted?: boolean | undefined
        is_calculating: boolean
        last_calculated_at?: string | undefined
        team_id: number
        is_action: boolean
        bytecode_error: string | null
        pinned_at?: (string | null) | undefined
        creation_context: string
        _create_in_folder?: string | undefined
    }
    export type ActionConversionGoal = { actionId: number }
    export type PropertyOperator =
        | 'exact'
        | 'is_not'
        | 'icontains'
        | 'not_icontains'
        | 'regex'
        | 'not_regex'
        | 'gt'
        | 'gte'
        | 'lt'
        | 'lte'
        | 'is_set'
        | 'is_not_set'
        | 'is_date_exact'
        | 'is_date_before'
        | 'is_date_after'
        | 'between'
        | 'not_between'
        | 'min'
        | 'max'
        | 'in'
        | 'not_in'
        | 'is_cleaned_path_exact'
        | 'flag_evaluates_to'
    export type EventPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator?: (PropertyOperator | null) | undefined
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type PersonPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type Key = 'tag_name' | 'text' | 'href' | 'selector'
    export type ElementPropertyFilter = {
        key: Key
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type EventMetadataPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type SessionPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type CohortPropertyFilter = {
        cohort_name?: (string | null) | undefined
        key?: string | undefined
        label?: (string | null) | undefined
        operator?: (PropertyOperator | null) | undefined
        type?: string | undefined
        value: number
    }
    export type DurationType = 'duration' | 'active_seconds' | 'inactive_seconds'
    export type RecordingPropertyFilter = {
        key: DurationType | string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type LogEntryPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type GroupPropertyFilter = {
        group_type_index?: (number | null) | undefined
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type FeaturePropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type FlagPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator?: string | undefined
        type?: string | undefined
        value: boolean | string
    }
    export type HogQLPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type EmptyPropertyFilter = Partial<{}>
    export type DataWarehousePropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type DataWarehousePersonPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type ErrorTrackingIssueFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type LogPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type RevenueAnalyticsPropertyFilter = {
        key: string
        label?: (string | null) | undefined
        operator: PropertyOperator
        type?: string | undefined
        value?: (Array<string | number | boolean> | string | number | boolean | null) | undefined
    }
    export type BaseMathType =
        | 'total'
        | 'dau'
        | 'weekly_active'
        | 'monthly_active'
        | 'unique_session'
        | 'first_time_for_user'
        | 'first_matching_event_for_user'
    export type FunnelMathType =
        | 'total'
        | 'first_time_for_user'
        | 'first_time_for_user_with_filters'
    export type PropertyMathType =
        | 'avg'
        | 'sum'
        | 'min'
        | 'max'
        | 'median'
        | 'p75'
        | 'p90'
        | 'p95'
        | 'p99'
    export type CountPerActorMathType =
        | 'avg_count_per_actor'
        | 'min_count_per_actor'
        | 'max_count_per_actor'
        | 'median_count_per_actor'
        | 'p75_count_per_actor'
        | 'p90_count_per_actor'
        | 'p95_count_per_actor'
        | 'p99_count_per_actor'
    export type ExperimentMetricMathType =
        | 'total'
        | 'sum'
        | 'unique_session'
        | 'min'
        | 'max'
        | 'avg'
        | 'dau'
        | 'unique_group'
        | 'hogql'
    export type CalendarHeatmapMathType = 'total' | 'dau'
    export type MathGroupTypeIndex = 0 | 1 | 2 | 3 | 4
    export type CurrencyCode =
        | 'AED'
        | 'AFN'
        | 'ALL'
        | 'AMD'
        | 'ANG'
        | 'AOA'
        | 'ARS'
        | 'AUD'
        | 'AWG'
        | 'AZN'
        | 'BAM'
        | 'BBD'
        | 'BDT'
        | 'BGN'
        | 'BHD'
        | 'BIF'
        | 'BMD'
        | 'BND'
        | 'BOB'
        | 'BRL'
        | 'BSD'
        | 'BTC'
        | 'BTN'
        | 'BWP'
        | 'BYN'
        | 'BZD'
        | 'CAD'
        | 'CDF'
        | 'CHF'
        | 'CLP'
        | 'CNY'
        | 'COP'
        | 'CRC'
        | 'CVE'
        | 'CZK'
        | 'DJF'
        | 'DKK'
        | 'DOP'
        | 'DZD'
        | 'EGP'
        | 'ERN'
        | 'ETB'
        | 'EUR'
        | 'FJD'
        | 'GBP'
        | 'GEL'
        | 'GHS'
        | 'GIP'
        | 'GMD'
        | 'GNF'
        | 'GTQ'
        | 'GYD'
        | 'HKD'
        | 'HNL'
        | 'HRK'
        | 'HTG'
        | 'HUF'
        | 'IDR'
        | 'ILS'
        | 'INR'
        | 'IQD'
        | 'IRR'
        | 'ISK'
        | 'JMD'
        | 'JOD'
        | 'JPY'
        | 'KES'
        | 'KGS'
        | 'KHR'
        | 'KMF'
        | 'KRW'
        | 'KWD'
        | 'KYD'
        | 'KZT'
        | 'LAK'
        | 'LBP'
        | 'LKR'
        | 'LRD'
        | 'LTL'
        | 'LVL'
        | 'LSL'
        | 'LYD'
        | 'MAD'
        | 'MDL'
        | 'MGA'
        | 'MKD'
        | 'MMK'
        | 'MNT'
        | 'MOP'
        | 'MRU'
        | 'MTL'
        | 'MUR'
        | 'MVR'
        | 'MWK'
        | 'MXN'
        | 'MYR'
        | 'MZN'
        | 'NAD'
        | 'NGN'
        | 'NIO'
        | 'NOK'
        | 'NPR'
        | 'NZD'
        | 'OMR'
        | 'PAB'
        | 'PEN'
        | 'PGK'
        | 'PHP'
        | 'PKR'
        | 'PLN'
        | 'PYG'
        | 'QAR'
        | 'RON'
        | 'RSD'
        | 'RUB'
        | 'RWF'
        | 'SAR'
        | 'SBD'
        | 'SCR'
        | 'SDG'
        | 'SEK'
        | 'SGD'
        | 'SRD'
        | 'SSP'
        | 'STN'
        | 'SYP'
        | 'SZL'
        | 'THB'
        | 'TJS'
        | 'TMT'
        | 'TND'
        | 'TOP'
        | 'TRY'
        | 'TTD'
        | 'TWD'
        | 'TZS'
        | 'UAH'
        | 'UGX'
        | 'USD'
        | 'UYU'
        | 'UZS'
        | 'VES'
        | 'VND'
        | 'VUV'
        | 'WST'
        | 'XAF'
        | 'XCD'
        | 'XOF'
        | 'XPF'
        | 'YER'
        | 'ZAR'
        | 'ZMW'
    export type RevenueCurrencyPropertyConfig = Partial<{
        property: string | null
        static: CurrencyCode | null
    }>
    export type ActionsNode = {
        custom_name?: (string | null) | undefined
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
            | undefined
        id: number
        kind?: string | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        version?: (number | null) | undefined
    }
    export type ActionsPie = Partial<{
        disableHoverOffset: boolean | null
        hideAggregation: boolean | null
    }>
    export type ActivityLog = {
        id: string
        user: UserBasic
        unread: boolean
        organization_id?: (string | null) | undefined
        was_impersonated?: (boolean | null) | undefined
        is_system?: (boolean | null) | undefined
        activity: string
        item_id?: (string | null) | undefined
        scope: string
        detail?: (unknown | null) | undefined
        created_at?: string | undefined
    }
    export type BounceRatePageViewMode =
        | 'count_pageviews'
        | 'uniq_urls'
        | 'uniq_page_screen_autocaptures'
    export type FilterLogicalOperator = 'AND' | 'OR'
    export type CustomChannelField =
        | 'utm_source'
        | 'utm_medium'
        | 'utm_campaign'
        | 'referring_domain'
        | 'url'
        | 'pathname'
        | 'hostname'
    export type CustomChannelOperator =
        | 'exact'
        | 'is_not'
        | 'is_set'
        | 'is_not_set'
        | 'icontains'
        | 'not_icontains'
        | 'regex'
        | 'not_regex'
    export type CustomChannelCondition = {
        id: string
        key: CustomChannelField
        op: CustomChannelOperator
        value?: (string | Array<string> | null) | undefined
    }
    export type CustomChannelRule = {
        channel_type: string
        combiner: FilterLogicalOperator
        id: string
        items: Array<CustomChannelCondition>
    }
    export type DataWarehouseEventsModifier = {
        distinct_id_field: string
        id_field: string
        table_name: string
        timestamp_field: string
    }
    export type InCohortVia = 'auto' | 'leftjoin' | 'subquery' | 'leftjoin_conjoined'
    export type MaterializationMode =
        | 'auto'
        | 'legacy_null_as_string'
        | 'legacy_null_as_null'
        | 'disabled'
    export type PersonsArgMaxVersion = 'auto' | 'v1' | 'v2'
    export type PersonsJoinMode = 'inner' | 'left'
    export type PersonsOnEventsMode =
        | 'disabled'
        | 'person_id_no_override_properties_on_events'
        | 'person_id_override_properties_on_events'
        | 'person_id_override_properties_joined'
    export type PropertyGroupsMode = 'enabled' | 'disabled' | 'optimized'
    export type SessionTableVersion = 'auto' | 'v1' | 'v2'
    export type SessionsV2JoinMode = 'string' | 'uuid'
    export type HogQLQueryModifiers = Partial<{
        bounceRateDurationSeconds: number | null
        bounceRatePageViewMode: BounceRatePageViewMode | null
        convertToProjectTimezone: boolean | null
        customChannelTypeRules: Array<CustomChannelRule> | null
        dataWarehouseEventsModifiers: Array<DataWarehouseEventsModifier> | null
        debug: boolean | null
        formatCsvAllowDoubleQuotes: boolean | null
        inCohortVia: InCohortVia | null
        materializationMode: MaterializationMode | null
        optimizeJoinedFilters: boolean | null
        personsArgMaxVersion: PersonsArgMaxVersion | null
        personsJoinMode: PersonsJoinMode | null
        personsOnEventsMode: PersonsOnEventsMode | null
        propertyGroupsMode: PropertyGroupsMode | null
        s3TableUseInvalidColumns: boolean | null
        sessionTableVersion: SessionTableVersion | null
        sessionsV2JoinMode: SessionsV2JoinMode | null
        timings: boolean | null
        useMaterializedViews: boolean | null
        usePreaggregatedTableTransforms: boolean | null
        usePresortedEventsTable: boolean | null
        useWebAnalyticsPreAggregatedTables: boolean | null
    }>
    export type ClickhouseQueryProgress = {
        active_cpu_time: number
        bytes_read: number
        estimated_rows_total: number
        rows_read: number
        time_elapsed: number
    }
    export type QueryStatus = {
        complete?: (boolean | null) | undefined
        dashboard_id?: (number | null) | undefined
        end_time?: (string | null) | undefined
        error?: (boolean | null) | undefined
        error_message?: (string | null) | undefined
        expiration_time?: (string | null) | undefined
        id: string
        insight_id?: (number | null) | undefined
        labels?: (Array<string> | null) | undefined
        pickup_time?: (string | null) | undefined
        query_async?: boolean | undefined
        query_progress?: (ClickhouseQueryProgress | null) | undefined
        results?: (unknown | null) | undefined
        start_time?: (string | null) | undefined
        task_id?: (string | null) | undefined
        team_id: number
    }
    export type ResolvedDateRangeResponse = { date_from: string; date_to: string }
    export type ActorsPropertyTaxonomyResponse = {
        sample_count: number
        sample_values: Array<string | number | boolean | number>
    }
    export type QueryTiming = { k: string; t: number }
    export type ActorsPropertyTaxonomyQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: ActorsPropertyTaxonomyResponse | Array<ActorsPropertyTaxonomyResponse>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryLogTags = Partial<{ productKey: string | null; scene: string | null }>
    export type ActorsPropertyTaxonomyQuery = {
        groupTypeIndex?: (number | null) | undefined
        kind?: string | undefined
        maxPropertyValues?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties: Array<string>
        response?: (ActorsPropertyTaxonomyQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type PropertyGroupFilterValue = {
        type: FilterLogicalOperator
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
        >
    }
    export type ActorsQueryResponse = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit: number
        missing_actors_count?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<string> | null) | undefined
    }
    export type Compare = 'current' | 'previous'
    export type BreakdownType =
        | 'cohort'
        | 'person'
        | 'event'
        | 'event_metadata'
        | 'group'
        | 'session'
        | 'hogql'
        | 'data_warehouse'
        | 'data_warehouse_person_property'
        | 'revenue_analytics'
    export type MultipleBreakdownType =
        | 'cohort'
        | 'person'
        | 'event'
        | 'event_metadata'
        | 'group'
        | 'session'
        | 'hogql'
        | 'revenue_analytics'
    export type Breakdown = {
        group_type_index?: (number | null) | undefined
        histogram_bin_count?: (number | null) | undefined
        normalize_url?: (boolean | null) | undefined
        property: string | number
        type?: (MultipleBreakdownType | null) | undefined
    }
    export type BreakdownFilter = Partial<{
        breakdown: string | Array<string | number> | number | null
        breakdown_group_type_index: number | null
        breakdown_hide_other_aggregation: boolean | null
        breakdown_histogram_bin_count: number | null
        breakdown_limit: number | null
        breakdown_normalize_url: boolean | null
        breakdown_type: BreakdownType | null
        breakdowns: Array<Breakdown> | null
    }>
    export type CompareFilter = Partial<{ compare: boolean | null; compare_to: string | null }>
    export type CustomEventConversionGoal = { customEventName: string }
    export type DateRange = Partial<{
        date_from: string | null
        date_to: string | null
        explicitDate: boolean | null
    }>
    export type IntervalType = 'minute' | 'hour' | 'day' | 'week' | 'month'
    export type PropertyGroupFilter = {
        type: FilterLogicalOperator
        values: Array<PropertyGroupFilterValue>
    }
    export type TrendsQueryResponse = {
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Record<string, unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type EventsNode = Partial<{
        custom_name: string | null
        event: string | null
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
        > | null
        kind: string
        limit: number | null
        math:
            | BaseMathType
            | FunnelMathType
            | PropertyMathType
            | CountPerActorMathType
            | ExperimentMetricMathType
            | CalendarHeatmapMathType
            | string
            | string
            | null
        math_group_type_index: MathGroupTypeIndex | null
        math_hogql: string | null
        math_multiplier: number | null
        math_property: string | null
        math_property_revenue_currency: RevenueCurrencyPropertyConfig | null
        math_property_type: string | null
        name: string | null
        orderBy: Array<string> | null
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
        > | null
        response: Record<string, unknown> | null
        version: number | null
    }>
    export type DataWarehouseNode = {
        custom_name?: (string | null) | undefined
        distinct_id_field: string
        dw_source_type?: (string | null) | undefined
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
            | undefined
        id: string
        id_field: string
        kind?: string | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        table_name: string
        timestamp_field: string
        version?: (number | null) | undefined
    }
    export type AggregationAxisFormat =
        | 'numeric'
        | 'duration'
        | 'duration_ms'
        | 'percentage'
        | 'percentage_scaled'
    export type ChartDisplayType =
        | 'ActionsLineGraph'
        | 'ActionsBar'
        | 'ActionsStackedBar'
        | 'ActionsAreaGraph'
        | 'ActionsLineGraphCumulative'
        | 'BoldNumber'
        | 'ActionsPie'
        | 'ActionsBarValue'
        | 'ActionsTable'
        | 'WorldMap'
        | 'CalendarHeatmap'
    export type TrendsFormulaNode = { custom_name?: (string | null) | undefined; formula: string }
    export type GoalLine = {
        borderColor?: (string | null) | undefined
        displayIfCrossed?: (boolean | null) | undefined
        displayLabel?: (boolean | null) | undefined
        label: string
        value: number
    }
    export type ResultCustomizationBy = 'value' | 'position'
    export type DataColorToken =
        | 'preset-1'
        | 'preset-2'
        | 'preset-3'
        | 'preset-4'
        | 'preset-5'
        | 'preset-6'
        | 'preset-7'
        | 'preset-8'
        | 'preset-9'
        | 'preset-10'
        | 'preset-11'
        | 'preset-12'
        | 'preset-13'
        | 'preset-14'
        | 'preset-15'
    export type ResultCustomizationByValue = Partial<{
        assignmentBy: string
        color: DataColorToken | null
        hidden: boolean | null
    }>
    export type ResultCustomizationByPosition = Partial<{
        assignmentBy: string
        color: DataColorToken | null
        hidden: boolean | null
    }>
    export type YAxisScaleType = 'log10' | 'linear'
    export type TrendsFilter = Partial<{
        aggregationAxisFormat: AggregationAxisFormat | null
        aggregationAxisPostfix: string | null
        aggregationAxisPrefix: string | null
        breakdown_histogram_bin_count: number | null
        confidenceLevel: number | null
        decimalPlaces: number | null
        display: ChartDisplayType | null
        formula: string | null
        formulaNodes: Array<TrendsFormulaNode> | null
        formulas: Array<string> | null
        goalLines: Array<GoalLine> | null
        hiddenLegendIndexes: Array<number> | null
        minDecimalPlaces: number | null
        movingAverageIntervals: number | null
        resultCustomizationBy: ResultCustomizationBy | null
        resultCustomizations: Record<string, unknown> | Record<string, unknown> | null
        showAlertThresholdLines: boolean | null
        showConfidenceIntervals: boolean | null
        showLabelsOnSeries: boolean | null
        showLegend: boolean | null
        showMovingAverage: boolean | null
        showMultipleYAxes: boolean | null
        showPercentStackView: boolean | null
        showTrendLines: boolean | null
        showValuesOnSeries: boolean | null
        smoothingIntervals: number | null
        yAxisScaleType: YAxisScaleType | null
    }>
    export type TrendsQuery = {
        aggregation_group_type_index?: (number | null) | undefined
        breakdownFilter?: (BreakdownFilter | null) | undefined
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dataColorTheme?: (number | null) | undefined
        dateRange?: (DateRange | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        interval?: (IntervalType | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties?:
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
                  | null
              )
            | undefined
        response?: (TrendsQueryResponse | null) | undefined
        samplingFactor?: (number | null) | undefined
        series: Array<EventsNode | ActionsNode | DataWarehouseNode>
        tags?: (QueryLogTags | null) | undefined
        trendsFilter?: (TrendsFilter | null) | undefined
        version?: (number | null) | undefined
    }
    export type BreakdownAttributionType = 'first_touch' | 'last_touch' | 'all_events' | 'step'
    export type FunnelExclusionEventsNode = {
        custom_name?: (string | null) | undefined
        event?: (string | null) | undefined
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
            | undefined
        funnelFromStep: number
        funnelToStep: number
        kind?: string | undefined
        limit?: (number | null) | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
        orderBy?: (Array<string> | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        version?: (number | null) | undefined
    }
    export type FunnelExclusionActionsNode = {
        custom_name?: (string | null) | undefined
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
            | undefined
        funnelFromStep: number
        funnelToStep: number
        id: number
        kind?: string | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        version?: (number | null) | undefined
    }
    export type StepOrderValue = 'strict' | 'unordered' | 'ordered'
    export type FunnelStepReference = 'total' | 'previous'
    export type FunnelVizType = 'steps' | 'time_to_convert' | 'trends'
    export type FunnelConversionWindowTimeUnit =
        | 'second'
        | 'minute'
        | 'hour'
        | 'day'
        | 'week'
        | 'month'
    export type FunnelLayout = 'horizontal' | 'vertical'
    export type FunnelsFilter = Partial<{
        binCount: number | null
        breakdownAttributionType: BreakdownAttributionType | null
        breakdownAttributionValue: number | null
        exclusions: Array<FunnelExclusionEventsNode | FunnelExclusionActionsNode> | null
        funnelAggregateByHogQL: string | null
        funnelFromStep: number | null
        funnelOrderType: StepOrderValue | null
        funnelStepReference: FunnelStepReference | null
        funnelToStep: number | null
        funnelVizType: FunnelVizType | null
        funnelWindowInterval: number | null
        funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | null
        goalLines: Array<GoalLine> | null
        hiddenLegendBreakdowns: Array<string> | null
        layout: FunnelLayout | null
        resultCustomizations: Record<string, unknown> | null
        showValuesOnSeries: boolean | null
        useUdf: boolean | null
    }>
    export type FunnelsQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        isUdf?: (boolean | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type FunnelsQuery = {
        aggregation_group_type_index?: (number | null) | undefined
        breakdownFilter?: (BreakdownFilter | null) | undefined
        dataColorTheme?: (number | null) | undefined
        dateRange?: (DateRange | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        funnelsFilter?: (FunnelsFilter | null) | undefined
        interval?: (IntervalType | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties?:
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
                  | null
              )
            | undefined
        response?: (FunnelsQueryResponse | null) | undefined
        samplingFactor?: (number | null) | undefined
        series: Array<EventsNode | ActionsNode | DataWarehouseNode>
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RetentionValue = { count: number; label?: (string | null) | undefined }
    export type RetentionResult = {
        breakdown_value?: (string | number | null) | undefined
        date: string
        label: string
        values: Array<RetentionValue>
    }
    export type RetentionQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RetentionResult>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RetentionDashboardDisplayType = 'table_only' | 'graph_only' | 'all'
    export type MeanRetentionCalculation = 'simple' | 'weighted' | 'none'
    export type RetentionPeriod = 'Hour' | 'Day' | 'Week' | 'Month'
    export type RetentionReference = 'total' | 'previous'
    export type RetentionType =
        | 'retention_recurring'
        | 'retention_first_time'
        | 'retention_first_ever_occurrence'
    export type RetentionEntityKind = 'ActionsNode' | 'EventsNode'
    export type EntityType = 'actions' | 'events' | 'data_warehouse' | 'new_entity'
    export type RetentionEntity = Partial<{
        custom_name: string | null
        id: string | number | null
        kind: RetentionEntityKind | null
        name: string | null
        order: number | null
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
        > | null
        type: EntityType | null
        uuid: string | null
    }>
    export type RetentionFilter = Partial<{
        cumulative: boolean | null
        dashboardDisplay: RetentionDashboardDisplayType | null
        display: ChartDisplayType | null
        meanRetentionCalculation: MeanRetentionCalculation | null
        minimumOccurrences: number | null
        period: RetentionPeriod | null
        retentionReference: RetentionReference | null
        retentionType: RetentionType | null
        returningEntity: RetentionEntity | null
        showTrendLines: boolean | null
        targetEntity: RetentionEntity | null
        totalIntervals: number | null
    }>
    export type RetentionQuery = {
        aggregation_group_type_index?: (number | null) | undefined
        breakdownFilter?: (BreakdownFilter | null) | undefined
        dataColorTheme?: (number | null) | undefined
        dateRange?: (DateRange | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties?:
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
                  | null
              )
            | undefined
        response?: (RetentionQueryResponse | null) | undefined
        retentionFilter: RetentionFilter
        samplingFactor?: (number | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type FunnelPathType =
        | 'funnel_path_before_step'
        | 'funnel_path_between_steps'
        | 'funnel_path_after_step'
    export type FunnelPathsFilter = {
        funnelPathType?: (FunnelPathType | null) | undefined
        funnelSource: FunnelsQuery
        funnelStep?: (number | null) | undefined
    }
    export type PathType = '$pageview' | '$screen' | 'custom_event' | 'hogql'
    export type PathCleaningFilter = Partial<{
        alias: string | null
        order: number | null
        regex: string | null
    }>
    export type PathsFilter = Partial<{
        edgeLimit: number | null
        endPoint: string | null
        excludeEvents: Array<string> | null
        includeEventTypes: Array<PathType> | null
        localPathCleaningFilters: Array<PathCleaningFilter> | null
        maxEdgeWeight: number | null
        minEdgeWeight: number | null
        pathDropoffKey: string | null
        pathEndKey: string | null
        pathGroupings: Array<string> | null
        pathReplacements: boolean | null
        pathStartKey: string | null
        pathsHogQLExpression: string | null
        startPoint: string | null
        stepLimit: number | null
    }>
    export type PathsLink = {
        average_conversion_time: number
        source: string
        target: string
        value: number
    }
    export type PathsQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<PathsLink>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type PathsQuery = {
        aggregation_group_type_index?: (number | null) | undefined
        dataColorTheme?: (number | null) | undefined
        dateRange?: (DateRange | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        funnelPathsFilter?: (FunnelPathsFilter | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        pathsFilter: PathsFilter
        properties?:
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
                  | null
              )
            | undefined
        response?: (PathsQueryResponse | null) | undefined
        samplingFactor?: (number | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type StickinessQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Record<string, unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type StickinessComputationMode = 'non_cumulative' | 'cumulative'
    export type StickinessOperator = 'gte' | 'lte' | 'exact'
    export type StickinessCriteria = { operator: StickinessOperator; value: number }
    export type StickinessFilter = Partial<{
        computedAs: StickinessComputationMode | null
        display: ChartDisplayType | null
        hiddenLegendIndexes: Array<number> | null
        resultCustomizationBy: ResultCustomizationBy | null
        resultCustomizations: Record<string, unknown> | Record<string, unknown> | null
        showLegend: boolean | null
        showMultipleYAxes: boolean | null
        showValuesOnSeries: boolean | null
        stickinessCriteria: StickinessCriteria | null
    }>
    export type StickinessQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        dataColorTheme?: (number | null) | undefined
        dateRange?: (DateRange | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        interval?: (IntervalType | null) | undefined
        intervalCount?: (number | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties?:
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
                  | null
              )
            | undefined
        response?: (StickinessQueryResponse | null) | undefined
        samplingFactor?: (number | null) | undefined
        series: Array<EventsNode | ActionsNode | DataWarehouseNode>
        stickinessFilter?: (StickinessFilter | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type LifecycleToggle = 'new' | 'resurrecting' | 'returning' | 'dormant'
    export type LifecycleFilter = Partial<{
        showLegend: boolean | null
        showValuesOnSeries: boolean | null
        stacked: boolean | null
        toggledLifecycles: Array<LifecycleToggle> | null
    }>
    export type LifecycleQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Record<string, unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type LifecycleQuery = {
        aggregation_group_type_index?: (number | null) | undefined
        dataColorTheme?: (number | null) | undefined
        dateRange?: (DateRange | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        interval?: (IntervalType | null) | undefined
        kind?: string | undefined
        lifecycleFilter?: (LifecycleFilter | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties?:
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
                  | null
              )
            | undefined
        response?: (LifecycleQueryResponse | null) | undefined
        samplingFactor?: (number | null) | undefined
        series: Array<EventsNode | ActionsNode | DataWarehouseNode>
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type InsightActorsQuery = {
        breakdown?: (string | Array<string> | number | null) | undefined
        compare?: (Compare | null) | undefined
        day?: (string | number | null) | undefined
        includeRecordings?: (boolean | null) | undefined
        interval?: (number | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        response?: (ActorsQueryResponse | null) | undefined
        series?: (number | null) | undefined
        source:
            | TrendsQuery
            | FunnelsQuery
            | RetentionQuery
            | PathsQuery
            | StickinessQuery
            | LifecycleQuery
        status?: (string | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type FunnelsActorsQuery = {
        funnelCustomSteps?: (Array<number> | null) | undefined
        funnelStep?: (number | null) | undefined
        funnelStepBreakdown?:
            | (number | string | number | Array<number | string | number> | null)
            | undefined
        funnelTrendsDropOff?: (boolean | null) | undefined
        funnelTrendsEntrancePeriodStart?: (string | null) | undefined
        includeRecordings?: (boolean | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        response?: (ActorsQueryResponse | null) | undefined
        source: FunnelsQuery
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type FunnelCorrelationResultsType = 'events' | 'properties' | 'event_with_properties'
    export type CorrelationType = 'success' | 'failure'
    export type EventDefinition = {
        elements: Array<unknown>
        event: string
        properties: Record<string, unknown>
    }
    export type EventOddsRatioSerialized = {
        correlation_type: CorrelationType
        event: EventDefinition
        failure_count: number
        odds_ratio: number
        success_count: number
    }
    export type FunnelCorrelationResult = {
        events: Array<EventOddsRatioSerialized>
        skewed: boolean
    }
    export type FunnelCorrelationResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: FunnelCorrelationResult
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type FunnelCorrelationQuery = {
        funnelCorrelationEventExcludePropertyNames?: (Array<string> | null) | undefined
        funnelCorrelationEventNames?: (Array<string> | null) | undefined
        funnelCorrelationExcludeEventNames?: (Array<string> | null) | undefined
        funnelCorrelationExcludeNames?: (Array<string> | null) | undefined
        funnelCorrelationNames?: (Array<string> | null) | undefined
        funnelCorrelationType: FunnelCorrelationResultsType
        kind?: string | undefined
        response?: (FunnelCorrelationResponse | null) | undefined
        source: FunnelsActorsQuery
        version?: (number | null) | undefined
    }
    export type FunnelCorrelationActorsQuery = {
        funnelCorrelationPersonConverted?: (boolean | null) | undefined
        funnelCorrelationPersonEntity?:
            | (EventsNode | ActionsNode | DataWarehouseNode | null)
            | undefined
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
            | undefined
        includeRecordings?: (boolean | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        response?: (ActorsQueryResponse | null) | undefined
        source: FunnelCorrelationQuery
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type StickinessActorsQuery = {
        compare?: (Compare | null) | undefined
        day?: (string | number | null) | undefined
        includeRecordings?: (boolean | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        operator?: (StickinessOperator | null) | undefined
        response?: (ActorsQueryResponse | null) | undefined
        series?: (number | null) | undefined
        source: StickinessQuery
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type HogQLFilters = Partial<{
        dateRange: DateRange | null
        filterTestAccounts: boolean | null
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
        > | null
    }>
    export type HogQLNotice = {
        end?: (number | null) | undefined
        fix?: (string | null) | undefined
        message: string
        start?: (number | null) | undefined
    }
    export type QueryIndexUsage = 'undecisive' | 'no' | 'partial' | 'yes'
    export type HogQLMetadataResponse = {
        errors: Array<HogQLNotice>
        isUsingIndices?: (QueryIndexUsage | null) | undefined
        isValid?: (boolean | null) | undefined
        notices: Array<HogQLNotice>
        query?: (string | null) | undefined
        table_names?: (Array<string> | null) | undefined
        warnings: Array<HogQLNotice>
    }
    export type HogQLQueryResponse = {
        clickhouse?: (string | null) | undefined
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        explain?: (Array<string> | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        metadata?: (HogQLMetadataResponse | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query?: (string | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type HogQLVariable = {
        code_name: string
        isNull?: (boolean | null) | undefined
        value?: (unknown | null) | undefined
        variableId: string
    }
    export type HogQLQuery = {
        explain?: (boolean | null) | undefined
        filters?: (HogQLFilters | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        name?: (string | null) | undefined
        query: string
        response?: (HogQLQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        values?: (Record<string, unknown> | null) | undefined
        variables?: (Record<string, unknown> | null) | undefined
        version?: (number | null) | undefined
    }
    export type ActorsQuery = Partial<{
        fixedProperties: Array<
            PersonPropertyFilter | CohortPropertyFilter | HogQLPropertyFilter | EmptyPropertyFilter
        > | null
        kind: string
        limit: number | null
        modifiers: HogQLQueryModifiers | null
        offset: number | null
        orderBy: Array<string> | null
        properties:
            | Array<
                  | PersonPropertyFilter
                  | CohortPropertyFilter
                  | HogQLPropertyFilter
                  | EmptyPropertyFilter
              >
            | PropertyGroupFilterValue
            | null
        response: ActorsQueryResponse | null
        search: string | null
        select: Array<string> | null
        source:
            | InsightActorsQuery
            | FunnelsActorsQuery
            | FunnelCorrelationActorsQuery
            | StickinessActorsQuery
            | HogQLQuery
            | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type CreationTypeEnum = 'USR' | 'GIT'
    export type AnnotationScopeEnum =
        | 'dashboard_item'
        | 'dashboard'
        | 'project'
        | 'organization'
        | 'recording'
    export type Annotation = {
        id: number
        content?: (string | null) | undefined
        date_marker?: (string | null) | undefined
        creation_type?: CreationTypeEnum | undefined
        dashboard_item?: (number | null) | undefined
        dashboard_id: number | null
        dashboard_name: string | null
        insight_short_id: string | null
        insight_name: string | null
        insight_derived_name: string | null
        created_by: UserBasic & unknown
        created_at: string | null
        updated_at: string
        deleted?: boolean | undefined
        scope?: AnnotationScopeEnum | undefined
    }
    export type AutocompleteCompletionItemKind =
        | 'Method'
        | 'Function'
        | 'Constructor'
        | 'Field'
        | 'Variable'
        | 'Class'
        | 'Struct'
        | 'Interface'
        | 'Module'
        | 'Property'
        | 'Event'
        | 'Operator'
        | 'Unit'
        | 'Value'
        | 'Constant'
        | 'Enum'
        | 'EnumMember'
        | 'Keyword'
        | 'Text'
        | 'Color'
        | 'File'
        | 'Reference'
        | 'Customcolor'
        | 'Folder'
        | 'TypeParameter'
        | 'User'
        | 'Issue'
        | 'Snippet'
    export type AutocompleteCompletionItem = {
        detail?: (string | null) | undefined
        documentation?: (string | null) | undefined
        insertText: string
        kind: AutocompleteCompletionItemKind
        label: string
    }
    export type BaseCurrencyEnum =
        | 'AED'
        | 'AFN'
        | 'ALL'
        | 'AMD'
        | 'ANG'
        | 'AOA'
        | 'ARS'
        | 'AUD'
        | 'AWG'
        | 'AZN'
        | 'BAM'
        | 'BBD'
        | 'BDT'
        | 'BGN'
        | 'BHD'
        | 'BIF'
        | 'BMD'
        | 'BND'
        | 'BOB'
        | 'BRL'
        | 'BSD'
        | 'BTC'
        | 'BTN'
        | 'BWP'
        | 'BYN'
        | 'BZD'
        | 'CAD'
        | 'CDF'
        | 'CHF'
        | 'CLP'
        | 'CNY'
        | 'COP'
        | 'CRC'
        | 'CVE'
        | 'CZK'
        | 'DJF'
        | 'DKK'
        | 'DOP'
        | 'DZD'
        | 'EGP'
        | 'ERN'
        | 'ETB'
        | 'EUR'
        | 'FJD'
        | 'GBP'
        | 'GEL'
        | 'GHS'
        | 'GIP'
        | 'GMD'
        | 'GNF'
        | 'GTQ'
        | 'GYD'
        | 'HKD'
        | 'HNL'
        | 'HRK'
        | 'HTG'
        | 'HUF'
        | 'IDR'
        | 'ILS'
        | 'INR'
        | 'IQD'
        | 'IRR'
        | 'ISK'
        | 'JMD'
        | 'JOD'
        | 'JPY'
        | 'KES'
        | 'KGS'
        | 'KHR'
        | 'KMF'
        | 'KRW'
        | 'KWD'
        | 'KYD'
        | 'KZT'
        | 'LAK'
        | 'LBP'
        | 'LKR'
        | 'LRD'
        | 'LTL'
        | 'LVL'
        | 'LSL'
        | 'LYD'
        | 'MAD'
        | 'MDL'
        | 'MGA'
        | 'MKD'
        | 'MMK'
        | 'MNT'
        | 'MOP'
        | 'MRU'
        | 'MTL'
        | 'MUR'
        | 'MVR'
        | 'MWK'
        | 'MXN'
        | 'MYR'
        | 'MZN'
        | 'NAD'
        | 'NGN'
        | 'NIO'
        | 'NOK'
        | 'NPR'
        | 'NZD'
        | 'OMR'
        | 'PAB'
        | 'PEN'
        | 'PGK'
        | 'PHP'
        | 'PKR'
        | 'PLN'
        | 'PYG'
        | 'QAR'
        | 'RON'
        | 'RSD'
        | 'RUB'
        | 'RWF'
        | 'SAR'
        | 'SBD'
        | 'SCR'
        | 'SDG'
        | 'SEK'
        | 'SGD'
        | 'SRD'
        | 'SSP'
        | 'STN'
        | 'SYP'
        | 'SZL'
        | 'THB'
        | 'TJS'
        | 'TMT'
        | 'TND'
        | 'TOP'
        | 'TRY'
        | 'TTD'
        | 'TWD'
        | 'TZS'
        | 'UAH'
        | 'UGX'
        | 'USD'
        | 'UYU'
        | 'UZS'
        | 'VES'
        | 'VND'
        | 'VUV'
        | 'WST'
        | 'XAF'
        | 'XCD'
        | 'XOF'
        | 'XPF'
        | 'YER'
        | 'ZAR'
        | 'ZMW'
    export type ModelEnum = 'events' | 'persons' | 'sessions'
    export type BatchExportDestinationTypeEnum =
        | 'S3'
        | 'Snowflake'
        | 'Postgres'
        | 'Redshift'
        | 'BigQuery'
        | 'HTTP'
        | 'NoOp'
    export type BatchExportDestination = {
        type: BatchExportDestinationTypeEnum
        config?: unknown | undefined
    }
    export type IntervalEnum = 'hour' | 'day' | 'week' | 'every 5 minutes'
    export type BatchExportRunStatusEnum =
        | 'Cancelled'
        | 'Completed'
        | 'ContinuedAsNew'
        | 'Failed'
        | 'FailedRetryable'
        | 'FailedBilling'
        | 'Terminated'
        | 'TimedOut'
        | 'Running'
        | 'Starting'
    export type BatchExportRun = {
        id: string
        status: BatchExportRunStatusEnum
        records_completed?: (number | null) | undefined
        latest_error?: (string | null) | undefined
        data_interval_start?: (string | null) | undefined
        data_interval_end: string
        cursor?: (string | null) | undefined
        created_at: string
        finished_at?: (string | null) | undefined
        last_updated_at: string
        records_total_count?: (number | null) | undefined
        bytes_exported?: (number | null) | undefined
        batch_export: string
        backfill?: (string | null) | undefined
    }
    export type BatchExport = {
        id: string
        team_id: number
        name: string
        model?: ((ModelEnum | BlankEnum | NullEnum) | null) | undefined
        destination: BatchExportDestination
        interval: IntervalEnum
        paused?: boolean | undefined
        created_at: string
        last_updated_at: string
        last_paused_at?: (string | null) | undefined
        start_at?: (string | null) | undefined
        end_at?: (string | null) | undefined
        latest_runs: Array<BatchExportRun>
        hogql_query?: string | undefined
        schema: unknown | null
        filters?: (unknown | null) | undefined
    }
    export type BatchExportBackfillStatusEnum =
        | 'Cancelled'
        | 'Completed'
        | 'ContinuedAsNew'
        | 'Failed'
        | 'FailedRetryable'
        | 'Terminated'
        | 'TimedOut'
        | 'Running'
        | 'Starting'
    export type BatchExportBackfill = {
        id: string
        progress: string
        start_at?: (string | null) | undefined
        end_at?: (string | null) | undefined
        status: BatchExportBackfillStatusEnum
        created_at: string
        finished_at?: (string | null) | undefined
        last_updated_at: string
        team: number
        batch_export: string
    }
    export type BreakdownItem = { label: string; value: string | number }
    export type ByweekdayEnum =
        | 'monday'
        | 'tuesday'
        | 'wednesday'
        | 'thursday'
        | 'friday'
        | 'saturday'
        | 'sunday'
    export type CalendarHeatmapFilter = Partial<{ dummy: string | null }>
    export type EventsHeatMapColumnAggregationResult = { column: number; value: number }
    export type EventsHeatMapDataResult = { column: number; row: number; value: number }
    export type EventsHeatMapRowAggregationResult = { row: number; value: number }
    export type EventsHeatMapStructuredResult = {
        allAggregations: number
        columnAggregations: Array<EventsHeatMapColumnAggregationResult>
        data: Array<EventsHeatMapDataResult>
        rowAggregations: Array<EventsHeatMapRowAggregationResult>
    }
    export type CalendarHeatmapResponse = {
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: EventsHeatMapStructuredResult
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type CalendarHeatmapQuery = {
        aggregation_group_type_index?: (number | null) | undefined
        calendarHeatmapFilter?: (CalendarHeatmapFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dataColorTheme?: (number | null) | undefined
        dateRange?: (DateRange | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        interval?: (IntervalType | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties?:
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
                  | null
              )
            | undefined
        response?: (CalendarHeatmapResponse | null) | undefined
        samplingFactor?: (number | null) | undefined
        series: Array<EventsNode | ActionsNode | DataWarehouseNode>
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type DisplayType = 'auto' | 'line' | 'bar'
    export type YAxisPosition = 'left' | 'right'
    export type ChartSettingsDisplay = Partial<{
        color: string | null
        displayType: DisplayType | null
        label: string | null
        trendLine: boolean | null
        yAxisPosition: YAxisPosition | null
    }>
    export type Style = 'none' | 'number' | 'percent'
    export type ChartSettingsFormatting = Partial<{
        decimalPlaces: number | null
        prefix: string | null
        style: Style | null
        suffix: string | null
    }>
    export type Settings = Partial<{
        display: ChartSettingsDisplay | null
        formatting: ChartSettingsFormatting | null
    }>
    export type ChartAxis = { column: string; settings?: (Settings | null) | undefined }
    export type Scale = 'linear' | 'logarithmic'
    export type YAxisSettings = Partial<{
        scale: Scale | null
        showGridLines: boolean | null
        showTicks: boolean | null
        startAtZero: boolean | null
    }>
    export type ChartSettings = Partial<{
        goalLines: Array<GoalLine> | null
        leftYAxisSettings: YAxisSettings | null
        rightYAxisSettings: YAxisSettings | null
        seriesBreakdownColumn: string | null
        showLegend: boolean | null
        showTotalRow: boolean | null
        showXAxisBorder: boolean | null
        showXAxisTicks: boolean | null
        showYAxisBorder: boolean | null
        stackBars100: boolean | null
        xAxis: ChartAxis | null
        yAxis: Array<ChartAxis> | null
        yAxisAtZero: boolean | null
    }>
    export type ClickhouseEvent = {
        id: string
        distinct_id: string
        properties: string
        event: string
        timestamp: string
        person: string
        elements: string
        elements_chain: string
    }
    export type CohortTypeEnum = 'static' | 'person_property' | 'behavioral' | 'analytical'
    export type Cohort = {
        id: number
        name?: (string | null) | undefined
        description?: string | undefined
        groups?: unknown | undefined
        deleted?: boolean | undefined
        filters?: (unknown | null) | undefined
        query?: (unknown | null) | undefined
        is_calculating: boolean
        created_by: UserBasic & unknown
        created_at: string | null
        last_calculation: string | null
        errors_calculating: number
        count: number | null
        is_static?: boolean | undefined
        cohort_type?: ((CohortTypeEnum | BlankEnum | NullEnum) | null) | undefined
        experiment_set: Array<number>
        _create_in_folder?: string | undefined
    }
    export type ColorMode = 'light' | 'dark'
    export type CompareItem = { label: string; value: string }
    export type ConclusionEnum = 'won' | 'lost' | 'inconclusive' | 'stopped_early' | 'invalid'
    export type ConditionalFormattingRule = {
        bytecode: Array<unknown>
        color: string
        colorMode?: (ColorMode | null) | undefined
        columnName: string
        id: string
        input: string
        templateId: string
    }
    export type ConversionGoalFilter1 = {
        conversion_goal_id: string
        conversion_goal_name: string
        custom_name?: (string | null) | undefined
        event?: (string | null) | undefined
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
            | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
        orderBy?: (Array<string> | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        schema_map: Record<string, unknown>
        version?: (number | null) | undefined
    }
    export type ConversionGoalFilter2 = {
        conversion_goal_id: string
        conversion_goal_name: string
        custom_name?: (string | null) | undefined
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
            | undefined
        id: number
        kind?: string | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        schema_map: Record<string, unknown>
        version?: (number | null) | undefined
    }
    export type ConversionGoalFilter3 = {
        conversion_goal_id: string
        conversion_goal_name: string
        custom_name?: (string | null) | undefined
        distinct_id_field: string
        dw_source_type?: (string | null) | undefined
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
            | undefined
        id: string
        id_field: string
        kind?: string | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        schema_map: Record<string, unknown>
        table_name: string
        timestamp_field: string
        version?: (number | null) | undefined
    }
    export type CookielessServerHashModeEnum = 0 | 1 | 2
    export type CreateGroup = {
        group_type_index: number
        group_key: string
        group_properties?: (unknown | null) | undefined
    }
    export type CreationContextEnum =
        | 'feature_flags'
        | 'experiments'
        | 'surveys'
        | 'early_access_features'
        | 'web_experiments'
    export type CreationModeEnum = 'default' | 'template' | 'duplicate'
    export type Credential = {
        id: string
        created_by: UserBasic & unknown
        created_at: string
        access_key: string
        access_secret: string
    }
    export type DashboardRestrictionLevel = 21 | 37
    export type EffectiveRestrictionLevelEnum = 21 | 37
    export type EffectivePrivilegeLevelEnum = 21 | 37
    export type Dashboard = {
        id: number
        name?: (string | null) | undefined
        description?: string | undefined
        pinned?: boolean | undefined
        created_at: string
        created_by: UserBasic & unknown
        is_shared: boolean
        deleted?: boolean | undefined
        creation_mode: CreationModeEnum & unknown
        use_template?: string | undefined
        use_dashboard?: (number | null) | undefined
        delete_insights?: boolean | undefined
        filters: Record<string, unknown>
        variables: Record<string, unknown> | null
        breakdown_colors?: unknown | undefined
        data_color_theme_id?: (number | null) | undefined
        tags?: Array<unknown> | undefined
        tiles: Array<Record<string, unknown>> | null
        restriction_level?: (DashboardRestrictionLevel & unknown) | undefined
        effective_restriction_level: EffectiveRestrictionLevelEnum & unknown
        effective_privilege_level: EffectivePrivilegeLevelEnum & unknown
        user_access_level: string | null
        access_control_version: string
        _create_in_folder?: string | undefined
        last_refresh?: (string | null) | undefined
        persisted_filters: Record<string, unknown> | null
        persisted_variables: Record<string, unknown> | null
        team_id: number
    }
    export type DashboardBasic = {
        id: number
        name: string | null
        description: string
        pinned: boolean
        created_at: string
        created_by: UserBasic & unknown
        last_accessed_at: string | null
        is_shared: boolean
        deleted: boolean
        creation_mode: CreationModeEnum & unknown
        tags?: Array<unknown> | undefined
        restriction_level: DashboardRestrictionLevel & unknown
        effective_restriction_level: EffectiveRestrictionLevelEnum & unknown
        effective_privilege_level: EffectivePrivilegeLevelEnum & unknown
        user_access_level: string | null
        access_control_version: string
        last_refresh: string | null
        team_id: number
    }
    export type DashboardCollaborator = {
        id: string
        dashboard_id: number
        user: UserBasic & unknown
        level: DashboardRestrictionLevel & unknown
        added_at: string
        updated_at: string
        user_uuid: string
    }
    export type DashboardFilter = Partial<{
        breakdown_filter: BreakdownFilter | null
        date_from: string | null
        date_to: string | null
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
        > | null
    }>
    export type DashboardTemplateScopeEnum = 'team' | 'global' | 'feature_flag'
    export type DashboardTemplate = {
        id: string
        template_name?: (string | null) | undefined
        dashboard_description?: (string | null) | undefined
        dashboard_filters?: (unknown | null) | undefined
        tags?: (Array<string> | null) | undefined
        tiles?: (unknown | null) | undefined
        variables?: (unknown | null) | undefined
        deleted?: (boolean | null) | undefined
        created_at: string | null
        created_by?: (number | null) | undefined
        image_url?: (string | null) | undefined
        team_id: number | null
        scope?: ((DashboardTemplateScopeEnum | BlankEnum | NullEnum) | null) | undefined
        availability_contexts?: (Array<string> | null) | undefined
    }
    export type DashboardTileBasic = {
        id: number
        dashboard_id: number
        deleted?: (boolean | null) | undefined
    }
    export type DataTableNodeViewPropsContextType = 'event_definition' | 'team_columns'
    export type DataTableNodeViewPropsContext = {
        eventDefinitionId?: (string | null) | undefined
        type: DataTableNodeViewPropsContextType
    }
    export type Response = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type Response1 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit: number
        missing_actors_count?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<string> | null) | undefined
    }
    export type Response2 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        kind?: string | undefined
        limit: number
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type Response3 = {
        clickhouse?: (string | null) | undefined
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        explain?: (Array<string> | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        metadata?: (HogQLMetadataResponse | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query?: (string | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type WebAnalyticsItemKind = 'unit' | 'duration_s' | 'percentage' | 'currency'
    export type WebOverviewItem = {
        changeFromPreviousPct?: (number | null) | undefined
        isIncreaseBad?: (boolean | null) | undefined
        key: string
        kind: WebAnalyticsItemKind
        previous?: (number | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
        value?: (number | null) | undefined
    }
    export type SamplingRate = { denominator?: (number | null) | undefined; numerator: number }
    export type Response4 = {
        dateFrom?: (string | null) | undefined
        dateTo?: (string | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebOverviewItem>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type Response5 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type Response6 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type WebVitalsPathBreakdownResultItem = { path: string; value: number }
    export type WebVitalsPathBreakdownResult = {
        good: Array<WebVitalsPathBreakdownResultItem>
        needs_improvements: Array<WebVitalsPathBreakdownResultItem>
        poor: Array<WebVitalsPathBreakdownResultItem>
    }
    export type Response8 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebVitalsPathBreakdownResult>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type Response9 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type Response10 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type Response11 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RevenueAnalyticsMRRQueryResultItem = {
        churn: unknown
        contraction: unknown
        expansion: unknown
        new: unknown
        total: unknown
    }
    export type Response12 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsMRRQueryResultItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RevenueAnalyticsOverviewItemKey =
        | 'revenue'
        | 'paying_customer_count'
        | 'avg_revenue_per_customer'
    export type RevenueAnalyticsOverviewItem = {
        key: RevenueAnalyticsOverviewItemKey
        value: number
    }
    export type Response13 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsOverviewItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type Response14 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type Response15 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type MarketingAnalyticsItem = {
        changeFromPreviousPct?: (number | null) | undefined
        hasComparison?: (boolean | null) | undefined
        isIncreaseBad?: (boolean | null) | undefined
        key: string
        kind: WebAnalyticsItemKind
        previous?: (number | string | null) | undefined
        value?: (number | string | null) | undefined
    }
    export type Response17 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<MarketingAnalyticsItem>>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type VolumeBucket = { label: string; value: number }
    export type ErrorTrackingIssueAggregations = {
        occurrences: number
        sessions: number
        users: number
        volumeRange?: (Array<number> | null) | undefined
        volume_buckets: Array<VolumeBucket>
    }
    export type ErrorTrackingIssueAssigneeType = 'user' | 'role'
    export type ErrorTrackingIssueAssignee = {
        id: string | number
        type: ErrorTrackingIssueAssigneeType
    }
    export type IntegrationKind =
        | 'slack'
        | 'salesforce'
        | 'hubspot'
        | 'google-pubsub'
        | 'google-cloud-storage'
        | 'google-ads'
        | 'google-sheets'
        | 'linkedin-ads'
        | 'snapchat'
        | 'intercom'
        | 'email'
        | 'twilio'
        | 'linear'
        | 'github'
        | 'gitlab'
        | 'meta-ads'
        | 'clickup'
        | 'reddit-ads'
    export type ErrorTrackingExternalReferenceIntegration = {
        display_name: string
        id: number
        kind: IntegrationKind
    }
    export type ErrorTrackingExternalReference = {
        external_url: string
        id: string
        integration: ErrorTrackingExternalReferenceIntegration
    }
    export type FirstEvent = { properties: string; timestamp: string; uuid: string }
    export type LastEvent = { properties: string; timestamp: string; uuid: string }
    export type Status = 'archived' | 'active' | 'resolved' | 'pending_release' | 'suppressed'
    export type ErrorTrackingIssue = {
        aggregations?: (ErrorTrackingIssueAggregations | null) | undefined
        assignee?: (ErrorTrackingIssueAssignee | null) | undefined
        description?: (string | null) | undefined
        external_issues?: (Array<ErrorTrackingExternalReference> | null) | undefined
        first_event?: (FirstEvent | null) | undefined
        first_seen: string
        id: string
        last_event?: (LastEvent | null) | undefined
        last_seen: string
        library?: (string | null) | undefined
        name?: (string | null) | undefined
        status: Status
    }
    export type Response18 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<ErrorTrackingIssue>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type Population = {
        both: number
        exception_only: number
        neither: number
        success_only: number
    }
    export type ErrorTrackingCorrelatedIssue = {
        assignee?: (ErrorTrackingIssueAssignee | null) | undefined
        description?: (string | null) | undefined
        event: string
        external_issues?: (Array<ErrorTrackingExternalReference> | null) | undefined
        first_seen: string
        id: string
        last_seen: string
        library?: (string | null) | undefined
        name?: (string | null) | undefined
        odds_ratio: number
        population: Population
        status: Status
    }
    export type Response19 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<ErrorTrackingCorrelatedIssue>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type ExperimentSignificanceCode =
        | 'significant'
        | 'not_enough_exposure'
        | 'low_win_probability'
        | 'high_loss'
        | 'high_p_value'
    export type ExperimentVariantFunnelsBaseStats = {
        failure_count: number
        key: string
        success_count: number
    }
    export type Response20 = {
        credible_intervals: Record<string, Array<number>>
        expected_loss: number
        funnels_query?: (FunnelsQuery | null) | undefined
        insight: Array<Array<Record<string, unknown>>>
        kind?: string | undefined
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantFunnelsBaseStats>
    }
    export type ExperimentVariantTrendsBaseStats = {
        absolute_exposure: number
        count: number
        exposure: number
        key: string
    }
    export type Response21 = {
        count_query?: (TrendsQuery | null) | undefined
        credible_intervals: Record<string, Array<number>>
        exposure_query?: (TrendsQuery | null) | undefined
        insight: Array<Record<string, unknown>>
        kind?: string | undefined
        p_value: number
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantTrendsBaseStats>
    }
    export type LLMTraceEvent = {
        createdAt: string
        event: AIEventType | string
        id: string
        properties: Record<string, unknown>
    }
    export type LLMTracePerson = {
        created_at: string
        distinct_id: string
        properties: Record<string, unknown>
        uuid: string
    }
    export type LLMTrace = {
        createdAt: string
        events: Array<LLMTraceEvent>
        id: string
        inputCost?: (number | null) | undefined
        inputState?: (unknown | null) | undefined
        inputTokens?: (number | null) | undefined
        outputCost?: (number | null) | undefined
        outputState?: (unknown | null) | undefined
        outputTokens?: (number | null) | undefined
        person: LLMTracePerson
        totalCost?: (number | null) | undefined
        totalLatency?: (number | null) | undefined
        traceName?: (string | null) | undefined
    }
    export type Response22 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<LLMTrace>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type TaxonomicFilterGroupType =
        | 'metadata'
        | 'actions'
        | 'cohorts'
        | 'cohorts_with_all'
        | 'data_warehouse'
        | 'data_warehouse_properties'
        | 'data_warehouse_person_properties'
        | 'elements'
        | 'events'
        | 'event_properties'
        | 'event_feature_flags'
        | 'event_metadata'
        | 'numerical_event_properties'
        | 'person_properties'
        | 'pageview_urls'
        | 'screens'
        | 'custom_events'
        | 'wildcard'
        | 'groups'
        | 'persons'
        | 'feature_flags'
        | 'insights'
        | 'experiments'
        | 'plugins'
        | 'dashboards'
        | 'name_groups'
        | 'session_properties'
        | 'hogql_expression'
        | 'notebooks'
        | 'log_entries'
        | 'error_tracking_issues'
        | 'log_attributes'
        | 'replay'
        | 'revenue_analytics_properties'
        | 'resources'
        | 'error_tracking_properties'
        | 'max_ai_context'
    export type EventsQueryResponse = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type EventsQuery = {
        actionId?: (number | null) | undefined
        after?: (string | null) | undefined
        before?: (string | null) | undefined
        event?: (string | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
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
            | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        orderBy?: (Array<string> | null) | undefined
        personId?: (string | null) | undefined
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
            | undefined
        response?: (EventsQueryResponse | null) | undefined
        select: Array<string>
        source?: (InsightActorsQuery | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
        where?: (Array<string> | null) | undefined
    }
    export type PersonsNode = Partial<{
        cohort: number | null
        distinctId: string | null
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
        > | null
        kind: string
        limit: number | null
        modifiers: HogQLQueryModifiers | null
        offset: number | null
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
        > | null
        response: Record<string, unknown> | null
        search: string | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type GroupsQueryResponse = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        kind?: string | undefined
        limit: number
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type GroupsQuery = {
        group_type_index: number
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        orderBy?: (Array<string> | null) | undefined
        properties?: (Array<GroupPropertyFilter | HogQLPropertyFilter> | null) | undefined
        response?: (GroupsQueryResponse | null) | undefined
        search?: (string | null) | undefined
        select?: (Array<string> | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebAnalyticsOrderByFields =
        | 'Visitors'
        | 'Views'
        | 'Clicks'
        | 'BounceRate'
        | 'AverageScrollPercentage'
        | 'ScrollGt80Percentage'
        | 'TotalConversions'
        | 'UniqueConversions'
        | 'ConversionRate'
        | 'ConvertingUsers'
        | 'RageClicks'
        | 'DeadClicks'
        | 'Errors'
    export type WebAnalyticsOrderByDirection = 'ASC' | 'DESC'
    export type WebOverviewQueryResponse = {
        dateFrom?: (string | null) | undefined
        dateTo?: (string | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebOverviewItem>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type WebAnalyticsSampling = Partial<{
        enabled: boolean | null
        forceSamplingRate: SamplingRate | null
    }>
    export type WebOverviewQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebOverviewQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebStatsBreakdown =
        | 'Page'
        | 'InitialPage'
        | 'ExitPage'
        | 'ExitClick'
        | 'PreviousPage'
        | 'ScreenName'
        | 'InitialChannelType'
        | 'InitialReferringDomain'
        | 'InitialUTMSource'
        | 'InitialUTMCampaign'
        | 'InitialUTMMedium'
        | 'InitialUTMTerm'
        | 'InitialUTMContent'
        | 'InitialUTMSourceMediumCampaign'
        | 'Browser'
        | 'OS'
        | 'Viewport'
        | 'DeviceType'
        | 'Country'
        | 'Region'
        | 'City'
        | 'Timezone'
        | 'Language'
        | 'FrustrationMetrics'
    export type WebStatsTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type WebStatsTableQuery = {
        breakdownBy: WebStatsBreakdown
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeBounceRate?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        includeScrollDepth?: (boolean | null) | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebStatsTableQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebExternalClicksTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type WebExternalClicksTableQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebExternalClicksTableQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        stripQueryParams?: (boolean | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebGoalsQueryResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type WebGoalsQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebGoalsQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebVitalsQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebGoalsQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        source:
            | TrendsQuery
            | FunnelsQuery
            | RetentionQuery
            | PathsQuery
            | StickinessQuery
            | LifecycleQuery
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebVitalsMetric = 'INP' | 'LCP' | 'CLS' | 'FCP'
    export type WebVitalsPercentile = 'p75' | 'p90' | 'p99'
    export type WebVitalsPathBreakdownQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebVitalsPathBreakdownResult>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type WebVitalsPathBreakdownQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        kind?: string | undefined
        metric: WebVitalsMetric
        modifiers?: (HogQLQueryModifiers | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        percentile: WebVitalsPercentile
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebVitalsPathBreakdownQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        thresholds: Array<number>
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type Filters = Partial<{
        dateRange: DateRange | null
        properties: Array<SessionPropertyFilter> | null
    }>
    export type SessionAttributionGroupBy =
        | 'ChannelType'
        | 'Medium'
        | 'Source'
        | 'Campaign'
        | 'AdIds'
        | 'ReferringDomain'
        | 'InitialURL'
    export type SessionAttributionExplorerQueryResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type SessionAttributionExplorerQuery = {
        filters?: (Filters | null) | undefined
        groupBy: Array<SessionAttributionGroupBy>
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        response?: (SessionAttributionExplorerQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RevenueAnalyticsBreakdown = { property: string; type?: string | undefined }
    export type SimpleIntervalType = 'day' | 'month'
    export type RevenueAnalyticsGrossRevenueQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RevenueAnalyticsGrossRevenueQuery = {
        breakdown: Array<RevenueAnalyticsBreakdown>
        dateRange?: (DateRange | null) | undefined
        interval: SimpleIntervalType
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties: Array<RevenueAnalyticsPropertyFilter>
        response?: (RevenueAnalyticsGrossRevenueQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RevenueAnalyticsMetricsQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RevenueAnalyticsMetricsQuery = {
        breakdown: Array<RevenueAnalyticsBreakdown>
        dateRange?: (DateRange | null) | undefined
        interval: SimpleIntervalType
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties: Array<RevenueAnalyticsPropertyFilter>
        response?: (RevenueAnalyticsMetricsQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RevenueAnalyticsMRRQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsMRRQueryResultItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RevenueAnalyticsMRRQuery = {
        breakdown: Array<RevenueAnalyticsBreakdown>
        dateRange?: (DateRange | null) | undefined
        interval: SimpleIntervalType
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties: Array<RevenueAnalyticsPropertyFilter>
        response?: (RevenueAnalyticsMRRQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RevenueAnalyticsOverviewQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsOverviewItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RevenueAnalyticsOverviewQuery = {
        dateRange?: (DateRange | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties: Array<RevenueAnalyticsPropertyFilter>
        response?: (RevenueAnalyticsOverviewQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RevenueAnalyticsTopCustomersGroupBy = 'month' | 'all'
    export type RevenueAnalyticsTopCustomersQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type RevenueAnalyticsTopCustomersQuery = {
        dateRange?: (DateRange | null) | undefined
        groupBy: RevenueAnalyticsTopCustomersGroupBy
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        properties: Array<RevenueAnalyticsPropertyFilter>
        response?: (RevenueAnalyticsTopCustomersQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RevenueExampleEventsQueryResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type RevenueExampleEventsQuery = Partial<{
        kind: string
        limit: number | null
        modifiers: HogQLQueryModifiers | null
        offset: number | null
        response: RevenueExampleEventsQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type RevenueExampleDataWarehouseTablesQueryResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type RevenueExampleDataWarehouseTablesQuery = Partial<{
        kind: string
        limit: number | null
        modifiers: HogQLQueryModifiers | null
        offset: number | null
        response: RevenueExampleDataWarehouseTablesQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type MarketingAnalyticsOrderByEnum = 'ASC' | 'DESC'
    export type MarketingAnalyticsTableQueryResponse = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<MarketingAnalyticsItem>>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type MarketingAnalyticsTableQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        draftConversionGoal?:
            | (ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3 | null)
            | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        orderBy?: (Array<Array<string | MarketingAnalyticsOrderByEnum>> | null) | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (MarketingAnalyticsTableQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        select?: (Array<string> | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type OrderBy = 'last_seen' | 'first_seen' | 'occurrences' | 'users' | 'sessions'
    export type OrderDirection = 'ASC' | 'DESC'
    export type ErrorTrackingQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<ErrorTrackingIssue>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type Status2 =
        | 'archived'
        | 'active'
        | 'resolved'
        | 'pending_release'
        | 'suppressed'
        | 'all'
    export type ErrorTrackingQuery = {
        assignee?: (ErrorTrackingIssueAssignee | null) | undefined
        dateRange: DateRange
        filterGroup?: (PropertyGroupFilter | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        issueId?: (string | null) | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        orderBy?: (OrderBy | null) | undefined
        orderDirection?: (OrderDirection | null) | undefined
        response?: (ErrorTrackingQueryResponse | null) | undefined
        searchQuery?: (string | null) | undefined
        status?: (Status2 | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
        volumeResolution: number
        withAggregations?: (boolean | null) | undefined
        withFirstEvent?: (boolean | null) | undefined
        withLastEvent?: (boolean | null) | undefined
    }
    export type ErrorTrackingIssueCorrelationQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<ErrorTrackingCorrelatedIssue>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type ErrorTrackingIssueCorrelationQuery = {
        events: Array<string>
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        response?: (ErrorTrackingIssueCorrelationQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type ExperimentFunnelsQueryResponse = {
        credible_intervals: Record<string, Array<number>>
        expected_loss: number
        funnels_query?: (FunnelsQuery | null) | undefined
        insight: Array<Array<Record<string, unknown>>>
        kind?: string | undefined
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantFunnelsBaseStats>
    }
    export type ExperimentFunnelsQuery = {
        experiment_id?: (number | null) | undefined
        funnels_query: FunnelsQuery
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        name?: (string | null) | undefined
        response?: (ExperimentFunnelsQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        uuid?: (string | null) | undefined
        version?: (number | null) | undefined
    }
    export type ExperimentTrendsQueryResponse = {
        count_query?: (TrendsQuery | null) | undefined
        credible_intervals: Record<string, Array<number>>
        exposure_query?: (TrendsQuery | null) | undefined
        insight: Array<Record<string, unknown>>
        kind?: string | undefined
        p_value: number
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantTrendsBaseStats>
    }
    export type ExperimentTrendsQuery = {
        count_query: TrendsQuery
        experiment_id?: (number | null) | undefined
        exposure_query?: (TrendsQuery | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        name?: (string | null) | undefined
        response?: (ExperimentTrendsQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        uuid?: (string | null) | undefined
        version?: (number | null) | undefined
    }
    export type TracesQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<LLMTrace>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type TracesQuery = Partial<{
        dateRange: DateRange | null
        filterTestAccounts: boolean | null
        kind: string
        limit: number | null
        modifiers: HogQLQueryModifiers | null
        offset: number | null
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
        > | null
        response: TracesQueryResponse | null
        showColumnConfigurator: boolean | null
        tags: QueryLogTags | null
        traceId: string | null
        version: number | null
    }>
    export type DataTableNode = {
        allowSorting?: (boolean | null) | undefined
        columns?: (Array<string> | null) | undefined
        context?: (DataTableNodeViewPropsContext | null) | undefined
        embedded?: (boolean | null) | undefined
        expandable?: (boolean | null) | undefined
        full?: (boolean | null) | undefined
        hiddenColumns?: (Array<string> | null) | undefined
        kind?: string | undefined
        pinnedColumns?: (Array<string> | null) | undefined
        propertiesViaUrl?: (boolean | null) | undefined
        response?:
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
                  | Response17
                  | Response18
                  | Response19
                  | Response20
                  | Response21
                  | Response22
                  | null
              )
            | undefined
        showActions?: (boolean | null) | undefined
        showColumnConfigurator?: (boolean | null) | undefined
        showDateRange?: (boolean | null) | undefined
        showElapsedTime?: (boolean | null) | undefined
        showEventFilter?: (boolean | null) | undefined
        showExport?: (boolean | null) | undefined
        showHogQLEditor?: (boolean | null) | undefined
        showOpenEditorButton?: (boolean | null) | undefined
        showPersistentColumnConfigurator?: (boolean | null) | undefined
        showPropertyFilter?: (boolean | Array<TaxonomicFilterGroupType> | null) | undefined
        showReload?: (boolean | null) | undefined
        showResultsTable?: (boolean | null) | undefined
        showSavedFilters?: (boolean | null) | undefined
        showSavedQueries?: (boolean | null) | undefined
        showSearch?: (boolean | null) | undefined
        showTestAccountFilters?: (boolean | null) | undefined
        showTimings?: (boolean | null) | undefined
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
            | RevenueAnalyticsGrossRevenueQuery
            | RevenueAnalyticsMetricsQuery
            | RevenueAnalyticsMRRQuery
            | RevenueAnalyticsOverviewQuery
            | RevenueAnalyticsTopCustomersQuery
            | RevenueExampleEventsQuery
            | RevenueExampleDataWarehouseTablesQuery
            | MarketingAnalyticsTableQuery
            | ErrorTrackingQuery
            | ErrorTrackingIssueCorrelationQuery
            | ExperimentFunnelsQuery
            | ExperimentTrendsQuery
            | TracesQuery
        version?: (number | null) | undefined
    }
    export type TableSettings = Partial<{
        columns: Array<ChartAxis> | null
        conditionalFormatting: Array<ConditionalFormattingRule> | null
    }>
    export type DataVisualizationNode = {
        chartSettings?: (ChartSettings | null) | undefined
        display?: (ChartDisplayType | null) | undefined
        kind?: string | undefined
        source: HogQLQuery
        tableSettings?: (TableSettings | null) | undefined
        version?: (number | null) | undefined
    }
    export type DataWarehouseSavedQueryStatusEnum =
        | 'Cancelled'
        | 'Modified'
        | 'Completed'
        | 'Failed'
        | 'Running'
    export type DataWarehouseSavedQuery = {
        id: string
        deleted?: (boolean | null) | undefined
        name: string
        query?: (unknown | null) | undefined
        created_by: UserBasic & unknown
        created_at: string
        sync_frequency: string
        columns: string
        status: (DataWarehouseSavedQueryStatusEnum | NullEnum) | null
        last_run_at: string | null
        latest_error: string | null
        edited_history_id?: (string | null) | undefined
        latest_history_id: string
        soft_update?: (boolean | null) | undefined
        is_materialized: boolean | null
    }
    export type DataWarehouseViewLinkConfiguration = Partial<{
        experiments_optimized: boolean | null
        experiments_timestamp_key: string | null
    }>
    export type HedgehogColorOptions =
        | 'green'
        | 'red'
        | 'blue'
        | 'purple'
        | 'dark'
        | 'light'
        | 'sepia'
        | 'invert'
        | 'invert-hue'
        | 'greyscale'
    export type MinimalHedgehogConfig = {
        accessories: Array<string>
        color?: (HedgehogColorOptions | null) | undefined
        use_as_profile: boolean
    }
    export type UserBasicType = {
        distinct_id: string
        email: string
        first_name: string
        hedgehog_config?: (MinimalHedgehogConfig | null) | undefined
        id: number
        is_email_verified?: (unknown | null) | undefined
        last_name?: (string | null) | undefined
        uuid: string
    }
    export type DataWarehouseViewLink = {
        configuration?: (DataWarehouseViewLinkConfiguration | null) | undefined
        created_at?: (string | null) | undefined
        created_by?: (UserBasicType | null) | undefined
        field_name?: (string | null) | undefined
        id: string
        joining_table_key?: (string | null) | undefined
        joining_table_name?: (string | null) | undefined
        source_table_key?: (string | null) | undefined
        source_table_name?: (string | null) | undefined
    }
    export type DatabaseSerializedFieldType =
        | 'integer'
        | 'float'
        | 'decimal'
        | 'string'
        | 'datetime'
        | 'date'
        | 'boolean'
        | 'array'
        | 'json'
        | 'lazy_table'
        | 'virtual_table'
        | 'field_traverser'
        | 'expression'
        | 'view'
        | 'materialized_view'
        | 'unknown'
    export type DatabaseSchemaField = {
        chain?: (Array<string | number> | null) | undefined
        fields?: (Array<string> | null) | undefined
        hogql_value: string
        id?: (string | null) | undefined
        name: string
        schema_valid: boolean
        table?: (string | null) | undefined
        type: DatabaseSerializedFieldType
    }
    export type DatabaseSchemaBatchExportTable = {
        fields: Record<string, unknown>
        id: string
        name: string
        row_count?: (number | null) | undefined
        type?: string | undefined
    }
    export type DatabaseSchemaSchema = {
        id: string
        incremental: boolean
        last_synced_at?: (string | null) | undefined
        name: string
        should_sync: boolean
        status?: (string | null) | undefined
    }
    export type DatabaseSchemaSource = {
        id: string
        last_synced_at?: (string | null) | undefined
        prefix: string
        source_type: string
        status: string
    }
    export type DatabaseSchemaDataWarehouseTable = {
        fields: Record<string, unknown>
        format: string
        id: string
        name: string
        row_count?: (number | null) | undefined
        schema?: (DatabaseSchemaSchema | null) | undefined
        source?: (DatabaseSchemaSource | null) | undefined
        type?: string | undefined
        url_pattern: string
    }
    export type DatabaseSchemaManagedViewTableKind =
        | 'revenue_analytics_charge'
        | 'revenue_analytics_customer'
        | 'revenue_analytics_product'
        | 'revenue_analytics_revenue_item'
        | 'revenue_analytics_subscription'
    export type DatabaseSchemaManagedViewTable = {
        fields: Record<string, unknown>
        id: string
        kind: DatabaseSchemaManagedViewTableKind
        name: string
        query: HogQLQuery
        row_count?: (number | null) | undefined
        source_id?: (string | null) | undefined
        type?: string | undefined
    }
    export type DatabaseSchemaMaterializedViewTable = {
        fields: Record<string, unknown>
        id: string
        last_run_at?: (string | null) | undefined
        name: string
        query: HogQLQuery
        row_count?: (number | null) | undefined
        status?: (string | null) | undefined
        type?: string | undefined
    }
    export type DatabaseSchemaPostHogTable = {
        fields: Record<string, unknown>
        id: string
        name: string
        row_count?: (number | null) | undefined
        type?: string | undefined
    }
    export type DatabaseSchemaViewTable = {
        fields: Record<string, unknown>
        id: string
        name: string
        query: HogQLQuery
        row_count?: (number | null) | undefined
        type?: string | undefined
    }
    export type DatabaseSchemaQueryResponse = {
        joins: Array<DataWarehouseViewLink>
        tables: Record<string, unknown>
    }
    export type DatabaseSchemaQuery = Partial<{
        kind: string
        modifiers: HogQLQueryModifiers | null
        response: DatabaseSchemaQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type DayItem = { label: string; value: string | string | number }
    export type DefaultExperimentStatsMethodEnum = 'bayesian' | 'frequentist'
    export type DisplayEnum = 'number' | 'sparkline'
    export type EvaluationRuntimeEnum = 'server' | 'client' | 'all'
    export type MinimalFeatureFlag = {
        id: number
        team_id: number
        name?: string | undefined
        key: string
        filters?: Record<string, unknown> | undefined
        deleted?: boolean | undefined
        active?: boolean | undefined
        ensure_experience_continuity?: (boolean | null) | undefined
        has_encrypted_payloads?: (boolean | null) | undefined
        version?: (number | null) | undefined
        evaluation_runtime?: ((EvaluationRuntimeEnum | BlankEnum | NullEnum) | null) | undefined
    }
    export type StageEnum =
        | 'draft'
        | 'concept'
        | 'alpha'
        | 'beta'
        | 'general-availability'
        | 'archived'
    export type EarlyAccessFeature = {
        id: string
        feature_flag: MinimalFeatureFlag & unknown
        name: string
        description?: string | undefined
        stage: StageEnum
        documentation_url?: string | undefined
        created_at: string
    }
    export type EarlyAccessFeatureSerializerCreateOnly = {
        id: string
        name: string
        description?: string | undefined
        stage: StageEnum
        documentation_url?: string | undefined
        created_at: string
        feature_flag_id?: number | undefined
        feature_flag: MinimalFeatureFlag & unknown
        _create_in_folder?: string | undefined
    }
    export type EffectiveMembershipLevelEnum = 1 | 8 | 15
    export type ElementType = {
        attr_class?: (Array<string> | null) | undefined
        attr_id?: (string | null) | undefined
        attributes: Record<string, string>
        href?: (string | null) | undefined
        nth_child?: (number | null) | undefined
        nth_of_type?: (number | null) | undefined
        order?: (number | null) | undefined
        tag_name: string
        text?: (string | null) | undefined
    }
    export type ErrorTrackingAssignmentRule = {
        id: string
        filters: unknown
        assignee: string
        order_key: number
        disabled_data?: (unknown | null) | undefined
    }
    export type ErrorTrackingGroupingRule = {
        id: string
        filters: unknown
        assignee: string
        order_key: number
        disabled_data?: (unknown | null) | undefined
    }
    export type ErrorTrackingRelease = {
        id: string
        hash_id: string
        team_id: number
        created_at: string
        metadata?: (unknown | null) | undefined
        version: string
        project: string
    }
    export type ErrorTrackingSuppressionRule = { id: string; filters: unknown; order_key: number }
    export type ErrorTrackingSymbolSet = {
        id: string
        ref: string
        team_id: number
        created_at: string
        storage_ptr?: (string | null) | undefined
        failure_reason?: (string | null) | undefined
    }
    export type EventTaxonomyItem = {
        property: string
        sample_count: number
        sample_values: Array<string>
    }
    export type EventTaxonomyQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<EventTaxonomyItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type EventTaxonomyQuery = Partial<{
        actionId: number | null
        event: string | null
        kind: string
        maxPropertyValues: number | null
        modifiers: HogQLQueryModifiers | null
        properties: Array<string> | null
        response: EventTaxonomyQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type Person = {
        id: number
        name: string
        distinct_ids: Array<string>
        properties?: unknown | undefined
        created_at: string
        uuid: string
    }
    export type EventType = {
        distinct_id: string
        elements: Array<ElementType>
        elements_chain?: (string | null) | undefined
        event: string
        id: string
        person?: (Person | null) | undefined
        properties: Record<string, unknown>
        timestamp: string
        uuid?: (string | null) | undefined
    }
    export type ExperimentHoldout = {
        id: number
        name: string
        description?: (string | null) | undefined
        filters?: unknown | undefined
        created_by: UserBasic & unknown
        created_at: string
        updated_at: string
    }
    export type ExperimentToSavedMetric = {
        id: number
        experiment: number
        saved_metric: number
        metadata?: unknown | undefined
        created_at: string
        query: unknown
        name: string
    }
    export type ExperimentTypeEnum = 'web' | 'product'
    export type Experiment = {
        id: number
        name: string
        description?: (string | null) | undefined
        start_date?: (string | null) | undefined
        end_date?: (string | null) | undefined
        feature_flag_key: string
        feature_flag: MinimalFeatureFlag & unknown
        holdout: ExperimentHoldout & unknown
        holdout_id?: (number | null) | undefined
        exposure_cohort: number | null
        parameters?: (unknown | null) | undefined
        secondary_metrics?: (unknown | null) | undefined
        saved_metrics: Array<ExperimentToSavedMetric>
        saved_metrics_ids?: (Array<unknown> | null) | undefined
        filters?: unknown | undefined
        archived?: boolean | undefined
        deleted?: (boolean | null) | undefined
        created_by: UserBasic & unknown
        created_at: string
        updated_at: string
        type?: ((ExperimentTypeEnum | BlankEnum | NullEnum) | null) | undefined
        exposure_criteria?: (unknown | null) | undefined
        metrics?: (unknown | null) | undefined
        metrics_secondary?: (unknown | null) | undefined
        stats_config?: (unknown | null) | undefined
        _create_in_folder?: string | undefined
        conclusion?: ((ConclusionEnum | BlankEnum | NullEnum) | null) | undefined
        conclusion_comment?: (string | null) | undefined
        primary_metrics_ordered_uuids?: (unknown | null) | undefined
        secondary_metrics_ordered_uuids?: (unknown | null) | undefined
    }
    export type ExperimentDataWarehouseNode = {
        custom_name?: (string | null) | undefined
        data_warehouse_join_key: string
        events_join_key: string
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
            | undefined
        kind?: string | undefined
        math?:
            | (
                  | BaseMathType
                  | FunnelMathType
                  | PropertyMathType
                  | CountPerActorMathType
                  | ExperimentMetricMathType
                  | CalendarHeatmapMathType
                  | string
                  | string
                  | null
              )
            | undefined
        math_group_type_index?: (MathGroupTypeIndex | null) | undefined
        math_hogql?: (string | null) | undefined
        math_multiplier?: (number | null) | undefined
        math_property?: (string | null) | undefined
        math_property_revenue_currency?: (RevenueCurrencyPropertyConfig | null) | undefined
        math_property_type?: (string | null) | undefined
        name?: (string | null) | undefined
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
            | undefined
        response?: (Record<string, unknown> | null) | undefined
        table_name: string
        timestamp_field: string
        version?: (number | null) | undefined
    }
    export type ExperimentEventExposureConfig = {
        event: string
        kind?: string | undefined
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
        >
        response?: (Record<string, unknown> | null) | undefined
        version?: (number | null) | undefined
    }
    export type MultipleVariantHandling = 'exclude' | 'first_seen'
    export type ExperimentExposureCriteria = Partial<{
        exposure_config: ExperimentEventExposureConfig | null
        filterTestAccounts: boolean | null
        multiple_variant_handling: MultipleVariantHandling | null
    }>
    export type ExperimentHoldoutType = {
        created_at?: (string | null) | undefined
        created_by?: (UserBasicType | null) | undefined
        description?: (string | null) | undefined
        filters: Record<string, unknown>
        id?: (number | null) | undefined
        name: string
        updated_at?: (string | null) | undefined
    }
    export type ExperimentExposureTimeSeries = {
        days: Array<string>
        exposure_counts: Array<number>
        variant: string
    }
    export type ExperimentExposureQueryResponse = {
        date_range: DateRange
        kind?: string | undefined
        timeseries: Array<ExperimentExposureTimeSeries>
        total_exposures: Record<string, number>
    }
    export type ExperimentExposureQuery = {
        end_date?: (string | null) | undefined
        experiment_id?: (number | null) | undefined
        experiment_name: string
        exposure_criteria?: (ExperimentExposureCriteria | null) | undefined
        feature_flag: Record<string, unknown>
        holdout?: (ExperimentHoldoutType | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        response?: (ExperimentExposureQueryResponse | null) | undefined
        start_date?: (string | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type ExperimentMetricGoal = 'increase' | 'decrease'
    export type ExperimentFunnelMetric = {
        conversion_window?: (number | null) | undefined
        conversion_window_unit?: (FunnelConversionWindowTimeUnit | null) | undefined
        funnel_order_type?: (StepOrderValue | null) | undefined
        goal?: (ExperimentMetricGoal | null) | undefined
        kind?: string | undefined
        metric_type?: string | undefined
        name?: (string | null) | undefined
        response?: (Record<string, unknown> | null) | undefined
        series: Array<EventsNode | ActionsNode>
        uuid?: (string | null) | undefined
        version?: (number | null) | undefined
    }
    export type ExperimentMeanMetric = {
        conversion_window?: (number | null) | undefined
        conversion_window_unit?: (FunnelConversionWindowTimeUnit | null) | undefined
        goal?: (ExperimentMetricGoal | null) | undefined
        kind?: string | undefined
        lower_bound_percentile?: (number | null) | undefined
        metric_type?: string | undefined
        name?: (string | null) | undefined
        response?: (Record<string, unknown> | null) | undefined
        source: EventsNode | ActionsNode | ExperimentDataWarehouseNode
        upper_bound_percentile?: (number | null) | undefined
        uuid?: (string | null) | undefined
        version?: (number | null) | undefined
    }
    export type ExperimentRatioMetric = {
        conversion_window?: (number | null) | undefined
        conversion_window_unit?: (FunnelConversionWindowTimeUnit | null) | undefined
        denominator: EventsNode | ActionsNode | ExperimentDataWarehouseNode
        goal?: (ExperimentMetricGoal | null) | undefined
        kind?: string | undefined
        metric_type?: string | undefined
        name?: (string | null) | undefined
        numerator: EventsNode | ActionsNode | ExperimentDataWarehouseNode
        response?: (Record<string, unknown> | null) | undefined
        uuid?: (string | null) | undefined
        version?: (number | null) | undefined
    }
    export type ExperimentStatsValidationFailure =
        | 'not-enough-exposures'
        | 'baseline-mean-is-zero'
        | 'not-enough-metric-data'
    export type ExperimentStatsBaseValidated = {
        denominator_sum?: (number | null) | undefined
        denominator_sum_squares?: (number | null) | undefined
        key: string
        number_of_samples: number
        numerator_denominator_sum_product?: (number | null) | undefined
        sum: number
        sum_squares: number
        validation_failures?: (Array<ExperimentStatsValidationFailure> | null) | undefined
    }
    export type ExperimentVariantResultFrequentist = {
        confidence_interval?: (Array<number> | null) | undefined
        denominator_sum?: (number | null) | undefined
        denominator_sum_squares?: (number | null) | undefined
        key: string
        method?: string | undefined
        number_of_samples: number
        numerator_denominator_sum_product?: (number | null) | undefined
        p_value?: (number | null) | undefined
        significant?: (boolean | null) | undefined
        sum: number
        sum_squares: number
        validation_failures?: (Array<ExperimentStatsValidationFailure> | null) | undefined
    }
    export type ExperimentVariantResultBayesian = {
        chance_to_win?: (number | null) | undefined
        credible_interval?: (Array<number> | null) | undefined
        denominator_sum?: (number | null) | undefined
        denominator_sum_squares?: (number | null) | undefined
        key: string
        method?: string | undefined
        number_of_samples: number
        numerator_denominator_sum_product?: (number | null) | undefined
        significant?: (boolean | null) | undefined
        sum: number
        sum_squares: number
        validation_failures?: (Array<ExperimentStatsValidationFailure> | null) | undefined
    }
    export type ExperimentQueryResponse = Partial<{
        baseline: ExperimentStatsBaseValidated | null
        credible_intervals: Record<string, Array<number>> | null
        insight: Array<Record<string, unknown>> | null
        kind: string
        metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | null
        p_value: number | null
        probability: Record<string, number> | null
        significance_code: ExperimentSignificanceCode | null
        significant: boolean | null
        stats_version: number | null
        variant_results:
            | Array<ExperimentVariantResultFrequentist>
            | Array<ExperimentVariantResultBayesian>
            | null
        variants:
            | Array<ExperimentVariantTrendsBaseStats>
            | Array<ExperimentVariantFunnelsBaseStats>
            | null
    }>
    export type ExperimentQuery = {
        experiment_id?: (number | null) | undefined
        kind?: string | undefined
        metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric
        modifiers?: (HogQLQueryModifiers | null) | undefined
        name?: (string | null) | undefined
        response?: (ExperimentQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type ExperimentSavedMetric = {
        id: number
        name: string
        description?: (string | null) | undefined
        query: unknown
        created_by: UserBasic & unknown
        created_at: string
        updated_at: string
        tags?: Array<unknown> | undefined
    }
    export type ExplicitTeamMemberLevelEnum = 1 | 8
    export type ExplicitTeamMember = {
        id: string
        level?: (ExplicitTeamMemberLevelEnum & unknown) | undefined
        parent_level: number
        parent_membership_id: string
        joined_at: string
        updated_at: string
        user: UserBasic & unknown
        user_uuid: string
        effective_level: EffectiveMembershipLevelEnum & unknown
    }
    export type ExportFormatEnum =
        | 'image/png'
        | 'application/pdf'
        | 'text/csv'
        | 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        | 'video/webm'
        | 'video/mp4'
        | 'image/gif'
        | 'application/json'
    export type ExportedAsset = {
        id: number
        dashboard?: (number | null) | undefined
        insight?: (number | null) | undefined
        export_format: ExportFormatEnum
        created_at: string
        has_content: string
        export_context?: (unknown | null) | undefined
        filename: string
        expires_after?: (string | null) | undefined
        exception: string | null
    }
    export type ExternalQueryErrorCode = 'platform_access_required' | 'query_execution_failed'
    export type ExternalQueryError = { code: ExternalQueryErrorCode; detail: string }
    export type ExternalQueryStatus = 'success' | 'error'
    export type FeatureFlag = {
        id: number
        name?: string | undefined
        key: string
        filters?: Record<string, unknown> | undefined
        deleted?: boolean | undefined
        active?: boolean | undefined
        created_by: UserBasic & unknown
        created_at?: string | undefined
        version?: number | undefined
        last_modified_by: UserBasic & unknown
        is_simple_flag: boolean
        rollout_percentage: number | null
        ensure_experience_continuity?: (boolean | null) | undefined
        experiment_set: string
        surveys: Record<string, unknown>
        features: Record<string, unknown>
        rollback_conditions?: (unknown | null) | undefined
        performed_rollback?: (boolean | null) | undefined
        can_edit: boolean
        tags?: Array<unknown> | undefined
        usage_dashboard: number
        analytics_dashboards?: Array<number> | undefined
        has_enriched_analytics?: (boolean | null) | undefined
        user_access_level: string | null
        creation_context?: (CreationContextEnum & unknown) | undefined
        is_remote_configuration?: (boolean | null) | undefined
        has_encrypted_payloads?: (boolean | null) | undefined
        status: string
        evaluation_runtime?: ((EvaluationRuntimeEnum | BlankEnum | NullEnum) | null) | undefined
        _create_in_folder?: string | undefined
    }
    export type FeatureFlagsAccessLevelEnum = 21 | 37
    export type Role = {
        id: string
        name: string
        feature_flags_access_level?: (FeatureFlagsAccessLevelEnum & unknown) | undefined
        created_at: string
        created_by: UserBasic & unknown
        members: string
        is_default: string
    }
    export type FeatureFlagRoleAccess = {
        id: number
        feature_flag: FeatureFlag & unknown
        role: Role & unknown
        role_id: string
        added_at: string
        updated_at: string
    }
    export type FileSystem = {
        id: string
        path: string
        depth: number | null
        type?: string | undefined
        ref?: (string | null) | undefined
        href?: (string | null) | undefined
        meta?: (unknown | null) | undefined
        shortcut?: (boolean | null) | undefined
        created_at: string
    }
    export type FileSystemShortcut = {
        id: string
        path: string
        type?: string | undefined
        ref?: (string | null) | undefined
        href?: (string | null) | undefined
        created_at: string
    }
    export type FrequencyEnum = 'daily' | 'weekly' | 'monthly' | 'yearly'
    export type Group = {
        group_type_index: number
        group_key: string
        group_properties?: unknown | undefined
        created_at: string
    }
    export type GroupType = {
        group_type: string
        group_type_index: number
        name_singular?: (string | null) | undefined
        name_plural?: (string | null) | undefined
        detail_dashboard?: (number | null) | undefined
        default_columns?: (Array<string> | null) | undefined
        created_at?: (string | null) | undefined
    }
    export type GroupUsageMetricFormatEnum = 'numeric' | 'currency'
    export type GroupUsageMetric = {
        id: string
        name: string
        format?: GroupUsageMetricFormatEnum | undefined
        interval?: number | undefined
        display?: DisplayEnum | undefined
        filters: unknown
    }
    export type HogFunctionTypeEnum =
        | 'destination'
        | 'site_destination'
        | 'internal_destination'
        | 'source_webhook'
        | 'site_app'
        | 'transformation'
    export type InputsSchemaItemTypeEnum =
        | 'string'
        | 'number'
        | 'boolean'
        | 'dictionary'
        | 'choice'
        | 'json'
        | 'integration'
        | 'integration_field'
        | 'email'
        | 'native_email'
    export type InputsSchemaItemTemplatingEnum = true | false | 'hog' | 'liquid'
    export type InputsSchemaItem = {
        type: InputsSchemaItemTypeEnum
        key: string
        label?: string | undefined
        choices?: Array<Record<string, unknown>> | undefined
        required?: boolean | undefined
        default?: unknown | undefined
        secret?: boolean | undefined
        hidden?: boolean | undefined
        description?: string | undefined
        integration?: string | undefined
        integration_key?: string | undefined
        requires_field?: string | undefined
        integration_field?: string | undefined
        requiredScopes?: string | undefined
        templating?: InputsSchemaItemTemplatingEnum | undefined
    }
    export type InputsItemTemplatingEnum = 'hog' | 'liquid'
    export type InputsItem = {
        value?: string | undefined
        templating?: InputsItemTemplatingEnum | undefined
        bytecode: Array<unknown>
        order: number
        transpiled: unknown
    }
    export type HogFunctionFiltersSourceEnum = 'events' | 'person-updates'
    export type HogFunctionFilters = Partial<{
        source: HogFunctionFiltersSourceEnum & unknown
        actions: Array<Record<string, unknown>>
        events: Array<Record<string, unknown>>
        properties: Array<Record<string, unknown>>
        bytecode: unknown | null
        transpiled: unknown
        filter_test_accounts: boolean
        bytecode_error: string
    }>
    export type HogFunctionMasking = {
        ttl: number
        threshold?: (number | null) | undefined
        hash: string
        bytecode?: (unknown | null) | undefined
    }
    export type Mappings = Partial<{
        name: string
        inputs_schema: Array<InputsSchemaItem>
        inputs: Record<string, unknown>
        filters: HogFunctionFilters
    }>
    export type HogFunctionMappingTemplate = {
        name: string
        include_by_default?: (boolean | null) | undefined
        filters?: (unknown | null) | undefined
        inputs?: (unknown | null) | undefined
        inputs_schema?: (unknown | null) | undefined
    }
    export type HogFunctionTemplate = {
        id: string
        name: string
        description?: (string | null) | undefined
        code: string
        code_language?: string | undefined
        inputs_schema: unknown
        type: string
        status?: string | undefined
        category?: unknown | undefined
        free?: boolean | undefined
        icon_url?: (string | null) | undefined
        filters?: (unknown | null) | undefined
        masking?: (unknown | null) | undefined
        mapping_templates?: (Array<HogFunctionMappingTemplate> | null) | undefined
    }
    export type StateEnum = 0 | 1 | 2 | 3 | 11 | 12
    export type HogFunctionStatus = { state: StateEnum; tokens: number }
    export type HogFunction = {
        id: string
        type?: ((HogFunctionTypeEnum | NullEnum) | null) | undefined
        name?: (string | null) | undefined
        description?: string | undefined
        created_at: string
        created_by: UserBasic & unknown
        updated_at: string
        enabled?: boolean | undefined
        deleted?: boolean | undefined
        hog?: string | undefined
        bytecode: unknown | null
        transpiled: string | null
        inputs_schema?: Array<InputsSchemaItem> | undefined
        inputs?: Record<string, unknown> | undefined
        filters?: HogFunctionFilters | undefined
        masking?: ((HogFunctionMasking & (unknown | null)) | null) | undefined
        mappings?: (Array<Mappings> | null) | undefined
        icon_url?: (string | null) | undefined
        template: HogFunctionTemplate & unknown
        template_id?: (string | null) | undefined
        status: (HogFunctionStatus & (unknown | null)) | null
        execution_order?: (number | null) | undefined
        _create_in_folder?: string | undefined
    }
    export type HogFunctionMinimal = {
        id: string
        type: string | null
        name: string | null
        description: string
        created_at: string
        created_by: UserBasic & unknown
        updated_at: string
        enabled: boolean
        hog: string
        filters: unknown | null
        icon_url: string | null
        template: HogFunctionTemplate & unknown
        status: (HogFunctionStatus & (unknown | null)) | null
        execution_order: number | null
    }
    export type HogLanguage = 'hog' | 'hogJson' | 'hogQL' | 'hogQLExpr' | 'hogTemplate'
    export type HogQLASTQuery = {
        explain?: (boolean | null) | undefined
        filters?: (HogQLFilters | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        name?: (string | null) | undefined
        query: Record<string, unknown>
        response?: (HogQLQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        values?: (Record<string, unknown> | null) | undefined
        variables?: (Record<string, unknown> | null) | undefined
        version?: (number | null) | undefined
    }
    export type HogQLAutocompleteResponse = {
        incomplete_list: boolean
        suggestions: Array<AutocompleteCompletionItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type MultipleBreakdownOptions = { values: Array<BreakdownItem> }
    export type IntervalItem = { label: string; value: number }
    export type Series = { label: string; value: number }
    export type StatusItem = { label: string; value: string }
    export type InsightActorsQueryOptionsResponse = Partial<{
        breakdown: Array<BreakdownItem> | null
        breakdowns: Array<MultipleBreakdownOptions> | null
        compare: Array<CompareItem> | null
        day: Array<DayItem> | null
        interval: Array<IntervalItem> | null
        series: Array<Series> | null
        status: Array<StatusItem> | null
    }>
    export type InsightActorsQueryOptions = {
        kind?: string | undefined
        response?: (InsightActorsQueryOptionsResponse | null) | undefined
        source:
            | InsightActorsQuery
            | FunnelsActorsQuery
            | FunnelCorrelationActorsQuery
            | StickinessActorsQuery
        version?: (number | null) | undefined
    }
    export type TimelineEntry = {
        events: Array<EventType>
        recording_duration_s?: (number | null) | undefined
        sessionId?: (string | null) | undefined
    }
    export type SessionsTimelineQueryResponse = {
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<TimelineEntry>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type SessionsTimelineQuery = Partial<{
        after: string | null
        before: string | null
        kind: string
        modifiers: HogQLQueryModifiers | null
        personId: string | null
        response: SessionsTimelineQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type HogQueryResponse = {
        bytecode?: (Array<unknown> | null) | undefined
        coloredBytecode?: (Array<unknown> | null) | undefined
        results: unknown
        stdout?: (string | null) | undefined
    }
    export type HogQuery = Partial<{
        code: string | null
        kind: string
        modifiers: HogQLQueryModifiers | null
        response: HogQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type PageURL = { count: number; url: string }
    export type WebPageURLSearchQueryResponse = {
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<PageURL>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type WebPageURLSearchQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebPageURLSearchQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        searchTerm?: (string | null) | undefined
        stripQueryParams?: (boolean | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebTrendsMetric =
        | 'UniqueUsers'
        | 'PageViews'
        | 'Sessions'
        | 'Bounces'
        | 'SessionDuration'
        | 'TotalSessions'
    export type Metrics = Partial<{
        Bounces: number | null
        PageViews: number | null
        SessionDuration: number | null
        Sessions: number | null
        TotalSessions: number | null
        UniqueUsers: number | null
    }>
    export type WebTrendsItem = { bucket: string; metrics: Metrics }
    export type WebTrendsQueryResponse = {
        clickhouse?: (string | null) | undefined
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        explain?: (Array<string> | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        metadata?: (HogQLMetadataResponse | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query?: (string | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebTrendsItem>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type WebTrendsQuery = {
        compareFilter?: (CompareFilter | null) | undefined
        conversionGoal?: (ActionConversionGoal | CustomEventConversionGoal | null) | undefined
        dateRange?: (DateRange | null) | undefined
        doPathCleaning?: (boolean | null) | undefined
        filterTestAccounts?: (boolean | null) | undefined
        includeRevenue?: (boolean | null) | undefined
        interval: IntervalType
        kind?: string | undefined
        limit?: (number | null) | undefined
        metrics: Array<WebTrendsMetric>
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        orderBy?:
            | (Array<WebAnalyticsOrderByFields | WebAnalyticsOrderByDirection> | null)
            | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebTrendsQueryResponse | null) | undefined
        sampling?: (WebAnalyticsSampling | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        useSessionsTable?: (boolean | null) | undefined
        version?: (number | null) | undefined
    }
    export type WebAnalyticsExternalSummaryQueryResponse = {
        data: Record<string, unknown>
        error?: (ExternalQueryError | null) | undefined
        status: ExternalQueryStatus
    }
    export type WebAnalyticsExternalSummaryQuery = {
        dateRange: DateRange
        kind?: string | undefined
        properties: Array<EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter>
        response?: (WebAnalyticsExternalSummaryQueryResponse | null) | undefined
        version?: (number | null) | undefined
    }
    export type OrderBy2 = 'latest' | 'earliest'
    export type LogsQueryResponse = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type LogSeverityLevel = 'trace' | 'debug' | 'info' | 'warn' | 'error' | 'fatal'
    export type LogsQuery = {
        dateRange: DateRange
        filterGroup: PropertyGroupFilter
        kind?: string | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        orderBy?: (OrderBy2 | null) | undefined
        response?: (LogsQueryResponse | null) | undefined
        searchTerm?: (string | null) | undefined
        serviceNames: Array<string>
        severityLevels: Array<LogSeverityLevel>
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type RecordingOrder =
        | 'duration'
        | 'recording_duration'
        | 'inactive_seconds'
        | 'active_seconds'
        | 'start_time'
        | 'console_error_count'
        | 'click_count'
        | 'keypress_count'
        | 'mouse_activity_count'
        | 'activity_score'
    export type RecordingOrderDirection = 'ASC' | 'DESC'
    export type MatchedRecordingEvent = { uuid: string }
    export type MatchedRecording = {
        events: Array<MatchedRecordingEvent>
        session_id?: (string | null) | undefined
    }
    export type PersonType = {
        created_at?: (string | null) | undefined
        distinct_ids: Array<string>
        id?: (string | null) | undefined
        is_identified?: (boolean | null) | undefined
        name?: (string | null) | undefined
        properties: Record<string, unknown>
        uuid?: (string | null) | undefined
    }
    export type SnapshotSource = 'web' | 'mobile' | 'unknown'
    export type Storage = 'object_storage_lts' | 'object_storage'
    export type SessionRecordingType = {
        active_seconds?: (number | null) | undefined
        activity_score?: (number | null) | undefined
        click_count?: (number | null) | undefined
        console_error_count?: (number | null) | undefined
        console_log_count?: (number | null) | undefined
        console_warn_count?: (number | null) | undefined
        distinct_id?: (string | null) | undefined
        email?: (string | null) | undefined
        end_time: string
        id: string
        inactive_seconds?: (number | null) | undefined
        keypress_count?: (number | null) | undefined
        matching_events?: (Array<MatchedRecording> | null) | undefined
        mouse_activity_count?: (number | null) | undefined
        ongoing?: (boolean | null) | undefined
        person?: (PersonType | null) | undefined
        recording_duration: number
        retention_period_days?: (number | null) | undefined
        snapshot_source: SnapshotSource
        start_time: string
        start_url?: (string | null) | undefined
        storage?: (Storage | null) | undefined
        summary?: (string | null) | undefined
        viewed: boolean
        viewers: Array<string>
    }
    export type RecordingsQueryResponse = {
        has_next: boolean
        results: Array<SessionRecordingType>
    }
    export type RecordingsQuery = Partial<{
        actions: Array<Record<string, unknown>> | null
        comment_text: RecordingPropertyFilter | null
        console_log_filters: Array<LogEntryPropertyFilter> | null
        date_from: string | null
        date_to: string | null
        distinct_ids: Array<string> | null
        events: Array<Record<string, unknown>> | null
        filter_test_accounts: boolean | null
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
        > | null
        kind: string
        limit: number | null
        modifiers: HogQLQueryModifiers | null
        offset: number | null
        operand: FilterLogicalOperator | null
        order: RecordingOrder | null
        order_direction: RecordingOrderDirection | null
        person_uuid: string | null
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
        > | null
        response: RecordingsQueryResponse | null
        session_ids: Array<string> | null
        tags: QueryLogTags | null
        user_modified_filters: Record<string, unknown> | null
        version: number | null
    }>
    export type VectorSearchResponseItem = { distance: number; id: string }
    export type VectorSearchQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<VectorSearchResponseItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type VectorSearchQuery = {
        embedding: Array<number>
        embeddingVersion?: (number | null) | undefined
        kind?: string | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        response?: (VectorSearchQueryResponse | null) | undefined
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type HogQLMetadata = {
        debug?: (boolean | null) | undefined
        filters?: (HogQLFilters | null) | undefined
        globals?: (Record<string, unknown> | null) | undefined
        kind?: string | undefined
        language: HogLanguage
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query: string
        response?: (HogQLMetadataResponse | null) | undefined
        sourceQuery?:
            | (
                  | EventsNode
                  | ActionsNode
                  | PersonsNode
                  | EventsQuery
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
                  | ErrorTrackingIssueCorrelationQuery
                  | LogsQuery
                  | ExperimentFunnelsQuery
                  | ExperimentTrendsQuery
                  | CalendarHeatmapQuery
                  | RecordingsQuery
                  | TracesQuery
                  | VectorSearchQuery
                  | null
              )
            | undefined
        tags?: (QueryLogTags | null) | undefined
        variables?: (Record<string, unknown> | null) | undefined
        version?: (number | null) | undefined
    }
    export type HogQLAutocomplete = {
        endPosition: number
        filters?: (HogQLFilters | null) | undefined
        globals?: (Record<string, unknown> | null) | undefined
        kind?: string | undefined
        language: HogLanguage
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query: string
        response?: (HogQLAutocompleteResponse | null) | undefined
        sourceQuery?:
            | (
                  | EventsNode
                  | ActionsNode
                  | PersonsNode
                  | EventsQuery
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
                  | ErrorTrackingIssueCorrelationQuery
                  | LogsQuery
                  | ExperimentFunnelsQuery
                  | ExperimentTrendsQuery
                  | CalendarHeatmapQuery
                  | RecordingsQuery
                  | TracesQuery
                  | VectorSearchQuery
                  | null
              )
            | undefined
        startPosition: number
        tags?: (QueryLogTags | null) | undefined
        version?: (number | null) | undefined
    }
    export type Insight = {
        id: number
        short_id: string
        name?: (string | null) | undefined
        derived_name?: (string | null) | undefined
        query?: (Record<string, unknown> | null) | undefined
        order?: (number | null) | undefined
        deleted?: boolean | undefined
        dashboards?: Array<number> | undefined
        dashboard_tiles: Array<DashboardTileBasic>
        last_refresh: string
        cache_target_age: string
        next_allowed_client_refresh: string
        result: string
        hasMore: string
        columns: string
        created_at: string | null
        created_by: UserBasic & unknown
        description?: (string | null) | undefined
        updated_at: string
        tags?: Array<unknown> | undefined
        favorited?: boolean | undefined
        last_modified_at: string
        last_modified_by: UserBasic & unknown
        is_sample: boolean
        effective_restriction_level: EffectiveRestrictionLevelEnum & unknown
        effective_privilege_level: EffectivePrivilegeLevelEnum & unknown
        user_access_level: string | null
        timezone: string
        is_cached: string
        query_status: string
        hogql: string
        types: string
        _create_in_folder?: string | undefined
        alerts: string
    }
    export type RETENTION = Partial<{
        hideLineGraph: boolean | null
        hideSizeColumn: boolean | null
        useSmallLayout: boolean | null
    }>
    export type VizSpecificOptions = Partial<{
        ActionsPie: ActionsPie | null
        RETENTION: RETENTION | null
    }>
    export type InsightVizNode = {
        embedded?: (boolean | null) | undefined
        full?: (boolean | null) | undefined
        hidePersonsModal?: (boolean | null) | undefined
        hideTooltipOnScroll?: (boolean | null) | undefined
        kind?: string | undefined
        showCorrelationTable?: (boolean | null) | undefined
        showFilters?: (boolean | null) | undefined
        showHeader?: (boolean | null) | undefined
        showLastComputation?: (boolean | null) | undefined
        showLastComputationRefresh?: (boolean | null) | undefined
        showResults?: (boolean | null) | undefined
        showTable?: (boolean | null) | undefined
        source:
            | TrendsQuery
            | FunnelsQuery
            | RetentionQuery
            | PathsQuery
            | StickinessQuery
            | LifecycleQuery
        suppressSessionAnalysisWarning?: (boolean | null) | undefined
        version?: (number | null) | undefined
        vizSpecificOptions?: (VizSpecificOptions | null) | undefined
    }
    export type MinimalPerson = {
        id: number
        name: string
        distinct_ids: string
        properties?: unknown | undefined
        created_at: string
        uuid: string
    }
    export type Notebook = {
        id: string
        short_id: string
        title?: (string | null) | undefined
        content?: (unknown | null) | undefined
        text_content?: (string | null) | undefined
        version?: number | undefined
        deleted?: boolean | undefined
        created_at: string
        created_by: UserBasic & unknown
        last_modified_at: string
        last_modified_by: UserBasic & unknown
        user_access_level: string | null
        _create_in_folder?: string | undefined
    }
    export type NotebookMinimal = {
        id: string
        short_id: string
        title: string | null
        deleted: boolean
        created_at: string
        created_by: UserBasic & unknown
        last_modified_at: string
        last_modified_by: UserBasic & unknown
        user_access_level: string | null
        _create_in_folder?: string | undefined
    }
    export type OperatorEnum =
        | 'exact'
        | 'is_not'
        | 'icontains'
        | 'not_icontains'
        | 'regex'
        | 'not_regex'
        | 'gt'
        | 'lt'
        | 'gte'
        | 'lte'
        | 'is_set'
        | 'is_not_set'
        | 'is_date_exact'
        | 'is_date_after'
        | 'is_date_before'
        | 'in'
        | 'not_in'
    export type PluginsAccessLevelEnum = 0 | 3 | 6 | 9
    export type Organization = {
        id: string
        name: string
        slug: string
        logo_media_id?: (string | null) | undefined
        created_at: string
        updated_at: string
        membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null
        plugins_access_level: PluginsAccessLevelEnum & unknown
        teams: Array<Record<string, unknown>>
        projects: Array<Record<string, unknown>>
        available_product_features: Array<unknown> | null
        is_member_join_email_enabled?: boolean | undefined
        metadata: string
        customer_id: string | null
        enforce_2fa?: (boolean | null) | undefined
        members_can_invite?: (boolean | null) | undefined
        members_can_use_personal_api_keys?: boolean | undefined
        allow_publicly_shared_resources?: boolean | undefined
        member_count: string
        is_ai_data_processing_approved?: (boolean | null) | undefined
        default_experiment_stats_method?:
            | ((DefaultExperimentStatsMethodEnum | BlankEnum | NullEnum) | null)
            | undefined
        default_role_id?: (string | null) | undefined
    }
    export type OrganizationBasic = {
        id: string
        name: string
        slug: string
        logo_media_id: string | null
        membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null
        members_can_use_personal_api_keys?: boolean | undefined
    }
    export type OrganizationDomain = {
        id: string
        domain: string
        is_verified: boolean
        verified_at: string | null
        verification_challenge: string
        jit_provisioning_enabled?: boolean | undefined
        sso_enforcement?: string | undefined
        has_saml: boolean
        saml_entity_id?: (string | null) | undefined
        saml_acs_url?: (string | null) | undefined
        saml_x509_cert?: (string | null) | undefined
    }
    export type OrganizationMembershipLevel = 1 | 8 | 15
    export type OrganizationInvite = {
        id: string
        target_email: string
        first_name?: string | undefined
        emailing_attempt_made: boolean
        level?: (OrganizationMembershipLevel & unknown) | undefined
        is_expired: boolean
        created_by: UserBasic & unknown
        created_at: string
        updated_at: string
        message?: (string | null) | undefined
        private_project_access?: (unknown | null) | undefined
        send_email?: boolean | undefined
        combine_pending_invites?: boolean | undefined
    }
    export type OrganizationMember = {
        id: string
        user: UserBasic & unknown
        level?: (OrganizationMembershipLevel & unknown) | undefined
        joined_at: string
        updated_at: string
        is_2fa_enabled: boolean
        has_social_auth: boolean
        last_login: string
    }
    export type PaginatedActionList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Action>
    }
    export type PaginatedActivityLogList = Array<ActivityLog>
    export type PaginatedAnnotationList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Annotation>
    }
    export type PaginatedBatchExportBackfillList = {
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<BatchExportBackfill>
    }
    export type PaginatedBatchExportList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<BatchExport>
    }
    export type PaginatedBatchExportRunList = {
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<BatchExportRun>
    }
    export type PaginatedClickhouseEventList = Partial<{
        next: string | null
        results: Array<ClickhouseEvent>
    }>
    export type PaginatedCohortList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Cohort>
    }
    export type PaginatedDashboardBasicList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<DashboardBasic>
    }
    export type PaginatedDashboardTemplateList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<DashboardTemplate>
    }
    export type PaginatedDataWarehouseSavedQueryList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<DataWarehouseSavedQuery>
    }
    export type PaginatedEarlyAccessFeatureList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<EarlyAccessFeature>
    }
    export type PaginatedErrorTrackingAssignmentRuleList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ErrorTrackingAssignmentRule>
    }
    export type PaginatedErrorTrackingGroupingRuleList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ErrorTrackingGroupingRule>
    }
    export type PaginatedErrorTrackingReleaseList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ErrorTrackingRelease>
    }
    export type PaginatedErrorTrackingSuppressionRuleList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ErrorTrackingSuppressionRule>
    }
    export type PaginatedErrorTrackingSymbolSetList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ErrorTrackingSymbolSet>
    }
    export type PaginatedExperimentHoldoutList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ExperimentHoldout>
    }
    export type PaginatedExperimentList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Experiment>
    }
    export type PaginatedExperimentSavedMetricList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ExperimentSavedMetric>
    }
    export type PaginatedExportedAssetList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ExportedAsset>
    }
    export type PaginatedFeatureFlagList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<FeatureFlag>
    }
    export type PaginatedFeatureFlagRoleAccessList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<FeatureFlagRoleAccess>
    }
    export type PaginatedFileSystemList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<FileSystem>
    }
    export type PaginatedFileSystemShortcutList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<FileSystemShortcut>
    }
    export type PaginatedGroupList = {
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Group>
    }
    export type PaginatedGroupUsageMetricList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<GroupUsageMetric>
    }
    export type PaginatedHogFunctionMinimalList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<HogFunctionMinimal>
    }
    export type PaginatedInsightList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Insight>
    }
    export type PaginatedNotebookMinimalList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<NotebookMinimal>
    }
    export type PaginatedOrganizationDomainList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<OrganizationDomain>
    }
    export type PaginatedOrganizationInviteList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<OrganizationInvite>
    }
    export type PaginatedOrganizationList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Organization>
    }
    export type PaginatedOrganizationMemberList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<OrganizationMember>
    }
    export type PersistedFolderTypeEnum = 'home' | 'pinned'
    export type PersistedFolder = {
        id: string
        type: PersistedFolderTypeEnum
        protocol?: string | undefined
        path?: string | undefined
        created_at: string
        updated_at: string
    }
    export type PaginatedPersistedFolderList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<PersistedFolder>
    }
    export type PaginatedPersonList = Partial<{
        next: string | null
        previous: string | null
        count: number
        results: Array<Person>
    }>
    export type PluginLogEntrySourceEnum = 'SYSTEM' | 'PLUGIN' | 'CONSOLE'
    export type PluginLogEntryTypeEnum = 'DEBUG' | 'LOG' | 'INFO' | 'WARN' | 'ERROR'
    export type PluginLogEntry = {
        id: string
        team_id: number
        plugin_id: number
        plugin_config_id: number
        timestamp: string
        source: PluginLogEntrySourceEnum
        type: PluginLogEntryTypeEnum
        message: string
        instance_id: string
    }
    export type PaginatedPluginLogEntryList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<PluginLogEntry>
    }
    export type TimezoneEnum =
        | 'Africa/Abidjan'
        | 'Africa/Accra'
        | 'Africa/Addis_Ababa'
        | 'Africa/Algiers'
        | 'Africa/Asmara'
        | 'Africa/Asmera'
        | 'Africa/Bamako'
        | 'Africa/Bangui'
        | 'Africa/Banjul'
        | 'Africa/Bissau'
        | 'Africa/Blantyre'
        | 'Africa/Brazzaville'
        | 'Africa/Bujumbura'
        | 'Africa/Cairo'
        | 'Africa/Casablanca'
        | 'Africa/Ceuta'
        | 'Africa/Conakry'
        | 'Africa/Dakar'
        | 'Africa/Dar_es_Salaam'
        | 'Africa/Djibouti'
        | 'Africa/Douala'
        | 'Africa/El_Aaiun'
        | 'Africa/Freetown'
        | 'Africa/Gaborone'
        | 'Africa/Harare'
        | 'Africa/Johannesburg'
        | 'Africa/Juba'
        | 'Africa/Kampala'
        | 'Africa/Khartoum'
        | 'Africa/Kigali'
        | 'Africa/Kinshasa'
        | 'Africa/Lagos'
        | 'Africa/Libreville'
        | 'Africa/Lome'
        | 'Africa/Luanda'
        | 'Africa/Lubumbashi'
        | 'Africa/Lusaka'
        | 'Africa/Malabo'
        | 'Africa/Maputo'
        | 'Africa/Maseru'
        | 'Africa/Mbabane'
        | 'Africa/Mogadishu'
        | 'Africa/Monrovia'
        | 'Africa/Nairobi'
        | 'Africa/Ndjamena'
        | 'Africa/Niamey'
        | 'Africa/Nouakchott'
        | 'Africa/Ouagadougou'
        | 'Africa/Porto-Novo'
        | 'Africa/Sao_Tome'
        | 'Africa/Timbuktu'
        | 'Africa/Tripoli'
        | 'Africa/Tunis'
        | 'Africa/Windhoek'
        | 'America/Adak'
        | 'America/Anchorage'
        | 'America/Anguilla'
        | 'America/Antigua'
        | 'America/Araguaina'
        | 'America/Argentina/Buenos_Aires'
        | 'America/Argentina/Catamarca'
        | 'America/Argentina/ComodRivadavia'
        | 'America/Argentina/Cordoba'
        | 'America/Argentina/Jujuy'
        | 'America/Argentina/La_Rioja'
        | 'America/Argentina/Mendoza'
        | 'America/Argentina/Rio_Gallegos'
        | 'America/Argentina/Salta'
        | 'America/Argentina/San_Juan'
        | 'America/Argentina/San_Luis'
        | 'America/Argentina/Tucuman'
        | 'America/Argentina/Ushuaia'
        | 'America/Aruba'
        | 'America/Asuncion'
        | 'America/Atikokan'
        | 'America/Atka'
        | 'America/Bahia'
        | 'America/Bahia_Banderas'
        | 'America/Barbados'
        | 'America/Belem'
        | 'America/Belize'
        | 'America/Blanc-Sablon'
        | 'America/Boa_Vista'
        | 'America/Bogota'
        | 'America/Boise'
        | 'America/Buenos_Aires'
        | 'America/Cambridge_Bay'
        | 'America/Campo_Grande'
        | 'America/Cancun'
        | 'America/Caracas'
        | 'America/Catamarca'
        | 'America/Cayenne'
        | 'America/Cayman'
        | 'America/Chicago'
        | 'America/Chihuahua'
        | 'America/Ciudad_Juarez'
        | 'America/Coral_Harbour'
        | 'America/Cordoba'
        | 'America/Costa_Rica'
        | 'America/Creston'
        | 'America/Cuiaba'
        | 'America/Curacao'
        | 'America/Danmarkshavn'
        | 'America/Dawson'
        | 'America/Dawson_Creek'
        | 'America/Denver'
        | 'America/Detroit'
        | 'America/Dominica'
        | 'America/Edmonton'
        | 'America/Eirunepe'
        | 'America/El_Salvador'
        | 'America/Ensenada'
        | 'America/Fort_Nelson'
        | 'America/Fort_Wayne'
        | 'America/Fortaleza'
        | 'America/Glace_Bay'
        | 'America/Godthab'
        | 'America/Goose_Bay'
        | 'America/Grand_Turk'
        | 'America/Grenada'
        | 'America/Guadeloupe'
        | 'America/Guatemala'
        | 'America/Guayaquil'
        | 'America/Guyana'
        | 'America/Halifax'
        | 'America/Havana'
        | 'America/Hermosillo'
        | 'America/Indiana/Indianapolis'
        | 'America/Indiana/Knox'
        | 'America/Indiana/Marengo'
        | 'America/Indiana/Petersburg'
        | 'America/Indiana/Tell_City'
        | 'America/Indiana/Vevay'
        | 'America/Indiana/Vincennes'
        | 'America/Indiana/Winamac'
        | 'America/Indianapolis'
        | 'America/Inuvik'
        | 'America/Iqaluit'
        | 'America/Jamaica'
        | 'America/Jujuy'
        | 'America/Juneau'
        | 'America/Kentucky/Louisville'
        | 'America/Kentucky/Monticello'
        | 'America/Knox_IN'
        | 'America/Kralendijk'
        | 'America/La_Paz'
        | 'America/Lima'
        | 'America/Los_Angeles'
        | 'America/Louisville'
        | 'America/Lower_Princes'
        | 'America/Maceio'
        | 'America/Managua'
        | 'America/Manaus'
        | 'America/Marigot'
        | 'America/Martinique'
        | 'America/Matamoros'
        | 'America/Mazatlan'
        | 'America/Mendoza'
        | 'America/Menominee'
        | 'America/Merida'
        | 'America/Metlakatla'
        | 'America/Mexico_City'
        | 'America/Miquelon'
        | 'America/Moncton'
        | 'America/Monterrey'
        | 'America/Montevideo'
        | 'America/Montreal'
        | 'America/Montserrat'
        | 'America/Nassau'
        | 'America/New_York'
        | 'America/Nipigon'
        | 'America/Nome'
        | 'America/Noronha'
        | 'America/North_Dakota/Beulah'
        | 'America/North_Dakota/Center'
        | 'America/North_Dakota/New_Salem'
        | 'America/Nuuk'
        | 'America/Ojinaga'
        | 'America/Panama'
        | 'America/Pangnirtung'
        | 'America/Paramaribo'
        | 'America/Phoenix'
        | 'America/Port-au-Prince'
        | 'America/Port_of_Spain'
        | 'America/Porto_Acre'
        | 'America/Porto_Velho'
        | 'America/Puerto_Rico'
        | 'America/Punta_Arenas'
        | 'America/Rainy_River'
        | 'America/Rankin_Inlet'
        | 'America/Recife'
        | 'America/Regina'
        | 'America/Resolute'
        | 'America/Rio_Branco'
        | 'America/Rosario'
        | 'America/Santa_Isabel'
        | 'America/Santarem'
        | 'America/Santiago'
        | 'America/Santo_Domingo'
        | 'America/Sao_Paulo'
        | 'America/Scoresbysund'
        | 'America/Shiprock'
        | 'America/Sitka'
        | 'America/St_Barthelemy'
        | 'America/St_Johns'
        | 'America/St_Kitts'
        | 'America/St_Lucia'
        | 'America/St_Thomas'
        | 'America/St_Vincent'
        | 'America/Swift_Current'
        | 'America/Tegucigalpa'
        | 'America/Thule'
        | 'America/Thunder_Bay'
        | 'America/Tijuana'
        | 'America/Toronto'
        | 'America/Tortola'
        | 'America/Vancouver'
        | 'America/Virgin'
        | 'America/Whitehorse'
        | 'America/Winnipeg'
        | 'America/Yakutat'
        | 'America/Yellowknife'
        | 'Antarctica/Casey'
        | 'Antarctica/Davis'
        | 'Antarctica/DumontDUrville'
        | 'Antarctica/Macquarie'
        | 'Antarctica/Mawson'
        | 'Antarctica/McMurdo'
        | 'Antarctica/Palmer'
        | 'Antarctica/Rothera'
        | 'Antarctica/South_Pole'
        | 'Antarctica/Syowa'
        | 'Antarctica/Troll'
        | 'Antarctica/Vostok'
        | 'Arctic/Longyearbyen'
        | 'Asia/Aden'
        | 'Asia/Almaty'
        | 'Asia/Amman'
        | 'Asia/Anadyr'
        | 'Asia/Aqtau'
        | 'Asia/Aqtobe'
        | 'Asia/Ashgabat'
        | 'Asia/Ashkhabad'
        | 'Asia/Atyrau'
        | 'Asia/Baghdad'
        | 'Asia/Bahrain'
        | 'Asia/Baku'
        | 'Asia/Bangkok'
        | 'Asia/Barnaul'
        | 'Asia/Beirut'
        | 'Asia/Bishkek'
        | 'Asia/Brunei'
        | 'Asia/Calcutta'
        | 'Asia/Chita'
        | 'Asia/Choibalsan'
        | 'Asia/Chongqing'
        | 'Asia/Chungking'
        | 'Asia/Colombo'
        | 'Asia/Dacca'
        | 'Asia/Damascus'
        | 'Asia/Dhaka'
        | 'Asia/Dili'
        | 'Asia/Dubai'
        | 'Asia/Dushanbe'
        | 'Asia/Famagusta'
        | 'Asia/Gaza'
        | 'Asia/Harbin'
        | 'Asia/Hebron'
        | 'Asia/Ho_Chi_Minh'
        | 'Asia/Hong_Kong'
        | 'Asia/Hovd'
        | 'Asia/Irkutsk'
        | 'Asia/Istanbul'
        | 'Asia/Jakarta'
        | 'Asia/Jayapura'
        | 'Asia/Jerusalem'
        | 'Asia/Kabul'
        | 'Asia/Kamchatka'
        | 'Asia/Karachi'
        | 'Asia/Kashgar'
        | 'Asia/Kathmandu'
        | 'Asia/Katmandu'
        | 'Asia/Khandyga'
        | 'Asia/Kolkata'
        | 'Asia/Krasnoyarsk'
        | 'Asia/Kuala_Lumpur'
        | 'Asia/Kuching'
        | 'Asia/Kuwait'
        | 'Asia/Macao'
        | 'Asia/Macau'
        | 'Asia/Magadan'
        | 'Asia/Makassar'
        | 'Asia/Manila'
        | 'Asia/Muscat'
        | 'Asia/Nicosia'
        | 'Asia/Novokuznetsk'
        | 'Asia/Novosibirsk'
        | 'Asia/Omsk'
        | 'Asia/Oral'
        | 'Asia/Phnom_Penh'
        | 'Asia/Pontianak'
        | 'Asia/Pyongyang'
        | 'Asia/Qatar'
        | 'Asia/Qostanay'
        | 'Asia/Qyzylorda'
        | 'Asia/Rangoon'
        | 'Asia/Riyadh'
        | 'Asia/Saigon'
        | 'Asia/Sakhalin'
        | 'Asia/Samarkand'
        | 'Asia/Seoul'
        | 'Asia/Shanghai'
        | 'Asia/Singapore'
        | 'Asia/Srednekolymsk'
        | 'Asia/Taipei'
        | 'Asia/Tashkent'
        | 'Asia/Tbilisi'
        | 'Asia/Tehran'
        | 'Asia/Tel_Aviv'
        | 'Asia/Thimbu'
        | 'Asia/Thimphu'
        | 'Asia/Tokyo'
        | 'Asia/Tomsk'
        | 'Asia/Ujung_Pandang'
        | 'Asia/Ulaanbaatar'
        | 'Asia/Ulan_Bator'
        | 'Asia/Urumqi'
        | 'Asia/Ust-Nera'
        | 'Asia/Vientiane'
        | 'Asia/Vladivostok'
        | 'Asia/Yakutsk'
        | 'Asia/Yangon'
        | 'Asia/Yekaterinburg'
        | 'Asia/Yerevan'
        | 'Atlantic/Azores'
        | 'Atlantic/Bermuda'
        | 'Atlantic/Canary'
        | 'Atlantic/Cape_Verde'
        | 'Atlantic/Faeroe'
        | 'Atlantic/Faroe'
        | 'Atlantic/Jan_Mayen'
        | 'Atlantic/Madeira'
        | 'Atlantic/Reykjavik'
        | 'Atlantic/South_Georgia'
        | 'Atlantic/St_Helena'
        | 'Atlantic/Stanley'
        | 'Australia/ACT'
        | 'Australia/Adelaide'
        | 'Australia/Brisbane'
        | 'Australia/Broken_Hill'
        | 'Australia/Canberra'
        | 'Australia/Currie'
        | 'Australia/Darwin'
        | 'Australia/Eucla'
        | 'Australia/Hobart'
        | 'Australia/LHI'
        | 'Australia/Lindeman'
        | 'Australia/Lord_Howe'
        | 'Australia/Melbourne'
        | 'Australia/NSW'
        | 'Australia/North'
        | 'Australia/Perth'
        | 'Australia/Queensland'
        | 'Australia/South'
        | 'Australia/Sydney'
        | 'Australia/Tasmania'
        | 'Australia/Victoria'
        | 'Australia/West'
        | 'Australia/Yancowinna'
        | 'Brazil/Acre'
        | 'Brazil/DeNoronha'
        | 'Brazil/East'
        | 'Brazil/West'
        | 'CET'
        | 'CST6CDT'
        | 'Canada/Atlantic'
        | 'Canada/Central'
        | 'Canada/Eastern'
        | 'Canada/Mountain'
        | 'Canada/Newfoundland'
        | 'Canada/Pacific'
        | 'Canada/Saskatchewan'
        | 'Canada/Yukon'
        | 'Chile/Continental'
        | 'Chile/EasterIsland'
        | 'Cuba'
        | 'EET'
        | 'EST'
        | 'EST5EDT'
        | 'Egypt'
        | 'Eire'
        | 'Etc/GMT'
        | 'Etc/GMT+0'
        | 'Etc/GMT+1'
        | 'Etc/GMT+10'
        | 'Etc/GMT+11'
        | 'Etc/GMT+12'
        | 'Etc/GMT+2'
        | 'Etc/GMT+3'
        | 'Etc/GMT+4'
        | 'Etc/GMT+5'
        | 'Etc/GMT+6'
        | 'Etc/GMT+7'
        | 'Etc/GMT+8'
        | 'Etc/GMT+9'
        | 'Etc/GMT-0'
        | 'Etc/GMT-1'
        | 'Etc/GMT-10'
        | 'Etc/GMT-11'
        | 'Etc/GMT-12'
        | 'Etc/GMT-13'
        | 'Etc/GMT-14'
        | 'Etc/GMT-2'
        | 'Etc/GMT-3'
        | 'Etc/GMT-4'
        | 'Etc/GMT-5'
        | 'Etc/GMT-6'
        | 'Etc/GMT-7'
        | 'Etc/GMT-8'
        | 'Etc/GMT-9'
        | 'Etc/GMT0'
        | 'Etc/Greenwich'
        | 'Etc/UCT'
        | 'Etc/UTC'
        | 'Etc/Universal'
        | 'Etc/Zulu'
        | 'Europe/Amsterdam'
        | 'Europe/Andorra'
        | 'Europe/Astrakhan'
        | 'Europe/Athens'
        | 'Europe/Belfast'
        | 'Europe/Belgrade'
        | 'Europe/Berlin'
        | 'Europe/Bratislava'
        | 'Europe/Brussels'
        | 'Europe/Bucharest'
        | 'Europe/Budapest'
        | 'Europe/Busingen'
        | 'Europe/Chisinau'
        | 'Europe/Copenhagen'
        | 'Europe/Dublin'
        | 'Europe/Gibraltar'
        | 'Europe/Guernsey'
        | 'Europe/Helsinki'
        | 'Europe/Isle_of_Man'
        | 'Europe/Istanbul'
        | 'Europe/Jersey'
        | 'Europe/Kaliningrad'
        | 'Europe/Kiev'
        | 'Europe/Kirov'
        | 'Europe/Kyiv'
        | 'Europe/Lisbon'
        | 'Europe/Ljubljana'
        | 'Europe/London'
        | 'Europe/Luxembourg'
        | 'Europe/Madrid'
        | 'Europe/Malta'
        | 'Europe/Mariehamn'
        | 'Europe/Minsk'
        | 'Europe/Monaco'
        | 'Europe/Moscow'
        | 'Europe/Nicosia'
        | 'Europe/Oslo'
        | 'Europe/Paris'
        | 'Europe/Podgorica'
        | 'Europe/Prague'
        | 'Europe/Riga'
        | 'Europe/Rome'
        | 'Europe/Samara'
        | 'Europe/San_Marino'
        | 'Europe/Sarajevo'
        | 'Europe/Saratov'
        | 'Europe/Simferopol'
        | 'Europe/Skopje'
        | 'Europe/Sofia'
        | 'Europe/Stockholm'
        | 'Europe/Tallinn'
        | 'Europe/Tirane'
        | 'Europe/Tiraspol'
        | 'Europe/Ulyanovsk'
        | 'Europe/Uzhgorod'
        | 'Europe/Vaduz'
        | 'Europe/Vatican'
        | 'Europe/Vienna'
        | 'Europe/Vilnius'
        | 'Europe/Volgograd'
        | 'Europe/Warsaw'
        | 'Europe/Zagreb'
        | 'Europe/Zaporozhye'
        | 'Europe/Zurich'
        | 'GB'
        | 'GB-Eire'
        | 'GMT'
        | 'GMT+0'
        | 'GMT-0'
        | 'GMT0'
        | 'Greenwich'
        | 'HST'
        | 'Hongkong'
        | 'Iceland'
        | 'Indian/Antananarivo'
        | 'Indian/Chagos'
        | 'Indian/Christmas'
        | 'Indian/Cocos'
        | 'Indian/Comoro'
        | 'Indian/Kerguelen'
        | 'Indian/Mahe'
        | 'Indian/Maldives'
        | 'Indian/Mauritius'
        | 'Indian/Mayotte'
        | 'Indian/Reunion'
        | 'Iran'
        | 'Israel'
        | 'Jamaica'
        | 'Japan'
        | 'Kwajalein'
        | 'Libya'
        | 'MET'
        | 'MST'
        | 'MST7MDT'
        | 'Mexico/BajaNorte'
        | 'Mexico/BajaSur'
        | 'Mexico/General'
        | 'NZ'
        | 'NZ-CHAT'
        | 'Navajo'
        | 'PRC'
        | 'PST8PDT'
        | 'Pacific/Apia'
        | 'Pacific/Auckland'
        | 'Pacific/Bougainville'
        | 'Pacific/Chatham'
        | 'Pacific/Chuuk'
        | 'Pacific/Easter'
        | 'Pacific/Efate'
        | 'Pacific/Enderbury'
        | 'Pacific/Fakaofo'
        | 'Pacific/Fiji'
        | 'Pacific/Funafuti'
        | 'Pacific/Galapagos'
        | 'Pacific/Gambier'
        | 'Pacific/Guadalcanal'
        | 'Pacific/Guam'
        | 'Pacific/Honolulu'
        | 'Pacific/Johnston'
        | 'Pacific/Kanton'
        | 'Pacific/Kiritimati'
        | 'Pacific/Kosrae'
        | 'Pacific/Kwajalein'
        | 'Pacific/Majuro'
        | 'Pacific/Marquesas'
        | 'Pacific/Midway'
        | 'Pacific/Nauru'
        | 'Pacific/Niue'
        | 'Pacific/Norfolk'
        | 'Pacific/Noumea'
        | 'Pacific/Pago_Pago'
        | 'Pacific/Palau'
        | 'Pacific/Pitcairn'
        | 'Pacific/Pohnpei'
        | 'Pacific/Ponape'
        | 'Pacific/Port_Moresby'
        | 'Pacific/Rarotonga'
        | 'Pacific/Saipan'
        | 'Pacific/Samoa'
        | 'Pacific/Tahiti'
        | 'Pacific/Tarawa'
        | 'Pacific/Tongatapu'
        | 'Pacific/Truk'
        | 'Pacific/Wake'
        | 'Pacific/Wallis'
        | 'Pacific/Yap'
        | 'Poland'
        | 'Portugal'
        | 'ROC'
        | 'ROK'
        | 'Singapore'
        | 'Turkey'
        | 'UCT'
        | 'US/Alaska'
        | 'US/Aleutian'
        | 'US/Arizona'
        | 'US/Central'
        | 'US/East-Indiana'
        | 'US/Eastern'
        | 'US/Hawaii'
        | 'US/Indiana-Starke'
        | 'US/Michigan'
        | 'US/Mountain'
        | 'US/Pacific'
        | 'US/Samoa'
        | 'UTC'
        | 'Universal'
        | 'W-SU'
        | 'WET'
        | 'Zulu'
    export type ProjectBackwardCompatBasic = {
        id: number
        uuid: string
        organization: string
        api_token: string
        name: string
        completed_snippet_onboarding: boolean
        has_completed_onboarding_for: unknown | null
        ingested_event: boolean
        is_demo: boolean
        timezone: TimezoneEnum & unknown
        access_control: boolean
    }
    export type PaginatedProjectBackwardCompatBasicList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ProjectBackwardCompatBasic>
    }
    export type PropertyTypeEnum = 'DateTime' | 'String' | 'Numeric' | 'Boolean' | 'Duration'
    export type PropertyDefinition = {
        id: string
        name: string
        is_numerical?: boolean | undefined
        property_type?: ((PropertyTypeEnum | BlankEnum | NullEnum) | null) | undefined
        tags?: Array<unknown> | undefined
        is_seen_on_filtered_events: string
    }
    export type PaginatedPropertyDefinitionList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<PropertyDefinition>
    }
    export type ProxyRecordStatusEnum =
        | 'waiting'
        | 'issuing'
        | 'valid'
        | 'warning'
        | 'erroring'
        | 'deleting'
        | 'timed_out'
    export type ProxyRecord = {
        id: string
        domain: string
        target_cname: string
        status: ProxyRecordStatusEnum & unknown
        message: string | null
        created_at: string
        updated_at: string
        created_by: number | null
    }
    export type PaginatedProxyRecordList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<ProxyRecord>
    }
    export type PaginatedRoleList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Role>
    }
    export type RoleMembership = {
        id: string
        role_id: string
        organization_member: OrganizationMember & unknown
        user: UserBasic & unknown
        joined_at: string
        updated_at: string
        user_uuid: string
    }
    export type PaginatedRoleMembershipList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<RoleMembership>
    }
    export type SessionRecording = {
        id: string
        distinct_id: string | null
        viewed: boolean
        viewers: Array<string>
        recording_duration: number
        active_seconds: number | null
        inactive_seconds: number | null
        start_time: string | null
        end_time: string | null
        click_count: number | null
        keypress_count: number | null
        mouse_activity_count: number | null
        console_log_count: number | null
        console_warn_count: number | null
        console_error_count: number | null
        start_url: string | null
        person?: MinimalPerson | undefined
        storage: string
        retention_period_days: number | null
        snapshot_source: string | null
        ongoing: boolean
        activity_score: number | null
    }
    export type PaginatedSessionRecordingList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<SessionRecording>
    }
    export type SessionRecordingPlaylistTypeEnum = 'collection' | 'filters'
    export type SessionRecordingPlaylist = {
        id: number
        short_id: string
        name?: (string | null) | undefined
        derived_name?: (string | null) | undefined
        description?: string | undefined
        pinned?: boolean | undefined
        created_at: string
        created_by: UserBasic & unknown
        deleted?: boolean | undefined
        filters?: unknown | undefined
        last_modified_at: string
        last_modified_by: UserBasic & unknown
        recordings_counts: Record<string, Record<string, unknown>>
        type: (SessionRecordingPlaylistTypeEnum | NullEnum) | null
        _create_in_folder?: string | undefined
    }
    export type PaginatedSessionRecordingPlaylistList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<SessionRecordingPlaylist>
    }
    export type TargetTypeEnum = 'email' | 'slack' | 'webhook'
    export type Subscription = {
        id: number
        dashboard?: (number | null) | undefined
        insight?: (number | null) | undefined
        target_type: TargetTypeEnum
        target_value: string
        frequency: FrequencyEnum
        interval?: number | undefined
        byweekday?: (Array<ByweekdayEnum> | null) | undefined
        bysetpos?: (number | null) | undefined
        count?: (number | null) | undefined
        start_date: string
        until_date?: (string | null) | undefined
        created_at: string
        created_by: UserBasic & unknown
        deleted?: boolean | undefined
        title?: (string | null) | undefined
        summary: string
        next_delivery_date: string | null
        invite_message?: (string | null) | undefined
    }
    export type PaginatedSubscriptionList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Subscription>
    }
    export type SurveyType = 'popover' | 'widget' | 'external_survey' | 'api'
    export type ResponseSamplingIntervalTypeEnum = 'day' | 'week' | 'month'
    export type Survey = {
        id: string
        name: string
        description?: string | undefined
        type: SurveyType
        schedule?: (string | null) | undefined
        linked_flag: MinimalFeatureFlag & unknown
        linked_flag_id?: (number | null) | undefined
        targeting_flag: MinimalFeatureFlag & unknown
        internal_targeting_flag: MinimalFeatureFlag & unknown
        questions?: (unknown | null) | undefined
        conditions: string
        appearance?: (unknown | null) | undefined
        created_at: string
        created_by: UserBasic & unknown
        start_date?: (string | null) | undefined
        end_date?: (string | null) | undefined
        archived?: boolean | undefined
        responses_limit?: (number | null) | undefined
        feature_flag_keys: Array<unknown>
        iteration_count?: (number | null) | undefined
        iteration_frequency_days?: (number | null) | undefined
        iteration_start_dates?: (Array<string | null> | null) | undefined
        current_iteration?: (number | null) | undefined
        current_iteration_start_date?: (string | null) | undefined
        response_sampling_start_date?: (string | null) | undefined
        response_sampling_interval_type?:
            | ((ResponseSamplingIntervalTypeEnum | BlankEnum | NullEnum) | null)
            | undefined
        response_sampling_interval?: (number | null) | undefined
        response_sampling_limit?: (number | null) | undefined
        response_sampling_daily_limits?: (unknown | null) | undefined
        enable_partial_responses?: (boolean | null) | undefined
    }
    export type PaginatedSurveyList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Survey>
    }
    export type TableFormatEnum =
        | 'CSV'
        | 'CSVWithNames'
        | 'Parquet'
        | 'JSONEachRow'
        | 'Delta'
        | 'DeltaS3Wrapper'
    export type SourceTypeEnum =
        | 'Stripe'
        | 'Hubspot'
        | 'Postgres'
        | 'Zendesk'
        | 'Snowflake'
        | 'Salesforce'
        | 'MySQL'
        | 'MongoDB'
        | 'MSSQL'
        | 'Vitally'
        | 'BigQuery'
        | 'Chargebee'
        | 'GoogleAds'
        | 'TemporalIO'
        | 'DoIt'
        | 'GoogleSheets'
        | 'MetaAds'
        | 'Klaviyo'
        | 'Mailchimp'
        | 'Braze'
        | 'Mailjet'
        | 'Redshift'
        | 'Polar'
        | 'RevenueCat'
        | 'LinkedinAds'
        | 'RedditAds'
    export type SimpleExternalDataSourceSerializers = {
        id: string
        created_at: string
        created_by: number | null
        status: string
        source_type: SourceTypeEnum & unknown
    }
    export type Table = {
        id: string
        deleted?: (boolean | null) | undefined
        name: string
        format: TableFormatEnum
        created_by: UserBasic & unknown
        created_at: string
        url_pattern: string
        credential: Credential
        columns: string
        external_data_source: SimpleExternalDataSourceSerializers & unknown
        external_schema: string
    }
    export type PaginatedTableList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<Table>
    }
    export type TeamBasic = {
        id: number
        uuid: string
        organization: string
        project_id: number
        api_token: string
        name: string
        completed_snippet_onboarding: boolean
        has_completed_onboarding_for: unknown | null
        ingested_event: boolean
        is_demo: boolean
        timezone: TimezoneEnum & unknown
        access_control: boolean
    }
    export type PaginatedTeamBasicList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<TeamBasic>
    }
    export type UserInterview = {
        id: string
        created_by: UserBasic & unknown
        created_at: string
        interviewee_emails?: Array<string> | undefined
        transcript: string
        summary?: string | undefined
        audio: string
    }
    export type PaginatedUserInterviewList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<UserInterview>
    }
    export type ToolbarModeEnum = 'disabled' | 'toolbar'
    export type ScenePersonalisationBasic = {
        scene: string
        dashboard?: (number | null) | undefined
    }
    export type ThemeModeEnum = 'light' | 'dark' | 'system'
    export type User = {
        date_joined: string
        uuid: string
        distinct_id: string | null
        first_name?: string | undefined
        last_name?: string | undefined
        email: string
        pending_email: string | null
        is_email_verified: boolean | null
        notification_settings?: Record<string, unknown> | undefined
        anonymize_data?: (boolean | null) | undefined
        toolbar_mode?: ((ToolbarModeEnum | BlankEnum | NullEnum) | null) | undefined
        has_password: boolean
        id: number
        is_staff?: boolean | undefined
        is_impersonated: boolean | null
        is_impersonated_until: string | null
        sensitive_session_expires_at: string | null
        team: TeamBasic & unknown
        organization: Organization & unknown
        organizations: Array<OrganizationBasic>
        set_current_organization?: string | undefined
        set_current_team?: string | undefined
        password: string
        current_password?: string | undefined
        events_column_config?: unknown | undefined
        is_2fa_enabled: boolean
        has_social_auth: boolean
        has_sso_enforcement: boolean
        has_seen_product_intro_for?: (unknown | null) | undefined
        scene_personalisation: Array<ScenePersonalisationBasic>
        theme_mode?: ((ThemeModeEnum | BlankEnum | NullEnum) | null) | undefined
        hedgehog_config?: (unknown | null) | undefined
        role_at_organization?: RoleAtOrganizationEnum | undefined
    }
    export type PaginatedUserList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<User>
    }
    export type WebExperimentsAPI = {
        id: number
        name: string
        created_at?: string | undefined
        feature_flag_key: string
        variants: unknown
    }
    export type PaginatedWebExperimentsAPIList = {
        count: number
        next?: (string | null) | undefined
        previous?: (string | null) | undefined
        results: Array<WebExperimentsAPI>
    }
    export type PatchedAction = Partial<{
        id: number
        name: string | null
        description: string
        tags: Array<unknown>
        post_to_slack: boolean
        slack_message_format: string
        steps: Array<ActionStepJSON>
        created_at: string
        created_by: UserBasic & unknown
        deleted: boolean
        is_calculating: boolean
        last_calculated_at: string
        team_id: number
        is_action: boolean
        bytecode_error: string | null
        pinned_at: string | null
        creation_context: string
        _create_in_folder: string
    }>
    export type PatchedAnnotation = Partial<{
        id: number
        content: string | null
        date_marker: string | null
        creation_type: CreationTypeEnum
        dashboard_item: number | null
        dashboard_id: number | null
        dashboard_name: string | null
        insight_short_id: string | null
        insight_name: string | null
        insight_derived_name: string | null
        created_by: UserBasic & unknown
        created_at: string | null
        updated_at: string
        deleted: boolean
        scope: AnnotationScopeEnum
    }>
    export type PatchedBatchExport = Partial<{
        id: string
        team_id: number
        name: string
        model: (ModelEnum | BlankEnum | NullEnum) | null
        destination: BatchExportDestination
        interval: IntervalEnum
        paused: boolean
        created_at: string
        last_updated_at: string
        last_paused_at: string | null
        start_at: string | null
        end_at: string | null
        latest_runs: Array<BatchExportRun>
        hogql_query: string
        schema: unknown | null
        filters: unknown | null
    }>
    export type PatchedCohort = Partial<{
        id: number
        name: string | null
        description: string
        groups: unknown
        deleted: boolean
        filters: unknown | null
        query: unknown | null
        is_calculating: boolean
        created_by: UserBasic & unknown
        created_at: string | null
        last_calculation: string | null
        errors_calculating: number
        count: number | null
        is_static: boolean
        cohort_type: (CohortTypeEnum | BlankEnum | NullEnum) | null
        experiment_set: Array<number>
        _create_in_folder: string
    }>
    export type PatchedDashboard = Partial<{
        id: number
        name: string | null
        description: string
        pinned: boolean
        created_at: string
        created_by: UserBasic & unknown
        is_shared: boolean
        deleted: boolean
        creation_mode: CreationModeEnum & unknown
        use_template: string
        use_dashboard: number | null
        delete_insights: boolean
        filters: Record<string, unknown>
        variables: Record<string, unknown> | null
        breakdown_colors: unknown
        data_color_theme_id: number | null
        tags: Array<unknown>
        tiles: Array<Record<string, unknown>> | null
        restriction_level: DashboardRestrictionLevel & unknown
        effective_restriction_level: EffectiveRestrictionLevelEnum & unknown
        effective_privilege_level: EffectivePrivilegeLevelEnum & unknown
        user_access_level: string | null
        access_control_version: string
        _create_in_folder: string
        last_refresh: string | null
        persisted_filters: Record<string, unknown> | null
        persisted_variables: Record<string, unknown> | null
        team_id: number
    }>
    export type PatchedDashboardTemplate = Partial<{
        id: string
        template_name: string | null
        dashboard_description: string | null
        dashboard_filters: unknown | null
        tags: Array<string> | null
        tiles: unknown | null
        variables: unknown | null
        deleted: boolean | null
        created_at: string | null
        created_by: number | null
        image_url: string | null
        team_id: number | null
        scope: (DashboardTemplateScopeEnum | BlankEnum | NullEnum) | null
        availability_contexts: Array<string> | null
    }>
    export type PatchedDataWarehouseSavedQuery = Partial<{
        id: string
        deleted: boolean | null
        name: string
        query: unknown | null
        created_by: UserBasic & unknown
        created_at: string
        sync_frequency: string
        columns: string
        status: (DataWarehouseSavedQueryStatusEnum | NullEnum) | null
        last_run_at: string | null
        latest_error: string | null
        edited_history_id: string | null
        latest_history_id: string
        soft_update: boolean | null
        is_materialized: boolean | null
    }>
    export type PatchedEarlyAccessFeature = Partial<{
        id: string
        feature_flag: MinimalFeatureFlag & unknown
        name: string
        description: string
        stage: StageEnum
        documentation_url: string
        created_at: string
    }>
    export type PatchedErrorTrackingAssignmentRule = Partial<{
        id: string
        filters: unknown
        assignee: string
        order_key: number
        disabled_data: unknown | null
    }>
    export type PatchedErrorTrackingGroupingRule = Partial<{
        id: string
        filters: unknown
        assignee: string
        order_key: number
        disabled_data: unknown | null
    }>
    export type PatchedErrorTrackingRelease = Partial<{
        id: string
        hash_id: string
        team_id: number
        created_at: string
        metadata: unknown | null
        version: string
        project: string
    }>
    export type PatchedErrorTrackingSuppressionRule = Partial<{
        id: string
        filters: unknown
        order_key: number
    }>
    export type PatchedErrorTrackingSymbolSet = Partial<{
        id: string
        ref: string
        team_id: number
        created_at: string
        storage_ptr: string | null
        failure_reason: string | null
    }>
    export type PatchedExperiment = Partial<{
        id: number
        name: string
        description: string | null
        start_date: string | null
        end_date: string | null
        feature_flag_key: string
        feature_flag: MinimalFeatureFlag & unknown
        holdout: ExperimentHoldout & unknown
        holdout_id: number | null
        exposure_cohort: number | null
        parameters: unknown | null
        secondary_metrics: unknown | null
        saved_metrics: Array<ExperimentToSavedMetric>
        saved_metrics_ids: Array<unknown> | null
        filters: unknown
        archived: boolean
        deleted: boolean | null
        created_by: UserBasic & unknown
        created_at: string
        updated_at: string
        type: (ExperimentTypeEnum | BlankEnum | NullEnum) | null
        exposure_criteria: unknown | null
        metrics: unknown | null
        metrics_secondary: unknown | null
        stats_config: unknown | null
        _create_in_folder: string
        conclusion: (ConclusionEnum | BlankEnum | NullEnum) | null
        conclusion_comment: string | null
        primary_metrics_ordered_uuids: unknown | null
        secondary_metrics_ordered_uuids: unknown | null
    }>
    export type PatchedExperimentHoldout = Partial<{
        id: number
        name: string
        description: string | null
        filters: unknown
        created_by: UserBasic & unknown
        created_at: string
        updated_at: string
    }>
    export type PatchedExperimentSavedMetric = Partial<{
        id: number
        name: string
        description: string | null
        query: unknown
        created_by: UserBasic & unknown
        created_at: string
        updated_at: string
        tags: Array<unknown>
    }>
    export type PatchedExplicitTeamMember = Partial<{
        id: string
        level: ExplicitTeamMemberLevelEnum & unknown
        parent_level: number
        parent_membership_id: string
        joined_at: string
        updated_at: string
        user: UserBasic & unknown
        user_uuid: string
        effective_level: EffectiveMembershipLevelEnum & unknown
    }>
    export type PatchedFeatureFlag = Partial<{
        id: number
        name: string
        key: string
        filters: Record<string, unknown>
        deleted: boolean
        active: boolean
        created_by: UserBasic & unknown
        created_at: string
        version: number
        last_modified_by: UserBasic & unknown
        is_simple_flag: boolean
        rollout_percentage: number | null
        ensure_experience_continuity: boolean | null
        experiment_set: string
        surveys: Record<string, unknown>
        features: Record<string, unknown>
        rollback_conditions: unknown | null
        performed_rollback: boolean | null
        can_edit: boolean
        tags: Array<unknown>
        usage_dashboard: number
        analytics_dashboards: Array<number>
        has_enriched_analytics: boolean | null
        user_access_level: string | null
        creation_context: CreationContextEnum & unknown
        is_remote_configuration: boolean | null
        has_encrypted_payloads: boolean | null
        status: string
        evaluation_runtime: (EvaluationRuntimeEnum | BlankEnum | NullEnum) | null
        _create_in_folder: string
    }>
    export type PatchedFileSystem = Partial<{
        id: string
        path: string
        depth: number | null
        type: string
        ref: string | null
        href: string | null
        meta: unknown | null
        shortcut: boolean | null
        created_at: string
    }>
    export type PatchedFileSystemShortcut = Partial<{
        id: string
        path: string
        type: string
        ref: string | null
        href: string | null
        created_at: string
    }>
    export type PatchedGroupType = Partial<{
        group_type: string
        group_type_index: number
        name_singular: string | null
        name_plural: string | null
        detail_dashboard: number | null
        default_columns: Array<string> | null
        created_at: string | null
    }>
    export type PatchedGroupUsageMetric = Partial<{
        id: string
        name: string
        format: GroupUsageMetricFormatEnum
        interval: number
        display: DisplayEnum
        filters: unknown
    }>
    export type PatchedHogFunction = Partial<{
        id: string
        type: (HogFunctionTypeEnum | NullEnum) | null
        name: string | null
        description: string
        created_at: string
        created_by: UserBasic & unknown
        updated_at: string
        enabled: boolean
        deleted: boolean
        hog: string
        bytecode: unknown | null
        transpiled: string | null
        inputs_schema: Array<InputsSchemaItem>
        inputs: Record<string, unknown>
        filters: HogFunctionFilters
        masking: (HogFunctionMasking & (unknown | null)) | null
        mappings: Array<Mappings> | null
        icon_url: string | null
        template: HogFunctionTemplate & unknown
        template_id: string | null
        status: (HogFunctionStatus & (unknown | null)) | null
        execution_order: number | null
        _create_in_folder: string
    }>
    export type PatchedInsight = Partial<{
        id: number
        short_id: string
        name: string | null
        derived_name: string | null
        query: Record<string, unknown> | null
        order: number | null
        deleted: boolean
        dashboards: Array<number>
        dashboard_tiles: Array<DashboardTileBasic>
        last_refresh: string
        cache_target_age: string
        next_allowed_client_refresh: string
        result: string
        hasMore: string
        columns: string
        created_at: string | null
        created_by: UserBasic & unknown
        description: string | null
        updated_at: string
        tags: Array<unknown>
        favorited: boolean
        last_modified_at: string
        last_modified_by: UserBasic & unknown
        is_sample: boolean
        effective_restriction_level: EffectiveRestrictionLevelEnum & unknown
        effective_privilege_level: EffectivePrivilegeLevelEnum & unknown
        user_access_level: string | null
        timezone: string
        is_cached: string
        query_status: string
        hogql: string
        types: string
        _create_in_folder: string
        alerts: string
    }>
    export type PatchedNotebook = Partial<{
        id: string
        short_id: string
        title: string | null
        content: unknown | null
        text_content: string | null
        version: number
        deleted: boolean
        created_at: string
        created_by: UserBasic & unknown
        last_modified_at: string
        last_modified_by: UserBasic & unknown
        user_access_level: string | null
        _create_in_folder: string
    }>
    export type PatchedOrganization = Partial<{
        id: string
        name: string
        slug: string
        logo_media_id: string | null
        created_at: string
        updated_at: string
        membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null
        plugins_access_level: PluginsAccessLevelEnum & unknown
        teams: Array<Record<string, unknown>>
        projects: Array<Record<string, unknown>>
        available_product_features: Array<unknown> | null
        is_member_join_email_enabled: boolean
        metadata: string
        customer_id: string | null
        enforce_2fa: boolean | null
        members_can_invite: boolean | null
        members_can_use_personal_api_keys: boolean
        allow_publicly_shared_resources: boolean
        member_count: string
        is_ai_data_processing_approved: boolean | null
        default_experiment_stats_method:
            | (DefaultExperimentStatsMethodEnum | BlankEnum | NullEnum)
            | null
        default_role_id: string | null
    }>
    export type PatchedOrganizationDomain = Partial<{
        id: string
        domain: string
        is_verified: boolean
        verified_at: string | null
        verification_challenge: string
        jit_provisioning_enabled: boolean
        sso_enforcement: string
        has_saml: boolean
        saml_entity_id: string | null
        saml_acs_url: string | null
        saml_x509_cert: string | null
    }>
    export type PatchedOrganizationMember = Partial<{
        id: string
        user: UserBasic & unknown
        level: OrganizationMembershipLevel & unknown
        joined_at: string
        updated_at: string
        is_2fa_enabled: boolean
        has_social_auth: boolean
        last_login: string
    }>
    export type PatchedPersistedFolder = Partial<{
        id: string
        type: PersistedFolderTypeEnum
        protocol: string
        path: string
        created_at: string
        updated_at: string
    }>
    export type PatchedPerson = Partial<{
        id: number
        name: string
        distinct_ids: Array<string>
        properties: unknown
        created_at: string
        uuid: string
    }>
    export type WeekStartDayEnum = 0 | 1
    export type PatchedProjectBackwardCompat = Partial<{
        id: number
        organization: string
        name: string
        product_description: string | null
        created_at: string
        effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null
        has_group_types: boolean
        group_types: Array<Record<string, unknown>>
        live_events_token: string | null
        updated_at: string
        uuid: string
        api_token: string
        app_urls: Array<string | null>
        slack_incoming_webhook: string | null
        anonymize_ips: boolean
        completed_snippet_onboarding: boolean
        ingested_event: boolean
        test_account_filters: unknown
        test_account_filters_default_checked: boolean | null
        path_cleaning_filters: unknown | null
        is_demo: boolean
        timezone: TimezoneEnum
        data_attributes: unknown
        person_display_name_properties: Array<string> | null
        correlation_config: unknown | null
        autocapture_opt_out: boolean | null
        autocapture_exceptions_opt_in: boolean | null
        autocapture_web_vitals_opt_in: boolean | null
        autocapture_web_vitals_allowed_metrics: unknown | null
        autocapture_exceptions_errors_to_ignore: unknown | null
        capture_console_log_opt_in: boolean | null
        capture_performance_opt_in: boolean | null
        session_recording_opt_in: boolean
        session_recording_sample_rate: string | null
        session_recording_minimum_duration_milliseconds: number | null
        session_recording_linked_flag: unknown | null
        session_recording_network_payload_capture_config: unknown | null
        session_recording_masking_config: unknown | null
        session_replay_config: unknown | null
        survey_config: unknown | null
        access_control: boolean
        week_start_day: (WeekStartDayEnum | NullEnum) | null
        primary_dashboard: number | null
        live_events_columns: Array<string> | null
        recording_domains: Array<string | null> | null
        person_on_events_querying_enabled: string
        inject_web_apps: boolean | null
        extra_settings: unknown | null
        modifiers: unknown | null
        default_modifiers: string
        has_completed_onboarding_for: unknown | null
        surveys_opt_in: boolean | null
        heatmaps_opt_in: boolean | null
        product_intents: string
        flags_persistence_default: boolean | null
        secret_api_token: string | null
        secret_api_token_backup: string | null
    }>
    export type PatchedPropertyDefinition = Partial<{
        id: string
        name: string
        is_numerical: boolean
        property_type: (PropertyTypeEnum | BlankEnum | NullEnum) | null
        tags: Array<unknown>
        is_seen_on_filtered_events: string
    }>
    export type PatchedProxyRecord = Partial<{
        id: string
        domain: string
        target_cname: string
        status: ProxyRecordStatusEnum & unknown
        message: string | null
        created_at: string
        updated_at: string
        created_by: number | null
    }>
    export type PatchedRole = Partial<{
        id: string
        name: string
        feature_flags_access_level: FeatureFlagsAccessLevelEnum & unknown
        created_at: string
        created_by: UserBasic & unknown
        members: string
        is_default: string
    }>
    export type PatchedSessionRecording = Partial<{
        id: string
        distinct_id: string | null
        viewed: boolean
        viewers: Array<string>
        recording_duration: number
        active_seconds: number | null
        inactive_seconds: number | null
        start_time: string | null
        end_time: string | null
        click_count: number | null
        keypress_count: number | null
        mouse_activity_count: number | null
        console_log_count: number | null
        console_warn_count: number | null
        console_error_count: number | null
        start_url: string | null
        person: MinimalPerson
        storage: string
        retention_period_days: number | null
        snapshot_source: string | null
        ongoing: boolean
        activity_score: number | null
    }>
    export type PatchedSessionRecordingPlaylist = Partial<{
        id: number
        short_id: string
        name: string | null
        derived_name: string | null
        description: string
        pinned: boolean
        created_at: string
        created_by: UserBasic & unknown
        deleted: boolean
        filters: unknown
        last_modified_at: string
        last_modified_by: UserBasic & unknown
        recordings_counts: Record<string, Record<string, unknown>>
        type: (SessionRecordingPlaylistTypeEnum | NullEnum) | null
        _create_in_folder: string
    }>
    export type PatchedSubscription = Partial<{
        id: number
        dashboard: number | null
        insight: number | null
        target_type: TargetTypeEnum
        target_value: string
        frequency: FrequencyEnum
        interval: number
        byweekday: Array<ByweekdayEnum> | null
        bysetpos: number | null
        count: number | null
        start_date: string
        until_date: string | null
        created_at: string
        created_by: UserBasic & unknown
        deleted: boolean
        title: string | null
        summary: string
        next_delivery_date: string | null
        invite_message: string | null
    }>
    export type PatchedSurveySerializerCreateUpdateOnly = Partial<{
        id: string
        name: string
        description: string
        type: SurveyType
        schedule: string | null
        linked_flag: MinimalFeatureFlag & unknown
        linked_flag_id: number | null
        targeting_flag_id: number
        targeting_flag: MinimalFeatureFlag & unknown
        internal_targeting_flag: MinimalFeatureFlag & unknown
        targeting_flag_filters: unknown | null
        remove_targeting_flag: boolean | null
        questions: unknown | null
        conditions: unknown | null
        appearance: unknown | null
        created_at: string
        created_by: UserBasic & unknown
        start_date: string | null
        end_date: string | null
        archived: boolean
        responses_limit: number | null
        iteration_count: number | null
        iteration_frequency_days: number | null
        iteration_start_dates: Array<string | null> | null
        current_iteration: number | null
        current_iteration_start_date: string | null
        response_sampling_start_date: string | null
        response_sampling_interval_type:
            | (ResponseSamplingIntervalTypeEnum | BlankEnum | NullEnum)
            | null
        response_sampling_interval: number | null
        response_sampling_limit: number | null
        response_sampling_daily_limits: unknown | null
        enable_partial_responses: boolean | null
        _create_in_folder: string
    }>
    export type PatchedTable = Partial<{
        id: string
        deleted: boolean | null
        name: string
        format: TableFormatEnum
        created_by: UserBasic & unknown
        created_at: string
        url_pattern: string
        credential: Credential
        columns: string
        external_data_source: SimpleExternalDataSourceSerializers & unknown
        external_schema: string
    }>
    export type TeamRevenueAnalyticsConfig = Partial<{
        base_currency: BaseCurrencyEnum
        events: unknown
        goals: unknown
        filter_test_accounts: boolean
    }>
    export type TeamMarketingAnalyticsConfig = Partial<{
        sources_map: unknown
        conversion_goals: unknown
    }>
    export type PatchedTeam = Partial<{
        id: number
        uuid: string
        name: string
        access_control: boolean
        organization: string
        project_id: number
        api_token: string
        secret_api_token: string | null
        secret_api_token_backup: string | null
        created_at: string
        updated_at: string
        ingested_event: boolean
        default_modifiers: Record<string, unknown>
        person_on_events_querying_enabled: boolean
        user_access_level: string | null
        app_urls: Array<string | null>
        slack_incoming_webhook: string | null
        anonymize_ips: boolean
        completed_snippet_onboarding: boolean
        test_account_filters: unknown
        test_account_filters_default_checked: boolean | null
        path_cleaning_filters: unknown | null
        is_demo: boolean
        timezone: TimezoneEnum
        data_attributes: unknown
        person_display_name_properties: Array<string> | null
        correlation_config: unknown | null
        autocapture_opt_out: boolean | null
        autocapture_exceptions_opt_in: boolean | null
        autocapture_web_vitals_opt_in: boolean | null
        autocapture_web_vitals_allowed_metrics: unknown | null
        autocapture_exceptions_errors_to_ignore: unknown | null
        capture_console_log_opt_in: boolean | null
        capture_performance_opt_in: boolean | null
        session_recording_opt_in: boolean
        session_recording_sample_rate: string | null
        session_recording_minimum_duration_milliseconds: number | null
        session_recording_linked_flag: unknown | null
        session_recording_network_payload_capture_config: unknown | null
        session_recording_masking_config: unknown | null
        session_recording_url_trigger_config: Array<unknown | null> | null
        session_recording_url_blocklist_config: Array<unknown | null> | null
        session_recording_event_trigger_config: Array<string | null> | null
        session_recording_trigger_match_type_config: string | null
        session_replay_config: unknown | null
        survey_config: unknown | null
        week_start_day: (WeekStartDayEnum | NullEnum) | null
        primary_dashboard: number | null
        live_events_columns: Array<string> | null
        recording_domains: Array<string | null> | null
        cookieless_server_hash_mode: (CookielessServerHashModeEnum | NullEnum) | null
        human_friendly_comparison_periods: boolean | null
        inject_web_apps: boolean | null
        extra_settings: unknown | null
        modifiers: unknown | null
        has_completed_onboarding_for: unknown | null
        surveys_opt_in: boolean | null
        heatmaps_opt_in: boolean | null
        flags_persistence_default: boolean | null
        feature_flag_confirmation_enabled: boolean | null
        feature_flag_confirmation_message: string | null
        capture_dead_clicks: boolean | null
        default_data_theme: number | null
        revenue_analytics_config: TeamRevenueAnalyticsConfig
        marketing_analytics_config: TeamMarketingAnalyticsConfig
        onboarding_tasks: unknown | null
        base_currency: BaseCurrencyEnum & unknown
        web_analytics_pre_aggregated_tables_enabled: boolean | null
        effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null
        has_group_types: boolean
        group_types: Array<Record<string, unknown>>
        live_events_token: string | null
        product_intents: string
    }>
    export type PatchedUser = Partial<{
        date_joined: string
        uuid: string
        distinct_id: string | null
        first_name: string
        last_name: string
        email: string
        pending_email: string | null
        is_email_verified: boolean | null
        notification_settings: Record<string, unknown>
        anonymize_data: boolean | null
        toolbar_mode: (ToolbarModeEnum | BlankEnum | NullEnum) | null
        has_password: boolean
        id: number
        is_staff: boolean
        is_impersonated: boolean | null
        is_impersonated_until: string | null
        sensitive_session_expires_at: string | null
        team: TeamBasic & unknown
        organization: Organization & unknown
        organizations: Array<OrganizationBasic>
        set_current_organization: string
        set_current_team: string
        password: string
        current_password: string
        events_column_config: unknown
        is_2fa_enabled: boolean
        has_social_auth: boolean
        has_sso_enforcement: boolean
        has_seen_product_intro_for: unknown | null
        scene_personalisation: Array<ScenePersonalisationBasic>
        theme_mode: (ThemeModeEnum | BlankEnum | NullEnum) | null
        hedgehog_config: unknown | null
        role_at_organization: RoleAtOrganizationEnum
    }>
    export type PatchedUserInterview = Partial<{
        id: string
        created_by: UserBasic & unknown
        created_at: string
        interviewee_emails: Array<string>
        transcript: string
        summary: string
        audio: string
    }>
    export type PatchedWebExperimentsAPI = Partial<{
        id: number
        name: string
        created_at: string
        feature_flag_key: string
        variants: unknown
    }>
    export type ProjectBackwardCompat = {
        id: number
        organization: string
        name?: string | undefined
        product_description?: (string | null) | undefined
        created_at: string
        effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null
        has_group_types: boolean
        group_types: Array<Record<string, unknown>>
        live_events_token: string | null
        updated_at: string
        uuid: string
        api_token: string
        app_urls?: Array<string | null> | undefined
        slack_incoming_webhook?: (string | null) | undefined
        anonymize_ips?: boolean | undefined
        completed_snippet_onboarding?: boolean | undefined
        ingested_event: boolean
        test_account_filters?: unknown | undefined
        test_account_filters_default_checked?: (boolean | null) | undefined
        path_cleaning_filters?: (unknown | null) | undefined
        is_demo?: boolean | undefined
        timezone?: TimezoneEnum | undefined
        data_attributes?: unknown | undefined
        person_display_name_properties?: (Array<string> | null) | undefined
        correlation_config?: (unknown | null) | undefined
        autocapture_opt_out?: (boolean | null) | undefined
        autocapture_exceptions_opt_in?: (boolean | null) | undefined
        autocapture_web_vitals_opt_in?: (boolean | null) | undefined
        autocapture_web_vitals_allowed_metrics?: (unknown | null) | undefined
        autocapture_exceptions_errors_to_ignore?: (unknown | null) | undefined
        capture_console_log_opt_in?: (boolean | null) | undefined
        capture_performance_opt_in?: (boolean | null) | undefined
        session_recording_opt_in?: boolean | undefined
        session_recording_sample_rate?: (string | null) | undefined
        session_recording_minimum_duration_milliseconds?: (number | null) | undefined
        session_recording_linked_flag?: (unknown | null) | undefined
        session_recording_network_payload_capture_config?: (unknown | null) | undefined
        session_recording_masking_config?: (unknown | null) | undefined
        session_replay_config?: (unknown | null) | undefined
        survey_config?: (unknown | null) | undefined
        access_control?: boolean | undefined
        week_start_day?: ((WeekStartDayEnum | NullEnum) | null) | undefined
        primary_dashboard?: (number | null) | undefined
        live_events_columns?: (Array<string> | null) | undefined
        recording_domains?: (Array<string | null> | null) | undefined
        person_on_events_querying_enabled: string
        inject_web_apps?: (boolean | null) | undefined
        extra_settings?: (unknown | null) | undefined
        modifiers?: (unknown | null) | undefined
        default_modifiers: string
        has_completed_onboarding_for?: (unknown | null) | undefined
        surveys_opt_in?: (boolean | null) | undefined
        heatmaps_opt_in?: (boolean | null) | undefined
        product_intents: string
        flags_persistence_default?: (boolean | null) | undefined
        secret_api_token: string | null
        secret_api_token_backup: string | null
    }
    export type PropertyItemTypeEnum =
        | 'event'
        | 'event_metadata'
        | 'feature'
        | 'person'
        | 'cohort'
        | 'element'
        | 'static-cohort'
        | 'dynamic-cohort'
        | 'precalculated-cohort'
        | 'group'
        | 'recording'
        | 'log_entry'
        | 'behavioral'
        | 'session'
        | 'hogql'
        | 'data_warehouse'
        | 'data_warehouse_person_property'
        | 'error_tracking_issue'
        | 'log'
        | 'revenue_analytics'
        | 'flag'
    export type PropertyItem = {
        key: string
        value: string
        operator?: ((OperatorEnum | BlankEnum | NullEnum) | null) | undefined
        type?: (PropertyItemTypeEnum | BlankEnum) | undefined
    }
    export type Property = {
        type?: (PropertyTypeEnum & unknown) | undefined
        values: Array<PropertyItem>
    }
    export type SavedInsightNode = {
        allowSorting?: (boolean | null) | undefined
        context?: (DataTableNodeViewPropsContext | null) | undefined
        embedded?: (boolean | null) | undefined
        expandable?: (boolean | null) | undefined
        full?: (boolean | null) | undefined
        hidePersonsModal?: (boolean | null) | undefined
        hideTooltipOnScroll?: (boolean | null) | undefined
        kind?: string | undefined
        propertiesViaUrl?: (boolean | null) | undefined
        shortId: string
        showActions?: (boolean | null) | undefined
        showColumnConfigurator?: (boolean | null) | undefined
        showCorrelationTable?: (boolean | null) | undefined
        showDateRange?: (boolean | null) | undefined
        showElapsedTime?: (boolean | null) | undefined
        showEventFilter?: (boolean | null) | undefined
        showExport?: (boolean | null) | undefined
        showFilters?: (boolean | null) | undefined
        showHeader?: (boolean | null) | undefined
        showHogQLEditor?: (boolean | null) | undefined
        showLastComputation?: (boolean | null) | undefined
        showLastComputationRefresh?: (boolean | null) | undefined
        showOpenEditorButton?: (boolean | null) | undefined
        showPersistentColumnConfigurator?: (boolean | null) | undefined
        showPropertyFilter?: (boolean | Array<TaxonomicFilterGroupType> | null) | undefined
        showReload?: (boolean | null) | undefined
        showResults?: (boolean | null) | undefined
        showResultsTable?: (boolean | null) | undefined
        showSavedFilters?: (boolean | null) | undefined
        showSavedQueries?: (boolean | null) | undefined
        showSearch?: (boolean | null) | undefined
        showTable?: (boolean | null) | undefined
        showTestAccountFilters?: (boolean | null) | undefined
        showTimings?: (boolean | null) | undefined
        suppressSessionAnalysisWarning?: (boolean | null) | undefined
        version?: (number | null) | undefined
        vizSpecificOptions?: (VizSpecificOptions | null) | undefined
    }
    export type SuggestedQuestionsQueryResponse = { questions: Array<string> }
    export type SuggestedQuestionsQuery = Partial<{
        kind: string
        modifiers: HogQLQueryModifiers | null
        response: SuggestedQuestionsQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type TeamTaxonomyItem = { count: number; event: string }
    export type TeamTaxonomyQueryResponse = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<TeamTaxonomyItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type TeamTaxonomyQuery = Partial<{
        kind: string
        modifiers: HogQLQueryModifiers | null
        response: TeamTaxonomyQueryResponse | null
        tags: QueryLogTags | null
        version: number | null
    }>
    export type RefreshType =
        | 'async'
        | 'async_except_on_cache_miss'
        | 'blocking'
        | 'force_async'
        | 'force_blocking'
        | 'force_cache'
        | 'lazy_async'
    export type QueryRequest = {
        async?: (boolean | null) | undefined
        client_query_id?: (string | null) | undefined
        filters_override?: (DashboardFilter | null) | undefined
        name?: (string | null) | undefined
        query:
            | EventsNode
            | ActionsNode
            | PersonsNode
            | DataWarehouseNode
            | EventsQuery
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
            | ErrorTrackingIssueCorrelationQuery
            | ExperimentFunnelsQuery
            | ExperimentTrendsQuery
            | ExperimentQuery
            | ExperimentExposureQuery
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
            | SuggestedQuestionsQuery
            | TeamTaxonomyQuery
            | EventTaxonomyQuery
            | ActorsPropertyTaxonomyQuery
            | TracesQuery
            | VectorSearchQuery
        refresh?: (RefreshType | null) | undefined
        variables_override?: (Record<string, Record<string, unknown>> | null) | undefined
    }
    export type QueryResponseAlternative1 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type QueryResponseAlternative2 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit: number
        missing_actors_count?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<string> | null) | undefined
    }
    export type QueryResponseAlternative3 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        kind?: string | undefined
        limit: number
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type QueryResponseAlternative4 = Partial<{
        breakdown: Array<BreakdownItem> | null
        breakdowns: Array<MultipleBreakdownOptions> | null
        compare: Array<CompareItem> | null
        day: Array<DayItem> | null
        interval: Array<IntervalItem> | null
        series: Array<Series> | null
        status: Array<StatusItem> | null
    }>
    export type QueryResponseAlternative5 = {
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<TimelineEntry>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative6 = {
        bytecode?: (Array<unknown> | null) | undefined
        coloredBytecode?: (Array<unknown> | null) | undefined
        results: unknown
        stdout?: (string | null) | undefined
    }
    export type QueryResponseAlternative7 = {
        clickhouse?: (string | null) | undefined
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        explain?: (Array<string> | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        metadata?: (HogQLMetadataResponse | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query?: (string | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative8 = {
        errors: Array<HogQLNotice>
        isUsingIndices?: (QueryIndexUsage | null) | undefined
        isValid?: (boolean | null) | undefined
        notices: Array<HogQLNotice>
        query?: (string | null) | undefined
        table_names?: (Array<string> | null) | undefined
        warnings: Array<HogQLNotice>
    }
    export type QueryResponseAlternative9 = {
        incomplete_list: boolean
        suggestions: Array<AutocompleteCompletionItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative10 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative13 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<ErrorTrackingIssue>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative14 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<ErrorTrackingCorrelatedIssue>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative15 = {
        credible_intervals: Record<string, Array<number>>
        expected_loss: number
        funnels_query?: (FunnelsQuery | null) | undefined
        insight: Array<Array<Record<string, unknown>>>
        kind?: string | undefined
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantFunnelsBaseStats>
    }
    export type QueryResponseAlternative16 = {
        count_query?: (TrendsQuery | null) | undefined
        credible_intervals: Record<string, Array<number>>
        exposure_query?: (TrendsQuery | null) | undefined
        insight: Array<Record<string, unknown>>
        kind?: string | undefined
        p_value: number
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantTrendsBaseStats>
    }
    export type QueryResponseAlternative17 = Partial<{
        baseline: ExperimentStatsBaseValidated | null
        credible_intervals: Record<string, Array<number>> | null
        insight: Array<Record<string, unknown>> | null
        kind: string
        metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | null
        p_value: number | null
        probability: Record<string, number> | null
        significance_code: ExperimentSignificanceCode | null
        significant: boolean | null
        stats_version: number | null
        variant_results:
            | Array<ExperimentVariantResultFrequentist>
            | Array<ExperimentVariantResultBayesian>
            | null
        variants:
            | Array<ExperimentVariantTrendsBaseStats>
            | Array<ExperimentVariantFunnelsBaseStats>
            | null
    }>
    export type QueryResponseAlternative18 = {
        date_range: DateRange
        kind?: string | undefined
        timeseries: Array<ExperimentExposureTimeSeries>
        total_exposures: Record<string, number>
    }
    export type QueryResponseAlternative19 = {
        dateFrom?: (string | null) | undefined
        dateTo?: (string | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebOverviewItem>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type QueryResponseAlternative20 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type QueryResponseAlternative21 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative23 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebVitalsPathBreakdownResult>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative24 = {
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<PageURL>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative25 = {
        data: Record<string, unknown>
        error?: (ExternalQueryError | null) | undefined
        status: ExternalQueryStatus
    }
    export type QueryResponseAlternative26 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative27 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative28 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsMRRQueryResultItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative29 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsOverviewItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative30 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative31 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<MarketingAnalyticsItem>>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative32 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type QueryResponseAlternative33 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        limit: number
        missing_actors_count?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<string> | null) | undefined
    }
    export type QueryResponseAlternative34 = {
        columns: Array<unknown>
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql: string
        kind?: string | undefined
        limit: number
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset: number
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
        types: Array<string>
    }
    export type QueryResponseAlternative35 = {
        clickhouse?: (string | null) | undefined
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        explain?: (Array<string> | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        metadata?: (HogQLMetadataResponse | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query?: (string | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative36 = {
        dateFrom?: (string | null) | undefined
        dateTo?: (string | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebOverviewItem>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type QueryResponseAlternative37 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
        usedPreAggregatedTables?: (boolean | null) | undefined
    }
    export type QueryResponseAlternative38 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative40 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<WebVitalsPathBreakdownResult>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative41 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative42 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<unknown>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative43 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative44 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsMRRQueryResultItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative45 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RevenueAnalyticsOverviewItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative46 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative47 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative49 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Array<MarketingAnalyticsItem>>
        samplingRate?: (SamplingRate | null) | undefined
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative50 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<ErrorTrackingIssue>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative52 = {
        credible_intervals: Record<string, Array<number>>
        expected_loss: number
        funnels_query?: (FunnelsQuery | null) | undefined
        insight: Array<Array<Record<string, unknown>>>
        kind?: string | undefined
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantFunnelsBaseStats>
    }
    export type QueryResponseAlternative53 = {
        count_query?: (TrendsQuery | null) | undefined
        credible_intervals: Record<string, Array<number>>
        exposure_query?: (TrendsQuery | null) | undefined
        insight: Array<Record<string, unknown>>
        kind?: string | undefined
        p_value: number
        probability: Record<string, number>
        significance_code: ExperimentSignificanceCode
        significant: boolean
        stats_version?: (number | null) | undefined
        variants: Array<ExperimentVariantTrendsBaseStats>
    }
    export type QueryResponseAlternative54 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<LLMTrace>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative55 = {
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Record<string, unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative56 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        isUdf?: (boolean | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative57 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<RetentionResult>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative58 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<PathsLink>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative59 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<Record<string, unknown>>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative61 = {
        columns?: (Array<unknown> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: FunnelCorrelationResult
        timings?: (Array<QueryTiming> | null) | undefined
        types?: (Array<unknown> | null) | undefined
    }
    export type QueryResponseAlternative62 = {
        joins: Array<DataWarehouseViewLink>
        tables: Record<string, unknown>
    }
    export type QueryResponseAlternative63 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: unknown
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative64 = { questions: Array<string> }
    export type QueryResponseAlternative65 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<TeamTaxonomyItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative66 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<EventTaxonomyItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative67 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: ActorsPropertyTaxonomyResponse | Array<ActorsPropertyTaxonomyResponse>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative68 = {
        columns?: (Array<string> | null) | undefined
        error?: (string | null) | undefined
        hasMore?: (boolean | null) | undefined
        hogql?: (string | null) | undefined
        limit?: (number | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        offset?: (number | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<LLMTrace>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative69 = {
        error?: (string | null) | undefined
        hogql?: (string | null) | undefined
        modifiers?: (HogQLQueryModifiers | null) | undefined
        query_status?: (QueryStatus | null) | undefined
        resolved_date_range?: (ResolvedDateRangeResponse | null) | undefined
        results: Array<VectorSearchResponseItem>
        timings?: (Array<QueryTiming> | null) | undefined
    }
    export type QueryResponseAlternative =
        | Record<string, unknown>
        | QueryResponseAlternative1
        | QueryResponseAlternative2
        | QueryResponseAlternative3
        | QueryResponseAlternative4
        | QueryResponseAlternative5
        | QueryResponseAlternative6
        | QueryResponseAlternative7
        | QueryResponseAlternative8
        | QueryResponseAlternative9
        | QueryResponseAlternative10
        | QueryResponseAlternative13
        | QueryResponseAlternative14
        | QueryResponseAlternative15
        | QueryResponseAlternative16
        | QueryResponseAlternative17
        | QueryResponseAlternative18
        | QueryResponseAlternative19
        | QueryResponseAlternative20
        | QueryResponseAlternative21
        | QueryResponseAlternative23
        | QueryResponseAlternative24
        | QueryResponseAlternative25
        | QueryResponseAlternative26
        | QueryResponseAlternative27
        | QueryResponseAlternative28
        | QueryResponseAlternative29
        | QueryResponseAlternative30
        | QueryResponseAlternative31
        | unknown
        | QueryResponseAlternative32
        | QueryResponseAlternative33
        | QueryResponseAlternative34
        | QueryResponseAlternative35
        | QueryResponseAlternative36
        | QueryResponseAlternative37
        | QueryResponseAlternative38
        | QueryResponseAlternative40
        | QueryResponseAlternative41
        | QueryResponseAlternative42
        | QueryResponseAlternative43
        | QueryResponseAlternative44
        | QueryResponseAlternative45
        | QueryResponseAlternative46
        | QueryResponseAlternative47
        | QueryResponseAlternative49
        | QueryResponseAlternative50
        | QueryResponseAlternative52
        | QueryResponseAlternative53
        | QueryResponseAlternative54
        | QueryResponseAlternative55
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
    export type QueryStatusResponse = { query_status: QueryStatus }
    export type QueryUpgradeRequest = {
        query:
            | EventsNode
            | ActionsNode
            | PersonsNode
            | DataWarehouseNode
            | EventsQuery
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
            | ErrorTrackingIssueCorrelationQuery
            | ExperimentFunnelsQuery
            | ExperimentTrendsQuery
            | ExperimentQuery
            | ExperimentExposureQuery
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
            | SuggestedQuestionsQuery
            | TeamTaxonomyQuery
            | EventTaxonomyQuery
            | ActorsPropertyTaxonomyQuery
            | TracesQuery
            | VectorSearchQuery
    }
    export type QueryUpgradeResponse = {
        query:
            | EventsNode
            | ActionsNode
            | PersonsNode
            | DataWarehouseNode
            | EventsQuery
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
            | ErrorTrackingIssueCorrelationQuery
            | ExperimentFunnelsQuery
            | ExperimentTrendsQuery
            | ExperimentQuery
            | ExperimentExposureQuery
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
            | SuggestedQuestionsQuery
            | TeamTaxonomyQuery
            | EventTaxonomyQuery
            | ActorsPropertyTaxonomyQuery
            | TracesQuery
            | VectorSearchQuery
    }
    export type SessionSummaries = { session_ids: Array<string>; focus_area?: string | undefined }
    export type SharingConfiguration = {
        created_at: string
        enabled?: boolean | undefined
        access_token: string | null
        settings?: (unknown | null) | undefined
        password_required?: boolean | undefined
        share_passwords: string
    }
    export type SurveySerializerCreateUpdateOnly = {
        id: string
        name: string
        description?: string | undefined
        type: SurveyType
        schedule?: (string | null) | undefined
        linked_flag: MinimalFeatureFlag & unknown
        linked_flag_id?: (number | null) | undefined
        targeting_flag_id?: number | undefined
        targeting_flag: MinimalFeatureFlag & unknown
        internal_targeting_flag: MinimalFeatureFlag & unknown
        targeting_flag_filters?: (unknown | null) | undefined
        remove_targeting_flag?: (boolean | null) | undefined
        questions?: (unknown | null) | undefined
        conditions?: (unknown | null) | undefined
        appearance?: (unknown | null) | undefined
        created_at: string
        created_by: UserBasic & unknown
        start_date?: (string | null) | undefined
        end_date?: (string | null) | undefined
        archived?: boolean | undefined
        responses_limit?: (number | null) | undefined
        iteration_count?: (number | null) | undefined
        iteration_frequency_days?: (number | null) | undefined
        iteration_start_dates?: (Array<string | null> | null) | undefined
        current_iteration?: (number | null) | undefined
        current_iteration_start_date?: (string | null) | undefined
        response_sampling_start_date?: (string | null) | undefined
        response_sampling_interval_type?:
            | ((ResponseSamplingIntervalTypeEnum | BlankEnum | NullEnum) | null)
            | undefined
        response_sampling_interval?: (number | null) | undefined
        response_sampling_limit?: (number | null) | undefined
        response_sampling_daily_limits?: (unknown | null) | undefined
        enable_partial_responses?: (boolean | null) | undefined
        _create_in_folder?: string | undefined
    }
    export type Team = {
        id: number
        uuid: string
        name?: string | undefined
        access_control?: boolean | undefined
        organization: string
        project_id: number
        api_token: string
        secret_api_token: string | null
        secret_api_token_backup: string | null
        created_at: string
        updated_at: string
        ingested_event: boolean
        default_modifiers: Record<string, unknown>
        person_on_events_querying_enabled: boolean
        user_access_level: string | null
        app_urls?: Array<string | null> | undefined
        slack_incoming_webhook?: (string | null) | undefined
        anonymize_ips?: boolean | undefined
        completed_snippet_onboarding?: boolean | undefined
        test_account_filters?: unknown | undefined
        test_account_filters_default_checked?: (boolean | null) | undefined
        path_cleaning_filters?: (unknown | null) | undefined
        is_demo?: boolean | undefined
        timezone?: TimezoneEnum | undefined
        data_attributes?: unknown | undefined
        person_display_name_properties?: (Array<string> | null) | undefined
        correlation_config?: (unknown | null) | undefined
        autocapture_opt_out?: (boolean | null) | undefined
        autocapture_exceptions_opt_in?: (boolean | null) | undefined
        autocapture_web_vitals_opt_in?: (boolean | null) | undefined
        autocapture_web_vitals_allowed_metrics?: (unknown | null) | undefined
        autocapture_exceptions_errors_to_ignore?: (unknown | null) | undefined
        capture_console_log_opt_in?: (boolean | null) | undefined
        capture_performance_opt_in?: (boolean | null) | undefined
        session_recording_opt_in?: boolean | undefined
        session_recording_sample_rate?: (string | null) | undefined
        session_recording_minimum_duration_milliseconds?: (number | null) | undefined
        session_recording_linked_flag?: (unknown | null) | undefined
        session_recording_network_payload_capture_config?: (unknown | null) | undefined
        session_recording_masking_config?: (unknown | null) | undefined
        session_recording_url_trigger_config?: (Array<unknown | null> | null) | undefined
        session_recording_url_blocklist_config?: (Array<unknown | null> | null) | undefined
        session_recording_event_trigger_config?: (Array<string | null> | null) | undefined
        session_recording_trigger_match_type_config?: (string | null) | undefined
        session_replay_config?: (unknown | null) | undefined
        survey_config?: (unknown | null) | undefined
        week_start_day?: ((WeekStartDayEnum | NullEnum) | null) | undefined
        primary_dashboard?: (number | null) | undefined
        live_events_columns?: (Array<string> | null) | undefined
        recording_domains?: (Array<string | null> | null) | undefined
        cookieless_server_hash_mode?: ((CookielessServerHashModeEnum | NullEnum) | null) | undefined
        human_friendly_comparison_periods?: (boolean | null) | undefined
        inject_web_apps?: (boolean | null) | undefined
        extra_settings?: (unknown | null) | undefined
        modifiers?: (unknown | null) | undefined
        has_completed_onboarding_for?: (unknown | null) | undefined
        surveys_opt_in?: (boolean | null) | undefined
        heatmaps_opt_in?: (boolean | null) | undefined
        flags_persistence_default?: (boolean | null) | undefined
        feature_flag_confirmation_enabled?: (boolean | null) | undefined
        feature_flag_confirmation_message?: (string | null) | undefined
        capture_dead_clicks?: (boolean | null) | undefined
        default_data_theme?: (number | null) | undefined
        revenue_analytics_config?: TeamRevenueAnalyticsConfig | undefined
        marketing_analytics_config?: TeamMarketingAnalyticsConfig | undefined
        onboarding_tasks?: (unknown | null) | undefined
        base_currency?: (BaseCurrencyEnum & unknown) | undefined
        web_analytics_pre_aggregated_tables_enabled?: (boolean | null) | undefined
        effective_membership_level: (EffectiveMembershipLevelEnum & (unknown | null)) | null
        has_group_types: boolean
        group_types: Array<Record<string, unknown>>
        live_events_token: string | null
        product_intents: string
    }
    export type WebAnalyticsBreakdownResponse = {
        next?: (string | null) | undefined
        results: Array<unknown>
    }
    export type WebAnalyticsOverviewResponse = {
        visitors: number
        views: number
        sessions: number
        bounce_rate: number
        session_duration: number
    }

    // </Schemas>
}

export namespace Endpoints {
    // <Endpoints>

    export type get_Environments_app_metrics_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/app_metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_app_metrics_error_details_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/app_metrics/{id}/error_details/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_app_metrics_historical_exports_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/'
        requestFormat: 'json'
        parameters: {
            path: { plugin_config_id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_app_metrics_historical_exports_retrieve_2 = {
        method: 'GET'
        path: '/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; plugin_config_id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_batch_exports_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedBatchExportList }
    }
    export type post_Environments_batch_exports_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 201: Schemas.BatchExport }
    }
    export type get_Environments_batch_exports_backfills_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ cursor: string; ordering: string }>
            path: { batch_export_id: string; project_id: string }
        }
        responses: { 200: Schemas.PaginatedBatchExportBackfillList }
    }
    export type post_Environments_batch_exports_backfills_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; project_id: string }

            body: Schemas.BatchExportBackfill
        }
        responses: { 201: Schemas.BatchExportBackfill }
    }
    export type get_Environments_batch_exports_backfills_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }
        }
        responses: { 200: Schemas.BatchExportBackfill }
    }
    export type post_Environments_batch_exports_backfills_cancel_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }

            body: Schemas.BatchExportBackfill
        }
        responses: { 200: unknown }
    }
    export type get_Environments_batch_exports_runs_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ cursor: string; ordering: string }>
            path: { batch_export_id: string; project_id: string }
        }
        responses: { 200: Schemas.PaginatedBatchExportRunList }
    }
    export type get_Environments_batch_exports_runs_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }
        }
        responses: { 200: Schemas.BatchExportRun }
    }
    export type post_Environments_batch_exports_runs_cancel_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }

            body: Schemas.BatchExportRun
        }
        responses: { 200: unknown }
    }
    export type get_Environments_batch_exports_runs_logs_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_batch_exports_runs_retry_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }

            body: Schemas.BatchExportRun
        }
        responses: { 200: unknown }
    }
    export type get_Environments_batch_exports_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type put_Environments_batch_exports_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type patch_Environments_batch_exports_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedBatchExport
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type delete_Environments_batch_exports_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Environments_batch_exports_backfill_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{id}/backfill/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type get_Environments_batch_exports_logs_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/{id}/logs/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_batch_exports_pause_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{id}/pause/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Environments_batch_exports_run_test_step_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{id}/run_test_step/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Environments_batch_exports_unpause_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/{id}/unpause/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Environments_batch_exports_run_test_step_new_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/batch_exports/run_test_step_new/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type get_Environments_batch_exports_test_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/batch_exports/test/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_dashboards_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/dashboards/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt'; limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedDashboardBasicList }
    }
    export type post_Environments_dashboards_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/dashboards/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { project_id: string }

            body: Schemas.Dashboard
        }
        responses: { 201: Schemas.Dashboard }
    }
    export type get_Environments_dashboards_collaborators_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }
        }
        responses: { 200: Array<Schemas.DashboardCollaborator> }
    }
    export type post_Environments_dashboards_collaborators_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }

            body: Schemas.DashboardCollaborator
        }
        responses: { 201: Schemas.DashboardCollaborator }
    }
    export type delete_Environments_dashboards_collaborators_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string; user__uuid: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_dashboards_sharing_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }
        }
        responses: { 200: Array<Schemas.SharingConfiguration> }
    }
    export type post_Environments_dashboards_sharing_passwords_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type delete_Environments_dashboards_sharing_passwords_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; password_id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Environments_dashboards_sharing_refresh_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/refresh/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type get_Environments_dashboards_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Dashboard }
    }
    export type put_Environments_dashboards_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }

            body: Schemas.Dashboard
        }
        responses: { 200: Schemas.Dashboard }
    }
    export type patch_Environments_dashboards_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedDashboard
        }
        responses: { 200: Schemas.Dashboard }
    }
    export type delete_Environments_dashboards_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type patch_Environments_dashboards_move_tile_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/dashboards/{id}/move_tile/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedDashboard
        }
        responses: { 200: unknown }
    }
    export type get_Environments_dashboards_stream_tiles_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/dashboards/{id}/stream_tiles/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_dashboards_create_from_template_json_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/dashboards/create_from_template_json/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { project_id: string }

            body: Schemas.Dashboard
        }
        responses: { 200: unknown }
    }
    export type get_Environments_error_tracking_assignment_rules_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/assignment_rules/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedErrorTrackingAssignmentRuleList }
    }
    export type post_Environments_error_tracking_assignment_rules_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/assignment_rules/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingAssignmentRule
        }
        responses: { 201: Schemas.ErrorTrackingAssignmentRule }
    }
    export type get_Environments_error_tracking_assignment_rules_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.ErrorTrackingAssignmentRule }
    }
    export type put_Environments_error_tracking_assignment_rules_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.ErrorTrackingAssignmentRule
        }
        responses: { 200: Schemas.ErrorTrackingAssignmentRule }
    }
    export type patch_Environments_error_tracking_assignment_rules_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedErrorTrackingAssignmentRule
        }
        responses: { 200: Schemas.ErrorTrackingAssignmentRule }
    }
    export type delete_Environments_error_tracking_assignment_rules_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type patch_Environments_error_tracking_assignment_rules_reorder_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/assignment_rules/reorder/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PatchedErrorTrackingAssignmentRule
        }
        responses: { 200: unknown }
    }
    export type get_Environments_error_tracking_grouping_rules_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/grouping_rules/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedErrorTrackingGroupingRuleList }
    }
    export type post_Environments_error_tracking_grouping_rules_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/grouping_rules/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingGroupingRule
        }
        responses: { 201: Schemas.ErrorTrackingGroupingRule }
    }
    export type get_Environments_error_tracking_grouping_rules_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.ErrorTrackingGroupingRule }
    }
    export type put_Environments_error_tracking_grouping_rules_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.ErrorTrackingGroupingRule
        }
        responses: { 200: Schemas.ErrorTrackingGroupingRule }
    }
    export type patch_Environments_error_tracking_grouping_rules_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedErrorTrackingGroupingRule
        }
        responses: { 200: Schemas.ErrorTrackingGroupingRule }
    }
    export type delete_Environments_error_tracking_grouping_rules_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type patch_Environments_error_tracking_grouping_rules_reorder_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/grouping_rules/reorder/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PatchedErrorTrackingGroupingRule
        }
        responses: { 200: unknown }
    }
    export type get_Environments_error_tracking_releases_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/releases/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedErrorTrackingReleaseList }
    }
    export type post_Environments_error_tracking_releases_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/releases/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingRelease
        }
        responses: { 201: Schemas.ErrorTrackingRelease }
    }
    export type get_Environments_error_tracking_releases_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/releases/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.ErrorTrackingRelease }
    }
    export type put_Environments_error_tracking_releases_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/error_tracking/releases/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.ErrorTrackingRelease
        }
        responses: { 200: Schemas.ErrorTrackingRelease }
    }
    export type patch_Environments_error_tracking_releases_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/releases/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedErrorTrackingRelease
        }
        responses: { 200: Schemas.ErrorTrackingRelease }
    }
    export type delete_Environments_error_tracking_releases_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/error_tracking/releases/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_error_tracking_suppression_rules_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/suppression_rules/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedErrorTrackingSuppressionRuleList }
    }
    export type post_Environments_error_tracking_suppression_rules_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/suppression_rules/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingSuppressionRule
        }
        responses: { 201: Schemas.ErrorTrackingSuppressionRule }
    }
    export type get_Environments_error_tracking_suppression_rules_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.ErrorTrackingSuppressionRule }
    }
    export type put_Environments_error_tracking_suppression_rules_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.ErrorTrackingSuppressionRule
        }
        responses: { 200: Schemas.ErrorTrackingSuppressionRule }
    }
    export type patch_Environments_error_tracking_suppression_rules_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedErrorTrackingSuppressionRule
        }
        responses: { 200: Schemas.ErrorTrackingSuppressionRule }
    }
    export type delete_Environments_error_tracking_suppression_rules_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type patch_Environments_error_tracking_suppression_rules_reorder_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/suppression_rules/reorder/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PatchedErrorTrackingSuppressionRule
        }
        responses: { 200: unknown }
    }
    export type get_Environments_error_tracking_symbol_sets_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedErrorTrackingSymbolSetList }
    }
    export type post_Environments_error_tracking_symbol_sets_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/'
        requestFormat: 'form-data'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingSymbolSet
        }
        responses: { 201: Schemas.ErrorTrackingSymbolSet }
    }
    export type get_Environments_error_tracking_symbol_sets_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.ErrorTrackingSymbolSet }
    }
    export type put_Environments_error_tracking_symbol_sets_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/'
        requestFormat: 'form-data'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.ErrorTrackingSymbolSet
        }
        responses: { 200: Schemas.ErrorTrackingSymbolSet }
    }
    export type patch_Environments_error_tracking_symbol_sets_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/'
        requestFormat: 'form-data'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedErrorTrackingSymbolSet
        }
        responses: { 200: Schemas.ErrorTrackingSymbolSet }
    }
    export type delete_Environments_error_tracking_symbol_sets_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type put_Environments_error_tracking_symbol_sets_finish_upload_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/finish_upload/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.ErrorTrackingSymbolSet
        }
        responses: { 200: unknown }
    }
    export type post_Environments_error_tracking_symbol_sets_bulk_finish_upload_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/bulk_finish_upload/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingSymbolSet
        }
        responses: { 200: unknown }
    }
    export type post_Environments_error_tracking_symbol_sets_bulk_start_upload_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/bulk_start_upload/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingSymbolSet
        }
        responses: { 200: unknown }
    }
    export type post_Environments_error_tracking_symbol_sets_start_upload_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/error_tracking/symbol_sets/start_upload/'
        requestFormat: 'form-data'
        parameters: {
            path: { project_id: string }

            body: Schemas.ErrorTrackingSymbolSet
        }
        responses: { 200: unknown }
    }
    export type get_Environments_events_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/events/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                after: string
                before: string
                distinct_id: number
                event: string
                format: 'csv' | 'json'
                limit: number
                offset: number
                person_id: number
                properties: Array<Schemas.Property>
                select: Array<string>
                where: Array<string>
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedClickhouseEventList }
    }
    export type get_Environments_events_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/events/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.ClickhouseEvent }
    }
    export type get_Environments_events_values_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/events/values/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_explicit_members_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/explicit_members/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: Array<Schemas.ExplicitTeamMember> }
    }
    export type post_Environments_explicit_members_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/explicit_members/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ExplicitTeamMember
        }
        responses: { 201: Schemas.ExplicitTeamMember }
    }
    export type get_Environments_explicit_members_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }
        }
        responses: { 200: Schemas.ExplicitTeamMember }
    }
    export type put_Environments_explicit_members_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }

            body: Schemas.ExplicitTeamMember
        }
        responses: { 200: Schemas.ExplicitTeamMember }
    }
    export type patch_Environments_explicit_members_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }

            body: Schemas.PatchedExplicitTeamMember
        }
        responses: { 200: Schemas.ExplicitTeamMember }
    }
    export type delete_Environments_explicit_members_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_exports_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/exports/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedExportedAssetList }
    }
    export type post_Environments_exports_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/exports/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ExportedAsset
        }
        responses: { 201: Schemas.ExportedAsset }
    }
    export type get_Environments_exports_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.ExportedAsset }
    }
    export type get_Environments_exports_content_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/exports/{id}/content/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_file_system_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/file_system/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedFileSystemList }
    }
    export type post_Environments_file_system_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/file_system/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 201: Schemas.FileSystem }
    }
    export type get_Environments_file_system_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.FileSystem }
    }
    export type put_Environments_file_system_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: Schemas.FileSystem }
    }
    export type patch_Environments_file_system_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedFileSystem
        }
        responses: { 200: Schemas.FileSystem }
    }
    export type delete_Environments_file_system_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Environments_file_system_count_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/file_system/{id}/count/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type post_Environments_file_system_link_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/file_system/{id}/link/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type post_Environments_file_system_move_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/file_system/{id}/move/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type post_Environments_file_system_count_by_path_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/file_system/count_by_path/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type get_Environments_file_system_unfiled_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/file_system/unfiled/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_file_system_shortcut_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/file_system_shortcut/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedFileSystemShortcutList }
    }
    export type post_Environments_file_system_shortcut_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/file_system_shortcut/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FileSystemShortcut
        }
        responses: { 201: Schemas.FileSystemShortcut }
    }
    export type get_Environments_file_system_shortcut_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.FileSystemShortcut }
    }
    export type put_Environments_file_system_shortcut_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystemShortcut
        }
        responses: { 200: Schemas.FileSystemShortcut }
    }
    export type patch_Environments_file_system_shortcut_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedFileSystemShortcut
        }
        responses: { 200: Schemas.FileSystemShortcut }
    }
    export type delete_Environments_file_system_shortcut_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_groups_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/groups/'
        requestFormat: 'json'
        parameters: {
            query: { cursor?: string | undefined; group_type_index: number; search: string }
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedGroupList }
    }
    export type post_Environments_groups_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/groups/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.CreateGroup
        }
        responses: { 201: Schemas.Group }
    }
    export type get_Environments_groups_activity_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/groups/activity/'
        requestFormat: 'json'
        parameters: {
            query: { group_type_index: number; id: string }
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_groups_delete_property_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/groups/delete_property/'
        requestFormat: 'json'
        parameters: {
            query: { group_key: string; group_type_index: number }
            path: { project_id: string }

            body: Schemas.Group
        }
        responses: { 200: unknown }
    }
    export type get_Environments_groups_find_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/groups/find/'
        requestFormat: 'json'
        parameters: {
            query: { group_key: string; group_type_index: number }
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_groups_property_definitions_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/groups/property_definitions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_groups_property_values_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/groups/property_values/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_groups_related_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/groups/related/'
        requestFormat: 'json'
        parameters: {
            query: { group_type_index: number; id: string }
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_groups_update_property_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/groups/update_property/'
        requestFormat: 'json'
        parameters: {
            query: { group_key: string; group_type_index: number }
            path: { project_id: string }

            body: Schemas.Group
        }
        responses: { 200: unknown }
    }
    export type get_Environments_hog_functions_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/hog_functions/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                created_at: string
                created_by: number
                enabled: boolean
                id: string
                limit: number
                offset: number
                search: string
                type: Array<string>
                updated_at: string
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedHogFunctionMinimalList }
    }
    export type post_Environments_hog_functions_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/hog_functions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 201: Schemas.HogFunction }
    }
    export type get_Environments_hog_functions_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.HogFunction }
    }
    export type put_Environments_hog_functions_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 200: Schemas.HogFunction }
    }
    export type patch_Environments_hog_functions_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedHogFunction
        }
        responses: { 200: Schemas.HogFunction }
    }
    export type delete_Environments_hog_functions_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type post_Environments_hog_functions_broadcast_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/hog_functions/{id}/broadcast/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 200: unknown }
    }
    export type post_Environments_hog_functions_invocations_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/hog_functions/{id}/invocations/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 200: unknown }
    }
    export type get_Environments_hog_functions_logs_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/hog_functions/{id}/logs/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_hog_functions_metrics_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/hog_functions/{id}/metrics/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_hog_functions_metrics_totals_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/hog_functions/{id}/metrics/totals/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_hog_functions_icon_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/hog_functions/icon/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_hog_functions_icons_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/hog_functions/icons/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type patch_Environments_hog_functions_rearrange_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/hog_functions/rearrange/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PatchedHogFunction
        }
        responses: { 200: unknown }
    }
    export type get_Environments_insights_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/insights/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                basic: boolean
                created_by: number
                format: 'csv' | 'json'
                limit: number
                offset: number
                refresh:
                    | 'async'
                    | 'async_except_on_cache_miss'
                    | 'blocking'
                    | 'force_async'
                    | 'force_blocking'
                    | 'force_cache'
                    | 'lazy_async'
                short_id: string
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedInsightList }
    }
    export type post_Environments_insights_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/insights/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Insight
        }
        responses: { 201: Schemas.Insight }
    }
    export type get_Environments_insights_sharing_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/insights/{insight_id}/sharing/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; project_id: string }
        }
        responses: { 200: Array<Schemas.SharingConfiguration> }
    }
    export type post_Environments_insights_sharing_passwords_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type delete_Environments_insights_sharing_passwords_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; password_id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Environments_insights_sharing_refresh_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/insights/{insight_id}/sharing/refresh/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type get_Environments_insights_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                format: 'csv' | 'json'
                from_dashboard: number
                refresh:
                    | 'async'
                    | 'async_except_on_cache_miss'
                    | 'blocking'
                    | 'force_async'
                    | 'force_blocking'
                    | 'force_cache'
                    | 'lazy_async'
            }>
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Insight }
    }
    export type put_Environments_insights_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Insight
        }
        responses: { 200: Schemas.Insight }
    }
    export type patch_Environments_insights_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedInsight
        }
        responses: { 200: Schemas.Insight }
    }
    export type delete_Environments_insights_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Environments_insights_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/environments/{project_id}/insights/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_insights_viewed_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/insights/{id}/viewed/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Insight
        }
        responses: { 200: unknown }
    }
    export type get_Environments_insights_activity_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/insights/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_insights_cancel_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/insights/cancel/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Insight
        }
        responses: { 200: unknown }
    }
    export type get_Environments_insights_my_last_viewed_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/insights/my_last_viewed/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_logs_attributes_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/logs/attributes/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_logs_query_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/logs/query/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_logs_sparkline_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/logs/sparkline/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_logs_values_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/logs/values/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_max_tools_create_and_query_insight_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/max_tools/create_and_query_insight/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persisted_folder_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/persisted_folder/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedPersistedFolderList }
    }
    export type post_Environments_persisted_folder_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persisted_folder/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PersistedFolder
        }
        responses: { 201: Schemas.PersistedFolder }
    }
    export type get_Environments_persisted_folder_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.PersistedFolder }
    }
    export type put_Environments_persisted_folder_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PersistedFolder
        }
        responses: { 200: Schemas.PersistedFolder }
    }
    export type patch_Environments_persisted_folder_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedPersistedFolder
        }
        responses: { 200: Schemas.PersistedFolder }
    }
    export type delete_Environments_persisted_folder_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_persons_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                distinct_id: string
                email: string
                format: 'csv' | 'json'
                limit: number
                offset: number
                properties: Array<Schemas.Property>
                search: string
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedPersonList }
    }
    export type get_Environments_persons_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Person }
    }
    export type put_Environments_persons_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: Schemas.Person }
    }
    export type patch_Environments_persons_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedPerson
        }
        responses: { 200: Schemas.Person }
    }
    export type delete_Environments_persons_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ delete_events: boolean; format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_persons_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_delete_events_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/{id}/delete_events/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_delete_property_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/{id}/delete_property/'
        requestFormat: 'json'
        parameters: {
            query: { $unset: string; format?: ('csv' | 'json') | undefined }
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_properties_timeline_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/{id}/properties_timeline/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_split_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/{id}/split/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_update_property_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/{id}/update_property/'
        requestFormat: 'json'
        parameters: {
            query: { format?: ('csv' | 'json') | undefined; key: string; value: unknown }
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_activity_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_bulk_delete_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/bulk_delete/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                delete_events: boolean
                distinct_ids: Record<string, unknown>
                format: 'csv' | 'json'
                ids: Record<string, unknown>
            }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_cohorts_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/cohorts/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_funnel_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/funnel/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_funnel_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/funnel/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_funnel_correlation_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/funnel/correlation/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_funnel_correlation_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/funnel/correlation/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_lifecycle_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/lifecycle/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_persons_reset_person_distinct_id_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/persons/reset_person_distinct_id/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_stickiness_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/stickiness/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_trends_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/trends/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_persons_values_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/persons/values/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_plugin_configs_logs_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/plugin_configs/{plugin_config_id}/logs/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { plugin_config_id: string; project_id: string }
        }
        responses: { 200: Schemas.PaginatedPluginLogEntryList }
    }
    export type post_Environments_query_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/query/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.QueryRequest
        }
        responses: { 200: Schemas.QueryResponseAlternative }
    }
    export type get_Environments_query_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/query/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.QueryStatusResponse }
    }
    export type delete_Environments_query_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/query/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_query_log_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/query/{id}/log/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Record<string, unknown> }
    }
    export type post_Environments_query_check_auth_for_async_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/query/check_auth_for_async/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_query_draft_sql_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/query/draft_sql/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_query_upgrade_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/query/upgrade/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.QueryUpgradeRequest
        }
        responses: { 200: Schemas.QueryUpgradeResponse }
    }
    export type get_Environments_session_recording_playlists_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/session_recording_playlists/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ created_by: number; limit: number; offset: number; short_id: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedSessionRecordingPlaylistList }
    }
    export type post_Environments_session_recording_playlists_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/session_recording_playlists/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.SessionRecordingPlaylist
        }
        responses: { 201: Schemas.SessionRecordingPlaylist }
    }
    export type get_Environments_session_recording_playlists_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 200: Schemas.SessionRecordingPlaylist }
    }
    export type put_Environments_session_recording_playlists_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }

            body: Schemas.SessionRecordingPlaylist
        }
        responses: { 200: Schemas.SessionRecordingPlaylist }
    }
    export type patch_Environments_session_recording_playlists_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }

            body: Schemas.PatchedSessionRecordingPlaylist
        }
        responses: { 200: Schemas.SessionRecordingPlaylist }
    }
    export type delete_Environments_session_recording_playlists_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Environments_session_recording_playlists_recordings_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Environments_session_recording_playlists_recordings_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; session_recording_id: string; short_id: string }

            body: Schemas.SessionRecordingPlaylist
        }
        responses: { 200: unknown }
    }
    export type delete_Environments_session_recording_playlists_recordings_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; session_recording_id: string; short_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_session_recordings_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/session_recordings/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedSessionRecordingList }
    }
    export type get_Environments_session_recordings_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.SessionRecording }
    }
    export type put_Environments_session_recordings_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.SessionRecording
        }
        responses: { 200: Schemas.SessionRecording }
    }
    export type patch_Environments_session_recordings_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedSessionRecording
        }
        responses: { 200: Schemas.SessionRecording }
    }
    export type delete_Environments_session_recordings_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_session_recordings_sharing_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; recording_id: string }
        }
        responses: { 200: Array<Schemas.SharingConfiguration> }
    }
    export type post_Environments_session_recordings_sharing_passwords_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; recording_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type delete_Environments_session_recordings_sharing_passwords_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/'
        requestFormat: 'json'
        parameters: {
            path: { password_id: string; project_id: string; recording_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Environments_session_recordings_sharing_refresh_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/refresh/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; recording_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type post_Create_session_summaries = {
        method: 'POST'
        path: '/api/environments/{project_id}/session_summaries/create_session_summaries/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.SessionSummaries
        }
        responses: { 200: Schemas.SessionSummaries }
    }
    export type get_Environments_sessions_property_definitions_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/sessions/property_definitions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_sessions_values_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/sessions/values/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_subscriptions_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/subscriptions/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedSubscriptionList }
    }
    export type post_Environments_subscriptions_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/subscriptions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Subscription
        }
        responses: { 201: Schemas.Subscription }
    }
    export type get_Environments_subscriptions_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Subscription }
    }
    export type put_Environments_subscriptions_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Subscription
        }
        responses: { 200: Schemas.Subscription }
    }
    export type patch_Environments_subscriptions_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedSubscription
        }
        responses: { 200: Schemas.Subscription }
    }
    export type delete_Environments_subscriptions_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Environments_user_interviews_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/user_interviews/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedUserInterviewList }
    }
    export type post_Environments_user_interviews_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/user_interviews/'
        requestFormat: 'form-data'
        parameters: {
            path: { project_id: string }

            body: Schemas.UserInterview
        }
        responses: { 201: Schemas.UserInterview }
    }
    export type get_Environments_user_interviews_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/user_interviews/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.UserInterview }
    }
    export type put_Environments_user_interviews_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/user_interviews/{id}/'
        requestFormat: 'form-data'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.UserInterview
        }
        responses: { 200: Schemas.UserInterview }
    }
    export type patch_Environments_user_interviews_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/user_interviews/{id}/'
        requestFormat: 'form-data'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedUserInterview
        }
        responses: { 200: Schemas.UserInterview }
    }
    export type delete_Environments_user_interviews_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/user_interviews/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_warehouse_saved_queries_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/warehouse_saved_queries/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ page: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedDataWarehouseSavedQueryList }
    }
    export type post_Environments_warehouse_saved_queries_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_saved_queries/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 201: Schemas.DataWarehouseSavedQuery }
    }
    export type get_Environments_warehouse_saved_queries_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type put_Environments_warehouse_saved_queries_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type patch_Environments_warehouse_saved_queries_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedDataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type delete_Environments_warehouse_saved_queries_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_warehouse_saved_queries_activity_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Environments_warehouse_saved_queries_ancestors_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/ancestors/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Environments_warehouse_saved_queries_cancel_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/cancel/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Environments_warehouse_saved_queries_descendants_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/descendants/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Environments_warehouse_saved_queries_revert_materialization_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/revert_materialization/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Environments_warehouse_saved_queries_run_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_saved_queries/{id}/run/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type get_Environments_warehouse_tables_list = {
        method: 'GET'
        path: '/api/environments/{project_id}/warehouse_tables/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedTableList }
    }
    export type post_Environments_warehouse_tables_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_tables/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Table
        }
        responses: { 201: Schemas.Table }
    }
    export type get_Environments_warehouse_tables_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.Table }
    }
    export type put_Environments_warehouse_tables_update = {
        method: 'PUT'
        path: '/api/environments/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.Table
        }
        responses: { 200: Schemas.Table }
    }
    export type patch_Environments_warehouse_tables_partial_update = {
        method: 'PATCH'
        path: '/api/environments/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedTable
        }
        responses: { 200: Schemas.Table }
    }
    export type delete_Environments_warehouse_tables_destroy = {
        method: 'DELETE'
        path: '/api/environments/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Environments_warehouse_tables_refresh_schema_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_tables/{id}/refresh_schema/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.Table
        }
        responses: { 200: unknown }
    }
    export type post_Environments_warehouse_tables_update_schema_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_tables/{id}/update_schema/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.Table
        }
        responses: { 200: unknown }
    }
    export type post_Environments_warehouse_tables_file_create = {
        method: 'POST'
        path: '/api/environments/{project_id}/warehouse_tables/file/'
        requestFormat: 'form-data'
        parameters: {
            path: { project_id: string }

            body: Schemas.Table
        }
        responses: { 200: unknown }
    }
    export type get_Environments_web_vitals_retrieve = {
        method: 'GET'
        path: '/api/environments/{project_id}/web_vitals/'
        requestFormat: 'json'
        parameters: {
            query: { pathname: string }
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_List = {
        method: 'GET'
        path: '/api/organizations/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
        }
        responses: { 200: Schemas.PaginatedOrganizationList }
    }
    export type post_Create = {
        method: 'POST'
        path: '/api/organizations/'
        requestFormat: 'json'
        parameters: {
            body: Schemas.Organization
        }
        responses: { 201: Schemas.Organization }
    }
    export type get_Retrieve = {
        method: 'GET'
        path: '/api/organizations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string }
        }
        responses: { 200: Schemas.Organization }
    }
    export type put_Update = {
        method: 'PUT'
        path: '/api/organizations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string }

            body: Schemas.Organization
        }
        responses: { 200: Schemas.Organization }
    }
    export type patch_Partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string }

            body: Schemas.PatchedOrganization
        }
        responses: { 200: Schemas.Organization }
    }
    export type delete_Destroy = {
        method: 'DELETE'
        path: '/api/organizations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Environments_rollback_create = {
        method: 'POST'
        path: '/api/organizations/{id}/environments_rollback/'
        requestFormat: 'json'
        parameters: {
            path: { id: string }

            body: Schemas.Organization
        }
        responses: { 200: Schemas.Organization }
    }
    export type get_Batch_exports_list = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/batch_exports/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string }
        }
        responses: { 200: Schemas.PaginatedBatchExportList }
    }
    export type post_Batch_exports_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/batch_exports/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.BatchExport
        }
        responses: { 201: Schemas.BatchExport }
    }
    export type get_Batch_exports_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type put_Batch_exports_update = {
        method: 'PUT'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type patch_Batch_exports_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.PatchedBatchExport
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type delete_Batch_exports_destroy = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Batch_exports_backfill_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/backfill/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_logs_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/logs/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_pause_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/pause/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_run_test_step_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/run_test_step/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_unpause_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/batch_exports/{id}/unpause/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_run_test_step_new_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/batch_exports/run_test_step_new/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_test_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/batch_exports/test/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Domains_list = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/domains/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string }
        }
        responses: { 200: Schemas.PaginatedOrganizationDomainList }
    }
    export type post_Domains_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/domains/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.OrganizationDomain
        }
        responses: { 201: Schemas.OrganizationDomain }
    }
    export type get_Domains_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/domains/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 200: Schemas.OrganizationDomain }
    }
    export type put_Domains_update = {
        method: 'PUT'
        path: '/api/organizations/{organization_id}/domains/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.OrganizationDomain
        }
        responses: { 200: Schemas.OrganizationDomain }
    }
    export type patch_Domains_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/domains/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.PatchedOrganizationDomain
        }
        responses: { 200: Schemas.OrganizationDomain }
    }
    export type delete_Domains_destroy = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/domains/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Domains_verify_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/domains/{id}/verify/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.OrganizationDomain
        }
        responses: { 200: unknown }
    }
    export type get_Invites_list = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/invites/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string }
        }
        responses: { 200: Schemas.PaginatedOrganizationInviteList }
    }
    export type post_Invites_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/invites/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.OrganizationInvite
        }
        responses: { 201: Schemas.OrganizationInvite }
    }
    export type delete_Invites_destroy = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/invites/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Invites_bulk_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/invites/bulk/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.OrganizationInvite
        }
        responses: { 200: unknown }
    }
    export type get_Members_list = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/members/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string }
        }
        responses: { 200: Schemas.PaginatedOrganizationMemberList }
    }
    export type put_Members_update = {
        method: 'PUT'
        path: '/api/organizations/{organization_id}/members/{user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string; user__uuid: string }

            body: Schemas.OrganizationMember
        }
        responses: { 200: Schemas.OrganizationMember }
    }
    export type patch_Members_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/members/{user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string; user__uuid: string }

            body: Schemas.PatchedOrganizationMember
        }
        responses: { 200: Schemas.OrganizationMember }
    }
    export type delete_Members_destroy = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/members/{user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string; user__uuid: string }
        }
        responses: { 204: unknown }
    }
    export type get_Members_scoped_api_keys_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/members/{user__uuid}/scoped_api_keys/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string; user__uuid: string }
        }
        responses: { 200: Schemas.OrganizationMember }
    }
    export type get_List_2 = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/projects/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string }
        }
        responses: { 200: Schemas.PaginatedProjectBackwardCompatBasicList }
    }
    export type post_Create_2 = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/projects/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.ProjectBackwardCompat
        }
        responses: { 201: Schemas.ProjectBackwardCompat }
    }
    export type get_Retrieve_2 = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/projects/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type put_Update_2 = {
        method: 'PUT'
        path: '/api/organizations/{organization_id}/projects/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.ProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type patch_Partial_update_2 = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/projects/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.PatchedProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type delete_Destroy_2 = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/projects/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Activity_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/projects/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type patch_Add_product_intent_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/projects/{id}/add_product_intent/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.PatchedProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type post_Change_organization_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/projects/{id}/change_organization/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.ProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type patch_Complete_product_onboarding_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/projects/{id}/complete_product_onboarding/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.PatchedProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type patch_Delete_secret_token_backup_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/projects/{id}/delete_secret_token_backup/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.PatchedProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type get_Is_generating_demo_data_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/projects/{id}/is_generating_demo_data/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type patch_Reset_token_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/projects/{id}/reset_token/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.PatchedProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type patch_Rotate_secret_token_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/projects/{id}/rotate_secret_token/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; organization_id: string }

            body: Schemas.PatchedProjectBackwardCompat
        }
        responses: { 200: Schemas.ProjectBackwardCompat }
    }
    export type get_Proxy_records_list = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/proxy_records/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string }
        }
        responses: { 200: Schemas.PaginatedProxyRecordList }
    }
    export type post_Proxy_records_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/proxy_records/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.ProxyRecord
        }
        responses: { 201: Schemas.ProxyRecord }
    }
    export type get_Proxy_records_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/proxy_records/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 200: Schemas.ProxyRecord }
    }
    export type put_Proxy_records_update = {
        method: 'PUT'
        path: '/api/organizations/{organization_id}/proxy_records/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.ProxyRecord
        }
        responses: { 200: Schemas.ProxyRecord }
    }
    export type patch_Proxy_records_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/proxy_records/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.PatchedProxyRecord
        }
        responses: { 200: Schemas.ProxyRecord }
    }
    export type delete_Proxy_records_destroy = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/proxy_records/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Roles_list = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/roles/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string }
        }
        responses: { 200: Schemas.PaginatedRoleList }
    }
    export type post_Roles_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/roles/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string }

            body: Schemas.Role
        }
        responses: { 201: Schemas.Role }
    }
    export type get_Roles_retrieve = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/roles/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 200: Schemas.Role }
    }
    export type put_Roles_update = {
        method: 'PUT'
        path: '/api/organizations/{organization_id}/roles/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.Role
        }
        responses: { 200: Schemas.Role }
    }
    export type patch_Roles_partial_update = {
        method: 'PATCH'
        path: '/api/organizations/{organization_id}/roles/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }

            body: Schemas.PatchedRole
        }
        responses: { 200: Schemas.Role }
    }
    export type delete_Roles_destroy = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/roles/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Roles_role_memberships_list = {
        method: 'GET'
        path: '/api/organizations/{organization_id}/roles/{role_id}/role_memberships/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { organization_id: string; role_id: string }
        }
        responses: { 200: Schemas.PaginatedRoleMembershipList }
    }
    export type post_Roles_role_memberships_create = {
        method: 'POST'
        path: '/api/organizations/{organization_id}/roles/{role_id}/role_memberships/'
        requestFormat: 'json'
        parameters: {
            path: { organization_id: string; role_id: string }

            body: Schemas.RoleMembership
        }
        responses: { 201: Schemas.RoleMembership }
    }
    export type delete_Roles_role_memberships_destroy = {
        method: 'DELETE'
        path: '/api/organizations/{organization_id}/roles/{role_id}/role_memberships/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; organization_id: string; role_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Actions_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/actions/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json'; limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedActionList }
    }
    export type post_Actions_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/actions/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Action
        }
        responses: { 201: Schemas.Action }
    }
    export type get_Actions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/actions/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Action }
    }
    export type put_Actions_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/actions/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Action
        }
        responses: { 200: Schemas.Action }
    }
    export type patch_Actions_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/actions/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedAction
        }
        responses: { 200: Schemas.Action }
    }
    export type delete_Actions_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/actions/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Activity_log_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/activity_log/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedActivityLogList }
    }
    export type get_Annotations_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/annotations/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedAnnotationList }
    }
    export type post_Annotations_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/annotations/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Annotation
        }
        responses: { 201: Schemas.Annotation }
    }
    export type get_Annotations_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/annotations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Annotation }
    }
    export type put_Annotations_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/annotations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Annotation
        }
        responses: { 200: Schemas.Annotation }
    }
    export type patch_Annotations_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/annotations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedAnnotation
        }
        responses: { 200: Schemas.Annotation }
    }
    export type delete_Annotations_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/annotations/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_App_metrics_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/app_metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_App_metrics_error_details_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/app_metrics/{id}/error_details/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_App_metrics_historical_exports_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/'
        requestFormat: 'json'
        parameters: {
            path: { plugin_config_id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_App_metrics_historical_exports_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; plugin_config_id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_list_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedBatchExportList }
    }
    export type post_Batch_exports_create_2 = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 201: Schemas.BatchExport }
    }
    export type get_Batch_exports_backfills_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ cursor: string; ordering: string }>
            path: { batch_export_id: string; project_id: string }
        }
        responses: { 200: Schemas.PaginatedBatchExportBackfillList }
    }
    export type post_Batch_exports_backfills_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; project_id: string }

            body: Schemas.BatchExportBackfill
        }
        responses: { 201: Schemas.BatchExportBackfill }
    }
    export type get_Batch_exports_backfills_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }
        }
        responses: { 200: Schemas.BatchExportBackfill }
    }
    export type post_Batch_exports_backfills_cancel_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }

            body: Schemas.BatchExportBackfill
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_runs_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ cursor: string; ordering: string }>
            path: { batch_export_id: string; project_id: string }
        }
        responses: { 200: Schemas.PaginatedBatchExportRunList }
    }
    export type get_Batch_exports_runs_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }
        }
        responses: { 200: Schemas.BatchExportRun }
    }
    export type post_Batch_exports_runs_cancel_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }

            body: Schemas.BatchExportRun
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_runs_logs_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_runs_retry_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/'
        requestFormat: 'json'
        parameters: {
            path: { batch_export_id: string; id: string; project_id: string }

            body: Schemas.BatchExportRun
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type put_Batch_exports_update_2 = {
        method: 'PUT'
        path: '/api/projects/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type patch_Batch_exports_partial_update_2 = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedBatchExport
        }
        responses: { 200: Schemas.BatchExport }
    }
    export type delete_Batch_exports_destroy_2 = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/batch_exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Batch_exports_backfill_create_2 = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{id}/backfill/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_logs_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/{id}/logs/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_pause_create_2 = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{id}/pause/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_run_test_step_create_2 = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{id}/run_test_step/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_unpause_create_2 = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/{id}/unpause/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type post_Batch_exports_run_test_step_new_create_2 = {
        method: 'POST'
        path: '/api/projects/{project_id}/batch_exports/run_test_step_new/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.BatchExport
        }
        responses: { 200: unknown }
    }
    export type get_Batch_exports_test_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/batch_exports/test/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Cohorts_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/cohorts/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedCohortList }
    }
    export type post_Cohorts_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/cohorts/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Cohort
        }
        responses: { 201: Schemas.Cohort }
    }
    export type get_Cohorts_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/cohorts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Cohort }
    }
    export type put_Cohorts_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/cohorts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Cohort
        }
        responses: { 200: Schemas.Cohort }
    }
    export type patch_Cohorts_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/cohorts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedCohort
        }
        responses: { 200: Schemas.Cohort }
    }
    export type delete_Cohorts_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/cohorts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Cohorts_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/cohorts/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type patch_Cohorts_add_persons_to_static_cohort_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/cohorts/{id}/add_persons_to_static_cohort/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedCohort
        }
        responses: { 200: unknown }
    }
    export type get_Cohorts_duplicate_as_static_cohort_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/cohorts/{id}/duplicate_as_static_cohort/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Cohorts_persons_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/cohorts/{id}/persons/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Cohorts_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/cohorts/activity/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Dashboard_templates_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboard_templates/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedDashboardTemplateList }
    }
    export type post_Dashboard_templates_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/dashboard_templates/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.DashboardTemplate
        }
        responses: { 201: Schemas.DashboardTemplate }
    }
    export type get_Dashboard_templates_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboard_templates/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.DashboardTemplate }
    }
    export type put_Dashboard_templates_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/dashboard_templates/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DashboardTemplate
        }
        responses: { 200: Schemas.DashboardTemplate }
    }
    export type patch_Dashboard_templates_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/dashboard_templates/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedDashboardTemplate
        }
        responses: { 200: Schemas.DashboardTemplate }
    }
    export type delete_Dashboard_templates_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/dashboard_templates/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Dashboard_templates_json_schema_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboard_templates/json_schema/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Dashboards_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboards/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt'; limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedDashboardBasicList }
    }
    export type post_Dashboards_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/dashboards/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { project_id: string }

            body: Schemas.Dashboard
        }
        responses: { 201: Schemas.Dashboard }
    }
    export type get_Dashboards_collaborators_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }
        }
        responses: { 200: Array<Schemas.DashboardCollaborator> }
    }
    export type post_Dashboards_collaborators_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }

            body: Schemas.DashboardCollaborator
        }
        responses: { 201: Schemas.DashboardCollaborator }
    }
    export type delete_Dashboards_collaborators_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string; user__uuid: string }
        }
        responses: { 204: unknown }
    }
    export type get_Dashboards_sharing_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }
        }
        responses: { 200: Array<Schemas.SharingConfiguration> }
    }
    export type post_Dashboards_sharing_passwords_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type delete_Dashboards_sharing_passwords_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; password_id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Dashboards_sharing_refresh_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/refresh/'
        requestFormat: 'json'
        parameters: {
            path: { dashboard_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type get_Dashboards_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Dashboard }
    }
    export type put_Dashboards_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }

            body: Schemas.Dashboard
        }
        responses: { 200: Schemas.Dashboard }
    }
    export type patch_Dashboards_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedDashboard
        }
        responses: { 200: Schemas.Dashboard }
    }
    export type delete_Dashboards_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/dashboards/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type patch_Dashboards_move_tile_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/dashboards/{id}/move_tile/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedDashboard
        }
        responses: { 200: unknown }
    }
    export type get_Dashboards_stream_tiles_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/dashboards/{id}/stream_tiles/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Dashboards_create_from_template_json_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/dashboards/create_from_template_json/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'json' | 'txt' }>
            path: { project_id: string }

            body: Schemas.Dashboard
        }
        responses: { 200: unknown }
    }
    export type get_Early_access_feature_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/early_access_feature/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedEarlyAccessFeatureList }
    }
    export type post_Early_access_feature_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/early_access_feature/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.EarlyAccessFeatureSerializerCreateOnly
        }
        responses: { 201: Schemas.EarlyAccessFeatureSerializerCreateOnly }
    }
    export type get_Early_access_feature_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/early_access_feature/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.EarlyAccessFeature }
    }
    export type put_Early_access_feature_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/early_access_feature/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.EarlyAccessFeature
        }
        responses: { 200: Schemas.EarlyAccessFeature }
    }
    export type patch_Early_access_feature_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/early_access_feature/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedEarlyAccessFeature
        }
        responses: { 200: Schemas.EarlyAccessFeature }
    }
    export type delete_Early_access_feature_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/early_access_feature/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/environments/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedTeamBasicList }
    }
    export type post_Environments_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/environments/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Team
        }
        responses: { 201: Schemas.Team }
    }
    export type get_Environments_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/environments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Team }
    }
    export type put_Environments_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/environments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Team
        }
        responses: { 200: Schemas.Team }
    }
    export type patch_Environments_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/environments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedTeam
        }
        responses: { 200: Schemas.Team }
    }
    export type delete_Environments_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/environments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Environments_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/environments/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type patch_Environments_add_product_intent_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/environments/{id}/add_product_intent/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedTeam
        }
        responses: { 200: unknown }
    }
    export type patch_Environments_complete_product_onboarding_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/environments/{id}/complete_product_onboarding/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedTeam
        }
        responses: { 200: unknown }
    }
    export type patch_Environments_delete_secret_token_backup_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/environments/{id}/delete_secret_token_backup/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedTeam
        }
        responses: { 200: unknown }
    }
    export type get_Environments_event_ingestion_restrictions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/environments/{id}/event_ingestion_restrictions/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Environments_is_generating_demo_data_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/environments/{id}/is_generating_demo_data/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type patch_Environments_reset_token_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/environments/{id}/reset_token/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedTeam
        }
        responses: { 200: unknown }
    }
    export type patch_Environments_rotate_secret_token_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/environments/{id}/rotate_secret_token/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedTeam
        }
        responses: { 200: unknown }
    }
    export type get_Event_definitions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/event_definitions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Event_definitions_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/event_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type put_Event_definitions_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/event_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type patch_Event_definitions_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/event_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type delete_Event_definitions_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/event_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Event_definitions_metrics_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/event_definitions/{id}/metrics/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Events_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/events/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                after: string
                before: string
                distinct_id: number
                event: string
                format: 'csv' | 'json'
                limit: number
                offset: number
                person_id: number
                properties: Array<Schemas.Property>
                select: Array<string>
                where: Array<string>
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedClickhouseEventList }
    }
    export type get_Events_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/events/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.ClickhouseEvent }
    }
    export type get_Events_values_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/events/values/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Experiment_holdouts_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/experiment_holdouts/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedExperimentHoldoutList }
    }
    export type post_Experiment_holdouts_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/experiment_holdouts/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ExperimentHoldout
        }
        responses: { 201: Schemas.ExperimentHoldout }
    }
    export type get_Experiment_holdouts_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/experiment_holdouts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.ExperimentHoldout }
    }
    export type put_Experiment_holdouts_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/experiment_holdouts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.ExperimentHoldout
        }
        responses: { 200: Schemas.ExperimentHoldout }
    }
    export type patch_Experiment_holdouts_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/experiment_holdouts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedExperimentHoldout
        }
        responses: { 200: Schemas.ExperimentHoldout }
    }
    export type delete_Experiment_holdouts_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/experiment_holdouts/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Experiment_saved_metrics_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/experiment_saved_metrics/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedExperimentSavedMetricList }
    }
    export type post_Experiment_saved_metrics_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/experiment_saved_metrics/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ExperimentSavedMetric
        }
        responses: { 201: Schemas.ExperimentSavedMetric }
    }
    export type get_Experiment_saved_metrics_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/experiment_saved_metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.ExperimentSavedMetric }
    }
    export type put_Experiment_saved_metrics_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/experiment_saved_metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.ExperimentSavedMetric
        }
        responses: { 200: Schemas.ExperimentSavedMetric }
    }
    export type patch_Experiment_saved_metrics_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/experiment_saved_metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedExperimentSavedMetric
        }
        responses: { 200: Schemas.ExperimentSavedMetric }
    }
    export type delete_Experiment_saved_metrics_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/experiment_saved_metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Experiments_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/experiments/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedExperimentList }
    }
    export type post_Experiments_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/experiments/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Experiment
        }
        responses: { 201: Schemas.Experiment }
    }
    export type get_Experiments_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Experiment }
    }
    export type put_Experiments_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Experiment
        }
        responses: { 200: Schemas.Experiment }
    }
    export type patch_Experiments_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedExperiment
        }
        responses: { 200: Schemas.Experiment }
    }
    export type delete_Experiments_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type post_Experiments_create_exposure_cohort_for_experiment_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/experiments/{id}/create_exposure_cohort_for_experiment/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Experiment
        }
        responses: { 200: unknown }
    }
    export type post_Experiments_duplicate_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/experiments/{id}/duplicate/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Experiment
        }
        responses: { 200: unknown }
    }
    export type get_Experiments_requires_flag_implementation_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/experiments/requires_flag_implementation/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Explicit_members_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/explicit_members/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: Array<Schemas.ExplicitTeamMember> }
    }
    export type post_Explicit_members_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/explicit_members/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ExplicitTeamMember
        }
        responses: { 201: Schemas.ExplicitTeamMember }
    }
    export type get_Explicit_members_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }
        }
        responses: { 200: Schemas.ExplicitTeamMember }
    }
    export type put_Explicit_members_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }

            body: Schemas.ExplicitTeamMember
        }
        responses: { 200: Schemas.ExplicitTeamMember }
    }
    export type patch_Explicit_members_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }

            body: Schemas.PatchedExplicitTeamMember
        }
        responses: { 200: Schemas.ExplicitTeamMember }
    }
    export type delete_Explicit_members_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { parent_membership__user__uuid: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Exports_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/exports/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedExportedAssetList }
    }
    export type post_Exports_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/exports/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.ExportedAsset
        }
        responses: { 201: Schemas.ExportedAsset }
    }
    export type get_Exports_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/exports/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.ExportedAsset }
    }
    export type get_Exports_content_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/exports/{id}/content/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Feature_flags_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                active: 'STALE' | 'false' | 'true'
                created_by_id: string
                evaluation_runtime: 'both' | 'client' | 'server'
                excluded_properties: string
                limit: number
                offset: number
                search: string
                type: 'boolean' | 'experiment' | 'multivariant'
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedFeatureFlagList }
    }
    export type post_Feature_flags_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/feature_flags/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FeatureFlag
        }
        responses: { 201: Schemas.FeatureFlag }
    }
    export type get_Feature_flags_role_access_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { feature_flag_id: number; project_id: string }
        }
        responses: { 200: Schemas.PaginatedFeatureFlagRoleAccessList }
    }
    export type post_Feature_flags_role_access_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/'
        requestFormat: 'json'
        parameters: {
            path: { feature_flag_id: number; project_id: string }

            body: Schemas.FeatureFlagRoleAccess
        }
        responses: { 201: Schemas.FeatureFlagRoleAccess }
    }
    export type get_Feature_flags_role_access_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { feature_flag_id: number; id: number; project_id: string }
        }
        responses: { 200: Schemas.FeatureFlagRoleAccess }
    }
    export type delete_Feature_flags_role_access_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { feature_flag_id: number; id: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Feature_flags_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.FeatureFlag }
    }
    export type put_Feature_flags_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/feature_flags/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.FeatureFlag
        }
        responses: { 200: Schemas.FeatureFlag }
    }
    export type patch_Feature_flags_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/feature_flags/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedFeatureFlag
        }
        responses: { 200: Schemas.FeatureFlag }
    }
    export type delete_Feature_flags_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/feature_flags/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Feature_flags_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Feature_flags_create_static_cohort_for_flag_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/feature_flags/{id}/create_static_cohort_for_flag/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.FeatureFlag
        }
        responses: { 200: unknown }
    }
    export type post_Feature_flags_dashboard_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/feature_flags/{id}/dashboard/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.FeatureFlag
        }
        responses: { 200: unknown }
    }
    export type post_Feature_flags_enrich_usage_dashboard_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/feature_flags/{id}/enrich_usage_dashboard/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.FeatureFlag
        }
        responses: { 200: unknown }
    }
    export type get_Feature_flags_remote_config_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/{id}/remote_config/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Feature_flags_status_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/{id}/status/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Feature_flags_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/activity/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Feature_flags_bulk_keys_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/feature_flags/bulk_keys/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FeatureFlag
        }
        responses: { 200: unknown }
    }
    export type get_Feature_flags_evaluation_reasons_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/evaluation_reasons/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Feature_flags_local_evaluation_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/local_evaluation/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Feature_flags_my_flags_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/feature_flags/my_flags/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Feature_flags_user_blast_radius_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/feature_flags/user_blast_radius/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FeatureFlag
        }
        responses: { 200: unknown }
    }
    export type get_File_system_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/file_system/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedFileSystemList }
    }
    export type post_File_system_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/file_system/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 201: Schemas.FileSystem }
    }
    export type get_File_system_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.FileSystem }
    }
    export type put_File_system_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: Schemas.FileSystem }
    }
    export type patch_File_system_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedFileSystem
        }
        responses: { 200: Schemas.FileSystem }
    }
    export type delete_File_system_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/file_system/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_File_system_count_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/file_system/{id}/count/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type post_File_system_link_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/file_system/{id}/link/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type post_File_system_move_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/file_system/{id}/move/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type post_File_system_count_by_path_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/file_system/count_by_path/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FileSystem
        }
        responses: { 200: unknown }
    }
    export type get_File_system_unfiled_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/file_system/unfiled/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_File_system_shortcut_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/file_system_shortcut/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedFileSystemShortcutList }
    }
    export type post_File_system_shortcut_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/file_system_shortcut/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.FileSystemShortcut
        }
        responses: { 201: Schemas.FileSystemShortcut }
    }
    export type get_File_system_shortcut_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.FileSystemShortcut }
    }
    export type put_File_system_shortcut_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.FileSystemShortcut
        }
        responses: { 200: Schemas.FileSystemShortcut }
    }
    export type patch_File_system_shortcut_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedFileSystemShortcut
        }
        responses: { 200: Schemas.FileSystemShortcut }
    }
    export type delete_File_system_shortcut_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/file_system_shortcut/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Flag_value_values_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/flag_value/values/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Groups_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups/'
        requestFormat: 'json'
        parameters: {
            query: { cursor?: string | undefined; group_type_index: number; search: string }
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedGroupList }
    }
    export type post_Groups_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/groups/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.CreateGroup
        }
        responses: { 201: Schemas.Group }
    }
    export type get_Groups_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups/activity/'
        requestFormat: 'json'
        parameters: {
            query: { group_type_index: number; id: string }
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Groups_delete_property_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/groups/delete_property/'
        requestFormat: 'json'
        parameters: {
            query: { group_key: string; group_type_index: number }
            path: { project_id: string }

            body: Schemas.Group
        }
        responses: { 200: unknown }
    }
    export type get_Groups_find_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups/find/'
        requestFormat: 'json'
        parameters: {
            query: { group_key: string; group_type_index: number }
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Groups_property_definitions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups/property_definitions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Groups_property_values_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups/property_values/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Groups_related_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups/related/'
        requestFormat: 'json'
        parameters: {
            query: { group_type_index: number; id: string }
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Groups_update_property_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/groups/update_property/'
        requestFormat: 'json'
        parameters: {
            query: { group_key: string; group_type_index: number }
            path: { project_id: string }

            body: Schemas.Group
        }
        responses: { 200: unknown }
    }
    export type get_Groups_types_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups_types/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: Array<Schemas.GroupType> }
    }
    export type delete_Groups_types_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/groups_types/{group_type_index}/'
        requestFormat: 'json'
        parameters: {
            path: { group_type_index: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Groups_types_metrics_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { group_type_index: number; project_id: string }
        }
        responses: { 200: Schemas.PaginatedGroupUsageMetricList }
    }
    export type post_Groups_types_metrics_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/'
        requestFormat: 'json'
        parameters: {
            path: { group_type_index: number; project_id: string }

            body: Schemas.GroupUsageMetric
        }
        responses: { 201: Schemas.GroupUsageMetric }
    }
    export type get_Groups_types_metrics_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { group_type_index: number; id: string; project_id: string }
        }
        responses: { 200: Schemas.GroupUsageMetric }
    }
    export type put_Groups_types_metrics_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { group_type_index: number; id: string; project_id: string }

            body: Schemas.GroupUsageMetric
        }
        responses: { 200: Schemas.GroupUsageMetric }
    }
    export type patch_Groups_types_metrics_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { group_type_index: number; id: string; project_id: string }

            body: Schemas.PatchedGroupUsageMetric
        }
        responses: { 200: Schemas.GroupUsageMetric }
    }
    export type delete_Groups_types_metrics_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { group_type_index: number; id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type put_Groups_types_create_detail_dashboard_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/groups_types/create_detail_dashboard/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.GroupType
        }
        responses: { 200: unknown }
    }
    export type put_Groups_types_set_default_columns_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/groups_types/set_default_columns/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.GroupType
        }
        responses: { 200: unknown }
    }
    export type patch_Groups_types_update_metadata_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/groups_types/update_metadata/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PatchedGroupType
        }
        responses: { 200: unknown }
    }
    export type get_Hog_functions_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/hog_functions/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                created_at: string
                created_by: number
                enabled: boolean
                id: string
                limit: number
                offset: number
                search: string
                type: Array<string>
                updated_at: string
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedHogFunctionMinimalList }
    }
    export type post_Hog_functions_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/hog_functions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 201: Schemas.HogFunction }
    }
    export type get_Hog_functions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.HogFunction }
    }
    export type put_Hog_functions_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 200: Schemas.HogFunction }
    }
    export type patch_Hog_functions_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedHogFunction
        }
        responses: { 200: Schemas.HogFunction }
    }
    export type delete_Hog_functions_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/hog_functions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type post_Hog_functions_broadcast_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/hog_functions/{id}/broadcast/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 200: unknown }
    }
    export type post_Hog_functions_invocations_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/hog_functions/{id}/invocations/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.HogFunction
        }
        responses: { 200: unknown }
    }
    export type get_Hog_functions_logs_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/hog_functions/{id}/logs/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Hog_functions_metrics_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/hog_functions/{id}/metrics/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Hog_functions_metrics_totals_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/hog_functions/{id}/metrics/totals/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Hog_functions_icon_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/hog_functions/icon/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Hog_functions_icons_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/hog_functions/icons/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type patch_Hog_functions_rearrange_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/hog_functions/rearrange/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PatchedHogFunction
        }
        responses: { 200: unknown }
    }
    export type get_Insights_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/insights/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                basic: boolean
                created_by: number
                format: 'csv' | 'json'
                limit: number
                offset: number
                refresh:
                    | 'async'
                    | 'async_except_on_cache_miss'
                    | 'blocking'
                    | 'force_async'
                    | 'force_blocking'
                    | 'force_cache'
                    | 'lazy_async'
                short_id: string
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedInsightList }
    }
    export type post_Insights_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/insights/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Insight
        }
        responses: { 201: Schemas.Insight }
    }
    export type get_Insights_sharing_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/insights/{insight_id}/sharing/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; project_id: string }
        }
        responses: { 200: Array<Schemas.SharingConfiguration> }
    }
    export type post_Insights_sharing_passwords_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type delete_Insights_sharing_passwords_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; password_id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Insights_sharing_refresh_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/insights/{insight_id}/sharing/refresh/'
        requestFormat: 'json'
        parameters: {
            path: { insight_id: number; project_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type get_Insights_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                format: 'csv' | 'json'
                from_dashboard: number
                refresh:
                    | 'async'
                    | 'async_except_on_cache_miss'
                    | 'blocking'
                    | 'force_async'
                    | 'force_blocking'
                    | 'force_cache'
                    | 'lazy_async'
            }>
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Insight }
    }
    export type put_Insights_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Insight
        }
        responses: { 200: Schemas.Insight }
    }
    export type patch_Insights_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedInsight
        }
        responses: { 200: Schemas.Insight }
    }
    export type delete_Insights_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/insights/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Insights_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/insights/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Insights_viewed_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/insights/{id}/viewed/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Insight
        }
        responses: { 200: unknown }
    }
    export type get_Insights_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/insights/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Insights_cancel_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/insights/cancel/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Insight
        }
        responses: { 200: unknown }
    }
    export type get_Insights_my_last_viewed_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/insights/my_last_viewed/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Logs_attributes_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/logs/attributes/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Logs_query_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/logs/query/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Logs_sparkline_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/logs/sparkline/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Logs_values_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/logs/values/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Notebooks_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/notebooks/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                contains: string
                created_by: number
                date_from: string
                date_to: string
                limit: number
                offset: number
                user: string
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedNotebookMinimalList }
    }
    export type post_Notebooks_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/notebooks/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Notebook
        }
        responses: { 201: Schemas.Notebook }
    }
    export type get_Notebooks_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/notebooks/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 200: Schemas.Notebook }
    }
    export type put_Notebooks_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/notebooks/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }

            body: Schemas.Notebook
        }
        responses: { 200: Schemas.Notebook }
    }
    export type patch_Notebooks_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/notebooks/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }

            body: Schemas.PatchedNotebook
        }
        responses: { 200: Schemas.Notebook }
    }
    export type delete_Notebooks_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/notebooks/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Notebooks_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/notebooks/{short_id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Notebooks_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/notebooks/activity/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Notebooks_recording_comments_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/notebooks/recording_comments/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Persisted_folder_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/persisted_folder/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedPersistedFolderList }
    }
    export type post_Persisted_folder_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persisted_folder/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.PersistedFolder
        }
        responses: { 201: Schemas.PersistedFolder }
    }
    export type get_Persisted_folder_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.PersistedFolder }
    }
    export type put_Persisted_folder_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PersistedFolder
        }
        responses: { 200: Schemas.PersistedFolder }
    }
    export type patch_Persisted_folder_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedPersistedFolder
        }
        responses: { 200: Schemas.PersistedFolder }
    }
    export type delete_Persisted_folder_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/persisted_folder/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Persons_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                distinct_id: string
                email: string
                format: 'csv' | 'json'
                limit: number
                offset: number
                properties: Array<Schemas.Property>
                search: string
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedPersonList }
    }
    export type get_Persons_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Person }
    }
    export type put_Persons_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: Schemas.Person }
    }
    export type patch_Persons_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.PatchedPerson
        }
        responses: { 200: Schemas.Person }
    }
    export type delete_Persons_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/persons/{id}/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ delete_events: boolean; format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Persons_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Persons_delete_events_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/{id}/delete_events/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type post_Persons_delete_property_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/{id}/delete_property/'
        requestFormat: 'json'
        parameters: {
            query: { $unset: string; format?: ('csv' | 'json') | undefined }
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Persons_properties_timeline_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/{id}/properties_timeline/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Persons_split_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/{id}/split/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type post_Persons_update_property_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/{id}/update_property/'
        requestFormat: 'json'
        parameters: {
            query: { format?: ('csv' | 'json') | undefined; key: string; value: unknown }
            path: { id: number; project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Persons_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/activity/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Persons_bulk_delete_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/bulk_delete/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                delete_events: boolean
                distinct_ids: Record<string, unknown>
                format: 'csv' | 'json'
                ids: Record<string, unknown>
            }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Persons_cohorts_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/cohorts/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Persons_funnel_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/funnel/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Persons_funnel_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/funnel/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Persons_funnel_correlation_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/funnel/correlation/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Persons_funnel_correlation_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/funnel/correlation/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Persons_lifecycle_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/lifecycle/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Persons_reset_person_distinct_id_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/persons/reset_person_distinct_id/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }

            body: Schemas.Person
        }
        responses: { 200: unknown }
    }
    export type get_Persons_stickiness_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/stickiness/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Persons_trends_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/trends/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Persons_values_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/persons/values/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ format: 'csv' | 'json' }>
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Plugin_configs_logs_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/plugin_configs/{plugin_config_id}/logs/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { plugin_config_id: string; project_id: string }
        }
        responses: { 200: Schemas.PaginatedPluginLogEntryList }
    }
    export type get_Property_definitions_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/property_definitions/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{
                event_names: string
                exclude_core_properties: boolean
                exclude_hidden: boolean
                excluded_properties: string
                filter_by_event_names: boolean | null
                group_type_index: number
                is_feature_flag: boolean | null
                is_numerical: boolean | null
                limit: number
                offset: number
                properties: string
                search: string
                type: 'event' | 'person' | 'group' | 'session'
            }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedPropertyDefinitionList }
    }
    export type get_Property_definitions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/property_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.PropertyDefinition }
    }
    export type put_Property_definitions_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/property_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PropertyDefinition
        }
        responses: { 200: Schemas.PropertyDefinition }
    }
    export type patch_Property_definitions_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/property_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedPropertyDefinition
        }
        responses: { 200: Schemas.PropertyDefinition }
    }
    export type delete_Property_definitions_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/property_definitions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Property_definitions_seen_together_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/property_definitions/seen_together/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Query_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/query/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.QueryRequest
        }
        responses: { 200: Schemas.QueryResponseAlternative }
    }
    export type get_Query_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/query/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.QueryStatusResponse }
    }
    export type delete_Query_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/query/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Query_log_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/query/{id}/log/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Record<string, unknown> }
    }
    export type post_Query_check_auth_for_async_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/query/check_auth_for_async/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Query_draft_sql_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/query/draft_sql/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Query_upgrade_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/query/upgrade/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.QueryUpgradeRequest
        }
        responses: { 200: Schemas.QueryUpgradeResponse }
    }
    export type get_Session_recording_playlists_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/session_recording_playlists/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ created_by: number; limit: number; offset: number; short_id: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedSessionRecordingPlaylistList }
    }
    export type post_Session_recording_playlists_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/session_recording_playlists/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.SessionRecordingPlaylist
        }
        responses: { 201: Schemas.SessionRecordingPlaylist }
    }
    export type get_Session_recording_playlists_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 200: Schemas.SessionRecordingPlaylist }
    }
    export type put_Session_recording_playlists_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }

            body: Schemas.SessionRecordingPlaylist
        }
        responses: { 200: Schemas.SessionRecordingPlaylist }
    }
    export type patch_Session_recording_playlists_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }

            body: Schemas.PatchedSessionRecordingPlaylist
        }
        responses: { 200: Schemas.SessionRecordingPlaylist }
    }
    export type delete_Session_recording_playlists_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/session_recording_playlists/{short_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Session_recording_playlists_recordings_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; short_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Session_recording_playlists_recordings_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; session_recording_id: string; short_id: string }

            body: Schemas.SessionRecordingPlaylist
        }
        responses: { 200: unknown }
    }
    export type delete_Session_recording_playlists_recordings_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; session_recording_id: string; short_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Session_recordings_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/session_recordings/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedSessionRecordingList }
    }
    export type get_Session_recordings_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.SessionRecording }
    }
    export type put_Session_recordings_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.SessionRecording
        }
        responses: { 200: Schemas.SessionRecording }
    }
    export type patch_Session_recordings_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedSessionRecording
        }
        responses: { 200: Schemas.SessionRecording }
    }
    export type delete_Session_recordings_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/session_recordings/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Session_recordings_sharing_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; recording_id: string }
        }
        responses: { 200: Array<Schemas.SharingConfiguration> }
    }
    export type post_Session_recordings_sharing_passwords_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; recording_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type delete_Session_recordings_sharing_passwords_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/'
        requestFormat: 'json'
        parameters: {
            path: { password_id: string; project_id: string; recording_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Session_recordings_sharing_refresh_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/refresh/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string; recording_id: string }

            body: Schemas.SharingConfiguration
        }
        responses: { 200: Schemas.SharingConfiguration }
    }
    export type get_Sessions_property_definitions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/sessions/property_definitions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Sessions_values_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/sessions/values/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Subscriptions_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/subscriptions/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedSubscriptionList }
    }
    export type post_Subscriptions_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/subscriptions/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Subscription
        }
        responses: { 201: Schemas.Subscription }
    }
    export type get_Subscriptions_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.Subscription }
    }
    export type put_Subscriptions_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.Subscription
        }
        responses: { 200: Schemas.Subscription }
    }
    export type patch_Subscriptions_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedSubscription
        }
        responses: { 200: Schemas.Subscription }
    }
    export type delete_Subscriptions_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/subscriptions/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 405: unknown }
    }
    export type get_Surveys_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/surveys/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedSurveyList }
    }
    export type post_Surveys_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/surveys/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.SurveySerializerCreateUpdateOnly
        }
        responses: { 201: Schemas.SurveySerializerCreateUpdateOnly }
    }
    export type get_Surveys_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/surveys/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.Survey }
    }
    export type put_Surveys_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/surveys/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.Survey
        }
        responses: { 200: Schemas.Survey }
    }
    export type patch_Surveys_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/surveys/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedSurveySerializerCreateUpdateOnly
        }
        responses: { 200: Schemas.SurveySerializerCreateUpdateOnly }
    }
    export type delete_Surveys_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/surveys/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Surveys_activity_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/surveys/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Surveys_stats_retrieve_2 = {
        method: 'GET'
        path: '/api/projects/{project_id}/surveys/{id}/stats/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: unknown }
    }
    export type post_Surveys_summarize_responses_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/surveys/{id}/summarize_responses/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.SurveySerializerCreateUpdateOnly
        }
        responses: { 200: unknown }
    }
    export type get_Surveys_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/surveys/activity/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Surveys_responses_count_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/surveys/responses_count/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Surveys_stats_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/surveys/stats/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }
        }
        responses: { 200: unknown }
    }
    export type get_Warehouse_saved_queries_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/warehouse_saved_queries/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ page: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedDataWarehouseSavedQueryList }
    }
    export type post_Warehouse_saved_queries_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_saved_queries/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 201: Schemas.DataWarehouseSavedQuery }
    }
    export type get_Warehouse_saved_queries_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type put_Warehouse_saved_queries_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type patch_Warehouse_saved_queries_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedDataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type delete_Warehouse_saved_queries_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Warehouse_saved_queries_activity_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/activity/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Warehouse_saved_queries_ancestors_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/ancestors/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Warehouse_saved_queries_cancel_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/cancel/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Warehouse_saved_queries_descendants_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/descendants/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Warehouse_saved_queries_revert_materialization_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/revert_materialization/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type post_Warehouse_saved_queries_run_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_saved_queries/{id}/run/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.DataWarehouseSavedQuery
        }
        responses: { 200: Schemas.DataWarehouseSavedQuery }
    }
    export type get_Warehouse_tables_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/warehouse_tables/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number; search: string }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedTableList }
    }
    export type post_Warehouse_tables_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_tables/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.Table
        }
        responses: { 201: Schemas.Table }
    }
    export type get_Warehouse_tables_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 200: Schemas.Table }
    }
    export type put_Warehouse_tables_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.Table
        }
        responses: { 200: Schemas.Table }
    }
    export type patch_Warehouse_tables_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.PatchedTable
        }
        responses: { 200: Schemas.Table }
    }
    export type delete_Warehouse_tables_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/warehouse_tables/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type post_Warehouse_tables_refresh_schema_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_tables/{id}/refresh_schema/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.Table
        }
        responses: { 200: unknown }
    }
    export type post_Warehouse_tables_update_schema_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_tables/{id}/update_schema/'
        requestFormat: 'json'
        parameters: {
            path: { id: string; project_id: string }

            body: Schemas.Table
        }
        responses: { 200: unknown }
    }
    export type post_Warehouse_tables_file_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/warehouse_tables/file/'
        requestFormat: 'form-data'
        parameters: {
            path: { project_id: string }

            body: Schemas.Table
        }
        responses: { 200: unknown }
    }
    export type get_Web_analytics_breakdown_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/web_analytics/breakdown/'
        requestFormat: 'json'
        parameters: {
            query: {
                apply_path_cleaning?: boolean | undefined
                breakdown_by:
                    | 'DeviceType'
                    | 'Browser'
                    | 'OS'
                    | 'Viewport'
                    | 'InitialReferringDomain'
                    | 'InitialUTMSource'
                    | 'InitialUTMMedium'
                    | 'InitialUTMCampaign'
                    | 'InitialUTMTerm'
                    | 'InitialUTMContent'
                    | 'Country'
                    | 'Region'
                    | 'City'
                    | 'InitialPage'
                    | 'Page'
                    | 'ExitPage'
                    | 'InitialChannelType'
                date_from: string
                date_to: string
                filter_test_accounts?: boolean | undefined
                host?: (string | null) | undefined
                limit?: number | undefined
                offset?: number | undefined
            }
            path: { project_id: string }
        }
        responses: { 200: Schemas.WebAnalyticsBreakdownResponse }
    }
    export type get_Web_analytics_overview_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/web_analytics/overview/'
        requestFormat: 'json'
        parameters: {
            query: {
                date_from: string
                date_to: string
                filter_test_accounts?: boolean | undefined
                host?: (string | null) | undefined
            }
            path: { project_id: string }
        }
        responses: { 200: Schemas.WebAnalyticsOverviewResponse }
    }
    export type get_Web_experiments_list = {
        method: 'GET'
        path: '/api/projects/{project_id}/web_experiments/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ limit: number; offset: number }>
            path: { project_id: string }
        }
        responses: { 200: Schemas.PaginatedWebExperimentsAPIList }
    }
    export type post_Web_experiments_create = {
        method: 'POST'
        path: '/api/projects/{project_id}/web_experiments/'
        requestFormat: 'json'
        parameters: {
            path: { project_id: string }

            body: Schemas.WebExperimentsAPI
        }
        responses: { 201: Schemas.WebExperimentsAPI }
    }
    export type get_Web_experiments_retrieve = {
        method: 'GET'
        path: '/api/projects/{project_id}/web_experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 200: Schemas.WebExperimentsAPI }
    }
    export type put_Web_experiments_update = {
        method: 'PUT'
        path: '/api/projects/{project_id}/web_experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.WebExperimentsAPI
        }
        responses: { 200: Schemas.WebExperimentsAPI }
    }
    export type patch_Web_experiments_partial_update = {
        method: 'PATCH'
        path: '/api/projects/{project_id}/web_experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }

            body: Schemas.PatchedWebExperimentsAPI
        }
        responses: { 200: Schemas.WebExperimentsAPI }
    }
    export type delete_Web_experiments_destroy = {
        method: 'DELETE'
        path: '/api/projects/{project_id}/web_experiments/{id}/'
        requestFormat: 'json'
        parameters: {
            path: { id: number; project_id: string }
        }
        responses: { 204: unknown }
    }
    export type get_Users_list = {
        method: 'GET'
        path: '/api/users/'
        requestFormat: 'json'
        parameters: {
            query: Partial<{ email: string; is_staff: boolean; limit: number; offset: number }>
        }
        responses: { 200: Schemas.PaginatedUserList }
    }
    export type get_Users_retrieve = {
        method: 'GET'
        path: '/api/users/{uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }
        }
        responses: { 200: Schemas.User }
    }
    export type put_Users_update = {
        method: 'PUT'
        path: '/api/users/{uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.User
        }
        responses: { 200: Schemas.User }
    }
    export type patch_Users_partial_update = {
        method: 'PATCH'
        path: '/api/users/{uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.PatchedUser
        }
        responses: { 200: Schemas.User }
    }
    export type delete_Users_destroy = {
        method: 'DELETE'
        path: '/api/users/{uuid}/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }
        }
        responses: { 204: unknown }
    }
    export type get_Users_hedgehog_config_retrieve = {
        method: 'GET'
        path: '/api/users/{uuid}/hedgehog_config/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }
        }
        responses: { 200: unknown }
    }
    export type patch_Users_hedgehog_config_partial_update = {
        method: 'PATCH'
        path: '/api/users/{uuid}/hedgehog_config/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.PatchedUser
        }
        responses: { 200: unknown }
    }
    export type post_Users_scene_personalisation_create = {
        method: 'POST'
        path: '/api/users/{uuid}/scene_personalisation/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.User
        }
        responses: { 200: unknown }
    }
    export type get_Users_start_2fa_setup_retrieve = {
        method: 'GET'
        path: '/api/users/{uuid}/start_2fa_setup/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }
        }
        responses: { 200: unknown }
    }
    export type post_Users_two_factor_backup_codes_create = {
        method: 'POST'
        path: '/api/users/{uuid}/two_factor_backup_codes/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.User
        }
        responses: { 200: unknown }
    }
    export type post_Users_two_factor_disable_create = {
        method: 'POST'
        path: '/api/users/{uuid}/two_factor_disable/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.User
        }
        responses: { 200: unknown }
    }
    export type get_Users_two_factor_start_setup_retrieve = {
        method: 'GET'
        path: '/api/users/{uuid}/two_factor_start_setup/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }
        }
        responses: { 200: unknown }
    }
    export type get_Users_two_factor_status_retrieve = {
        method: 'GET'
        path: '/api/users/{uuid}/two_factor_status/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }
        }
        responses: { 200: unknown }
    }
    export type post_Users_two_factor_validate_create = {
        method: 'POST'
        path: '/api/users/{uuid}/two_factor_validate/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.User
        }
        responses: { 200: unknown }
    }
    export type post_Users_validate_2fa_create = {
        method: 'POST'
        path: '/api/users/{uuid}/validate_2fa/'
        requestFormat: 'json'
        parameters: {
            path: { uuid: string }

            body: Schemas.User
        }
        responses: { 200: unknown }
    }
    export type patch_Users_cancel_email_change_request_partial_update = {
        method: 'PATCH'
        path: '/api/users/cancel_email_change_request/'
        requestFormat: 'json'
        parameters: {
            body: Schemas.PatchedUser
        }
        responses: { 200: unknown }
    }
    export type post_Users_request_email_verification_create = {
        method: 'POST'
        path: '/api/users/request_email_verification/'
        requestFormat: 'json'
        parameters: {
            body: Schemas.User
        }
        responses: { 200: unknown }
    }
    export type post_Users_verify_email_create = {
        method: 'POST'
        path: '/api/users/verify_email/'
        requestFormat: 'json'
        parameters: {
            body: Schemas.User
        }
        responses: { 200: unknown }
    }

    // </Endpoints>
}

// <EndpointByMethod>
export type EndpointByMethod = {
    get: {
        '/api/environments/{project_id}/app_metrics/{id}/': Endpoints.get_Environments_app_metrics_retrieve
        '/api/environments/{project_id}/app_metrics/{id}/error_details/': Endpoints.get_Environments_app_metrics_error_details_retrieve
        '/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/': Endpoints.get_Environments_app_metrics_historical_exports_retrieve
        '/api/environments/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/': Endpoints.get_Environments_app_metrics_historical_exports_retrieve_2
        '/api/environments/{project_id}/batch_exports/': Endpoints.get_Environments_batch_exports_list
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/': Endpoints.get_Environments_batch_exports_backfills_list
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/': Endpoints.get_Environments_batch_exports_backfills_retrieve
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/': Endpoints.get_Environments_batch_exports_runs_list
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/': Endpoints.get_Environments_batch_exports_runs_retrieve
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/': Endpoints.get_Environments_batch_exports_runs_logs_retrieve
        '/api/environments/{project_id}/batch_exports/{id}/': Endpoints.get_Environments_batch_exports_retrieve
        '/api/environments/{project_id}/batch_exports/{id}/logs/': Endpoints.get_Environments_batch_exports_logs_retrieve
        '/api/environments/{project_id}/batch_exports/test/': Endpoints.get_Environments_batch_exports_test_retrieve
        '/api/environments/{project_id}/dashboards/': Endpoints.get_Environments_dashboards_list
        '/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/': Endpoints.get_Environments_dashboards_collaborators_list
        '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/': Endpoints.get_Environments_dashboards_sharing_list
        '/api/environments/{project_id}/dashboards/{id}/': Endpoints.get_Environments_dashboards_retrieve
        '/api/environments/{project_id}/dashboards/{id}/stream_tiles/': Endpoints.get_Environments_dashboards_stream_tiles_retrieve
        '/api/environments/{project_id}/error_tracking/assignment_rules/': Endpoints.get_Environments_error_tracking_assignment_rules_list
        '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/': Endpoints.get_Environments_error_tracking_assignment_rules_retrieve
        '/api/environments/{project_id}/error_tracking/grouping_rules/': Endpoints.get_Environments_error_tracking_grouping_rules_list
        '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/': Endpoints.get_Environments_error_tracking_grouping_rules_retrieve
        '/api/environments/{project_id}/error_tracking/releases/': Endpoints.get_Environments_error_tracking_releases_list
        '/api/environments/{project_id}/error_tracking/releases/{id}/': Endpoints.get_Environments_error_tracking_releases_retrieve
        '/api/environments/{project_id}/error_tracking/suppression_rules/': Endpoints.get_Environments_error_tracking_suppression_rules_list
        '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/': Endpoints.get_Environments_error_tracking_suppression_rules_retrieve
        '/api/environments/{project_id}/error_tracking/symbol_sets/': Endpoints.get_Environments_error_tracking_symbol_sets_list
        '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/': Endpoints.get_Environments_error_tracking_symbol_sets_retrieve
        '/api/environments/{project_id}/events/': Endpoints.get_Environments_events_list
        '/api/environments/{project_id}/events/{id}/': Endpoints.get_Environments_events_retrieve
        '/api/environments/{project_id}/events/values/': Endpoints.get_Environments_events_values_retrieve
        '/api/environments/{project_id}/explicit_members/': Endpoints.get_Environments_explicit_members_list
        '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.get_Environments_explicit_members_retrieve
        '/api/environments/{project_id}/exports/': Endpoints.get_Environments_exports_list
        '/api/environments/{project_id}/exports/{id}/': Endpoints.get_Environments_exports_retrieve
        '/api/environments/{project_id}/exports/{id}/content/': Endpoints.get_Environments_exports_content_retrieve
        '/api/environments/{project_id}/file_system/': Endpoints.get_Environments_file_system_list
        '/api/environments/{project_id}/file_system/{id}/': Endpoints.get_Environments_file_system_retrieve
        '/api/environments/{project_id}/file_system/unfiled/': Endpoints.get_Environments_file_system_unfiled_retrieve
        '/api/environments/{project_id}/file_system_shortcut/': Endpoints.get_Environments_file_system_shortcut_list
        '/api/environments/{project_id}/file_system_shortcut/{id}/': Endpoints.get_Environments_file_system_shortcut_retrieve
        '/api/environments/{project_id}/groups/': Endpoints.get_Environments_groups_list
        '/api/environments/{project_id}/groups/activity/': Endpoints.get_Environments_groups_activity_retrieve
        '/api/environments/{project_id}/groups/find/': Endpoints.get_Environments_groups_find_retrieve
        '/api/environments/{project_id}/groups/property_definitions/': Endpoints.get_Environments_groups_property_definitions_retrieve
        '/api/environments/{project_id}/groups/property_values/': Endpoints.get_Environments_groups_property_values_retrieve
        '/api/environments/{project_id}/groups/related/': Endpoints.get_Environments_groups_related_retrieve
        '/api/environments/{project_id}/hog_functions/': Endpoints.get_Environments_hog_functions_list
        '/api/environments/{project_id}/hog_functions/{id}/': Endpoints.get_Environments_hog_functions_retrieve
        '/api/environments/{project_id}/hog_functions/{id}/logs/': Endpoints.get_Environments_hog_functions_logs_retrieve
        '/api/environments/{project_id}/hog_functions/{id}/metrics/': Endpoints.get_Environments_hog_functions_metrics_retrieve
        '/api/environments/{project_id}/hog_functions/{id}/metrics/totals/': Endpoints.get_Environments_hog_functions_metrics_totals_retrieve
        '/api/environments/{project_id}/hog_functions/icon/': Endpoints.get_Environments_hog_functions_icon_retrieve
        '/api/environments/{project_id}/hog_functions/icons/': Endpoints.get_Environments_hog_functions_icons_retrieve
        '/api/environments/{project_id}/insights/': Endpoints.get_Environments_insights_list
        '/api/environments/{project_id}/insights/{insight_id}/sharing/': Endpoints.get_Environments_insights_sharing_list
        '/api/environments/{project_id}/insights/{id}/': Endpoints.get_Environments_insights_retrieve
        '/api/environments/{project_id}/insights/{id}/activity/': Endpoints.get_Environments_insights_activity_retrieve_2
        '/api/environments/{project_id}/insights/activity/': Endpoints.get_Environments_insights_activity_retrieve
        '/api/environments/{project_id}/insights/my_last_viewed/': Endpoints.get_Environments_insights_my_last_viewed_retrieve
        '/api/environments/{project_id}/logs/attributes/': Endpoints.get_Environments_logs_attributes_retrieve
        '/api/environments/{project_id}/logs/values/': Endpoints.get_Environments_logs_values_retrieve
        '/api/environments/{project_id}/persisted_folder/': Endpoints.get_Environments_persisted_folder_list
        '/api/environments/{project_id}/persisted_folder/{id}/': Endpoints.get_Environments_persisted_folder_retrieve
        '/api/environments/{project_id}/persons/': Endpoints.get_Environments_persons_list
        '/api/environments/{project_id}/persons/{id}/': Endpoints.get_Environments_persons_retrieve
        '/api/environments/{project_id}/persons/{id}/activity/': Endpoints.get_Environments_persons_activity_retrieve_2
        '/api/environments/{project_id}/persons/{id}/properties_timeline/': Endpoints.get_Environments_persons_properties_timeline_retrieve
        '/api/environments/{project_id}/persons/activity/': Endpoints.get_Environments_persons_activity_retrieve
        '/api/environments/{project_id}/persons/cohorts/': Endpoints.get_Environments_persons_cohorts_retrieve
        '/api/environments/{project_id}/persons/funnel/': Endpoints.get_Environments_persons_funnel_retrieve
        '/api/environments/{project_id}/persons/funnel/correlation/': Endpoints.get_Environments_persons_funnel_correlation_retrieve
        '/api/environments/{project_id}/persons/lifecycle/': Endpoints.get_Environments_persons_lifecycle_retrieve
        '/api/environments/{project_id}/persons/stickiness/': Endpoints.get_Environments_persons_stickiness_retrieve
        '/api/environments/{project_id}/persons/trends/': Endpoints.get_Environments_persons_trends_retrieve
        '/api/environments/{project_id}/persons/values/': Endpoints.get_Environments_persons_values_retrieve
        '/api/environments/{project_id}/plugin_configs/{plugin_config_id}/logs/': Endpoints.get_Environments_plugin_configs_logs_list
        '/api/environments/{project_id}/query/{id}/': Endpoints.get_Environments_query_retrieve
        '/api/environments/{project_id}/query/{id}/log/': Endpoints.get_Environments_query_log_retrieve
        '/api/environments/{project_id}/query/draft_sql/': Endpoints.get_Environments_query_draft_sql_retrieve
        '/api/environments/{project_id}/session_recording_playlists/': Endpoints.get_Environments_session_recording_playlists_list
        '/api/environments/{project_id}/session_recording_playlists/{short_id}/': Endpoints.get_Environments_session_recording_playlists_retrieve
        '/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/': Endpoints.get_Environments_session_recording_playlists_recordings_retrieve
        '/api/environments/{project_id}/session_recordings/': Endpoints.get_Environments_session_recordings_list
        '/api/environments/{project_id}/session_recordings/{id}/': Endpoints.get_Environments_session_recordings_retrieve
        '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/': Endpoints.get_Environments_session_recordings_sharing_list
        '/api/environments/{project_id}/sessions/property_definitions/': Endpoints.get_Environments_sessions_property_definitions_retrieve
        '/api/environments/{project_id}/sessions/values/': Endpoints.get_Environments_sessions_values_retrieve
        '/api/environments/{project_id}/subscriptions/': Endpoints.get_Environments_subscriptions_list
        '/api/environments/{project_id}/subscriptions/{id}/': Endpoints.get_Environments_subscriptions_retrieve
        '/api/environments/{project_id}/user_interviews/': Endpoints.get_Environments_user_interviews_list
        '/api/environments/{project_id}/user_interviews/{id}/': Endpoints.get_Environments_user_interviews_retrieve
        '/api/environments/{project_id}/warehouse_saved_queries/': Endpoints.get_Environments_warehouse_saved_queries_list
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/': Endpoints.get_Environments_warehouse_saved_queries_retrieve
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/activity/': Endpoints.get_Environments_warehouse_saved_queries_activity_retrieve
        '/api/environments/{project_id}/warehouse_tables/': Endpoints.get_Environments_warehouse_tables_list
        '/api/environments/{project_id}/warehouse_tables/{id}/': Endpoints.get_Environments_warehouse_tables_retrieve
        '/api/environments/{project_id}/web_vitals/': Endpoints.get_Environments_web_vitals_retrieve
        '/api/organizations/': Endpoints.get_List
        '/api/organizations/{id}/': Endpoints.get_Retrieve
        '/api/organizations/{organization_id}/batch_exports/': Endpoints.get_Batch_exports_list
        '/api/organizations/{organization_id}/batch_exports/{id}/': Endpoints.get_Batch_exports_retrieve
        '/api/organizations/{organization_id}/batch_exports/{id}/logs/': Endpoints.get_Batch_exports_logs_retrieve
        '/api/organizations/{organization_id}/batch_exports/test/': Endpoints.get_Batch_exports_test_retrieve
        '/api/organizations/{organization_id}/domains/': Endpoints.get_Domains_list
        '/api/organizations/{organization_id}/domains/{id}/': Endpoints.get_Domains_retrieve
        '/api/organizations/{organization_id}/invites/': Endpoints.get_Invites_list
        '/api/organizations/{organization_id}/members/': Endpoints.get_Members_list
        '/api/organizations/{organization_id}/members/{user__uuid}/scoped_api_keys/': Endpoints.get_Members_scoped_api_keys_retrieve
        '/api/organizations/{organization_id}/projects/': Endpoints.get_List_2
        '/api/organizations/{organization_id}/projects/{id}/': Endpoints.get_Retrieve_2
        '/api/organizations/{organization_id}/projects/{id}/activity/': Endpoints.get_Activity_retrieve
        '/api/organizations/{organization_id}/projects/{id}/is_generating_demo_data/': Endpoints.get_Is_generating_demo_data_retrieve
        '/api/organizations/{organization_id}/proxy_records/': Endpoints.get_Proxy_records_list
        '/api/organizations/{organization_id}/proxy_records/{id}/': Endpoints.get_Proxy_records_retrieve
        '/api/organizations/{organization_id}/roles/': Endpoints.get_Roles_list
        '/api/organizations/{organization_id}/roles/{id}/': Endpoints.get_Roles_retrieve
        '/api/organizations/{organization_id}/roles/{role_id}/role_memberships/': Endpoints.get_Roles_role_memberships_list
        '/api/projects/{project_id}/actions/': Endpoints.get_Actions_list
        '/api/projects/{project_id}/actions/{id}/': Endpoints.get_Actions_retrieve
        '/api/projects/{project_id}/activity_log/': Endpoints.get_Activity_log_list
        '/api/projects/{project_id}/annotations/': Endpoints.get_Annotations_list
        '/api/projects/{project_id}/annotations/{id}/': Endpoints.get_Annotations_retrieve
        '/api/projects/{project_id}/app_metrics/{id}/': Endpoints.get_App_metrics_retrieve
        '/api/projects/{project_id}/app_metrics/{id}/error_details/': Endpoints.get_App_metrics_error_details_retrieve
        '/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/': Endpoints.get_App_metrics_historical_exports_retrieve
        '/api/projects/{project_id}/app_metrics/{plugin_config_id}/historical_exports/{id}/': Endpoints.get_App_metrics_historical_exports_retrieve_2
        '/api/projects/{project_id}/batch_exports/': Endpoints.get_Batch_exports_list_2
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/': Endpoints.get_Batch_exports_backfills_list
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/': Endpoints.get_Batch_exports_backfills_retrieve
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/': Endpoints.get_Batch_exports_runs_list
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/': Endpoints.get_Batch_exports_runs_retrieve
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/logs/': Endpoints.get_Batch_exports_runs_logs_retrieve
        '/api/projects/{project_id}/batch_exports/{id}/': Endpoints.get_Batch_exports_retrieve_2
        '/api/projects/{project_id}/batch_exports/{id}/logs/': Endpoints.get_Batch_exports_logs_retrieve_2
        '/api/projects/{project_id}/batch_exports/test/': Endpoints.get_Batch_exports_test_retrieve_2
        '/api/projects/{project_id}/cohorts/': Endpoints.get_Cohorts_list
        '/api/projects/{project_id}/cohorts/{id}/': Endpoints.get_Cohorts_retrieve
        '/api/projects/{project_id}/cohorts/{id}/activity/': Endpoints.get_Cohorts_activity_retrieve_2
        '/api/projects/{project_id}/cohorts/{id}/duplicate_as_static_cohort/': Endpoints.get_Cohorts_duplicate_as_static_cohort_retrieve
        '/api/projects/{project_id}/cohorts/{id}/persons/': Endpoints.get_Cohorts_persons_retrieve
        '/api/projects/{project_id}/cohorts/activity/': Endpoints.get_Cohorts_activity_retrieve
        '/api/projects/{project_id}/dashboard_templates/': Endpoints.get_Dashboard_templates_list
        '/api/projects/{project_id}/dashboard_templates/{id}/': Endpoints.get_Dashboard_templates_retrieve
        '/api/projects/{project_id}/dashboard_templates/json_schema/': Endpoints.get_Dashboard_templates_json_schema_retrieve
        '/api/projects/{project_id}/dashboards/': Endpoints.get_Dashboards_list
        '/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/': Endpoints.get_Dashboards_collaborators_list
        '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/': Endpoints.get_Dashboards_sharing_list
        '/api/projects/{project_id}/dashboards/{id}/': Endpoints.get_Dashboards_retrieve
        '/api/projects/{project_id}/dashboards/{id}/stream_tiles/': Endpoints.get_Dashboards_stream_tiles_retrieve
        '/api/projects/{project_id}/early_access_feature/': Endpoints.get_Early_access_feature_list
        '/api/projects/{project_id}/early_access_feature/{id}/': Endpoints.get_Early_access_feature_retrieve
        '/api/projects/{project_id}/environments/': Endpoints.get_Environments_list
        '/api/projects/{project_id}/environments/{id}/': Endpoints.get_Environments_retrieve
        '/api/projects/{project_id}/environments/{id}/activity/': Endpoints.get_Environments_activity_retrieve
        '/api/projects/{project_id}/environments/{id}/event_ingestion_restrictions/': Endpoints.get_Environments_event_ingestion_restrictions_retrieve
        '/api/projects/{project_id}/environments/{id}/is_generating_demo_data/': Endpoints.get_Environments_is_generating_demo_data_retrieve
        '/api/projects/{project_id}/event_definitions/': Endpoints.get_Event_definitions_retrieve
        '/api/projects/{project_id}/event_definitions/{id}/': Endpoints.get_Event_definitions_retrieve_2
        '/api/projects/{project_id}/event_definitions/{id}/metrics/': Endpoints.get_Event_definitions_metrics_retrieve
        '/api/projects/{project_id}/events/': Endpoints.get_Events_list
        '/api/projects/{project_id}/events/{id}/': Endpoints.get_Events_retrieve
        '/api/projects/{project_id}/events/values/': Endpoints.get_Events_values_retrieve
        '/api/projects/{project_id}/experiment_holdouts/': Endpoints.get_Experiment_holdouts_list
        '/api/projects/{project_id}/experiment_holdouts/{id}/': Endpoints.get_Experiment_holdouts_retrieve
        '/api/projects/{project_id}/experiment_saved_metrics/': Endpoints.get_Experiment_saved_metrics_list
        '/api/projects/{project_id}/experiment_saved_metrics/{id}/': Endpoints.get_Experiment_saved_metrics_retrieve
        '/api/projects/{project_id}/experiments/': Endpoints.get_Experiments_list
        '/api/projects/{project_id}/experiments/{id}/': Endpoints.get_Experiments_retrieve
        '/api/projects/{project_id}/experiments/requires_flag_implementation/': Endpoints.get_Experiments_requires_flag_implementation_retrieve
        '/api/projects/{project_id}/explicit_members/': Endpoints.get_Explicit_members_list
        '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.get_Explicit_members_retrieve
        '/api/projects/{project_id}/exports/': Endpoints.get_Exports_list
        '/api/projects/{project_id}/exports/{id}/': Endpoints.get_Exports_retrieve
        '/api/projects/{project_id}/exports/{id}/content/': Endpoints.get_Exports_content_retrieve
        '/api/projects/{project_id}/feature_flags/': Endpoints.get_Feature_flags_list
        '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/': Endpoints.get_Feature_flags_role_access_list
        '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/{id}/': Endpoints.get_Feature_flags_role_access_retrieve
        '/api/projects/{project_id}/feature_flags/{id}/': Endpoints.get_Feature_flags_retrieve
        '/api/projects/{project_id}/feature_flags/{id}/activity/': Endpoints.get_Feature_flags_activity_retrieve_2
        '/api/projects/{project_id}/feature_flags/{id}/remote_config/': Endpoints.get_Feature_flags_remote_config_retrieve
        '/api/projects/{project_id}/feature_flags/{id}/status/': Endpoints.get_Feature_flags_status_retrieve
        '/api/projects/{project_id}/feature_flags/activity/': Endpoints.get_Feature_flags_activity_retrieve
        '/api/projects/{project_id}/feature_flags/evaluation_reasons/': Endpoints.get_Feature_flags_evaluation_reasons_retrieve
        '/api/projects/{project_id}/feature_flags/local_evaluation/': Endpoints.get_Feature_flags_local_evaluation_retrieve
        '/api/projects/{project_id}/feature_flags/my_flags/': Endpoints.get_Feature_flags_my_flags_retrieve
        '/api/projects/{project_id}/file_system/': Endpoints.get_File_system_list
        '/api/projects/{project_id}/file_system/{id}/': Endpoints.get_File_system_retrieve
        '/api/projects/{project_id}/file_system/unfiled/': Endpoints.get_File_system_unfiled_retrieve
        '/api/projects/{project_id}/file_system_shortcut/': Endpoints.get_File_system_shortcut_list
        '/api/projects/{project_id}/file_system_shortcut/{id}/': Endpoints.get_File_system_shortcut_retrieve
        '/api/projects/{project_id}/flag_value/values/': Endpoints.get_Flag_value_values_retrieve
        '/api/projects/{project_id}/groups/': Endpoints.get_Groups_list
        '/api/projects/{project_id}/groups/activity/': Endpoints.get_Groups_activity_retrieve
        '/api/projects/{project_id}/groups/find/': Endpoints.get_Groups_find_retrieve
        '/api/projects/{project_id}/groups/property_definitions/': Endpoints.get_Groups_property_definitions_retrieve
        '/api/projects/{project_id}/groups/property_values/': Endpoints.get_Groups_property_values_retrieve
        '/api/projects/{project_id}/groups/related/': Endpoints.get_Groups_related_retrieve
        '/api/projects/{project_id}/groups_types/': Endpoints.get_Groups_types_list
        '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/': Endpoints.get_Groups_types_metrics_list
        '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/': Endpoints.get_Groups_types_metrics_retrieve
        '/api/projects/{project_id}/hog_functions/': Endpoints.get_Hog_functions_list
        '/api/projects/{project_id}/hog_functions/{id}/': Endpoints.get_Hog_functions_retrieve
        '/api/projects/{project_id}/hog_functions/{id}/logs/': Endpoints.get_Hog_functions_logs_retrieve
        '/api/projects/{project_id}/hog_functions/{id}/metrics/': Endpoints.get_Hog_functions_metrics_retrieve
        '/api/projects/{project_id}/hog_functions/{id}/metrics/totals/': Endpoints.get_Hog_functions_metrics_totals_retrieve
        '/api/projects/{project_id}/hog_functions/icon/': Endpoints.get_Hog_functions_icon_retrieve
        '/api/projects/{project_id}/hog_functions/icons/': Endpoints.get_Hog_functions_icons_retrieve
        '/api/projects/{project_id}/insights/': Endpoints.get_Insights_list
        '/api/projects/{project_id}/insights/{insight_id}/sharing/': Endpoints.get_Insights_sharing_list
        '/api/projects/{project_id}/insights/{id}/': Endpoints.get_Insights_retrieve
        '/api/projects/{project_id}/insights/{id}/activity/': Endpoints.get_Insights_activity_retrieve_2
        '/api/projects/{project_id}/insights/activity/': Endpoints.get_Insights_activity_retrieve
        '/api/projects/{project_id}/insights/my_last_viewed/': Endpoints.get_Insights_my_last_viewed_retrieve
        '/api/projects/{project_id}/logs/attributes/': Endpoints.get_Logs_attributes_retrieve
        '/api/projects/{project_id}/logs/values/': Endpoints.get_Logs_values_retrieve
        '/api/projects/{project_id}/notebooks/': Endpoints.get_Notebooks_list
        '/api/projects/{project_id}/notebooks/{short_id}/': Endpoints.get_Notebooks_retrieve
        '/api/projects/{project_id}/notebooks/{short_id}/activity/': Endpoints.get_Notebooks_activity_retrieve_2
        '/api/projects/{project_id}/notebooks/activity/': Endpoints.get_Notebooks_activity_retrieve
        '/api/projects/{project_id}/notebooks/recording_comments/': Endpoints.get_Notebooks_recording_comments_retrieve
        '/api/projects/{project_id}/persisted_folder/': Endpoints.get_Persisted_folder_list
        '/api/projects/{project_id}/persisted_folder/{id}/': Endpoints.get_Persisted_folder_retrieve
        '/api/projects/{project_id}/persons/': Endpoints.get_Persons_list
        '/api/projects/{project_id}/persons/{id}/': Endpoints.get_Persons_retrieve
        '/api/projects/{project_id}/persons/{id}/activity/': Endpoints.get_Persons_activity_retrieve_2
        '/api/projects/{project_id}/persons/{id}/properties_timeline/': Endpoints.get_Persons_properties_timeline_retrieve
        '/api/projects/{project_id}/persons/activity/': Endpoints.get_Persons_activity_retrieve
        '/api/projects/{project_id}/persons/cohorts/': Endpoints.get_Persons_cohorts_retrieve
        '/api/projects/{project_id}/persons/funnel/': Endpoints.get_Persons_funnel_retrieve
        '/api/projects/{project_id}/persons/funnel/correlation/': Endpoints.get_Persons_funnel_correlation_retrieve
        '/api/projects/{project_id}/persons/lifecycle/': Endpoints.get_Persons_lifecycle_retrieve
        '/api/projects/{project_id}/persons/stickiness/': Endpoints.get_Persons_stickiness_retrieve
        '/api/projects/{project_id}/persons/trends/': Endpoints.get_Persons_trends_retrieve
        '/api/projects/{project_id}/persons/values/': Endpoints.get_Persons_values_retrieve
        '/api/projects/{project_id}/plugin_configs/{plugin_config_id}/logs/': Endpoints.get_Plugin_configs_logs_list
        '/api/projects/{project_id}/property_definitions/': Endpoints.get_Property_definitions_list
        '/api/projects/{project_id}/property_definitions/{id}/': Endpoints.get_Property_definitions_retrieve
        '/api/projects/{project_id}/property_definitions/seen_together/': Endpoints.get_Property_definitions_seen_together_retrieve
        '/api/projects/{project_id}/query/{id}/': Endpoints.get_Query_retrieve
        '/api/projects/{project_id}/query/{id}/log/': Endpoints.get_Query_log_retrieve
        '/api/projects/{project_id}/query/draft_sql/': Endpoints.get_Query_draft_sql_retrieve
        '/api/projects/{project_id}/session_recording_playlists/': Endpoints.get_Session_recording_playlists_list
        '/api/projects/{project_id}/session_recording_playlists/{short_id}/': Endpoints.get_Session_recording_playlists_retrieve
        '/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/': Endpoints.get_Session_recording_playlists_recordings_retrieve
        '/api/projects/{project_id}/session_recordings/': Endpoints.get_Session_recordings_list
        '/api/projects/{project_id}/session_recordings/{id}/': Endpoints.get_Session_recordings_retrieve
        '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/': Endpoints.get_Session_recordings_sharing_list
        '/api/projects/{project_id}/sessions/property_definitions/': Endpoints.get_Sessions_property_definitions_retrieve
        '/api/projects/{project_id}/sessions/values/': Endpoints.get_Sessions_values_retrieve
        '/api/projects/{project_id}/subscriptions/': Endpoints.get_Subscriptions_list
        '/api/projects/{project_id}/subscriptions/{id}/': Endpoints.get_Subscriptions_retrieve
        '/api/projects/{project_id}/surveys/': Endpoints.get_Surveys_list
        '/api/projects/{project_id}/surveys/{id}/': Endpoints.get_Surveys_retrieve
        '/api/projects/{project_id}/surveys/{id}/activity/': Endpoints.get_Surveys_activity_retrieve_2
        '/api/projects/{project_id}/surveys/{id}/stats/': Endpoints.get_Surveys_stats_retrieve_2
        '/api/projects/{project_id}/surveys/activity/': Endpoints.get_Surveys_activity_retrieve
        '/api/projects/{project_id}/surveys/responses_count/': Endpoints.get_Surveys_responses_count_retrieve
        '/api/projects/{project_id}/surveys/stats/': Endpoints.get_Surveys_stats_retrieve
        '/api/projects/{project_id}/warehouse_saved_queries/': Endpoints.get_Warehouse_saved_queries_list
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/': Endpoints.get_Warehouse_saved_queries_retrieve
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/activity/': Endpoints.get_Warehouse_saved_queries_activity_retrieve
        '/api/projects/{project_id}/warehouse_tables/': Endpoints.get_Warehouse_tables_list
        '/api/projects/{project_id}/warehouse_tables/{id}/': Endpoints.get_Warehouse_tables_retrieve
        '/api/projects/{project_id}/web_analytics/breakdown/': Endpoints.get_Web_analytics_breakdown_retrieve
        '/api/projects/{project_id}/web_analytics/overview/': Endpoints.get_Web_analytics_overview_retrieve
        '/api/projects/{project_id}/web_experiments/': Endpoints.get_Web_experiments_list
        '/api/projects/{project_id}/web_experiments/{id}/': Endpoints.get_Web_experiments_retrieve
        '/api/users/': Endpoints.get_Users_list
        '/api/users/{uuid}/': Endpoints.get_Users_retrieve
        '/api/users/{uuid}/hedgehog_config/': Endpoints.get_Users_hedgehog_config_retrieve
        '/api/users/{uuid}/start_2fa_setup/': Endpoints.get_Users_start_2fa_setup_retrieve
        '/api/users/{uuid}/two_factor_start_setup/': Endpoints.get_Users_two_factor_start_setup_retrieve
        '/api/users/{uuid}/two_factor_status/': Endpoints.get_Users_two_factor_status_retrieve
    }
    post: {
        '/api/environments/{project_id}/batch_exports/': Endpoints.post_Environments_batch_exports_create
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/': Endpoints.post_Environments_batch_exports_backfills_create
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/': Endpoints.post_Environments_batch_exports_backfills_cancel_create
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/': Endpoints.post_Environments_batch_exports_runs_cancel_create
        '/api/environments/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/': Endpoints.post_Environments_batch_exports_runs_retry_create
        '/api/environments/{project_id}/batch_exports/{id}/backfill/': Endpoints.post_Environments_batch_exports_backfill_create
        '/api/environments/{project_id}/batch_exports/{id}/pause/': Endpoints.post_Environments_batch_exports_pause_create
        '/api/environments/{project_id}/batch_exports/{id}/run_test_step/': Endpoints.post_Environments_batch_exports_run_test_step_create
        '/api/environments/{project_id}/batch_exports/{id}/unpause/': Endpoints.post_Environments_batch_exports_unpause_create
        '/api/environments/{project_id}/batch_exports/run_test_step_new/': Endpoints.post_Environments_batch_exports_run_test_step_new_create
        '/api/environments/{project_id}/dashboards/': Endpoints.post_Environments_dashboards_create
        '/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/': Endpoints.post_Environments_dashboards_collaborators_create
        '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/': Endpoints.post_Environments_dashboards_sharing_passwords_create
        '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/refresh/': Endpoints.post_Environments_dashboards_sharing_refresh_create
        '/api/environments/{project_id}/dashboards/create_from_template_json/': Endpoints.post_Environments_dashboards_create_from_template_json_create
        '/api/environments/{project_id}/error_tracking/assignment_rules/': Endpoints.post_Environments_error_tracking_assignment_rules_create
        '/api/environments/{project_id}/error_tracking/grouping_rules/': Endpoints.post_Environments_error_tracking_grouping_rules_create
        '/api/environments/{project_id}/error_tracking/releases/': Endpoints.post_Environments_error_tracking_releases_create
        '/api/environments/{project_id}/error_tracking/suppression_rules/': Endpoints.post_Environments_error_tracking_suppression_rules_create
        '/api/environments/{project_id}/error_tracking/symbol_sets/': Endpoints.post_Environments_error_tracking_symbol_sets_create
        '/api/environments/{project_id}/error_tracking/symbol_sets/bulk_finish_upload/': Endpoints.post_Environments_error_tracking_symbol_sets_bulk_finish_upload_create
        '/api/environments/{project_id}/error_tracking/symbol_sets/bulk_start_upload/': Endpoints.post_Environments_error_tracking_symbol_sets_bulk_start_upload_create
        '/api/environments/{project_id}/error_tracking/symbol_sets/start_upload/': Endpoints.post_Environments_error_tracking_symbol_sets_start_upload_create
        '/api/environments/{project_id}/explicit_members/': Endpoints.post_Environments_explicit_members_create
        '/api/environments/{project_id}/exports/': Endpoints.post_Environments_exports_create
        '/api/environments/{project_id}/file_system/': Endpoints.post_Environments_file_system_create
        '/api/environments/{project_id}/file_system/{id}/count/': Endpoints.post_Environments_file_system_count_create
        '/api/environments/{project_id}/file_system/{id}/link/': Endpoints.post_Environments_file_system_link_create
        '/api/environments/{project_id}/file_system/{id}/move/': Endpoints.post_Environments_file_system_move_create
        '/api/environments/{project_id}/file_system/count_by_path/': Endpoints.post_Environments_file_system_count_by_path_create
        '/api/environments/{project_id}/file_system_shortcut/': Endpoints.post_Environments_file_system_shortcut_create
        '/api/environments/{project_id}/groups/': Endpoints.post_Environments_groups_create
        '/api/environments/{project_id}/groups/delete_property/': Endpoints.post_Environments_groups_delete_property_create
        '/api/environments/{project_id}/groups/update_property/': Endpoints.post_Environments_groups_update_property_create
        '/api/environments/{project_id}/hog_functions/': Endpoints.post_Environments_hog_functions_create
        '/api/environments/{project_id}/hog_functions/{id}/broadcast/': Endpoints.post_Environments_hog_functions_broadcast_create
        '/api/environments/{project_id}/hog_functions/{id}/invocations/': Endpoints.post_Environments_hog_functions_invocations_create
        '/api/environments/{project_id}/insights/': Endpoints.post_Environments_insights_create
        '/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/': Endpoints.post_Environments_insights_sharing_passwords_create
        '/api/environments/{project_id}/insights/{insight_id}/sharing/refresh/': Endpoints.post_Environments_insights_sharing_refresh_create
        '/api/environments/{project_id}/insights/{id}/viewed/': Endpoints.post_Environments_insights_viewed_create
        '/api/environments/{project_id}/insights/cancel/': Endpoints.post_Environments_insights_cancel_create
        '/api/environments/{project_id}/logs/query/': Endpoints.post_Environments_logs_query_create
        '/api/environments/{project_id}/logs/sparkline/': Endpoints.post_Environments_logs_sparkline_create
        '/api/environments/{project_id}/max_tools/create_and_query_insight/': Endpoints.post_Environments_max_tools_create_and_query_insight_create
        '/api/environments/{project_id}/persisted_folder/': Endpoints.post_Environments_persisted_folder_create
        '/api/environments/{project_id}/persons/{id}/delete_events/': Endpoints.post_Environments_persons_delete_events_create
        '/api/environments/{project_id}/persons/{id}/delete_property/': Endpoints.post_Environments_persons_delete_property_create
        '/api/environments/{project_id}/persons/{id}/split/': Endpoints.post_Environments_persons_split_create
        '/api/environments/{project_id}/persons/{id}/update_property/': Endpoints.post_Environments_persons_update_property_create
        '/api/environments/{project_id}/persons/bulk_delete/': Endpoints.post_Environments_persons_bulk_delete_create
        '/api/environments/{project_id}/persons/funnel/': Endpoints.post_Environments_persons_funnel_create
        '/api/environments/{project_id}/persons/funnel/correlation/': Endpoints.post_Environments_persons_funnel_correlation_create
        '/api/environments/{project_id}/persons/reset_person_distinct_id/': Endpoints.post_Environments_persons_reset_person_distinct_id_create
        '/api/environments/{project_id}/query/': Endpoints.post_Environments_query_create
        '/api/environments/{project_id}/query/check_auth_for_async/': Endpoints.post_Environments_query_check_auth_for_async_create
        '/api/environments/{project_id}/query/upgrade/': Endpoints.post_Environments_query_upgrade_create
        '/api/environments/{project_id}/session_recording_playlists/': Endpoints.post_Environments_session_recording_playlists_create
        '/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/': Endpoints.post_Environments_session_recording_playlists_recordings_create
        '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/': Endpoints.post_Environments_session_recordings_sharing_passwords_create
        '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/refresh/': Endpoints.post_Environments_session_recordings_sharing_refresh_create
        '/api/environments/{project_id}/session_summaries/create_session_summaries/': Endpoints.post_Create_session_summaries
        '/api/environments/{project_id}/subscriptions/': Endpoints.post_Environments_subscriptions_create
        '/api/environments/{project_id}/user_interviews/': Endpoints.post_Environments_user_interviews_create
        '/api/environments/{project_id}/warehouse_saved_queries/': Endpoints.post_Environments_warehouse_saved_queries_create
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/ancestors/': Endpoints.post_Environments_warehouse_saved_queries_ancestors_create
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/cancel/': Endpoints.post_Environments_warehouse_saved_queries_cancel_create
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/descendants/': Endpoints.post_Environments_warehouse_saved_queries_descendants_create
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/revert_materialization/': Endpoints.post_Environments_warehouse_saved_queries_revert_materialization_create
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/run/': Endpoints.post_Environments_warehouse_saved_queries_run_create
        '/api/environments/{project_id}/warehouse_tables/': Endpoints.post_Environments_warehouse_tables_create
        '/api/environments/{project_id}/warehouse_tables/{id}/refresh_schema/': Endpoints.post_Environments_warehouse_tables_refresh_schema_create
        '/api/environments/{project_id}/warehouse_tables/{id}/update_schema/': Endpoints.post_Environments_warehouse_tables_update_schema_create
        '/api/environments/{project_id}/warehouse_tables/file/': Endpoints.post_Environments_warehouse_tables_file_create
        '/api/organizations/': Endpoints.post_Create
        '/api/organizations/{id}/environments_rollback/': Endpoints.post_Environments_rollback_create
        '/api/organizations/{organization_id}/batch_exports/': Endpoints.post_Batch_exports_create
        '/api/organizations/{organization_id}/batch_exports/{id}/backfill/': Endpoints.post_Batch_exports_backfill_create
        '/api/organizations/{organization_id}/batch_exports/{id}/pause/': Endpoints.post_Batch_exports_pause_create
        '/api/organizations/{organization_id}/batch_exports/{id}/run_test_step/': Endpoints.post_Batch_exports_run_test_step_create
        '/api/organizations/{organization_id}/batch_exports/{id}/unpause/': Endpoints.post_Batch_exports_unpause_create
        '/api/organizations/{organization_id}/batch_exports/run_test_step_new/': Endpoints.post_Batch_exports_run_test_step_new_create
        '/api/organizations/{organization_id}/domains/': Endpoints.post_Domains_create
        '/api/organizations/{organization_id}/domains/{id}/verify/': Endpoints.post_Domains_verify_create
        '/api/organizations/{organization_id}/invites/': Endpoints.post_Invites_create
        '/api/organizations/{organization_id}/invites/bulk/': Endpoints.post_Invites_bulk_create
        '/api/organizations/{organization_id}/projects/': Endpoints.post_Create_2
        '/api/organizations/{organization_id}/projects/{id}/change_organization/': Endpoints.post_Change_organization_create
        '/api/organizations/{organization_id}/proxy_records/': Endpoints.post_Proxy_records_create
        '/api/organizations/{organization_id}/roles/': Endpoints.post_Roles_create
        '/api/organizations/{organization_id}/roles/{role_id}/role_memberships/': Endpoints.post_Roles_role_memberships_create
        '/api/projects/{project_id}/actions/': Endpoints.post_Actions_create
        '/api/projects/{project_id}/annotations/': Endpoints.post_Annotations_create
        '/api/projects/{project_id}/batch_exports/': Endpoints.post_Batch_exports_create_2
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/': Endpoints.post_Batch_exports_backfills_create
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/backfills/{id}/cancel/': Endpoints.post_Batch_exports_backfills_cancel_create
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/cancel/': Endpoints.post_Batch_exports_runs_cancel_create
        '/api/projects/{project_id}/batch_exports/{batch_export_id}/runs/{id}/retry/': Endpoints.post_Batch_exports_runs_retry_create
        '/api/projects/{project_id}/batch_exports/{id}/backfill/': Endpoints.post_Batch_exports_backfill_create_2
        '/api/projects/{project_id}/batch_exports/{id}/pause/': Endpoints.post_Batch_exports_pause_create_2
        '/api/projects/{project_id}/batch_exports/{id}/run_test_step/': Endpoints.post_Batch_exports_run_test_step_create_2
        '/api/projects/{project_id}/batch_exports/{id}/unpause/': Endpoints.post_Batch_exports_unpause_create_2
        '/api/projects/{project_id}/batch_exports/run_test_step_new/': Endpoints.post_Batch_exports_run_test_step_new_create_2
        '/api/projects/{project_id}/cohorts/': Endpoints.post_Cohorts_create
        '/api/projects/{project_id}/dashboard_templates/': Endpoints.post_Dashboard_templates_create
        '/api/projects/{project_id}/dashboards/': Endpoints.post_Dashboards_create
        '/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/': Endpoints.post_Dashboards_collaborators_create
        '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/': Endpoints.post_Dashboards_sharing_passwords_create
        '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/refresh/': Endpoints.post_Dashboards_sharing_refresh_create
        '/api/projects/{project_id}/dashboards/create_from_template_json/': Endpoints.post_Dashboards_create_from_template_json_create
        '/api/projects/{project_id}/early_access_feature/': Endpoints.post_Early_access_feature_create
        '/api/projects/{project_id}/environments/': Endpoints.post_Environments_create
        '/api/projects/{project_id}/experiment_holdouts/': Endpoints.post_Experiment_holdouts_create
        '/api/projects/{project_id}/experiment_saved_metrics/': Endpoints.post_Experiment_saved_metrics_create
        '/api/projects/{project_id}/experiments/': Endpoints.post_Experiments_create
        '/api/projects/{project_id}/experiments/{id}/create_exposure_cohort_for_experiment/': Endpoints.post_Experiments_create_exposure_cohort_for_experiment_create
        '/api/projects/{project_id}/experiments/{id}/duplicate/': Endpoints.post_Experiments_duplicate_create
        '/api/projects/{project_id}/explicit_members/': Endpoints.post_Explicit_members_create
        '/api/projects/{project_id}/exports/': Endpoints.post_Exports_create
        '/api/projects/{project_id}/feature_flags/': Endpoints.post_Feature_flags_create
        '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/': Endpoints.post_Feature_flags_role_access_create
        '/api/projects/{project_id}/feature_flags/{id}/create_static_cohort_for_flag/': Endpoints.post_Feature_flags_create_static_cohort_for_flag_create
        '/api/projects/{project_id}/feature_flags/{id}/dashboard/': Endpoints.post_Feature_flags_dashboard_create
        '/api/projects/{project_id}/feature_flags/{id}/enrich_usage_dashboard/': Endpoints.post_Feature_flags_enrich_usage_dashboard_create
        '/api/projects/{project_id}/feature_flags/bulk_keys/': Endpoints.post_Feature_flags_bulk_keys_create
        '/api/projects/{project_id}/feature_flags/user_blast_radius/': Endpoints.post_Feature_flags_user_blast_radius_create
        '/api/projects/{project_id}/file_system/': Endpoints.post_File_system_create
        '/api/projects/{project_id}/file_system/{id}/count/': Endpoints.post_File_system_count_create
        '/api/projects/{project_id}/file_system/{id}/link/': Endpoints.post_File_system_link_create
        '/api/projects/{project_id}/file_system/{id}/move/': Endpoints.post_File_system_move_create
        '/api/projects/{project_id}/file_system/count_by_path/': Endpoints.post_File_system_count_by_path_create
        '/api/projects/{project_id}/file_system_shortcut/': Endpoints.post_File_system_shortcut_create
        '/api/projects/{project_id}/groups/': Endpoints.post_Groups_create
        '/api/projects/{project_id}/groups/delete_property/': Endpoints.post_Groups_delete_property_create
        '/api/projects/{project_id}/groups/update_property/': Endpoints.post_Groups_update_property_create
        '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/': Endpoints.post_Groups_types_metrics_create
        '/api/projects/{project_id}/hog_functions/': Endpoints.post_Hog_functions_create
        '/api/projects/{project_id}/hog_functions/{id}/broadcast/': Endpoints.post_Hog_functions_broadcast_create
        '/api/projects/{project_id}/hog_functions/{id}/invocations/': Endpoints.post_Hog_functions_invocations_create
        '/api/projects/{project_id}/insights/': Endpoints.post_Insights_create
        '/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/': Endpoints.post_Insights_sharing_passwords_create
        '/api/projects/{project_id}/insights/{insight_id}/sharing/refresh/': Endpoints.post_Insights_sharing_refresh_create
        '/api/projects/{project_id}/insights/{id}/viewed/': Endpoints.post_Insights_viewed_create
        '/api/projects/{project_id}/insights/cancel/': Endpoints.post_Insights_cancel_create
        '/api/projects/{project_id}/logs/query/': Endpoints.post_Logs_query_create
        '/api/projects/{project_id}/logs/sparkline/': Endpoints.post_Logs_sparkline_create
        '/api/projects/{project_id}/notebooks/': Endpoints.post_Notebooks_create
        '/api/projects/{project_id}/persisted_folder/': Endpoints.post_Persisted_folder_create
        '/api/projects/{project_id}/persons/{id}/delete_events/': Endpoints.post_Persons_delete_events_create
        '/api/projects/{project_id}/persons/{id}/delete_property/': Endpoints.post_Persons_delete_property_create
        '/api/projects/{project_id}/persons/{id}/split/': Endpoints.post_Persons_split_create
        '/api/projects/{project_id}/persons/{id}/update_property/': Endpoints.post_Persons_update_property_create
        '/api/projects/{project_id}/persons/bulk_delete/': Endpoints.post_Persons_bulk_delete_create
        '/api/projects/{project_id}/persons/funnel/': Endpoints.post_Persons_funnel_create
        '/api/projects/{project_id}/persons/funnel/correlation/': Endpoints.post_Persons_funnel_correlation_create
        '/api/projects/{project_id}/persons/reset_person_distinct_id/': Endpoints.post_Persons_reset_person_distinct_id_create
        '/api/projects/{project_id}/query/': Endpoints.post_Query_create
        '/api/projects/{project_id}/query/check_auth_for_async/': Endpoints.post_Query_check_auth_for_async_create
        '/api/projects/{project_id}/query/upgrade/': Endpoints.post_Query_upgrade_create
        '/api/projects/{project_id}/session_recording_playlists/': Endpoints.post_Session_recording_playlists_create
        '/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/': Endpoints.post_Session_recording_playlists_recordings_create
        '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/': Endpoints.post_Session_recordings_sharing_passwords_create
        '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/refresh/': Endpoints.post_Session_recordings_sharing_refresh_create
        '/api/projects/{project_id}/subscriptions/': Endpoints.post_Subscriptions_create
        '/api/projects/{project_id}/surveys/': Endpoints.post_Surveys_create
        '/api/projects/{project_id}/surveys/{id}/summarize_responses/': Endpoints.post_Surveys_summarize_responses_create
        '/api/projects/{project_id}/warehouse_saved_queries/': Endpoints.post_Warehouse_saved_queries_create
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/ancestors/': Endpoints.post_Warehouse_saved_queries_ancestors_create
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/cancel/': Endpoints.post_Warehouse_saved_queries_cancel_create
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/descendants/': Endpoints.post_Warehouse_saved_queries_descendants_create
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/revert_materialization/': Endpoints.post_Warehouse_saved_queries_revert_materialization_create
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/run/': Endpoints.post_Warehouse_saved_queries_run_create
        '/api/projects/{project_id}/warehouse_tables/': Endpoints.post_Warehouse_tables_create
        '/api/projects/{project_id}/warehouse_tables/{id}/refresh_schema/': Endpoints.post_Warehouse_tables_refresh_schema_create
        '/api/projects/{project_id}/warehouse_tables/{id}/update_schema/': Endpoints.post_Warehouse_tables_update_schema_create
        '/api/projects/{project_id}/warehouse_tables/file/': Endpoints.post_Warehouse_tables_file_create
        '/api/projects/{project_id}/web_experiments/': Endpoints.post_Web_experiments_create
        '/api/users/{uuid}/scene_personalisation/': Endpoints.post_Users_scene_personalisation_create
        '/api/users/{uuid}/two_factor_backup_codes/': Endpoints.post_Users_two_factor_backup_codes_create
        '/api/users/{uuid}/two_factor_disable/': Endpoints.post_Users_two_factor_disable_create
        '/api/users/{uuid}/two_factor_validate/': Endpoints.post_Users_two_factor_validate_create
        '/api/users/{uuid}/validate_2fa/': Endpoints.post_Users_validate_2fa_create
        '/api/users/request_email_verification/': Endpoints.post_Users_request_email_verification_create
        '/api/users/verify_email/': Endpoints.post_Users_verify_email_create
    }
    put: {
        '/api/environments/{project_id}/batch_exports/{id}/': Endpoints.put_Environments_batch_exports_update
        '/api/environments/{project_id}/dashboards/{id}/': Endpoints.put_Environments_dashboards_update
        '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/': Endpoints.put_Environments_error_tracking_assignment_rules_update
        '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/': Endpoints.put_Environments_error_tracking_grouping_rules_update
        '/api/environments/{project_id}/error_tracking/releases/{id}/': Endpoints.put_Environments_error_tracking_releases_update
        '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/': Endpoints.put_Environments_error_tracking_suppression_rules_update
        '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/': Endpoints.put_Environments_error_tracking_symbol_sets_update
        '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/finish_upload/': Endpoints.put_Environments_error_tracking_symbol_sets_finish_upload_update
        '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.put_Environments_explicit_members_update
        '/api/environments/{project_id}/file_system/{id}/': Endpoints.put_Environments_file_system_update
        '/api/environments/{project_id}/file_system_shortcut/{id}/': Endpoints.put_Environments_file_system_shortcut_update
        '/api/environments/{project_id}/hog_functions/{id}/': Endpoints.put_Environments_hog_functions_update
        '/api/environments/{project_id}/insights/{id}/': Endpoints.put_Environments_insights_update
        '/api/environments/{project_id}/persisted_folder/{id}/': Endpoints.put_Environments_persisted_folder_update
        '/api/environments/{project_id}/persons/{id}/': Endpoints.put_Environments_persons_update
        '/api/environments/{project_id}/session_recording_playlists/{short_id}/': Endpoints.put_Environments_session_recording_playlists_update
        '/api/environments/{project_id}/session_recordings/{id}/': Endpoints.put_Environments_session_recordings_update
        '/api/environments/{project_id}/subscriptions/{id}/': Endpoints.put_Environments_subscriptions_update
        '/api/environments/{project_id}/user_interviews/{id}/': Endpoints.put_Environments_user_interviews_update
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/': Endpoints.put_Environments_warehouse_saved_queries_update
        '/api/environments/{project_id}/warehouse_tables/{id}/': Endpoints.put_Environments_warehouse_tables_update
        '/api/organizations/{id}/': Endpoints.put_Update
        '/api/organizations/{organization_id}/batch_exports/{id}/': Endpoints.put_Batch_exports_update
        '/api/organizations/{organization_id}/domains/{id}/': Endpoints.put_Domains_update
        '/api/organizations/{organization_id}/members/{user__uuid}/': Endpoints.put_Members_update
        '/api/organizations/{organization_id}/projects/{id}/': Endpoints.put_Update_2
        '/api/organizations/{organization_id}/proxy_records/{id}/': Endpoints.put_Proxy_records_update
        '/api/organizations/{organization_id}/roles/{id}/': Endpoints.put_Roles_update
        '/api/projects/{project_id}/actions/{id}/': Endpoints.put_Actions_update
        '/api/projects/{project_id}/annotations/{id}/': Endpoints.put_Annotations_update
        '/api/projects/{project_id}/batch_exports/{id}/': Endpoints.put_Batch_exports_update_2
        '/api/projects/{project_id}/cohorts/{id}/': Endpoints.put_Cohorts_update
        '/api/projects/{project_id}/dashboard_templates/{id}/': Endpoints.put_Dashboard_templates_update
        '/api/projects/{project_id}/dashboards/{id}/': Endpoints.put_Dashboards_update
        '/api/projects/{project_id}/early_access_feature/{id}/': Endpoints.put_Early_access_feature_update
        '/api/projects/{project_id}/environments/{id}/': Endpoints.put_Environments_update
        '/api/projects/{project_id}/event_definitions/{id}/': Endpoints.put_Event_definitions_update
        '/api/projects/{project_id}/experiment_holdouts/{id}/': Endpoints.put_Experiment_holdouts_update
        '/api/projects/{project_id}/experiment_saved_metrics/{id}/': Endpoints.put_Experiment_saved_metrics_update
        '/api/projects/{project_id}/experiments/{id}/': Endpoints.put_Experiments_update
        '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.put_Explicit_members_update
        '/api/projects/{project_id}/feature_flags/{id}/': Endpoints.put_Feature_flags_update
        '/api/projects/{project_id}/file_system/{id}/': Endpoints.put_File_system_update
        '/api/projects/{project_id}/file_system_shortcut/{id}/': Endpoints.put_File_system_shortcut_update
        '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/': Endpoints.put_Groups_types_metrics_update
        '/api/projects/{project_id}/groups_types/create_detail_dashboard/': Endpoints.put_Groups_types_create_detail_dashboard_update
        '/api/projects/{project_id}/groups_types/set_default_columns/': Endpoints.put_Groups_types_set_default_columns_update
        '/api/projects/{project_id}/hog_functions/{id}/': Endpoints.put_Hog_functions_update
        '/api/projects/{project_id}/insights/{id}/': Endpoints.put_Insights_update
        '/api/projects/{project_id}/notebooks/{short_id}/': Endpoints.put_Notebooks_update
        '/api/projects/{project_id}/persisted_folder/{id}/': Endpoints.put_Persisted_folder_update
        '/api/projects/{project_id}/persons/{id}/': Endpoints.put_Persons_update
        '/api/projects/{project_id}/property_definitions/{id}/': Endpoints.put_Property_definitions_update
        '/api/projects/{project_id}/session_recording_playlists/{short_id}/': Endpoints.put_Session_recording_playlists_update
        '/api/projects/{project_id}/session_recordings/{id}/': Endpoints.put_Session_recordings_update
        '/api/projects/{project_id}/subscriptions/{id}/': Endpoints.put_Subscriptions_update
        '/api/projects/{project_id}/surveys/{id}/': Endpoints.put_Surveys_update
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/': Endpoints.put_Warehouse_saved_queries_update
        '/api/projects/{project_id}/warehouse_tables/{id}/': Endpoints.put_Warehouse_tables_update
        '/api/projects/{project_id}/web_experiments/{id}/': Endpoints.put_Web_experiments_update
        '/api/users/{uuid}/': Endpoints.put_Users_update
    }
    patch: {
        '/api/environments/{project_id}/batch_exports/{id}/': Endpoints.patch_Environments_batch_exports_partial_update
        '/api/environments/{project_id}/dashboards/{id}/': Endpoints.patch_Environments_dashboards_partial_update
        '/api/environments/{project_id}/dashboards/{id}/move_tile/': Endpoints.patch_Environments_dashboards_move_tile_partial_update
        '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/': Endpoints.patch_Environments_error_tracking_assignment_rules_partial_update
        '/api/environments/{project_id}/error_tracking/assignment_rules/reorder/': Endpoints.patch_Environments_error_tracking_assignment_rules_reorder_partial_update
        '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/': Endpoints.patch_Environments_error_tracking_grouping_rules_partial_update
        '/api/environments/{project_id}/error_tracking/grouping_rules/reorder/': Endpoints.patch_Environments_error_tracking_grouping_rules_reorder_partial_update
        '/api/environments/{project_id}/error_tracking/releases/{id}/': Endpoints.patch_Environments_error_tracking_releases_partial_update
        '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/': Endpoints.patch_Environments_error_tracking_suppression_rules_partial_update
        '/api/environments/{project_id}/error_tracking/suppression_rules/reorder/': Endpoints.patch_Environments_error_tracking_suppression_rules_reorder_partial_update
        '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/': Endpoints.patch_Environments_error_tracking_symbol_sets_partial_update
        '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.patch_Environments_explicit_members_partial_update
        '/api/environments/{project_id}/file_system/{id}/': Endpoints.patch_Environments_file_system_partial_update
        '/api/environments/{project_id}/file_system_shortcut/{id}/': Endpoints.patch_Environments_file_system_shortcut_partial_update
        '/api/environments/{project_id}/hog_functions/{id}/': Endpoints.patch_Environments_hog_functions_partial_update
        '/api/environments/{project_id}/hog_functions/rearrange/': Endpoints.patch_Environments_hog_functions_rearrange_partial_update
        '/api/environments/{project_id}/insights/{id}/': Endpoints.patch_Environments_insights_partial_update
        '/api/environments/{project_id}/persisted_folder/{id}/': Endpoints.patch_Environments_persisted_folder_partial_update
        '/api/environments/{project_id}/persons/{id}/': Endpoints.patch_Environments_persons_partial_update
        '/api/environments/{project_id}/session_recording_playlists/{short_id}/': Endpoints.patch_Environments_session_recording_playlists_partial_update
        '/api/environments/{project_id}/session_recordings/{id}/': Endpoints.patch_Environments_session_recordings_partial_update
        '/api/environments/{project_id}/subscriptions/{id}/': Endpoints.patch_Environments_subscriptions_partial_update
        '/api/environments/{project_id}/user_interviews/{id}/': Endpoints.patch_Environments_user_interviews_partial_update
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/': Endpoints.patch_Environments_warehouse_saved_queries_partial_update
        '/api/environments/{project_id}/warehouse_tables/{id}/': Endpoints.patch_Environments_warehouse_tables_partial_update
        '/api/organizations/{id}/': Endpoints.patch_Partial_update
        '/api/organizations/{organization_id}/batch_exports/{id}/': Endpoints.patch_Batch_exports_partial_update
        '/api/organizations/{organization_id}/domains/{id}/': Endpoints.patch_Domains_partial_update
        '/api/organizations/{organization_id}/members/{user__uuid}/': Endpoints.patch_Members_partial_update
        '/api/organizations/{organization_id}/projects/{id}/': Endpoints.patch_Partial_update_2
        '/api/organizations/{organization_id}/projects/{id}/add_product_intent/': Endpoints.patch_Add_product_intent_partial_update
        '/api/organizations/{organization_id}/projects/{id}/complete_product_onboarding/': Endpoints.patch_Complete_product_onboarding_partial_update
        '/api/organizations/{organization_id}/projects/{id}/delete_secret_token_backup/': Endpoints.patch_Delete_secret_token_backup_partial_update
        '/api/organizations/{organization_id}/projects/{id}/reset_token/': Endpoints.patch_Reset_token_partial_update
        '/api/organizations/{organization_id}/projects/{id}/rotate_secret_token/': Endpoints.patch_Rotate_secret_token_partial_update
        '/api/organizations/{organization_id}/proxy_records/{id}/': Endpoints.patch_Proxy_records_partial_update
        '/api/organizations/{organization_id}/roles/{id}/': Endpoints.patch_Roles_partial_update
        '/api/projects/{project_id}/actions/{id}/': Endpoints.patch_Actions_partial_update
        '/api/projects/{project_id}/annotations/{id}/': Endpoints.patch_Annotations_partial_update
        '/api/projects/{project_id}/batch_exports/{id}/': Endpoints.patch_Batch_exports_partial_update_2
        '/api/projects/{project_id}/cohorts/{id}/': Endpoints.patch_Cohorts_partial_update
        '/api/projects/{project_id}/cohorts/{id}/add_persons_to_static_cohort/': Endpoints.patch_Cohorts_add_persons_to_static_cohort_partial_update
        '/api/projects/{project_id}/dashboard_templates/{id}/': Endpoints.patch_Dashboard_templates_partial_update
        '/api/projects/{project_id}/dashboards/{id}/': Endpoints.patch_Dashboards_partial_update
        '/api/projects/{project_id}/dashboards/{id}/move_tile/': Endpoints.patch_Dashboards_move_tile_partial_update
        '/api/projects/{project_id}/early_access_feature/{id}/': Endpoints.patch_Early_access_feature_partial_update
        '/api/projects/{project_id}/environments/{id}/': Endpoints.patch_Environments_partial_update
        '/api/projects/{project_id}/environments/{id}/add_product_intent/': Endpoints.patch_Environments_add_product_intent_partial_update
        '/api/projects/{project_id}/environments/{id}/complete_product_onboarding/': Endpoints.patch_Environments_complete_product_onboarding_partial_update
        '/api/projects/{project_id}/environments/{id}/delete_secret_token_backup/': Endpoints.patch_Environments_delete_secret_token_backup_partial_update
        '/api/projects/{project_id}/environments/{id}/reset_token/': Endpoints.patch_Environments_reset_token_partial_update
        '/api/projects/{project_id}/environments/{id}/rotate_secret_token/': Endpoints.patch_Environments_rotate_secret_token_partial_update
        '/api/projects/{project_id}/event_definitions/{id}/': Endpoints.patch_Event_definitions_partial_update
        '/api/projects/{project_id}/experiment_holdouts/{id}/': Endpoints.patch_Experiment_holdouts_partial_update
        '/api/projects/{project_id}/experiment_saved_metrics/{id}/': Endpoints.patch_Experiment_saved_metrics_partial_update
        '/api/projects/{project_id}/experiments/{id}/': Endpoints.patch_Experiments_partial_update
        '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.patch_Explicit_members_partial_update
        '/api/projects/{project_id}/feature_flags/{id}/': Endpoints.patch_Feature_flags_partial_update
        '/api/projects/{project_id}/file_system/{id}/': Endpoints.patch_File_system_partial_update
        '/api/projects/{project_id}/file_system_shortcut/{id}/': Endpoints.patch_File_system_shortcut_partial_update
        '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/': Endpoints.patch_Groups_types_metrics_partial_update
        '/api/projects/{project_id}/groups_types/update_metadata/': Endpoints.patch_Groups_types_update_metadata_partial_update
        '/api/projects/{project_id}/hog_functions/{id}/': Endpoints.patch_Hog_functions_partial_update
        '/api/projects/{project_id}/hog_functions/rearrange/': Endpoints.patch_Hog_functions_rearrange_partial_update
        '/api/projects/{project_id}/insights/{id}/': Endpoints.patch_Insights_partial_update
        '/api/projects/{project_id}/notebooks/{short_id}/': Endpoints.patch_Notebooks_partial_update
        '/api/projects/{project_id}/persisted_folder/{id}/': Endpoints.patch_Persisted_folder_partial_update
        '/api/projects/{project_id}/persons/{id}/': Endpoints.patch_Persons_partial_update
        '/api/projects/{project_id}/property_definitions/{id}/': Endpoints.patch_Property_definitions_partial_update
        '/api/projects/{project_id}/session_recording_playlists/{short_id}/': Endpoints.patch_Session_recording_playlists_partial_update
        '/api/projects/{project_id}/session_recordings/{id}/': Endpoints.patch_Session_recordings_partial_update
        '/api/projects/{project_id}/subscriptions/{id}/': Endpoints.patch_Subscriptions_partial_update
        '/api/projects/{project_id}/surveys/{id}/': Endpoints.patch_Surveys_partial_update
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/': Endpoints.patch_Warehouse_saved_queries_partial_update
        '/api/projects/{project_id}/warehouse_tables/{id}/': Endpoints.patch_Warehouse_tables_partial_update
        '/api/projects/{project_id}/web_experiments/{id}/': Endpoints.patch_Web_experiments_partial_update
        '/api/users/{uuid}/': Endpoints.patch_Users_partial_update
        '/api/users/{uuid}/hedgehog_config/': Endpoints.patch_Users_hedgehog_config_partial_update
        '/api/users/cancel_email_change_request/': Endpoints.patch_Users_cancel_email_change_request_partial_update
    }
    delete: {
        '/api/environments/{project_id}/batch_exports/{id}/': Endpoints.delete_Environments_batch_exports_destroy
        '/api/environments/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/': Endpoints.delete_Environments_dashboards_collaborators_destroy
        '/api/environments/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/': Endpoints.delete_Environments_dashboards_sharing_passwords_destroy
        '/api/environments/{project_id}/dashboards/{id}/': Endpoints.delete_Environments_dashboards_destroy
        '/api/environments/{project_id}/error_tracking/assignment_rules/{id}/': Endpoints.delete_Environments_error_tracking_assignment_rules_destroy
        '/api/environments/{project_id}/error_tracking/grouping_rules/{id}/': Endpoints.delete_Environments_error_tracking_grouping_rules_destroy
        '/api/environments/{project_id}/error_tracking/releases/{id}/': Endpoints.delete_Environments_error_tracking_releases_destroy
        '/api/environments/{project_id}/error_tracking/suppression_rules/{id}/': Endpoints.delete_Environments_error_tracking_suppression_rules_destroy
        '/api/environments/{project_id}/error_tracking/symbol_sets/{id}/': Endpoints.delete_Environments_error_tracking_symbol_sets_destroy
        '/api/environments/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.delete_Environments_explicit_members_destroy
        '/api/environments/{project_id}/file_system/{id}/': Endpoints.delete_Environments_file_system_destroy
        '/api/environments/{project_id}/file_system_shortcut/{id}/': Endpoints.delete_Environments_file_system_shortcut_destroy
        '/api/environments/{project_id}/hog_functions/{id}/': Endpoints.delete_Environments_hog_functions_destroy
        '/api/environments/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/': Endpoints.delete_Environments_insights_sharing_passwords_destroy
        '/api/environments/{project_id}/insights/{id}/': Endpoints.delete_Environments_insights_destroy
        '/api/environments/{project_id}/persisted_folder/{id}/': Endpoints.delete_Environments_persisted_folder_destroy
        '/api/environments/{project_id}/persons/{id}/': Endpoints.delete_Environments_persons_destroy
        '/api/environments/{project_id}/query/{id}/': Endpoints.delete_Environments_query_destroy
        '/api/environments/{project_id}/session_recording_playlists/{short_id}/': Endpoints.delete_Environments_session_recording_playlists_destroy
        '/api/environments/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/': Endpoints.delete_Environments_session_recording_playlists_recordings_destroy
        '/api/environments/{project_id}/session_recordings/{id}/': Endpoints.delete_Environments_session_recordings_destroy
        '/api/environments/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/': Endpoints.delete_Environments_session_recordings_sharing_passwords_destroy
        '/api/environments/{project_id}/subscriptions/{id}/': Endpoints.delete_Environments_subscriptions_destroy
        '/api/environments/{project_id}/user_interviews/{id}/': Endpoints.delete_Environments_user_interviews_destroy
        '/api/environments/{project_id}/warehouse_saved_queries/{id}/': Endpoints.delete_Environments_warehouse_saved_queries_destroy
        '/api/environments/{project_id}/warehouse_tables/{id}/': Endpoints.delete_Environments_warehouse_tables_destroy
        '/api/organizations/{id}/': Endpoints.delete_Destroy
        '/api/organizations/{organization_id}/batch_exports/{id}/': Endpoints.delete_Batch_exports_destroy
        '/api/organizations/{organization_id}/domains/{id}/': Endpoints.delete_Domains_destroy
        '/api/organizations/{organization_id}/invites/{id}/': Endpoints.delete_Invites_destroy
        '/api/organizations/{organization_id}/members/{user__uuid}/': Endpoints.delete_Members_destroy
        '/api/organizations/{organization_id}/projects/{id}/': Endpoints.delete_Destroy_2
        '/api/organizations/{organization_id}/proxy_records/{id}/': Endpoints.delete_Proxy_records_destroy
        '/api/organizations/{organization_id}/roles/{id}/': Endpoints.delete_Roles_destroy
        '/api/organizations/{organization_id}/roles/{role_id}/role_memberships/{id}/': Endpoints.delete_Roles_role_memberships_destroy
        '/api/projects/{project_id}/actions/{id}/': Endpoints.delete_Actions_destroy
        '/api/projects/{project_id}/annotations/{id}/': Endpoints.delete_Annotations_destroy
        '/api/projects/{project_id}/batch_exports/{id}/': Endpoints.delete_Batch_exports_destroy_2
        '/api/projects/{project_id}/cohorts/{id}/': Endpoints.delete_Cohorts_destroy
        '/api/projects/{project_id}/dashboard_templates/{id}/': Endpoints.delete_Dashboard_templates_destroy
        '/api/projects/{project_id}/dashboards/{dashboard_id}/collaborators/{user__uuid}/': Endpoints.delete_Dashboards_collaborators_destroy
        '/api/projects/{project_id}/dashboards/{dashboard_id}/sharing/passwords/{password_id}/': Endpoints.delete_Dashboards_sharing_passwords_destroy
        '/api/projects/{project_id}/dashboards/{id}/': Endpoints.delete_Dashboards_destroy
        '/api/projects/{project_id}/early_access_feature/{id}/': Endpoints.delete_Early_access_feature_destroy
        '/api/projects/{project_id}/environments/{id}/': Endpoints.delete_Environments_destroy
        '/api/projects/{project_id}/event_definitions/{id}/': Endpoints.delete_Event_definitions_destroy
        '/api/projects/{project_id}/experiment_holdouts/{id}/': Endpoints.delete_Experiment_holdouts_destroy
        '/api/projects/{project_id}/experiment_saved_metrics/{id}/': Endpoints.delete_Experiment_saved_metrics_destroy
        '/api/projects/{project_id}/experiments/{id}/': Endpoints.delete_Experiments_destroy
        '/api/projects/{project_id}/explicit_members/{parent_membership__user__uuid}/': Endpoints.delete_Explicit_members_destroy
        '/api/projects/{project_id}/feature_flags/{feature_flag_id}/role_access/{id}/': Endpoints.delete_Feature_flags_role_access_destroy
        '/api/projects/{project_id}/feature_flags/{id}/': Endpoints.delete_Feature_flags_destroy
        '/api/projects/{project_id}/file_system/{id}/': Endpoints.delete_File_system_destroy
        '/api/projects/{project_id}/file_system_shortcut/{id}/': Endpoints.delete_File_system_shortcut_destroy
        '/api/projects/{project_id}/groups_types/{group_type_index}/': Endpoints.delete_Groups_types_destroy
        '/api/projects/{project_id}/groups_types/{group_type_index}/metrics/{id}/': Endpoints.delete_Groups_types_metrics_destroy
        '/api/projects/{project_id}/hog_functions/{id}/': Endpoints.delete_Hog_functions_destroy
        '/api/projects/{project_id}/insights/{insight_id}/sharing/passwords/{password_id}/': Endpoints.delete_Insights_sharing_passwords_destroy
        '/api/projects/{project_id}/insights/{id}/': Endpoints.delete_Insights_destroy
        '/api/projects/{project_id}/notebooks/{short_id}/': Endpoints.delete_Notebooks_destroy
        '/api/projects/{project_id}/persisted_folder/{id}/': Endpoints.delete_Persisted_folder_destroy
        '/api/projects/{project_id}/persons/{id}/': Endpoints.delete_Persons_destroy
        '/api/projects/{project_id}/property_definitions/{id}/': Endpoints.delete_Property_definitions_destroy
        '/api/projects/{project_id}/query/{id}/': Endpoints.delete_Query_destroy
        '/api/projects/{project_id}/session_recording_playlists/{short_id}/': Endpoints.delete_Session_recording_playlists_destroy
        '/api/projects/{project_id}/session_recording_playlists/{short_id}/recordings/{session_recording_id}/': Endpoints.delete_Session_recording_playlists_recordings_destroy
        '/api/projects/{project_id}/session_recordings/{id}/': Endpoints.delete_Session_recordings_destroy
        '/api/projects/{project_id}/session_recordings/{recording_id}/sharing/passwords/{password_id}/': Endpoints.delete_Session_recordings_sharing_passwords_destroy
        '/api/projects/{project_id}/subscriptions/{id}/': Endpoints.delete_Subscriptions_destroy
        '/api/projects/{project_id}/surveys/{id}/': Endpoints.delete_Surveys_destroy
        '/api/projects/{project_id}/warehouse_saved_queries/{id}/': Endpoints.delete_Warehouse_saved_queries_destroy
        '/api/projects/{project_id}/warehouse_tables/{id}/': Endpoints.delete_Warehouse_tables_destroy
        '/api/projects/{project_id}/web_experiments/{id}/': Endpoints.delete_Web_experiments_destroy
        '/api/users/{uuid}/': Endpoints.delete_Users_destroy
    }
}

// </EndpointByMethod>

// <EndpointByMethod.Shorthands>
export type GetEndpoints = EndpointByMethod['get']
export type PostEndpoints = EndpointByMethod['post']
export type PutEndpoints = EndpointByMethod['put']
export type PatchEndpoints = EndpointByMethod['patch']
export type DeleteEndpoints = EndpointByMethod['delete']
// </EndpointByMethod.Shorthands>

// <ApiClientTypes>
export type EndpointParameters = {
    body?: unknown
    query?: Record<string, unknown>
    header?: Record<string, unknown>
    path?: Record<string, unknown>
}

export type MutationMethod = 'post' | 'put' | 'patch' | 'delete'
export type Method = 'get' | 'head' | 'options' | MutationMethod

type RequestFormat = 'json' | 'form-data' | 'form-url' | 'binary' | 'text'

export type DefaultEndpoint = {
    parameters?: EndpointParameters | undefined
    responses?: Record<string, unknown>
    responseHeaders?: Record<string, unknown>
}

export type Endpoint<TConfig extends DefaultEndpoint = DefaultEndpoint> = {
    operationId: string
    method: Method
    path: string
    requestFormat: RequestFormat
    parameters?: TConfig['parameters']
    meta: {
        alias: string
        hasParameters: boolean
        areParametersRequired: boolean
    }
    responses?: TConfig['responses']
    responseHeaders?: TConfig['responseHeaders']
}

export interface Fetcher {
    decodePathParams?: (path: string, pathParams: Record<string, string>) => string
    encodeSearchParams?: (searchParams: Record<string, unknown> | undefined) => URLSearchParams
    //
    fetch: (input: {
        method: Method
        url: URL
        urlSearchParams?: URLSearchParams | undefined
        parameters?: EndpointParameters | undefined
        path: string
        overrides?: RequestInit
        throwOnStatusError?: boolean
    }) => Promise<Response>
    parseResponseData?: (response: Response) => Promise<unknown>
}

export const successStatusCodes = [
    200, 201, 202, 203, 204, 205, 206, 207, 208, 226, 300, 301, 302, 303, 304, 305, 306, 307, 308,
] as const
export type SuccessStatusCode = (typeof successStatusCodes)[number]

export const errorStatusCodes = [
    400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414, 415, 416, 417, 418,
    421, 422, 423, 424, 425, 426, 428, 429, 431, 451, 500, 501, 502, 503, 504, 505, 506, 507, 508,
    510, 511,
] as const
export type ErrorStatusCode = (typeof errorStatusCodes)[number]

// Taken from https://github.com/unjs/fetchdts/blob/ec4eaeab5d287116171fc1efd61f4a1ad34e4609/src/fetch.ts#L3
export interface TypedHeaders<TypedHeaderValues extends Record<string, string> | unknown>
    extends Omit<
        Headers,
        'append' | 'delete' | 'get' | 'getSetCookie' | 'has' | 'set' | 'forEach'
    > {
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/append) */
    append: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
        name: Name,
        value: Lowercase<Name> extends keyof TypedHeaderValues
            ? TypedHeaderValues[Lowercase<Name>]
            : string
    ) => void
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/delete) */
    delete: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
        name: Name
    ) => void
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/get) */
    get: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
        name: Name
    ) =>
        | (Lowercase<Name> extends keyof TypedHeaderValues
              ? TypedHeaderValues[Lowercase<Name>]
              : string)
        | null
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/getSetCookie) */
    getSetCookie: () => string[]
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/has) */
    has: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
        name: Name
    ) => boolean
    /** [MDN Reference](https://developer.mozilla.org/docs/Web/API/Headers/set) */
    set: <Name extends Extract<keyof TypedHeaderValues, string> | (string & {})>(
        name: Name,
        value: Lowercase<Name> extends keyof TypedHeaderValues
            ? TypedHeaderValues[Lowercase<Name>]
            : string
    ) => void
    forEach: (
        callbackfn: (
            value: TypedHeaderValues[keyof TypedHeaderValues] | (string & {}),
            key: Extract<keyof TypedHeaderValues, string> | (string & {}),
            parent: TypedHeaders<TypedHeaderValues>
        ) => void,
        thisArg?: any
    ) => void
}

/** @see https://developer.mozilla.org/en-US/docs/Web/API/Response */
export interface TypedSuccessResponse<TSuccess, TStatusCode, THeaders>
    extends Omit<Response, 'ok' | 'status' | 'json' | 'headers'> {
    ok: true
    status: TStatusCode
    headers: never extends THeaders ? Headers : TypedHeaders<THeaders>
    data: TSuccess
    /** [MDN Reference](https://developer.mozilla.org/en-US/docs/Web/API/Response/json) */
    json: () => Promise<TSuccess>
}

/** @see https://developer.mozilla.org/en-US/docs/Web/API/Response */
export interface TypedErrorResponse<TData, TStatusCode, THeaders>
    extends Omit<Response, 'ok' | 'status' | 'json' | 'headers'> {
    ok: false
    status: TStatusCode
    headers: never extends THeaders ? Headers : TypedHeaders<THeaders>
    data: TData
    /** [MDN Reference](https://developer.mozilla.org/en-US/docs/Web/API/Response/json) */
    json: () => Promise<TData>
}

export type TypedApiResponse<
    TAllResponses extends Record<string | number, unknown> = {},
    THeaders = {},
> = {
    [K in keyof TAllResponses]: K extends string
        ? K extends `${infer TStatusCode extends number}`
            ? TStatusCode extends SuccessStatusCode
                ? TypedSuccessResponse<
                      TAllResponses[K],
                      TStatusCode,
                      K extends keyof THeaders ? THeaders[K] : never
                  >
                : TypedErrorResponse<
                      TAllResponses[K],
                      TStatusCode,
                      K extends keyof THeaders ? THeaders[K] : never
                  >
            : never
        : K extends number
          ? K extends SuccessStatusCode
              ? TypedSuccessResponse<
                    TAllResponses[K],
                    K,
                    K extends keyof THeaders ? THeaders[K] : never
                >
              : TypedErrorResponse<
                    TAllResponses[K],
                    K,
                    K extends keyof THeaders ? THeaders[K] : never
                >
          : never
}[keyof TAllResponses]

export type SafeApiResponse<TEndpoint> = TEndpoint extends { responses: infer TResponses }
    ? TResponses extends Record<string, unknown>
        ? TypedApiResponse<
              TResponses,
              TEndpoint extends { responseHeaders: infer THeaders } ? THeaders : never
          >
        : never
    : never

export type InferResponseByStatus<TEndpoint, TStatusCode> = Extract<
    SafeApiResponse<TEndpoint>,
    { status: TStatusCode }
>

type RequiredKeys<T> = {
    [P in keyof T]-?: undefined extends T[P] ? never : P
}[keyof T]

type MaybeOptionalArg<T> = RequiredKeys<T> extends never ? [config?: T] : [config: T]
type NotNever<T> = [T] extends [never] ? false : true

// </ApiClientTypes>

// <TypedStatusError>
export class TypedStatusError<TData = unknown> extends Error {
    response: TypedErrorResponse<TData, ErrorStatusCode, unknown>
    status: number
    constructor(response: TypedErrorResponse<TData, ErrorStatusCode, unknown>) {
        super(`HTTP ${response.status}: ${response.statusText}`)
        this.name = 'TypedStatusError'
        this.response = response
        this.status = response.status
    }
}
// </TypedStatusError>

// <ApiClient>
export class ApiClient {
    baseUrl = ''
    successStatusCodes = successStatusCodes
    errorStatusCodes = errorStatusCodes

    constructor(public fetcher: Fetcher) {}

    setBaseUrl(baseUrl: string) {
        this.baseUrl = baseUrl
        return this
    }

    /**
     * Replace path parameters in URL
     * Supports both OpenAPI format {param} and Express format :param
     */
    defaultDecodePathParams = (url: string, params: Record<string, string>): string => {
        return url
            .replace(/{(\w+)}/g, (_, key: string) => params[key] || `{${key}}`)
            .replace(/:([a-zA-Z0-9_]+)/g, (_, key: string) => params[key] || `:${key}`)
    }

    /** Uses URLSearchParams, skips null/undefined values */
    defaultEncodeSearchParams = (
        queryParams: Record<string, unknown> | undefined
    ): URLSearchParams | undefined => {
        if (!queryParams) {
            return
        }

        const searchParams = new URLSearchParams()
        Object.entries(queryParams).forEach(([key, value]) => {
            if (value != null) {
                // Skip null/undefined values
                if (Array.isArray(value)) {
                    value.forEach((val) => val != null && searchParams.append(key, String(val)))
                } else {
                    searchParams.append(key, String(value))
                }
            }
        })

        return searchParams
    }

    defaultParseResponseData = async (response: Response): Promise<unknown> => {
        const contentType = response.headers.get('content-type') ?? ''
        if (contentType.startsWith('text/')) {
            return await response.text()
        }

        if (contentType === 'application/octet-stream') {
            return await response.arrayBuffer()
        }

        if (
            contentType.includes('application/json') ||
            (contentType.includes('application/') && contentType.includes('json')) ||
            contentType === '*/*'
        ) {
            try {
                return await response.json()
            } catch {
                return undefined
            }
        }

        return
    }

    // <ApiClient.get>
    get<Path extends keyof GetEndpoints, TEndpoint extends GetEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                    : {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        >
    ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>['data']>

    get<Path extends keyof GetEndpoints, TEndpoint extends GetEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: true
                          throwOnStatusError?: boolean
                      }
                    : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
                : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        >
    ): Promise<SafeApiResponse<TEndpoint>>

    get<Path extends keyof GetEndpoints, _TEndpoint extends GetEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        return this.request('get', path, ...params)
    }
    // </ApiClient.get>

    // <ApiClient.post>
    post<Path extends keyof PostEndpoints, TEndpoint extends PostEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                    : {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        >
    ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>['data']>

    post<Path extends keyof PostEndpoints, TEndpoint extends PostEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: true
                          throwOnStatusError?: boolean
                      }
                    : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
                : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        >
    ): Promise<SafeApiResponse<TEndpoint>>

    post<Path extends keyof PostEndpoints, _TEndpoint extends PostEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        return this.request('post', path, ...params)
    }
    // </ApiClient.post>

    // <ApiClient.put>
    put<Path extends keyof PutEndpoints, TEndpoint extends PutEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                    : {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        >
    ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>['data']>

    put<Path extends keyof PutEndpoints, TEndpoint extends PutEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: true
                          throwOnStatusError?: boolean
                      }
                    : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
                : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        >
    ): Promise<SafeApiResponse<TEndpoint>>

    put<Path extends keyof PutEndpoints, _TEndpoint extends PutEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        return this.request('put', path, ...params)
    }
    // </ApiClient.put>

    // <ApiClient.patch>
    patch<Path extends keyof PatchEndpoints, TEndpoint extends PatchEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                    : {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        >
    ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>['data']>

    patch<Path extends keyof PatchEndpoints, TEndpoint extends PatchEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: true
                          throwOnStatusError?: boolean
                      }
                    : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
                : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        >
    ): Promise<SafeApiResponse<TEndpoint>>

    patch<Path extends keyof PatchEndpoints, _TEndpoint extends PatchEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        return this.request('patch', path, ...params)
    }
    // </ApiClient.patch>

    // <ApiClient.delete>
    delete<Path extends keyof DeleteEndpoints, TEndpoint extends DeleteEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                    : {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        >
    ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>['data']>

    delete<Path extends keyof DeleteEndpoints, TEndpoint extends DeleteEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<
            TEndpoint extends { parameters: infer UParams }
                ? NotNever<UParams> extends true
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: true
                          throwOnStatusError?: boolean
                      }
                    : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
                : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        >
    ): Promise<SafeApiResponse<TEndpoint>>

    delete<Path extends keyof DeleteEndpoints, _TEndpoint extends DeleteEndpoints[Path]>(
        path: Path,
        ...params: MaybeOptionalArg<any>
    ): Promise<any> {
        return this.request('delete', path, ...params)
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
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                    : {
                          overrides?: RequestInit
                          withResponse?: false
                          throwOnStatusError?: boolean
                      }
                : { overrides?: RequestInit; withResponse?: false; throwOnStatusError?: boolean }
        >
    ): Promise<Extract<InferResponseByStatus<TEndpoint, SuccessStatusCode>, { data: {} }>['data']>

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
                    ? UParams & {
                          overrides?: RequestInit
                          withResponse?: true
                          throwOnStatusError?: boolean
                      }
                    : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
                : { overrides?: RequestInit; withResponse?: true; throwOnStatusError?: boolean }
        >
    ): Promise<SafeApiResponse<TEndpoint>>

    request<
        TMethod extends keyof EndpointByMethod,
        TPath extends keyof EndpointByMethod[TMethod],
        TEndpoint extends EndpointByMethod[TMethod][TPath],
    >(method: TMethod, path: TPath, ...params: MaybeOptionalArg<any>): Promise<any> {
        const requestParams = params[0]
        const withResponse = requestParams?.withResponse
        const {
            withResponse: _,
            throwOnStatusError = withResponse ? false : true,
            overrides,
            ...fetchParams
        } = requestParams || {}

        const parametersToSend: EndpointParameters = {}
        if (requestParams?.body !== undefined) {
            ;(parametersToSend as any).body = requestParams.body
        }
        if (requestParams?.query !== undefined) {
            ;(parametersToSend as any).query = requestParams.query
        }
        if (requestParams?.header !== undefined) {
            ;(parametersToSend as any).header = requestParams.header
        }
        if (requestParams?.path !== undefined) {
            ;(parametersToSend as any).path = requestParams.path
        }

        const resolvedPath = (this.fetcher.decodePathParams ?? this.defaultDecodePathParams)(
            this.baseUrl + (path as string),
            (parametersToSend.path ?? {}) as Record<string, string>
        )
        const url = new URL(resolvedPath)
        const urlSearchParams = (this.fetcher.encodeSearchParams ?? this.defaultEncodeSearchParams)(
            parametersToSend.query
        )

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
                const data = await (
                    this.fetcher.parseResponseData ?? this.defaultParseResponseData
                )(response)
                const typedResponse = Object.assign(response, {
                    data: data,
                    json: () => Promise.resolve(data),
                }) as SafeApiResponse<TEndpoint>

                if (throwOnStatusError && errorStatusCodes.includes(response.status as never)) {
                    throw new TypedStatusError(typedResponse as never)
                }

                return withResponse ? typedResponse : data
            })

        return promise as Extract<
            InferResponseByStatus<TEndpoint, SuccessStatusCode>,
            { data: {} }
        >['data']
    }
    // </ApiClient.request>
}

export function createApiClient(fetcher: Fetcher, baseUrl?: string) {
    return new ApiClient(fetcher).setBaseUrl(baseUrl ?? '')
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
