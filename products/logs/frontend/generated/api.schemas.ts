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
 */
export type LogsAlertConfigurationStateEnumApi =
    (typeof LogsAlertConfigurationStateEnumApi)[keyof typeof LogsAlertConfigurationStateEnumApi]

export const LogsAlertConfigurationStateEnumApi = {
    NotFiring: 'not_firing',
    Firing: 'firing',
    PendingResolve: 'pending_resolve',
    Errored: 'errored',
    Snoozed: 'snoozed',
} as const

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

export interface LogsAlertConfigurationApi {
    readonly id: string
    /** @maxLength 255 */
    name: string
    enabled?: boolean
    /** Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). */
    filters: unknown
    /**
     * @minimum 1
     * @maximum 2147483647
     */
    threshold_count: number
    /** Whether the alert fires when the count is above or below the threshold.

* `above` - Above
* `below` - Below */
    threshold_operator?: ThresholdOperatorEnumApi
    /**
     * @minimum 0
     * @maximum 2147483647
     */
    window_minutes?: number
    readonly check_interval_minutes: number
    readonly state: LogsAlertConfigurationStateEnumApi
    /**
     * Total number of check periods in the sliding evaluation window (M in N-of-M).
     * @minimum 1
     */
    evaluation_periods?: number
    /**
     * How many periods within the evaluation window must breach the threshold to trigger (N in N-of-M).
     * @minimum 1
     */
    datapoints_to_alarm?: number
    /**
     * @minimum 0
     * @maximum 2147483647
     */
    cooldown_minutes?: number
    /** @nullable */
    snooze_until?: string | null
    /** @nullable */
    readonly next_check_at: string | null
    /** @nullable */
    readonly last_notified_at: string | null
    /** @nullable */
    readonly last_checked_at: string | null
    readonly consecutive_failures: number
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
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
    readonly id?: string
    /** @maxLength 255 */
    name?: string
    enabled?: boolean
    /** Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). */
    filters?: unknown
    /**
     * @minimum 1
     * @maximum 2147483647
     */
    threshold_count?: number
    /** Whether the alert fires when the count is above or below the threshold.

* `above` - Above
* `below` - Below */
    threshold_operator?: ThresholdOperatorEnumApi
    /**
     * @minimum 0
     * @maximum 2147483647
     */
    window_minutes?: number
    readonly check_interval_minutes?: number
    readonly state?: LogsAlertConfigurationStateEnumApi
    /**
     * Total number of check periods in the sliding evaluation window (M in N-of-M).
     * @minimum 1
     */
    evaluation_periods?: number
    /**
     * How many periods within the evaluation window must breach the threshold to trigger (N in N-of-M).
     * @minimum 1
     */
    datapoints_to_alarm?: number
    /**
     * @minimum 0
     * @maximum 2147483647
     */
    cooldown_minutes?: number
    /** @nullable */
    snooze_until?: string | null
    /** @nullable */
    readonly next_check_at?: string | null
    /** @nullable */
    readonly last_notified_at?: string | null
    /** @nullable */
    readonly last_checked_at?: string | null
    readonly consecutive_failures?: number
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly updated_at?: string | null
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
