/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ExplainRequestApi {
    /** UUID of the log entry to explain */
    uuid: string
    /** Timestamp of the log entry (used for efficient lookup) */
    timestamp: string
    /** Force regenerate explanation, bypassing cache */
    force_refresh?: boolean
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

/**
 * Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.
 */
export type LogsViewApiFilters = { [key: string]: unknown }

export interface LogsViewApi {
    readonly id: string
    readonly short_id: string
    /** @maxLength 400 */
    name: string
    /** Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys. */
    filters?: LogsViewApiFilters
    pinned?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedLogsViewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LogsViewApi[]
}

/**
 * Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.
 */
export type PatchedLogsViewApiFilters = { [key: string]: unknown }

export interface PatchedLogsViewApi {
    readonly id?: string
    readonly short_id?: string
    /** @maxLength 400 */
    name?: string
    /** Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys. */
    filters?: PatchedLogsViewApiFilters
    pinned?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `above` - Above
 * `below` - Below
 */
export type ThresholdOperatorEnumApi = (typeof ThresholdOperatorEnumApi)[keyof typeof ThresholdOperatorEnumApi]

export const ThresholdOperatorEnumApi = {
    Above: 'above',
    Below: 'below',
} as const

/**
 * * `not_firing` - Not firing
 * `firing` - Firing
 * `pending_resolve` - Pending resolve
 * `errored` - Errored
 * `snoozed` - Snoozed
 * `broken` - Broken
 */
export type LogsAlertConfigurationStateEnumApi =
    (typeof LogsAlertConfigurationStateEnumApi)[keyof typeof LogsAlertConfigurationStateEnumApi]

export const LogsAlertConfigurationStateEnumApi = {
    NotFiring: 'not_firing',
    Firing: 'firing',
    PendingResolve: 'pending_resolve',
    Errored: 'errored',
    Snoozed: 'snoozed',
    Broken: 'broken',
} as const

export interface LogsAlertStateIntervalApi {
    /** Interval start (UTC, inclusive). */
    start: string
    /** Interval end (UTC, exclusive). */
    end: string
    /** Alert state during this interval.

* `not_firing` - Not firing
* `firing` - Firing
* `pending_resolve` - Pending resolve
* `errored` - Errored
* `snoozed` - Snoozed
* `broken` - Broken */
    state: LogsAlertConfigurationStateEnumApi
    /** Whether the alert was enabled during this interval. Disabled alerts keep their state but are inactive. */
    enabled: boolean
}

/**
 * * `slack` - slack
 * `webhook` - webhook
 */
export type DestinationTypesEnumApi = (typeof DestinationTypesEnumApi)[keyof typeof DestinationTypesEnumApi]

export const DestinationTypesEnumApi = {
    Slack: 'slack',
    Webhook: 'webhook',
} as const

export interface LogsAlertConfigurationApi {
    /** Unique identifier for this alert. */
    readonly id: string
    /**
     * Human-readable name for this alert.
     * @maxLength 255
     */
    name: string
    /** Whether the alert is actively being evaluated. Disabling resets the state to not_firing. */
    enabled?: boolean
    /** Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). */
    filters: unknown
    /**
     * Number of matching log entries that constitutes a threshold breach within the evaluation window.
     * @minimum 1
     */
    threshold_count: number
    /** Whether the alert fires when the count is above or below the threshold.

* `above` - Above
* `below` - Below */
    threshold_operator?: ThresholdOperatorEnumApi
    /** Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60. */
    window_minutes?: number
    /** How often the alert is evaluated, in minutes. Server-managed. */
    readonly check_interval_minutes: number
    /** Current alert state: not_firing, firing, pending_resolve, errored, or snoozed. Server-managed.

* `not_firing` - Not firing
* `firing` - Firing
* `pending_resolve` - Pending resolve
* `errored` - Errored
* `snoozed` - Snoozed
* `broken` - Broken */
    readonly state: LogsAlertConfigurationStateEnumApi
    /**
     * Total number of check periods in the sliding evaluation window for firing (M in N-of-M).
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods?: number
    /**
     * How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm?: number
    /**
     * Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.
     * @minimum 0
     */
    cooldown_minutes?: number
    /**
     * ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.
     * @nullable
     */
    snooze_until?: string | null
    /**
     * When the next evaluation is scheduled. Server-managed.
     * @nullable
     */
    readonly next_check_at: string | null
    /**
     * When the last notification was sent. Server-managed.
     * @nullable
     */
    readonly last_notified_at: string | null
    /**
     * When the alert was last evaluated. Server-managed.
     * @nullable
     */
    readonly last_checked_at: string | null
    /** Number of consecutive evaluation failures. Resets on success. Server-managed. */
    readonly consecutive_failures: number
    /**
     * Error message from the most recent errored check, or null if the alert's most recent check was successful. Sourced from LogsAlertEvent without denormalization so retention-aware cleanup rules stay the only source of truth.
     * @nullable
     */
    readonly last_error_message: string | null
    /** Continuous state intervals over the last 24h, ordered oldest-first. Each interval covers a span during which (state, enabled) was constant. Derived from LogsAlertEvent rows walked in chronological order; consecutive identical intervals are collapsed. Drives the 'Last 24h' status bar on the alert list. */
    readonly state_timeline: readonly LogsAlertStateIntervalApi[]
    /** Notification destination types configured for this alert — e.g. 'slack', 'webhook'. Empty list means no notifications will fire. One or more destinations should be added after creating an alert. */
    readonly destination_types: readonly DestinationTypesEnumApi[]
    /** When the alert was created. */
    readonly created_at: string
    readonly created_by: UserBasicApi
    /**
     * When the alert was last modified.
     * @nullable
     */
    readonly updated_at: string | null
}

export interface PaginatedLogsAlertConfigurationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LogsAlertConfigurationApi[]
}

export interface PatchedLogsAlertConfigurationApi {
    /** Unique identifier for this alert. */
    readonly id?: string
    /**
     * Human-readable name for this alert.
     * @maxLength 255
     */
    name?: string
    /** Whether the alert is actively being evaluated. Disabling resets the state to not_firing. */
    enabled?: boolean
    /** Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). */
    filters?: unknown
    /**
     * Number of matching log entries that constitutes a threshold breach within the evaluation window.
     * @minimum 1
     */
    threshold_count?: number
    /** Whether the alert fires when the count is above or below the threshold.

* `above` - Above
* `below` - Below */
    threshold_operator?: ThresholdOperatorEnumApi
    /** Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60. */
    window_minutes?: number
    /** How often the alert is evaluated, in minutes. Server-managed. */
    readonly check_interval_minutes?: number
    /** Current alert state: not_firing, firing, pending_resolve, errored, or snoozed. Server-managed.

* `not_firing` - Not firing
* `firing` - Firing
* `pending_resolve` - Pending resolve
* `errored` - Errored
* `snoozed` - Snoozed
* `broken` - Broken */
    readonly state?: LogsAlertConfigurationStateEnumApi
    /**
     * Total number of check periods in the sliding evaluation window for firing (M in N-of-M).
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods?: number
    /**
     * How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm?: number
    /**
     * Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.
     * @minimum 0
     */
    cooldown_minutes?: number
    /**
     * ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.
     * @nullable
     */
    snooze_until?: string | null
    /**
     * When the next evaluation is scheduled. Server-managed.
     * @nullable
     */
    readonly next_check_at?: string | null
    /**
     * When the last notification was sent. Server-managed.
     * @nullable
     */
    readonly last_notified_at?: string | null
    /**
     * When the alert was last evaluated. Server-managed.
     * @nullable
     */
    readonly last_checked_at?: string | null
    /** Number of consecutive evaluation failures. Resets on success. Server-managed. */
    readonly consecutive_failures?: number
    /**
     * Error message from the most recent errored check, or null if the alert's most recent check was successful. Sourced from LogsAlertEvent without denormalization so retention-aware cleanup rules stay the only source of truth.
     * @nullable
     */
    readonly last_error_message?: string | null
    /** Continuous state intervals over the last 24h, ordered oldest-first. Each interval covers a span during which (state, enabled) was constant. Derived from LogsAlertEvent rows walked in chronological order; consecutive identical intervals are collapsed. Drives the 'Last 24h' status bar on the alert list. */
    readonly state_timeline?: readonly LogsAlertStateIntervalApi[]
    /** Notification destination types configured for this alert — e.g. 'slack', 'webhook'. Empty list means no notifications will fire. One or more destinations should be added after creating an alert. */
    readonly destination_types?: readonly DestinationTypesEnumApi[]
    /** When the alert was created. */
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /**
     * When the alert was last modified.
     * @nullable
     */
    readonly updated_at?: string | null
}

/**
 * * `slack` - slack
 * `webhook` - webhook
 */
export type TypeC34EnumApi = (typeof TypeC34EnumApi)[keyof typeof TypeC34EnumApi]

export const TypeC34EnumApi = {
    Slack: 'slack',
    Webhook: 'webhook',
} as const

export interface LogsAlertCreateDestinationApi {
    /** Destination type — slack or webhook.

* `slack` - slack
* `webhook` - webhook */
    type: TypeC34EnumApi
    /** Integration ID for the Slack workspace. Required when type=slack. */
    slack_workspace_id?: number
    /** Slack channel ID. Required when type=slack. */
    slack_channel_id?: string
    /** Human-readable channel name for display. */
    slack_channel_name?: string
    /** HTTPS endpoint to POST to. Required when type=webhook. */
    webhook_url?: string
}

export interface LogsAlertDestinationResponseApi {
    hog_function_ids: string[]
}

export interface LogsAlertDeleteDestinationApi {
    /**
     * HogFunction IDs to delete as one atomic destination group.
     * @minItems 1
     */
    hog_function_ids: string[]
}

/**
 * * `check` - Check
 * `reset` - Reset
 * `enable` - Enable
 * `disable` - Disable
 * `snooze` - Snooze
 * `unsnooze` - Unsnooze
 * `threshold_change` - Threshold change
 */
export type LogsAlertEventKindEnumApi = (typeof LogsAlertEventKindEnumApi)[keyof typeof LogsAlertEventKindEnumApi]

export const LogsAlertEventKindEnumApi = {
    Check: 'check',
    Reset: 'reset',
    Enable: 'enable',
    Disable: 'disable',
    Snooze: 'snooze',
    Unsnooze: 'unsnooze',
    ThresholdChange: 'threshold_change',
} as const

export interface LogsAlertEventApi {
    readonly id: string
    readonly created_at: string
    readonly kind: LogsAlertEventKindEnumApi
    readonly state_before: string
    readonly state_after: string
    readonly threshold_breached: boolean
    /** @nullable */
    readonly result_count: number | null
    /** @nullable */
    readonly error_message: string | null
    /** @nullable */
    readonly query_duration_ms: number | null
}

export interface PaginatedLogsAlertEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LogsAlertEventApi[]
}

export interface LogsAlertSimulateRequestApi {
    /** Filter criteria — same format as LogsAlertConfiguration.filters. */
    filters: unknown
    /**
     * Threshold count to evaluate against.
     * @minimum 1
     */
    threshold_count: number
    /** Whether the alert fires when the count is above or below the threshold.

* `above` - Above
* `below` - Below */
    threshold_operator: ThresholdOperatorEnumApi
    /** Window size in minutes — determines bucket interval. */
    window_minutes: number
    /**
     * Total check periods in the N-of-M evaluation window (M).
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods?: number
    /**
     * How many periods must breach to fire (N in N-of-M).
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm?: number
    /**
     * Minutes to wait after firing before sending another notification.
     * @minimum 0
     */
    cooldown_minutes?: number
    /** Relative date string for how far back to simulate (e.g. '-24h', '-7d', '-30d'). */
    date_from: string
}

export interface LogsAlertSimulateBucketApi {
    /** Bucket start timestamp. */
    timestamp: string
    /** Number of matching logs in this bucket. */
    count: number
    /** Whether the count crossed the threshold in this bucket. */
    threshold_breached: boolean
    /** Alert state after evaluating this bucket. */
    state: string
    /** Notification action: none, fire, or resolve. */
    notification: string
    /** Human-readable explanation of the state transition. */
    reason: string
}

export interface LogsAlertSimulateResponseApi {
    /** Time-bucketed counts with full state machine evaluation. */
    buckets: LogsAlertSimulateBucketApi[]
    /** Number of times the alert would have sent a fire notification. */
    fire_count: number
    /** Number of times the alert would have sent a resolve notification. */
    resolve_count: number
    /** Total number of buckets in the simulation window. */
    total_buckets: number
    /** Threshold count used for evaluation. */
    threshold_count: number
    /** Threshold operator used for evaluation. */
    threshold_operator: string
}

export interface _DateRangeApi {
    /**
     * Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.
     * @nullable
     */
    date_from?: string | null
    /**
     * End of the date range. Same format as date_from. Omit or null for "now".
     * @nullable
     */
    date_to?: string | null
}

/**
 * * `log` - log
 * `log_attribute` - log_attribute
 * `log_resource_attribute` - log_resource_attribute
 */
export type _LogPropertyFilterTypeEnumApi =
    (typeof _LogPropertyFilterTypeEnumApi)[keyof typeof _LogPropertyFilterTypeEnumApi]

export const _LogPropertyFilterTypeEnumApi = {
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
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
 * `is_date_exact` - is_date_exact
 * `is_date_before` - is_date_before
 * `is_date_after` - is_date_after
 * `is_set` - is_set
 * `is_not_set` - is_not_set
 */
export type _LogPropertyFilterOperatorEnumApi =
    (typeof _LogPropertyFilterOperatorEnumApi)[keyof typeof _LogPropertyFilterOperatorEnumApi]

export const _LogPropertyFilterOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Lt: 'lt',
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
} as const

export interface _LogPropertyFilterApi {
    /** Attribute key. For type "log", use "message". For "log_attribute"/"log_resource_attribute", use the attribute key (e.g. "k8s.container.name"). */
    key: string
    /** "log" filters the log body/message. "log_attribute" filters log-level attributes. "log_resource_attribute" filters resource-level attributes.

* `log` - log
* `log_attribute` - log_attribute
* `log_resource_attribute` - log_resource_attribute */
    type: _LogPropertyFilterTypeEnumApi
    /** Comparison operator.

* `exact` - exact
* `is_not` - is_not
* `icontains` - icontains
* `not_icontains` - not_icontains
* `regex` - regex
* `not_regex` - not_regex
* `gt` - gt
* `lt` - lt
* `is_date_exact` - is_date_exact
* `is_date_before` - is_date_before
* `is_date_after` - is_date_after
* `is_set` - is_set
* `is_not_set` - is_not_set */
    operator: _LogPropertyFilterOperatorEnumApi
    /** Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators. */
    value?: unknown | null
}

/**
 * * `trace` - trace
 * `debug` - debug
 * `info` - info
 * `warn` - warn
 * `error` - error
 * `fatal` - fatal
 */
export type SeverityLevelsEnumApi = (typeof SeverityLevelsEnumApi)[keyof typeof SeverityLevelsEnumApi]

export const SeverityLevelsEnumApi = {
    Trace: 'trace',
    Debug: 'debug',
    Info: 'info',
    Warn: 'warn',
    Error: 'error',
    Fatal: 'fatal',
} as const

/**
 * * `latest` - latest
 * `earliest` - earliest
 */
export type OrderByEnumApi = (typeof OrderByEnumApi)[keyof typeof OrderByEnumApi]

export const OrderByEnumApi = {
    Latest: 'latest',
    Earliest: 'earliest',
} as const

export interface _LogsQueryBodyApi {
    /** Date range for the query. Defaults to last hour. */
    dateRange?: _DateRangeApi
    /** Filter by log severity levels. */
    severityLevels?: SeverityLevelsEnumApi[]
    /** Filter by service names. */
    serviceNames?: string[]
    /** Order results by timestamp.

* `latest` - latest
* `earliest` - earliest */
    orderBy?: OrderByEnumApi
    /** Full-text search term to filter log bodies. */
    searchTerm?: string
    /** Property filters for the query. */
    filterGroup?: _LogPropertyFilterApi[]
    /** Max results (1-1000). */
    limit?: number
    /** Pagination cursor from previous response. */
    after?: string
}

export interface _LogsQueryRequestApi {
    /** The logs query to execute. */
    query: _LogsQueryBodyApi
}

/**
 * * `severity` - severity
 * `service` - service
 */
export type SparklineBreakdownByEnumApi = (typeof SparklineBreakdownByEnumApi)[keyof typeof SparklineBreakdownByEnumApi]

export const SparklineBreakdownByEnumApi = {
    Severity: 'severity',
    Service: 'service',
} as const

export interface _LogsSparklineBodyApi {
    /** Date range for the sparkline. Defaults to last hour. */
    dateRange?: _DateRangeApi
    /** Filter by log severity levels. */
    severityLevels?: SeverityLevelsEnumApi[]
    /** Filter by service names. */
    serviceNames?: string[]
    /** Full-text search term to filter log bodies. */
    searchTerm?: string
    /** Property filters for the query. */
    filterGroup?: _LogPropertyFilterApi[]
    /** Break down sparkline by "severity" (default) or "service".

* `severity` - severity
* `service` - service */
    sparklineBreakdownBy?: SparklineBreakdownByEnumApi
}

export interface _LogsSparklineRequestApi {
    /** The sparkline query to execute. */
    query: _LogsSparklineBodyApi
}

/**
 * * `SYSTEM` - SYSTEM
 * `PLUGIN` - PLUGIN
 * `CONSOLE` - CONSOLE
 */
export type PluginLogEntrySourceEnumApi = (typeof PluginLogEntrySourceEnumApi)[keyof typeof PluginLogEntrySourceEnumApi]

export const PluginLogEntrySourceEnumApi = {
    System: 'SYSTEM',
    Plugin: 'PLUGIN',
    Console: 'CONSOLE',
} as const

/**
 * * `DEBUG` - DEBUG
 * `LOG` - LOG
 * `INFO` - INFO
 * `WARN` - WARN
 * `ERROR` - ERROR
 */
export type PluginLogEntryTypeEnumApi = (typeof PluginLogEntryTypeEnumApi)[keyof typeof PluginLogEntryTypeEnumApi]

export const PluginLogEntryTypeEnumApi = {
    Debug: 'DEBUG',
    Log: 'LOG',
    Info: 'INFO',
    Warn: 'WARN',
    Error: 'ERROR',
} as const

export interface PluginLogEntryApi {
    id: string
    team_id: number
    plugin_id: number
    plugin_config_id: number
    timestamp: string
    source: PluginLogEntrySourceEnumApi
    type: PluginLogEntryTypeEnumApi
    message: string
    instance_id: string
}

export interface PaginatedPluginLogEntryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PluginLogEntryApi[]
}

export type LogsViewsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LogsAlertsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LogsAlertsEventsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LogsAttributesRetrieveParams = {
    /**
 * Type of attributes: "log" for log attributes, "resource" for resource attributes. Defaults to "log".

* `log` - log
* `resource` - resource
 * @minLength 1
 */
    attribute_type?: LogsAttributesRetrieveAttributeType
    /**
     * Date range to search within. Defaults to last hour.
     */
    dateRange?: _DateRangeApi
    /**
     * Property filters to narrow which logs are scanned for attributes.
     */
    filterGroup?: _LogPropertyFilterApi[]
    /**
     * Max results (default: 100)
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Pagination offset (default: 0)
     * @minimum 0
     */
    offset?: number
    /**
     * Search filter for attribute names
     * @minLength 1
     */
    search?: string
    /**
     * Filter attributes to those appearing in logs from these services.
     */
    serviceNames?: string[]
}

export type LogsAttributesRetrieveAttributeType =
    (typeof LogsAttributesRetrieveAttributeType)[keyof typeof LogsAttributesRetrieveAttributeType]

export const LogsAttributesRetrieveAttributeType = {
    Log: 'log',
    Resource: 'resource',
} as const

export type LogsValuesRetrieveParams = {
    /**
 * Type of attribute: "log" or "resource". Defaults to "log".

* `log` - log
* `resource` - resource
 * @minLength 1
 */
    attribute_type?: LogsValuesRetrieveAttributeType
    /**
     * Date range to search within. Defaults to last hour.
     */
    dateRange?: _DateRangeApi
    /**
     * Property filters to narrow which logs are scanned for values.
     */
    filterGroup?: _LogPropertyFilterApi[]
    /**
     * The attribute key to get values for
     * @minLength 1
     */
    key: string
    /**
     * Filter values to those appearing in logs from these services.
     */
    serviceNames?: string[]
    /**
     * Search filter for attribute values
     * @minLength 1
     */
    value?: string
}

export type LogsValuesRetrieveAttributeType =
    (typeof LogsValuesRetrieveAttributeType)[keyof typeof LogsValuesRetrieveAttributeType]

export const LogsValuesRetrieveAttributeType = {
    Log: 'log',
    Resource: 'resource',
} as const

export type PluginConfigsLogsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
