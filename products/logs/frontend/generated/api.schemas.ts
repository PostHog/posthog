/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

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

export type LogSeverityLevelApi = (typeof LogSeverityLevelApi)[keyof typeof LogSeverityLevelApi]

export const LogSeverityLevelApi = {
    Trace: 'trace',
    Debug: 'debug',
    Info: 'info',
    Warn: 'warn',
    Error: 'error',
    Fatal: 'fatal',
} as const

export interface LogsAlertFiltersApi {
    filterGroup?: PropertyGroupFilterApi | null
    serviceNames?: string[] | null
    severityLevels?: LogSeverityLevelApi[] | null
}

/**
 * * `above` - Above
 * * `below` - Below
 */
export type ThresholdOperatorEnumApi = (typeof ThresholdOperatorEnumApi)[keyof typeof ThresholdOperatorEnumApi]

export const ThresholdOperatorEnumApi = {
    Above: 'above',
    Below: 'below',
} as const

/**
 * * `not_firing` - Not firing
 * * `firing` - Firing
 * * `pending_resolve` - Pending resolve
 * * `errored` - Errored
 * * `snoozed` - Snoozed
 * * `broken` - Broken
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
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `pending_resolve` - Pending resolve
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
    state: LogsAlertConfigurationStateEnumApi
    /** Whether the alert was enabled during this interval. Disabled alerts keep their state but are inactive. */
    enabled: boolean
}

/**
 * * `slack` - slack
 * * `webhook` - webhook
 * * `teams` - teams
 */
export type NotificationDestinationTypeEnumApi =
    (typeof NotificationDestinationTypeEnumApi)[keyof typeof NotificationDestinationTypeEnumApi]

export const NotificationDestinationTypeEnumApi = {
    Slack: 'slack',
    Webhook: 'webhook',
    Teams: 'teams',
} as const

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

export interface LogsAlertConfigurationApi {
    /** Unique identifier for this alert. */
    readonly id: string
    /**
     * Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted.
     * @maxLength 255
     */
    name?: string
    /** Whether the alert is actively being evaluated. Disabling resets the state to not_firing. */
    enabled?: boolean
    /** Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false). */
    filters?: LogsAlertFiltersApi
    /**
     * Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching log.
     * @minimum 0
     */
    threshold_count?: number
    /** Whether the alert fires when the count is above or below the threshold.
     *
     * * `above` - Above
     * * `below` - Below */
    threshold_operator?: ThresholdOperatorEnumApi
    /** Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60. */
    window_minutes?: number
    /** How often the alert is evaluated, in minutes. Server-managed. */
    readonly check_interval_minutes: number
    /** Current alert state: not_firing, firing, pending_resolve, errored, or snoozed. Server-managed.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `pending_resolve` - Pending resolve
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
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
    readonly destination_types: readonly NotificationDestinationTypeEnumApi[]
    /**
     * When the alert was first enabled. Null means the alert is still in draft state.
     * @nullable
     */
    readonly first_enabled_at: string | null
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
     * Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted.
     * @maxLength 255
     */
    name?: string
    /** Whether the alert is actively being evaluated. Disabling resets the state to not_firing. */
    enabled?: boolean
    /** Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false). */
    filters?: LogsAlertFiltersApi
    /**
     * Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching log.
     * @minimum 0
     */
    threshold_count?: number
    /** Whether the alert fires when the count is above or below the threshold.
     *
     * * `above` - Above
     * * `below` - Below */
    threshold_operator?: ThresholdOperatorEnumApi
    /** Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60. */
    window_minutes?: number
    /** How often the alert is evaluated, in minutes. Server-managed. */
    readonly check_interval_minutes?: number
    /** Current alert state: not_firing, firing, pending_resolve, errored, or snoozed. Server-managed.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `pending_resolve` - Pending resolve
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
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
    readonly destination_types?: readonly NotificationDestinationTypeEnumApi[]
    /**
     * When the alert was first enabled. Null means the alert is still in draft state.
     * @nullable
     */
    readonly first_enabled_at?: string | null
    /** When the alert was created. */
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /**
     * When the alert was last modified.
     * @nullable
     */
    readonly updated_at?: string | null
}

export interface LogsAlertCreateDestinationApi {
    /** Destination type — slack, webhook, or teams.
     *
     * * `slack` - slack
     * * `webhook` - webhook
     * * `teams` - teams */
    type: NotificationDestinationTypeEnumApi
    /** Integration ID for the Slack workspace. Required when type=slack. */
    slack_workspace_id?: number
    /** Slack channel ID. Required when type=slack. */
    slack_channel_id?: string
    /** Human-readable channel name for display. */
    slack_channel_name?: string
    /** HTTPS endpoint to POST to. Required when type=webhook, or the Teams webhook URL when type=teams. */
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
 * * `reset` - Reset
 * * `enable` - Enable
 * * `disable` - Disable
 * * `snooze` - Snooze
 * * `unsnooze` - Unsnooze
 * * `threshold_change` - Threshold change
 * * `broken_config` - Broken config
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
    BrokenConfig: 'broken_config',
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
    filters: LogsAlertFiltersApi
    /**
     * Threshold count to evaluate against.
     * @minimum 0
     */
    threshold_count: number
    /** Whether the alert fires when the count is above or below the threshold.
     *
     * * `above` - Above
     * * `below` - Below */
    threshold_operator: ThresholdOperatorEnumApi
    /** Window size in minutes — determines bucket interval. */
    window_minutes: number
    /**
     * How often the alert is evaluated, in minutes.
     * @minimum 1
     * @maximum 60
     */
    check_interval_minutes?: number
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
 * * `log_attribute` - log_attribute
 * * `log_resource_attribute` - log_resource_attribute
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
 * * `is_not` - is_not
 * * `icontains` - icontains
 * * `not_icontains` - not_icontains
 * * `regex` - regex
 * * `not_regex` - not_regex
 * * `gt` - gt
 * * `lt` - lt
 * * `is_date_exact` - is_date_exact
 * * `is_date_before` - is_date_before
 * * `is_date_after` - is_date_after
 * * `is_set` - is_set
 * * `is_not_set` - is_not_set
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
     *
     * * `log` - log
     * * `log_attribute` - log_attribute
     * * `log_resource_attribute` - log_resource_attribute */
    type: _LogPropertyFilterTypeEnumApi
    /** Comparison operator.
     *
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `gt` - gt
     * * `lt` - lt
     * * `is_date_exact` - is_date_exact
     * * `is_date_before` - is_date_before
     * * `is_date_after` - is_date_after
     * * `is_set` - is_set
     * * `is_not_set` - is_not_set */
    operator: _LogPropertyFilterOperatorEnumApi
    /** Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators. */
    value?: unknown
}

/**
 * * `key` - key
 * * `value` - value
 */
export type MatchedOnEnumApi = (typeof MatchedOnEnumApi)[keyof typeof MatchedOnEnumApi]

export const MatchedOnEnumApi = {
    Key: 'key',
    Value: 'value',
} as const

export interface _LogAttributeEntryApi {
    name: string
    /** Property filter type: "log_attribute" or "log_resource_attribute". Use this as the `type` field when filtering. */
    propertyFilterType: string
    /** How the search query matched this row: "key" if the attribute key matched, "value" if a value matched.
     *
     * * `key` - key
     * * `value` - value */
    matchedOn: MatchedOnEnumApi
    /**
     * Sample matching value — only set when matchedOn is "value".
     * @nullable
     */
    matchedValue?: string | null
}

export interface _LogsAttributesResponseApi {
    /** Available attribute keys matching the filters. */
    results: _LogAttributeEntryApi[]
    /** Total attribute keys matched (not paginated). */
    count: number
}

/**
 * * `trace` - trace
 * * `debug` - debug
 * * `info` - info
 * * `warn` - warn
 * * `error` - error
 * * `fatal` - fatal
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

export interface _LogsCountBodyApi {
    /** Date range for the count. Defaults to last hour. */
    dateRange?: _DateRangeApi
    /** Filter by log severity levels. */
    severityLevels?: SeverityLevelsEnumApi[]
    /** Filter by service names. */
    serviceNames?: string[]
    /** Full-text search term to filter log bodies. */
    searchTerm?: string
    /** Property filters for the query. */
    filterGroup?: _LogPropertyFilterApi[]
}

export interface _LogsCountRequestApi {
    /** The count query to execute. */
    query: _LogsCountBodyApi
}

export interface _LogsCountResponseApi {
    /** Number of log entries matching the filters. */
    count: number
}

export interface _LogsCountRangesBodyApi {
    /** Window to bucket. Defaults to last hour. Use a bucket's date_from/date_to from a prior response to recursively narrow into a sub-range. */
    dateRange?: _DateRangeApi
    /**
     * Approximate number of buckets to return. The bucket interval is picked adaptively from a fixed list (1/5/10s, 1/2/5/10/15/30/60/120/240/360/720/1440m) to land near this target. Defaults to 10, capped at 100.
     * @minimum 1
     * @maximum 100
     */
    targetBuckets?: number
    /** Filter by log severity levels. Applied before bucketing. */
    severityLevels?: SeverityLevelsEnumApi[]
    /** Filter by service names. Applied before bucketing. */
    serviceNames?: string[]
    /** Full-text search across log bodies. Applied before bucketing. */
    searchTerm?: string
    /** Property filters applied before bucketing. Same shape as `query-logs`. */
    filterGroup?: _LogPropertyFilterApi[]
}

export interface _LogsCountRangesRequestApi {
    /** The bucketed-count query to execute. */
    query: _LogsCountRangesBodyApi
}

export interface _LogsCountRangeBucketApi {
    /** Bucket start as ISO 8601 timestamp. Inclusive lower bound. Pass back as `dateRange.date_from` to drill in. */
    date_from: string
    /** Bucket end as ISO 8601 timestamp. Exclusive upper bound. Pass back as `dateRange.date_to` to drill in. */
    date_to: string
    /** Log entries matching the filters within this bucket. */
    count: number
}

export interface _LogsCountRangesResponseApi {
    /** Buckets ordered by `date_from` ascending. Empty buckets are omitted — infer gaps by comparing each bucket's `date_to` to the next bucket's `date_from`. */
    ranges: _LogsCountRangeBucketApi[]
    /** Short-form duration of the chosen bucket width (e.g. "1h", "5m", "30s", "1d"). Informational only — use each bucket's `date_from`/`date_to` for follow-up queries. */
    interval: string
}

export interface ExplainRequestApi {
    /** UUID of the log entry to explain */
    uuid: string
    /** Timestamp of the log entry (used for efficient lookup) */
    timestamp: string
    /** Force regenerate explanation, bypassing cache */
    force_refresh?: boolean
}

/**
 * * `severity_text` - severity_text
 * * `service_name` - service_name
 */
export type FacetFieldEnumApi = (typeof FacetFieldEnumApi)[keyof typeof FacetFieldEnumApi]

export const FacetFieldEnumApi = {
    SeverityText: 'severity_text',
    ServiceName: 'service_name',
} as const

export interface _LogsFacetValuesBodyApi {
    /** Top-level column to facet on. Provide exactly one of facetField or facetResourceAttribute. Its own filter is excluded so counts reflect the other active filters.
     *
     * * `severity_text` - severity_text
     * * `service_name` - service_name */
    facetField?: FacetFieldEnumApi | null
    /**
     * Resource attribute key to facet on (e.g. 'k8s.namespace.name'). Provide exactly one of facetField or facetResourceAttribute. Its own log_resource_attribute filter is excluded so counts reflect the other active filters.
     * @nullable
     */
    facetResourceAttribute?: string | null
    /** Date range. Defaults to last hour. */
    dateRange?: _DateRangeApi
    /** Filter by log severity levels (ignored when faceting on severity_text). */
    severityLevels?: SeverityLevelsEnumApi[]
    /** Filter by service names (ignored when faceting on service_name). */
    serviceNames?: string[]
    /** Full-text search term to filter log bodies. */
    searchTerm?: string
    /** Type-ahead filter over the faceted field's own values (case-insensitive substring match). Distinct from searchTerm, which searches log bodies. */
    facetSearch?: string
    /** Property filters for the query. */
    filterGroup?: _LogPropertyFilterApi[]
}

export interface _LogsFacetValuesRequestApi {
    /** The facet values query to execute. */
    query: _LogsFacetValuesBodyApi
}

export interface _LogFacetValueApi {
    /** The facet value (e.g. a severity level or service name). */
    value: string
    /** Number of matching log records, with all active filters applied except this facet's own selection. */
    count: number
}

export interface _LogsFacetValuesResponseApi {
    /** Facet values with cross-filtered counts, ordered by count descending. */
    results: _LogFacetValueApi[]
}

export interface _LogsPatternsBodyApi {
    /** Date range to mine patterns from. Defaults to last hour. */
    dateRange?: _DateRangeApi
    /** Filter by log severity levels before mining. */
    severityLevels?: SeverityLevelsEnumApi[]
    /** Restrict mining to these service names. */
    serviceNames?: string[]
    /** Full-text search term to filter log bodies before mining. */
    searchTerm?: string
    /** Property filters applied before mining. Same shape as the query-logs endpoint. */
    filterGroup?: _LogPropertyFilterApi[]
}

export interface _LogsPatternsRequestApi {
    /** The patterns query to execute. */
    query: _LogsPatternsBodyApi
}

export interface _LogPatternApi {
    /** Mined log template with variable tokens masked, e.g. "Connected to <ip> in <num>ms". Tokens: <uuid>, <ip>, <hex>, <num>, plus <*> for word positions Drain found to vary. */
    pattern: string
    /** Occurrences of this pattern within the sample. When `sampled` is true this is a sample count, not the full-window total — prefer `estimated_count` for display. */
    count: number
    /** Estimated occurrences across the full window, extrapolated from the sample (`count / scanned_count * total_count`). Equals `count` when the window was not sampled. */
    estimated_count: number
    /** Share of the sampled log volume this pattern represents (0–100). */
    volume_share_pct: number
    /** Sampled occurrences at severity "error" or "fatal". Prefer `estimated_error_count` for display. */
    error_count: number
    /** Estimated error/fatal occurrences across the full window, extrapolated from the sample. Equals `error_count` when the window was not sampled. */
    estimated_error_count: number
    /** ISO 8601 timestamp of the earliest sampled occurrence. */
    first_seen: string
    /** ISO 8601 timestamp of the latest sampled occurrence. */
    last_seen: string
    /** Up to 3 distinct raw log bodies (truncated) that produced this pattern. */
    examples: string[]
    /** Up to 4 distinct service names this pattern was observed in. */
    services: string[]
}

export interface _LogsPatternsResponseApi {
    /** Mined patterns ordered by `count` descending. */
    patterns: _LogPatternApi[]
    /** Number of log rows fed to the miner (the sample size, capped at the sample limit). */
    scanned_count: number
    /** Total log rows matching the filters in the window, before sampling. Use with `scanned_count` to scale per-pattern counts when `sampled` is true. */
    total_count: number
    /** True when the window held more rows than the sample cap, so patterns were mined from a deterministic, evenly-distributed sample rather than every matching row. */
    sampled: boolean
    /** Share of the window's log rows that were eligible for sampling (0–100). Below 100, the scan was bounded to evenly-spaced time slices across the window to keep the query within its execution budget; rows outside the slices could not appear in the sample. */
    sample_coverage_pct: number
}

/**
 * * `latest` - latest
 * * `earliest` - earliest
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
     *
     * * `latest` - latest
     * * `earliest` - earliest */
    orderBy?: OrderByEnumApi
    /** Full-text search term to filter log bodies. */
    searchTerm?: string
    /** Property filters for the query. */
    filterGroup?: _LogPropertyFilterApi[]
    /** Max results (1-1000). */
    limit?: number
    /** Pagination cursor from previous response. */
    after?: string
    /** Omit the per-log attributes and resource_attributes maps from results to keep payloads compact. Defaults to false. */
    excludeAttributes?: boolean
}

export interface _LogsQueryRequestApi {
    /** The logs query to execute. */
    query: _LogsQueryBodyApi
}

/**
 * The parsed query that was executed, echoed back for confirmation.
 */
export type _LogsQueryResponseApiQuery = { [key: string]: unknown }

/**
 * Log-level attributes as a string-keyed map. Values are strings (numeric/datetime attributes are also accessible via materialized columns).
 */
export type _LogEntryApiAttributes = { [key: string]: string }

/**
 * Resource-level attributes (service.name, k8s.*, host.hostname, etc.) as a string-keyed map. Repeats across all logs from the same pod/host.
 */
export type _LogEntryApiResourceAttributes = { [key: string]: string }

export interface _LogEntryApi {
    uuid: string
    /** ISO 8601 timestamp of the original log event. */
    timestamp: string
    /** ISO 8601 timestamp the log pipeline observed the event (may differ from `timestamp`). */
    observed_timestamp: string
    body: string
    /** Log severity as a string (e.g. "info", "error"). Preferred over severity_number. */
    severity_text: string
    /** Log severity as a numeric code. Redundant with severity_text; kept for OpenTelemetry compatibility. */
    severity_number: number
    /** ClickHouse alias for severity_text. Redundant; prefer severity_text. */
    level: string
    /** Trace ID. Returns "00000000000000000000000000000000" when not set (padding, not null). */
    trace_id: string
    /** Span ID. Returns "0000000000000000" when not set (padding, not null). */
    span_id: string
    /** OpenTelemetry trace flags. */
    trace_flags?: number
    /** Log-level attributes as a string-keyed map. Values are strings (numeric/datetime attributes are also accessible via materialized columns). */
    attributes: _LogEntryApiAttributes
    /** Resource-level attributes (service.name, k8s.*, host.hostname, etc.) as a string-keyed map. Repeats across all logs from the same pod/host. */
    resource_attributes: _LogEntryApiResourceAttributes
    /** OpenTelemetry event name, if set. */
    event_name?: string
}

export interface _LogsQueryResponseApi {
    /** The parsed query that was executed, echoed back for confirmation. */
    query: _LogsQueryResponseApiQuery
    /** Log entries matching the query. */
    results: _LogEntryApi[]
    /** True if more results exist beyond this page. */
    hasMore: boolean
    /**
     * Opaque cursor to pass as `after` in the next request to fetch the next page. Null when hasMore is false.
     * @nullable
     */
    nextCursor?: string | null
    /** Maximum number of rows the `export` endpoint will produce — informational. */
    maxExportableLogs: number
}

/**
 * * `severity_sampling` - Severity-based reduction
 * * `path_drop` - Path exclusion
 * * `rate_limit` - Rate limit
 */
export type RuleTypeEnumApi = (typeof RuleTypeEnumApi)[keyof typeof RuleTypeEnumApi]

export const RuleTypeEnumApi = {
    SeveritySampling: 'severity_sampling',
    PathDrop: 'path_drop',
    RateLimit: 'rate_limit',
} as const

export type LogsSamplingRuleApiScopeAttributeFiltersItem = { [key: string]: unknown }

export interface LogsSamplingRuleApi {
    /** Unique identifier for this sampling rule. */
    readonly id: string
    /**
     * User-visible label for this rule.
     * @maxLength 255
     */
    name: string
    /** When false, the rule is ignored by ingestion and listing UIs that show active rules only. */
    enabled?: boolean
    /**
     * Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.
     * @minimum 0
     * @nullable
     */
    priority?: number | null
    /** Rule kind: severity_sampling, path_drop, or rate_limit (caps matching log volume at ingestion).
     *
     * * `severity_sampling` - Severity-based reduction
     * * `path_drop` - Path exclusion
     * * `rate_limit` - Rate limit */
    rule_type: RuleTypeEnumApi
    /**
     * Optional legacy service-name scope; new rules use `config.filter_group` for matching instead.
     * @maxLength 512
     * @nullable
     */
    scope_service?: string | null
    /**
     * Optional regex matched against a path-like log attribute when present.
     * @maxLength 1024
     * @nullable
     */
    scope_path_pattern?: string | null
    /** Optional list of predicates over string attributes, e.g. [{"key":"http.route","op":"eq","value":"/api"}]. */
    scope_attribute_filters?: LogsSamplingRuleApiScopeAttributeFiltersItem[]
    /** Type-specific JSON. For path_drop: object with optional `filter_group` (PropertyGroupFilter shape — AND/OR tree of property predicates evaluated per record) and/or legacy `patterns` (list of regex strings) + `match_attribute_key` (string). When both are present a record is dropped if EITHER matches. Filter group example: `{"type":"AND","values":[{"type":"AND","values":[{"key":"service.name","operator":"exact","value":"api"}]}]}`. For severity_sampling: object with `actions` per severity level and optional `always_keep`. For rate_limit: object with EITHER `logs_per_second` (integer 1–1000000, optional `burst_logs` integer ≥ logs_per_second, max 10000000) OR `kb_per_second` (integer 1–1000000 = 1 GB/s, optional `burst_kb` integer ≥ kb_per_second, max 10000000) — not both. Plus optional `filter_group` to narrow which logs the cap applies to. KB-mode charges each log its own uncompressed byte size, matching how billing measures ingested bytes. */
    config: unknown
    /** Incremented on each update for worker cache coherency. */
    readonly version: number
    readonly created_by: number
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedLogsSamplingRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LogsSamplingRuleApi[]
}

export type PatchedLogsSamplingRuleApiScopeAttributeFiltersItem = { [key: string]: unknown }

export interface PatchedLogsSamplingRuleApi {
    /** Unique identifier for this sampling rule. */
    readonly id?: string
    /**
     * User-visible label for this rule.
     * @maxLength 255
     */
    name?: string
    /** When false, the rule is ignored by ingestion and listing UIs that show active rules only. */
    enabled?: boolean
    /**
     * Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.
     * @minimum 0
     * @nullable
     */
    priority?: number | null
    /** Rule kind: severity_sampling, path_drop, or rate_limit (caps matching log volume at ingestion).
     *
     * * `severity_sampling` - Severity-based reduction
     * * `path_drop` - Path exclusion
     * * `rate_limit` - Rate limit */
    rule_type?: RuleTypeEnumApi
    /**
     * Optional legacy service-name scope; new rules use `config.filter_group` for matching instead.
     * @maxLength 512
     * @nullable
     */
    scope_service?: string | null
    /**
     * Optional regex matched against a path-like log attribute when present.
     * @maxLength 1024
     * @nullable
     */
    scope_path_pattern?: string | null
    /** Optional list of predicates over string attributes, e.g. [{"key":"http.route","op":"eq","value":"/api"}]. */
    scope_attribute_filters?: PatchedLogsSamplingRuleApiScopeAttributeFiltersItem[]
    /** Type-specific JSON. For path_drop: object with optional `filter_group` (PropertyGroupFilter shape — AND/OR tree of property predicates evaluated per record) and/or legacy `patterns` (list of regex strings) + `match_attribute_key` (string). When both are present a record is dropped if EITHER matches. Filter group example: `{"type":"AND","values":[{"type":"AND","values":[{"key":"service.name","operator":"exact","value":"api"}]}]}`. For severity_sampling: object with `actions` per severity level and optional `always_keep`. For rate_limit: object with EITHER `logs_per_second` (integer 1–1000000, optional `burst_logs` integer ≥ logs_per_second, max 10000000) OR `kb_per_second` (integer 1–1000000 = 1 GB/s, optional `burst_kb` integer ≥ kb_per_second, max 10000000) — not both. Plus optional `filter_group` to narrow which logs the cap applies to. KB-mode charges each log its own uncompressed byte size, matching how billing measures ingested bytes. */
    config?: unknown
    /** Incremented on each update for worker cache coherency. */
    readonly version?: number
    readonly created_by?: number
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

export interface LogsSamplingRuleSimulateResponseApi {
    /** Rough percent of log volume this rule would drop (0–100). Stub until ClickHouse-backed estimate ships. */
    estimated_reduction_pct: number
    /** Human-readable caveats for the estimate. */
    notes: string
}

export interface LogsSamplingRuleReorderApi {
    /** Rule IDs in the desired evaluation order (first element is highest priority / lowest order index). */
    ordered_ids: string[]
}

export interface _LogsServicesBodyApi {
    /** Date range for the services aggregation. Defaults to last hour. */
    dateRange?: _DateRangeApi
    /** Filter by log severity levels. */
    severityLevels?: SeverityLevelsEnumApi[]
    /** Restrict the aggregation to these service names. */
    serviceNames?: string[]
    /** Full-text search term to filter log bodies. */
    searchTerm?: string
    /** Property filters for the query. */
    filterGroup?: _LogPropertyFilterApi[]
}

export interface _LogsServicesRequestApi {
    /** The services aggregation query to execute. */
    query: _LogsServicesBodyApi
}

export interface _LogsServiceSeverityBreakdownApi {
    debug: number
    info: number
    warn: number
    error: number
}

export interface _LogsServiceActiveRuleApi {
    rule_id: string
    rule_name: string
    summary_string: string
}

export interface _LogsServiceAggregateApi {
    /** Service name, or "(no value)" / "(no service)" placeholder for unset entries. */
    service_name: string
    /** Total log entries from this service in the window. */
    log_count: number
    /** Count of logs at severity "error" or "fatal". */
    error_count: number
    /** Pre-computed error_count / log_count, rounded to 4 decimals. Useful for ranking noisy services. */
    error_rate: number
    /** Share of total log volume in the window for this service (0–100). */
    volume_share_pct?: number
    /** Counts by coarse severity bucket (debug, info, warn, error+fatal). */
    severity_breakdown?: _LogsServiceSeverityBreakdownApi
    /** Enabled sampling rules whose scope includes this service. */
    active_rules?: _LogsServiceActiveRuleApi[]
}

export interface _LogsServicesSparklineBucketApi {
    /** Bucket start time (ISO 8601). */
    time: string
    service_name: string
    count: number
}

export interface _LogsServicesSummaryApi {
    /** Number of top services included in the volume_share aggregate (up to 5). */
    top_services_count: number
    /** Combined volume share (percent) of the top services by log_count. */
    top_services_volume_share_pct: number
}

export interface _LogsServicesResponseApi {
    /** Per-service aggregates, ordered by log_count descending. Capped at 25 services. */
    services: _LogsServiceAggregateApi[]
    /** Time-bucketed counts broken down by service, for plotting volume over time. */
    sparkline: _LogsServicesSparklineBucketApi[]
    /** Roll-up stats for the Services tab header. */
    summary?: _LogsServicesSummaryApi
}

/**
 * * `severity` - severity
 * * `service` - service
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
     *
     * * `severity` - severity
     * * `service` - service */
    sparklineBreakdownBy?: SparklineBreakdownByEnumApi
}

export interface _LogsSparklineRequestApi {
    /** The sparkline query to execute. */
    query: _LogsSparklineBodyApi
}

export interface _LogsSparklineBucketApi {
    /** Bucket start time (ISO 8601). */
    time: string
    /** Severity label when sparklineBreakdownBy="severity". Present only for severity-broken-down sparklines. */
    severity?: string
    /** Service name when sparklineBreakdownBy="service". Present only for service-broken-down sparklines. */
    service?: string
    count: number
    /** Sum of uncompressed bytes for the bucket. */
    bytes_uncompressed?: number
}

export interface _LogsSparklineResponseApi {
    /** Time-bucketed log counts. Each bucket carries either `severity` or `service` depending on breakdown. */
    results: _LogsSparklineBucketApi[]
}

export interface _LogAttributeValueApi {
    /** Attribute value (used as the identifier). */
    id: string
    /** Display name — currently identical to `id`. */
    name: string
    /** Number of log records with this attribute value, scoped to the current date range, service, and resource filters. */
    count?: number
}

export interface _LogsValuesResponseApi {
    /** Distinct values observed for the requested attribute. */
    results: _LogAttributeValueApi[]
    /** Always false — reserved for future cached-value refresh signalling. */
    refreshing: boolean
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
     *
     * * `log` - log
     * * `resource` - resource
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
     * When true, the search query also matches attribute values (not just keys). Each result indicates whether it matched on key or value.
     */
    search_values?: boolean
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

export type LogsExportCreate201 = { [key: string]: unknown }

export type LogsHasLogsRetrieve200 = { [key: string]: unknown }

export type LogsSamplingRulesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LogsSamplingRulesReorderCreateParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LogsValuesRetrieveParams = {
    /**
     * Type of attribute: "log" or "resource". Defaults to "log".
     *
     * * `log` - log
     * * `resource` - resource
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
