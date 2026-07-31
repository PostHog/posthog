/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const FilterLogicalOperatorApi = zod.enum(['AND', 'OR'])

export type FilterLogicalOperatorApi = zod.input<typeof FilterLogicalOperatorApi>
export type FilterLogicalOperatorApiOutput = zod.output<typeof FilterLogicalOperatorApi>

export const PropertyGroupFilterValueApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PropertyGroupFilterValueApi = zod.input<typeof PropertyGroupFilterValueApi>
export type PropertyGroupFilterValueApiOutput = zod.output<typeof PropertyGroupFilterValueApi>

export const PropertyGroupFilterApi = zod.object({
    type: FilterLogicalOperatorApi,
    values: zod.array(PropertyGroupFilterValueApi),
})

export type PropertyGroupFilterApi = zod.input<typeof PropertyGroupFilterApi>
export type PropertyGroupFilterApiOutput = zod.output<typeof PropertyGroupFilterApi>

export const LogSeverityLevelApi = zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])

export type LogSeverityLevelApi = zod.input<typeof LogSeverityLevelApi>
export type LogSeverityLevelApiOutput = zod.output<typeof LogSeverityLevelApi>

export const LogsAlertFiltersApi = zod.object({
    filterGroup: zod.union([PropertyGroupFilterApi, zod.null()]).optional(),
    serviceNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    severityLevels: zod.union([zod.array(LogSeverityLevelApi), zod.null()]).optional(),
})

export type LogsAlertFiltersApi = zod.input<typeof LogsAlertFiltersApi>
export type LogsAlertFiltersApiOutput = zod.output<typeof LogsAlertFiltersApi>

export const LogsAlertThresholdOperatorEnumApi = zod
    .enum(['above', 'below'])
    .describe('\* `above` - Above\n\* `below` - Below')

export type LogsAlertThresholdOperatorEnumApi = zod.input<typeof LogsAlertThresholdOperatorEnumApi>
export type LogsAlertThresholdOperatorEnumApiOutput = zod.output<typeof LogsAlertThresholdOperatorEnumApi>

export const LogsAlertConfigurationStateEnumApi = zod
    .enum(['not_firing', 'firing', 'pending_resolve', 'errored', 'snoozed', 'broken'])
    .describe(
        '\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `pending_resolve` - Pending resolve\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
    )

export type LogsAlertConfigurationStateEnumApi = zod.input<typeof LogsAlertConfigurationStateEnumApi>
export type LogsAlertConfigurationStateEnumApiOutput = zod.output<typeof LogsAlertConfigurationStateEnumApi>

export const LogsAlertStateIntervalApi = zod.object({
    start: zod.iso.datetime({ offset: true }).describe('Interval start (UTC, inclusive).'),
    end: zod.iso.datetime({ offset: true }).describe('Interval end (UTC, exclusive).'),
    state: LogsAlertConfigurationStateEnumApi.describe(
        'Alert state during this interval.\n\n\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `pending_resolve` - Pending resolve\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
    ),
    enabled: zod
        .boolean()
        .describe(
            'Whether the alert was enabled during this interval. Disabled alerts keep their state but are inactive.'
        ),
})

export type LogsAlertStateIntervalApi = zod.input<typeof LogsAlertStateIntervalApi>
export type LogsAlertStateIntervalApiOutput = zod.output<typeof LogsAlertStateIntervalApi>

export const NotificationDestinationTypeEnumApi = zod
    .enum(['slack', 'webhook', 'teams'])
    .describe('\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams')

export type NotificationDestinationTypeEnumApi = zod.input<typeof NotificationDestinationTypeEnumApi>
export type NotificationDestinationTypeEnumApiOutput = zod.output<typeof NotificationDestinationTypeEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const logsAlertConfigurationApiNameMax = 255

export const logsAlertConfigurationApiEnabledDefault = true
export const logsAlertConfigurationApiThresholdCountDefault = 100
export const logsAlertConfigurationApiThresholdCountMin = 0

export const logsAlertConfigurationApiThresholdOperatorDefault = `above`
export const logsAlertConfigurationApiWindowMinutesDefault = 5
export const logsAlertConfigurationApiEvaluationPeriodsDefault = 1
export const logsAlertConfigurationApiEvaluationPeriodsMax = 10

export const logsAlertConfigurationApiDatapointsToAlarmDefault = 1
export const logsAlertConfigurationApiDatapointsToAlarmMax = 10

export const logsAlertConfigurationApiCooldownMinutesDefault = 0
export const logsAlertConfigurationApiCooldownMinutesMin = 0

export const LogsAlertConfigurationApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this alert.'),
    name: zod
        .string()
        .max(logsAlertConfigurationApiNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .default(logsAlertConfigurationApiEnabledDefault)
        .describe('Whether the alert is actively being evaluated. Disabling resets the state to not_firing.'),
    filters: LogsAlertFiltersApi.optional().describe(
        'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).'
    ),
    threshold_count: zod
        .number()
        .min(logsAlertConfigurationApiThresholdCountMin)
        .default(logsAlertConfigurationApiThresholdCountDefault)
        .describe(
            "Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching log."
        ),
    threshold_operator: LogsAlertThresholdOperatorEnumApi.default(
        logsAlertConfigurationApiThresholdOperatorDefault
    ).describe(
        'Whether the alert fires when the count is above or below the threshold.\n\n\* `above` - Above\n\* `below` - Below'
    ),
    window_minutes: zod
        .number()
        .default(logsAlertConfigurationApiWindowMinutesDefault)
        .describe('Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.'),
    check_interval_minutes: zod.number().describe('How often the alert is evaluated, in minutes. Server-managed.'),
    state: LogsAlertConfigurationStateEnumApi.describe(
        'Current alert state: not_firing, firing, pending_resolve, errored, or snoozed. Server-managed.\n\n\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `pending_resolve` - Pending resolve\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
    ),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertConfigurationApiEvaluationPeriodsMax)
        .default(logsAlertConfigurationApiEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertConfigurationApiDatapointsToAlarmMax)
        .default(logsAlertConfigurationApiDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertConfigurationApiCooldownMinutesMin)
        .default(logsAlertConfigurationApiCooldownMinutesDefault)
        .describe('Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.'),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
    next_check_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the next evaluation is scheduled. Server-managed.'),
    last_notified_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the last notification was sent. Server-managed.'),
    last_checked_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the alert was last evaluated. Server-managed.'),
    consecutive_failures: zod
        .number()
        .describe('Number of consecutive evaluation failures. Resets on success. Server-managed.'),
    last_error_message: zod
        .string()
        .nullable()
        .describe(
            "Error message from the most recent errored check, or null if the alert's most recent check was successful. Sourced from LogsAlertEvent without denormalization so retention-aware cleanup rules stay the only source of truth."
        ),
    state_timeline: zod
        .array(LogsAlertStateIntervalApi)
        .describe(
            "Continuous state intervals over the last 24h, ordered oldest-first. Each interval covers a span during which (state, enabled) was constant. Derived from LogsAlertEvent rows walked in chronological order; consecutive identical intervals are collapsed. Drives the 'Last 24h' status bar on the alert list."
        ),
    destination_types: zod
        .array(NotificationDestinationTypeEnumApi)
        .describe(
            "Notification destination types configured for this alert — e.g. 'slack', 'webhook'. Empty list means no notifications will fire. One or more destinations should be added after creating an alert."
        ),
    first_enabled_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the alert was first enabled. Null means the alert is still in draft state.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the alert was created.'),
    created_by: UserBasicApi,
    updated_at: zod.iso.datetime({ offset: true }).nullable().describe('When the alert was last modified.'),
})

export type LogsAlertConfigurationApi = zod.input<typeof LogsAlertConfigurationApi>
export type LogsAlertConfigurationApiOutput = zod.output<typeof LogsAlertConfigurationApi>

export const PaginatedLogsAlertConfigurationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LogsAlertConfigurationApi),
})

export type PaginatedLogsAlertConfigurationListApi = zod.input<typeof PaginatedLogsAlertConfigurationListApi>
export type PaginatedLogsAlertConfigurationListApiOutput = zod.output<typeof PaginatedLogsAlertConfigurationListApi>

export const patchedLogsAlertConfigurationApiNameMax = 255

export const patchedLogsAlertConfigurationApiEnabledDefault = true
export const patchedLogsAlertConfigurationApiThresholdCountDefault = 100
export const patchedLogsAlertConfigurationApiThresholdCountMin = 0

export const patchedLogsAlertConfigurationApiThresholdOperatorDefault = `above`
export const patchedLogsAlertConfigurationApiWindowMinutesDefault = 5
export const patchedLogsAlertConfigurationApiEvaluationPeriodsDefault = 1
export const patchedLogsAlertConfigurationApiEvaluationPeriodsMax = 10

export const patchedLogsAlertConfigurationApiDatapointsToAlarmDefault = 1
export const patchedLogsAlertConfigurationApiDatapointsToAlarmMax = 10

export const patchedLogsAlertConfigurationApiCooldownMinutesDefault = 0
export const patchedLogsAlertConfigurationApiCooldownMinutesMin = 0

export const PatchedLogsAlertConfigurationApi = zod.object({
    id: zod.uuid().optional().describe('Unique identifier for this alert.'),
    name: zod
        .string()
        .max(patchedLogsAlertConfigurationApiNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .default(patchedLogsAlertConfigurationApiEnabledDefault)
        .describe('Whether the alert is actively being evaluated. Disabling resets the state to not_firing.'),
    filters: LogsAlertFiltersApi.optional().describe(
        'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).'
    ),
    threshold_count: zod
        .number()
        .min(patchedLogsAlertConfigurationApiThresholdCountMin)
        .default(patchedLogsAlertConfigurationApiThresholdCountDefault)
        .describe(
            "Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100. Use 0 with the 'above' operator to fire on any matching log."
        ),
    threshold_operator: LogsAlertThresholdOperatorEnumApi.default(
        patchedLogsAlertConfigurationApiThresholdOperatorDefault
    ).describe(
        'Whether the alert fires when the count is above or below the threshold.\n\n\* `above` - Above\n\* `below` - Below'
    ),
    window_minutes: zod
        .number()
        .default(patchedLogsAlertConfigurationApiWindowMinutesDefault)
        .describe('Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.'),
    check_interval_minutes: zod
        .number()
        .optional()
        .describe('How often the alert is evaluated, in minutes. Server-managed.'),
    state: LogsAlertConfigurationStateEnumApi.optional().describe(
        'Current alert state: not_firing, firing, pending_resolve, errored, or snoozed. Server-managed.\n\n\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `pending_resolve` - Pending resolve\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
    ),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(patchedLogsAlertConfigurationApiEvaluationPeriodsMax)
        .default(patchedLogsAlertConfigurationApiEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(patchedLogsAlertConfigurationApiDatapointsToAlarmMax)
        .default(patchedLogsAlertConfigurationApiDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(patchedLogsAlertConfigurationApiCooldownMinutesMin)
        .default(patchedLogsAlertConfigurationApiCooldownMinutesDefault)
        .describe('Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.'),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
    next_check_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When the next evaluation is scheduled. Server-managed.'),
    last_notified_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When the last notification was sent. Server-managed.'),
    last_checked_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When the alert was last evaluated. Server-managed.'),
    consecutive_failures: zod
        .number()
        .optional()
        .describe('Number of consecutive evaluation failures. Resets on success. Server-managed.'),
    last_error_message: zod
        .string()
        .nullish()
        .describe(
            "Error message from the most recent errored check, or null if the alert's most recent check was successful. Sourced from LogsAlertEvent without denormalization so retention-aware cleanup rules stay the only source of truth."
        ),
    state_timeline: zod
        .array(LogsAlertStateIntervalApi)
        .optional()
        .describe(
            "Continuous state intervals over the last 24h, ordered oldest-first. Each interval covers a span during which (state, enabled) was constant. Derived from LogsAlertEvent rows walked in chronological order; consecutive identical intervals are collapsed. Drives the 'Last 24h' status bar on the alert list."
        ),
    destination_types: zod
        .array(NotificationDestinationTypeEnumApi)
        .optional()
        .describe(
            "Notification destination types configured for this alert — e.g. 'slack', 'webhook'. Empty list means no notifications will fire. One or more destinations should be added after creating an alert."
        ),
    first_enabled_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When the alert was first enabled. Null means the alert is still in draft state.'),
    created_at: zod.iso.datetime({ offset: true }).optional().describe('When the alert was created.'),
    created_by: UserBasicApi.optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish().describe('When the alert was last modified.'),
})

export type PatchedLogsAlertConfigurationApi = zod.input<typeof PatchedLogsAlertConfigurationApi>
export type PatchedLogsAlertConfigurationApiOutput = zod.output<typeof PatchedLogsAlertConfigurationApi>

export const LogsAlertCreateDestinationApi = zod.object({
    type: NotificationDestinationTypeEnumApi.describe(
        'Notification destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams'
    ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod.url().optional().describe('HTTPS endpoint to post to. Required for webhook and teams.'),
})

export type LogsAlertCreateDestinationApi = zod.input<typeof LogsAlertCreateDestinationApi>
export type LogsAlertCreateDestinationApiOutput = zod.output<typeof LogsAlertCreateDestinationApi>

export const LogsAlertDestinationResponseApi = zod.object({
    hog_function_ids: zod.array(zod.uuid()),
})

export type LogsAlertDestinationResponseApi = zod.input<typeof LogsAlertDestinationResponseApi>
export type LogsAlertDestinationResponseApiOutput = zod.output<typeof LogsAlertDestinationResponseApi>

export const logsAlertDeleteDestinationApiHogFunctionIdsMax = 4

export const LogsAlertDeleteDestinationApi = zod.object({
    hog_function_ids: zod
        .array(zod.uuid())
        .min(1)
        .max(logsAlertDeleteDestinationApiHogFunctionIdsMax)
        .describe('HogFunction IDs to delete as one atomic destination group.'),
})

export type LogsAlertDeleteDestinationApi = zod.input<typeof LogsAlertDeleteDestinationApi>
export type LogsAlertDeleteDestinationApiOutput = zod.output<typeof LogsAlertDeleteDestinationApi>

export const LogsAlertEventKindEnumApi = zod
    .enum(['check', 'reset', 'enable', 'disable', 'snooze', 'unsnooze', 'threshold_change', 'broken_config'])
    .describe(
        '\* `check` - Check\n\* `reset` - Reset\n\* `enable` - Enable\n\* `disable` - Disable\n\* `snooze` - Snooze\n\* `unsnooze` - Unsnooze\n\* `threshold_change` - Threshold change\n\* `broken_config` - Broken config'
    )

export type LogsAlertEventKindEnumApi = zod.input<typeof LogsAlertEventKindEnumApi>
export type LogsAlertEventKindEnumApiOutput = zod.output<typeof LogsAlertEventKindEnumApi>

export const LogsAlertEventApi = zod.object({
    id: zod.uuid(),
    created_at: zod.iso.datetime({ offset: true }),
    kind: LogsAlertEventKindEnumApi,
    state_before: zod.string(),
    state_after: zod.string(),
    threshold_breached: zod.boolean(),
    result_count: zod.number().nullable(),
    error_message: zod.string().nullable(),
    query_duration_ms: zod.number().nullable(),
})

export type LogsAlertEventApi = zod.input<typeof LogsAlertEventApi>
export type LogsAlertEventApiOutput = zod.output<typeof LogsAlertEventApi>

export const PaginatedLogsAlertEventListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LogsAlertEventApi),
})

export type PaginatedLogsAlertEventListApi = zod.input<typeof PaginatedLogsAlertEventListApi>
export type PaginatedLogsAlertEventListApiOutput = zod.output<typeof PaginatedLogsAlertEventListApi>

export const logsAlertSimulateRequestApiThresholdCountMin = 0

export const logsAlertSimulateRequestApiCheckIntervalMinutesDefault = 5
export const logsAlertSimulateRequestApiCheckIntervalMinutesMax = 60

export const logsAlertSimulateRequestApiEvaluationPeriodsDefault = 1
export const logsAlertSimulateRequestApiEvaluationPeriodsMax = 10

export const logsAlertSimulateRequestApiDatapointsToAlarmDefault = 1
export const logsAlertSimulateRequestApiDatapointsToAlarmMax = 10

export const logsAlertSimulateRequestApiCooldownMinutesDefault = 0
export const logsAlertSimulateRequestApiCooldownMinutesMin = 0

export const LogsAlertSimulateRequestApi = zod.object({
    filters: LogsAlertFiltersApi.describe('Filter criteria — same format as LogsAlertConfiguration.filters.'),
    threshold_count: zod
        .number()
        .min(logsAlertSimulateRequestApiThresholdCountMin)
        .describe('Threshold count to evaluate against.'),
    threshold_operator: LogsAlertThresholdOperatorEnumApi.describe(
        'Whether the alert fires when the count is above or below the threshold.\n\n\* `above` - Above\n\* `below` - Below'
    ),
    window_minutes: zod.number().describe('Window size in minutes — determines bucket interval.'),
    check_interval_minutes: zod
        .number()
        .min(1)
        .max(logsAlertSimulateRequestApiCheckIntervalMinutesMax)
        .default(logsAlertSimulateRequestApiCheckIntervalMinutesDefault)
        .describe('How often the alert is evaluated, in minutes.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertSimulateRequestApiEvaluationPeriodsMax)
        .default(logsAlertSimulateRequestApiEvaluationPeriodsDefault)
        .describe('Total check periods in the N-of-M evaluation window (M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertSimulateRequestApiDatapointsToAlarmMax)
        .default(logsAlertSimulateRequestApiDatapointsToAlarmDefault)
        .describe('How many periods must breach to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertSimulateRequestApiCooldownMinutesMin)
        .default(logsAlertSimulateRequestApiCooldownMinutesDefault)
        .describe('Minutes to wait after firing before sending another notification.'),
    date_from: zod.string().describe("Relative date string for how far back to simulate (e.g. '-24h', '-7d', '-30d')."),
})

export type LogsAlertSimulateRequestApi = zod.input<typeof LogsAlertSimulateRequestApi>
export type LogsAlertSimulateRequestApiOutput = zod.output<typeof LogsAlertSimulateRequestApi>

export const LogsAlertSimulateBucketApi = zod.object({
    timestamp: zod.iso.datetime({ offset: true }).describe('Bucket start timestamp.'),
    count: zod.number().describe('Number of matching logs in this bucket.'),
    threshold_breached: zod.boolean().describe('Whether the count crossed the threshold in this bucket.'),
    state: zod.string().describe('Alert state after evaluating this bucket.'),
    notification: zod.string().describe('Notification action: none, fire, or resolve.'),
    reason: zod.string().describe('Human-readable explanation of the state transition.'),
})

export type LogsAlertSimulateBucketApi = zod.input<typeof LogsAlertSimulateBucketApi>
export type LogsAlertSimulateBucketApiOutput = zod.output<typeof LogsAlertSimulateBucketApi>

export const LogsAlertSimulateResponseApi = zod.object({
    buckets: zod.array(LogsAlertSimulateBucketApi).describe('Time-bucketed counts with full state machine evaluation.'),
    fire_count: zod.number().describe('Number of times the alert would have sent a fire notification.'),
    resolve_count: zod.number().describe('Number of times the alert would have sent a resolve notification.'),
    total_buckets: zod.number().describe('Total number of buckets in the simulation window.'),
    threshold_count: zod.number().describe('Threshold count used for evaluation.'),
    threshold_operator: zod.string().describe('Threshold operator used for evaluation.'),
})

export type LogsAlertSimulateResponseApi = zod.input<typeof LogsAlertSimulateResponseApi>
export type LogsAlertSimulateResponseApiOutput = zod.output<typeof LogsAlertSimulateResponseApi>

export const _DateRangeApi = zod.object({
    date_from: zod
        .string()
        .nullish()
        .describe('Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'),
    date_to: zod
        .string()
        .nullish()
        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
})

export type _DateRangeApi = zod.input<typeof _DateRangeApi>
export type _DateRangeApiOutput = zod.output<typeof _DateRangeApi>

export const _LogPropertyFilterTypeEnumApi = zod
    .enum(['log', 'log_attribute', 'log_resource_attribute'])
    .describe(
        '\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute'
    )

export type _LogPropertyFilterTypeEnumApi = zod.input<typeof _LogPropertyFilterTypeEnumApi>
export type _LogPropertyFilterTypeEnumApiOutput = zod.output<typeof _LogPropertyFilterTypeEnumApi>

export const _LogPropertyFilterOperatorEnumApi = zod
    .enum([
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'starts_with',
        'not_starts_with',
        'ends_with',
        'not_ends_with',
        'regex',
        'not_regex',
        'gt',
        'lt',
        'is_date_exact',
        'is_date_before',
        'is_date_after',
        'is_set',
        'is_not_set',
    ])
    .describe(
        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
    )

export type _LogPropertyFilterOperatorEnumApi = zod.input<typeof _LogPropertyFilterOperatorEnumApi>
export type _LogPropertyFilterOperatorEnumApiOutput = zod.output<typeof _LogPropertyFilterOperatorEnumApi>

export const _LogPropertyFilterApi = zod.object({
    key: zod
        .string()
        .describe(
            'Attribute key. For type \"log\", use \"message\". For \"log_attribute\"\/\"log_resource_attribute\", use the attribute key (e.g. \"k8s.container.name\").'
        ),
    type: _LogPropertyFilterTypeEnumApi.describe(
        '\"log\" filters the log body\/message. \"log_attribute\" filters log-level attributes. \"log_resource_attribute\" filters resource-level attributes.\n\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute'
    ),
    operator: _LogPropertyFilterOperatorEnumApi.describe(
        'Comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex\n\* `gt` - gt\n\* `lt` - lt\n\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
    ),
    value: zod
        .unknown()
        .optional()
        .describe(
            'Value to compare against. String, number, or array of strings. Omit for is_set\/is_not_set operators.'
        ),
})

export type _LogPropertyFilterApi = zod.input<typeof _LogPropertyFilterApi>
export type _LogPropertyFilterApiOutput = zod.output<typeof _LogPropertyFilterApi>

export const MatchedOnEnumApi = zod.enum(['key', 'value']).describe('\* `key` - key\n\* `value` - value')

export type MatchedOnEnumApi = zod.input<typeof MatchedOnEnumApi>
export type MatchedOnEnumApiOutput = zod.output<typeof MatchedOnEnumApi>

export const _LogAttributeEntryApi = zod.object({
    name: zod.string(),
    propertyFilterType: zod
        .string()
        .describe(
            'Property filter type: \"log_attribute\" or \"log_resource_attribute\". Use this as the `type` field when filtering.'
        ),
    matchedOn: MatchedOnEnumApi.describe(
        'How the search query matched this row: \"key\" if the attribute key matched, \"value\" if a value matched.\n\n\* `key` - key\n\* `value` - value'
    ),
    matchedValue: zod.string().nullish().describe('Sample matching value — only set when matchedOn is \"value\".'),
})

export type _LogAttributeEntryApi = zod.input<typeof _LogAttributeEntryApi>
export type _LogAttributeEntryApiOutput = zod.output<typeof _LogAttributeEntryApi>

export const _LogsAttributesResponseApi = zod.object({
    results: zod.array(_LogAttributeEntryApi).describe('Available attribute keys matching the filters.'),
    count: zod.number().describe('Total attribute keys matched (not paginated).'),
})

export type _LogsAttributesResponseApi = zod.input<typeof _LogsAttributesResponseApi>
export type _LogsAttributesResponseApiOutput = zod.output<typeof _LogsAttributesResponseApi>

export const SeverityLevelsEnumApi = zod
    .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
    .describe(
        '\* `trace` - trace\n\* `debug` - debug\n\* `info` - info\n\* `warn` - warn\n\* `error` - error\n\* `fatal` - fatal'
    )

export type SeverityLevelsEnumApi = zod.input<typeof SeverityLevelsEnumApi>
export type SeverityLevelsEnumApiOutput = zod.output<typeof SeverityLevelsEnumApi>

export const _LogsCountBodyApi = zod.object({
    dateRange: _DateRangeApi.optional().describe('Date range for the count. Defaults to last hour.'),
    severityLevels: zod.array(SeverityLevelsEnumApi).optional().describe('Filter by log severity levels.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
    searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
    filterGroup: zod.array(_LogPropertyFilterApi).optional().describe('Property filters for the query.'),
})

export type _LogsCountBodyApi = zod.input<typeof _LogsCountBodyApi>
export type _LogsCountBodyApiOutput = zod.output<typeof _LogsCountBodyApi>

export const _LogsCountRequestApi = zod.object({
    query: _LogsCountBodyApi.describe('The count query to execute.'),
})

export type _LogsCountRequestApi = zod.input<typeof _LogsCountRequestApi>
export type _LogsCountRequestApiOutput = zod.output<typeof _LogsCountRequestApi>

export const _LogsCountResponseApi = zod.object({
    count: zod.number().describe('Number of log entries matching the filters.'),
})

export type _LogsCountResponseApi = zod.input<typeof _LogsCountResponseApi>
export type _LogsCountResponseApiOutput = zod.output<typeof _LogsCountResponseApi>

export const _logsCountRangesBodyApiTargetBucketsDefault = 10
export const _logsCountRangesBodyApiTargetBucketsMax = 100

export const _LogsCountRangesBodyApi = zod.object({
    dateRange: _DateRangeApi
        .optional()
        .describe(
            "Window to bucket. Defaults to last hour. Use a bucket's date_from\/date_to from a prior response to recursively narrow into a sub-range."
        ),
    targetBuckets: zod
        .number()
        .min(1)
        .max(_logsCountRangesBodyApiTargetBucketsMax)
        .default(_logsCountRangesBodyApiTargetBucketsDefault)
        .describe(
            'Approximate number of buckets to return. The bucket interval is picked adaptively from a fixed list (1\/5\/10s, 1\/2\/5\/10\/15\/30\/60\/120\/240\/360\/720\/1440m) to land near this target. Defaults to 10, capped at 100.'
        ),
    severityLevels: zod
        .array(SeverityLevelsEnumApi)
        .optional()
        .describe('Filter by log severity levels. Applied before bucketing.'),
    serviceNames: zod.array(zod.string()).optional().describe('Filter by service names. Applied before bucketing.'),
    searchTerm: zod.string().optional().describe('Full-text search across log bodies. Applied before bucketing.'),
    filterGroup: zod
        .array(_LogPropertyFilterApi)
        .optional()
        .describe('Property filters applied before bucketing. Same shape as `query-logs`.'),
})

export type _LogsCountRangesBodyApi = zod.input<typeof _LogsCountRangesBodyApi>
export type _LogsCountRangesBodyApiOutput = zod.output<typeof _LogsCountRangesBodyApi>

export const _LogsCountRangesRequestApi = zod.object({
    query: _LogsCountRangesBodyApi.describe('The bucketed-count query to execute.'),
})

export type _LogsCountRangesRequestApi = zod.input<typeof _LogsCountRangesRequestApi>
export type _LogsCountRangesRequestApiOutput = zod.output<typeof _LogsCountRangesRequestApi>

export const _LogsCountRangeBucketApi = zod.object({
    date_from: zod
        .string()
        .describe(
            'Bucket start as ISO 8601 timestamp. Inclusive lower bound. Pass back as `dateRange.date_from` to drill in.'
        ),
    date_to: zod
        .string()
        .describe(
            'Bucket end as ISO 8601 timestamp. Exclusive upper bound. Pass back as `dateRange.date_to` to drill in.'
        ),
    count: zod.number().describe('Log entries matching the filters within this bucket.'),
})

export type _LogsCountRangeBucketApi = zod.input<typeof _LogsCountRangeBucketApi>
export type _LogsCountRangeBucketApiOutput = zod.output<typeof _LogsCountRangeBucketApi>

export const _LogsCountRangesResponseApi = zod.object({
    ranges: zod
        .array(_LogsCountRangeBucketApi)
        .describe(
            "Buckets ordered by `date_from` ascending. Empty buckets are omitted — infer gaps by comparing each bucket's `date_to` to the next bucket's `date_from`."
        ),
    interval: zod
        .string()
        .describe(
            'Short-form duration of the chosen bucket width (e.g. \"1h\", \"5m\", \"30s\", \"1d\"). Informational only — use each bucket\'s `date_from`\/`date_to` for follow-up queries.'
        ),
})

export type _LogsCountRangesResponseApi = zod.input<typeof _LogsCountRangesResponseApi>
export type _LogsCountRangesResponseApiOutput = zod.output<typeof _LogsCountRangesResponseApi>

export const explainRequestApiForceRefreshDefault = false

export const ExplainRequestApi = zod.object({
    uuid: zod.string().describe('UUID of the log entry to explain'),
    timestamp: zod.iso.datetime({ offset: true }).describe('Timestamp of the log entry (used for efficient lookup)'),
    force_refresh: zod
        .boolean()
        .default(explainRequestApiForceRefreshDefault)
        .describe('Force regenerate explanation, bypassing cache'),
})

export type ExplainRequestApi = zod.input<typeof ExplainRequestApi>
export type ExplainRequestApiOutput = zod.output<typeof ExplainRequestApi>

export const FacetFieldEnumApi = zod
    .enum(['severity_text', 'service_name'])
    .describe('\* `severity_text` - severity_text\n\* `service_name` - service_name')

export type FacetFieldEnumApi = zod.input<typeof FacetFieldEnumApi>
export type FacetFieldEnumApiOutput = zod.output<typeof FacetFieldEnumApi>

export const _LogsFacetValuesBodyApi = zod.object({
    facetField: zod
        .union([FacetFieldEnumApi, zod.null()])
        .optional()
        .describe(
            'Top-level column to facet on. Provide exactly one of facetField or facetResourceAttribute. Its own filter is excluded so counts reflect the other active filters.\n\n\* `severity_text` - severity_text\n\* `service_name` - service_name'
        ),
    facetResourceAttribute: zod
        .string()
        .nullish()
        .describe(
            "Resource attribute key to facet on (e.g. 'k8s.namespace.name'). Provide exactly one of facetField or facetResourceAttribute. Its own log_resource_attribute filter is excluded so counts reflect the other active filters."
        ),
    dateRange: _DateRangeApi.optional().describe('Date range. Defaults to last hour.'),
    severityLevels: zod
        .array(SeverityLevelsEnumApi)
        .optional()
        .describe('Filter by log severity levels (ignored when faceting on severity_text).'),
    serviceNames: zod
        .array(zod.string())
        .optional()
        .describe('Filter by service names (ignored when faceting on service_name).'),
    searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
    facetSearch: zod
        .string()
        .optional()
        .describe(
            "Type-ahead filter over the faceted field's own values (case-insensitive substring match). Distinct from searchTerm, which searches log bodies."
        ),
    filterGroup: zod.array(_LogPropertyFilterApi).optional().describe('Property filters for the query.'),
    personId: zod
        .string()
        .optional()
        .describe(
            "Scope counts to one person (UUID or numeric ID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id log attribute keys."
        ),
})

export type _LogsFacetValuesBodyApi = zod.input<typeof _LogsFacetValuesBodyApi>
export type _LogsFacetValuesBodyApiOutput = zod.output<typeof _LogsFacetValuesBodyApi>

export const _LogsFacetValuesRequestApi = zod.object({
    query: _LogsFacetValuesBodyApi.describe('The facet values query to execute.'),
})

export type _LogsFacetValuesRequestApi = zod.input<typeof _LogsFacetValuesRequestApi>
export type _LogsFacetValuesRequestApiOutput = zod.output<typeof _LogsFacetValuesRequestApi>

export const _LogFacetValueApi = zod.object({
    value: zod.string().describe('The facet value (e.g. a severity level or service name).'),
    count: zod
        .number()
        .describe("Number of matching log records, with all active filters applied except this facet's own selection."),
})

export type _LogFacetValueApi = zod.input<typeof _LogFacetValueApi>
export type _LogFacetValueApiOutput = zod.output<typeof _LogFacetValueApi>

export const _LogsFacetValuesResponseApi = zod.object({
    results: zod
        .array(_LogFacetValueApi)
        .describe('Facet values with cross-filtered counts, ordered by count descending.'),
})

export type _LogsFacetValuesResponseApi = zod.input<typeof _LogsFacetValuesResponseApi>
export type _LogsFacetValuesResponseApiOutput = zod.output<typeof _LogsFacetValuesResponseApi>

export const LogsGroupBySourceEnumApi = zod
    .enum(['log', 'resource', 'column'])
    .describe('\* `log` - log\n\* `resource` - resource\n\* `column` - column')

export type LogsGroupBySourceEnumApi = zod.input<typeof LogsGroupBySourceEnumApi>
export type LogsGroupBySourceEnumApiOutput = zod.output<typeof LogsGroupBySourceEnumApi>

export const _logsGroupByDimensionApiSourceDefault = `log`

export const _LogsGroupByDimensionApi = zod.object({
    key: zod
        .string()
        .describe(
            'The key this dimension groups by — an attribute key (e.g. \"session_id\", \"service.name\") or, when source is \"column\", one of the top-level log fields: \"severity_level\", \"trace_id\", \"span_id\".'
        ),
    source: LogsGroupBySourceEnumApi.default(_logsGroupByDimensionApiSourceDefault).describe(
        'Where this dimension\'s key lives: \"log\" for log-level attributes, \"resource\" for resource-level attributes, \"column\" for top-level log fields.\n\n\* `log` - log\n\* `resource` - resource\n\* `column` - column'
    ),
})

export type _LogsGroupByDimensionApi = zod.input<typeof _LogsGroupByDimensionApi>
export type _LogsGroupByDimensionApiOutput = zod.output<typeof _LogsGroupByDimensionApi>

export const OrderGroupsByEnumApi = zod
    .enum(['log_count', 'error_count', 'last_seen'])
    .describe('\* `log_count` - log_count\n\* `error_count` - error_count\n\* `last_seen` - last_seen')

export type OrderGroupsByEnumApi = zod.input<typeof OrderGroupsByEnumApi>
export type OrderGroupsByEnumApiOutput = zod.output<typeof OrderGroupsByEnumApi>

export const _logsGroupByBodyApiGroupBySourceDefault = `log`
export const _logsGroupByBodyApiGroupBysMax = 4

export const _logsGroupByBodyApiOrderGroupsByDefault = `log_count`
export const _logsGroupByBodyApiLimitDefault = 100
export const _logsGroupByBodyApiLimitMax = 500

export const _LogsGroupByBodyApi = zod.object({
    dateRange: _DateRangeApi.optional().describe('Date range to aggregate over. Defaults to last hour.'),
    severityLevels: zod
        .array(SeverityLevelsEnumApi)
        .optional()
        .describe('Filter by log severity levels before grouping.'),
    serviceNames: zod.array(zod.string()).optional().describe('Restrict grouping to these service names.'),
    searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies before grouping.'),
    filterGroup: zod
        .array(_LogPropertyFilterApi)
        .optional()
        .describe('Property filters applied before grouping. Same shape as the query-logs endpoint.'),
    groupBy: zod
        .string()
        .optional()
        .describe(
            'The key to group logs by — an attribute key (e.g. \"session_id\", \"service.name\") or, when groupBySource is \"column\", one of the top-level log fields: \"severity_level\", \"trace_id\", \"span_id\". Ignored when groupBys is provided.'
        ),
    groupBySource: LogsGroupBySourceEnumApi.default(_logsGroupByBodyApiGroupBySourceDefault).describe(
        'Where the grouping key lives: \"log\" for log-level attributes, \"resource\" for resource-level attributes, \"column\" for top-level log fields. Ignored when groupBys is provided.\n\n\* `log` - log\n\* `resource` - resource\n\* `column` - column'
    ),
    groupBys: zod
        .array(_LogsGroupByDimensionApi)
        .min(1)
        .max(_logsGroupByBodyApiGroupBysMax)
        .optional()
        .describe(
            'Ordered group-by dimensions to combine (a group is one combination of per-dimension values), up to 4. Takes precedence over groupBy\/groupBySource; one of the two must be provided.'
        ),
    orderGroupsBy: OrderGroupsByEnumApi.default(_logsGroupByBodyApiOrderGroupsByDefault).describe(
        'Aggregate to rank groups by (descending): \"log_count\" for the noisiest groups, \"error_count\" for the most failing, \"last_seen\" for the most recent.\n\n\* `log_count` - log_count\n\* `error_count` - error_count\n\* `last_seen` - last_seen'
    ),
    limit: zod
        .number()
        .min(1)
        .max(_logsGroupByBodyApiLimitMax)
        .default(_logsGroupByBodyApiLimitDefault)
        .describe('Maximum number of groups to return (top-N by orderGroupsBy). Defaults to 100.'),
})

export type _LogsGroupByBodyApi = zod.input<typeof _LogsGroupByBodyApi>
export type _LogsGroupByBodyApiOutput = zod.output<typeof _LogsGroupByBodyApi>

export const _LogsGroupByRequestApi = zod.object({
    query: _LogsGroupByBodyApi.describe('The group-by query to execute.'),
})

export type _LogsGroupByRequestApi = zod.input<typeof _LogsGroupByRequestApi>
export type _LogsGroupByRequestApiOutput = zod.output<typeof _LogsGroupByRequestApi>

export const _LogsGroupByGroupApi = zod.object({
    value: zod
        .string()
        .describe("The first dimension's grouped value. Kept for single-dimension callers; prefer `values`."),
    values: zod.array(zod.string()).describe("This group's values, one per requested dimension, in request order."),
    log_count: zod.number().describe('Number of matching logs in this group.'),
    error_count: zod.number().describe('Number of matching logs in this group at severity \"error\" or \"fatal\".'),
    last_seen: zod.string().describe('ISO 8601 timestamp of the most recent matching log in this group.'),
})

export type _LogsGroupByGroupApi = zod.input<typeof _LogsGroupByGroupApi>
export type _LogsGroupByGroupApiOutput = zod.output<typeof _LogsGroupByGroupApi>

export const _LogsGroupByResponseApi = zod.object({
    groups: zod
        .array(_LogsGroupByGroupApi)
        .describe('Top groups ordered by the requested aggregate, descending. Capped at `limit`.'),
    total_groups: zod.number().describe('Total distinct group values matching the filters, before the top-N cap.'),
    total_logs: zod
        .number()
        .describe('Total matching logs across all groups (rows without the grouping key are excluded).'),
    truncated: zod
        .boolean()
        .describe('True when more groups matched than were returned (total_groups > groups length).'),
})

export type _LogsGroupByResponseApi = zod.input<typeof _LogsGroupByResponseApi>
export type _LogsGroupByResponseApiOutput = zod.output<typeof _LogsGroupByResponseApi>

export const logsMetricRuleApiNameMax = 255

export const logsMetricRuleApiMetricNameMax = 200

export const logsMetricRuleApiEnabledDefault = false
export const logsMetricRuleApiValueAttributeMax = 512

export const logsMetricRuleApiGroupByItemMax = 512

export const LogsMetricRuleApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this metric rule.'),
    name: zod.string().max(logsMetricRuleApiNameMax).describe('User-visible label for this rule.'),
    metric_name: zod
        .string()
        .max(logsMetricRuleApiMetricNameMax)
        .describe(
            'Name of the generated metric as it appears in the Metrics product. Must start with a letter and contain only letters, digits, dots, underscores, and dashes. Unique per project and immutable after creation — create a new rule to emit under a different name.'
        ),
    enabled: zod
        .boolean()
        .default(logsMetricRuleApiEnabledDefault)
        .describe(
            'When true, ingestion evaluates this rule against every log record. At most 10 rules can be enabled per project.'
        ),
    filter_group: zod
        .unknown()
        .optional()
        .describe(
            'PropertyGroupFilter JSON (AND\/OR tree of property predicates) selecting which log records feed the metric, e.g. `{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\",\"type\":\"log_attribute\"}]}]}`. Null matches every ingested log record. Every group must contain at least one filter — empty groups never match.'
        ),
    value_attribute: zod
        .string()
        .max(logsMetricRuleApiValueAttributeMax)
        .nullish()
        .describe(
            'Log attribute key holding a numeric value to aggregate into a distribution (count + sum), e.g. `attributes.duration_ms` or `resource_attributes.batch.size`. Omit to count matching log records instead. Immutable after creation — it determines the emitted metric type.'
        ),
    group_by: zod
        .array(zod.string().max(logsMetricRuleApiGroupByItemMax))
        .optional()
        .describe(
            'Up to 5 dimension keys; each distinct value combination becomes its own metric series. Allowed: service_name, severity_text, event_name, or map keys prefixed with `attributes.` \/ `resource_attributes.`. Avoid high-cardinality keys (user IDs, request IDs) — excess series are dropped at ingestion.'
        ),
    version: zod.number().describe('Incremented on each update for worker cache coherency.'),
    created_by: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type LogsMetricRuleApi = zod.input<typeof LogsMetricRuleApi>
export type LogsMetricRuleApiOutput = zod.output<typeof LogsMetricRuleApi>

export const PaginatedLogsMetricRuleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LogsMetricRuleApi),
})

export type PaginatedLogsMetricRuleListApi = zod.input<typeof PaginatedLogsMetricRuleListApi>
export type PaginatedLogsMetricRuleListApiOutput = zod.output<typeof PaginatedLogsMetricRuleListApi>

export const patchedLogsMetricRuleApiNameMax = 255

export const patchedLogsMetricRuleApiMetricNameMax = 200

export const patchedLogsMetricRuleApiEnabledDefault = false
export const patchedLogsMetricRuleApiValueAttributeMax = 512

export const patchedLogsMetricRuleApiGroupByItemMax = 512

export const PatchedLogsMetricRuleApi = zod.object({
    id: zod.uuid().optional().describe('Unique identifier for this metric rule.'),
    name: zod.string().max(patchedLogsMetricRuleApiNameMax).optional().describe('User-visible label for this rule.'),
    metric_name: zod
        .string()
        .max(patchedLogsMetricRuleApiMetricNameMax)
        .optional()
        .describe(
            'Name of the generated metric as it appears in the Metrics product. Must start with a letter and contain only letters, digits, dots, underscores, and dashes. Unique per project and immutable after creation — create a new rule to emit under a different name.'
        ),
    enabled: zod
        .boolean()
        .default(patchedLogsMetricRuleApiEnabledDefault)
        .describe(
            'When true, ingestion evaluates this rule against every log record. At most 10 rules can be enabled per project.'
        ),
    filter_group: zod
        .unknown()
        .optional()
        .describe(
            'PropertyGroupFilter JSON (AND\/OR tree of property predicates) selecting which log records feed the metric, e.g. `{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\",\"type\":\"log_attribute\"}]}]}`. Null matches every ingested log record. Every group must contain at least one filter — empty groups never match.'
        ),
    value_attribute: zod
        .string()
        .max(patchedLogsMetricRuleApiValueAttributeMax)
        .nullish()
        .describe(
            'Log attribute key holding a numeric value to aggregate into a distribution (count + sum), e.g. `attributes.duration_ms` or `resource_attributes.batch.size`. Omit to count matching log records instead. Immutable after creation — it determines the emitted metric type.'
        ),
    group_by: zod
        .array(zod.string().max(patchedLogsMetricRuleApiGroupByItemMax))
        .optional()
        .describe(
            'Up to 5 dimension keys; each distinct value combination becomes its own metric series. Allowed: service_name, severity_text, event_name, or map keys prefixed with `attributes.` \/ `resource_attributes.`. Avoid high-cardinality keys (user IDs, request IDs) — excess series are dropped at ingestion.'
        ),
    version: zod.number().optional().describe('Incremented on each update for worker cache coherency.'),
    created_by: zod.number().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedLogsMetricRuleApi = zod.input<typeof PatchedLogsMetricRuleApi>
export type PatchedLogsMetricRuleApiOutput = zod.output<typeof PatchedLogsMetricRuleApi>

export const _LogsPatternsBodyApi = zod.object({
    dateRange: _DateRangeApi.optional().describe('Date range to mine patterns from. Defaults to last hour.'),
    severityLevels: zod
        .array(SeverityLevelsEnumApi)
        .optional()
        .describe('Filter by log severity levels before mining.'),
    serviceNames: zod.array(zod.string()).optional().describe('Restrict mining to these service names.'),
    searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies before mining.'),
    filterGroup: zod
        .array(_LogPropertyFilterApi)
        .optional()
        .describe('Property filters applied before mining. Same shape as the query-logs endpoint.'),
})

export type _LogsPatternsBodyApi = zod.input<typeof _LogsPatternsBodyApi>
export type _LogsPatternsBodyApiOutput = zod.output<typeof _LogsPatternsBodyApi>

export const _LogsPatternsRequestApi = zod.object({
    query: _LogsPatternsBodyApi.describe('The patterns query to execute.'),
})

export type _LogsPatternsRequestApi = zod.input<typeof _LogsPatternsRequestApi>
export type _LogsPatternsRequestApiOutput = zod.output<typeof _LogsPatternsRequestApi>

export const _LogPatternExampleApi = zod.object({
    body: zod
        .string()
        .describe(
            'Log body as the miner saw it: whitespace-collapsed and truncated to the mining length cap, not the raw stored line.'
        ),
    severity_text: zod.string().describe('Severity of the sampled line, e.g. \"info\", \"error\".'),
    service_name: zod.string().describe('Service that emitted the sampled line.'),
    timestamp: zod.string().describe('ISO 8601 timestamp of the sampled line.'),
})

export type _LogPatternExampleApi = zod.input<typeof _LogPatternExampleApi>
export type _LogPatternExampleApiOutput = zod.output<typeof _LogPatternExampleApi>

export const _LogPatternApi = zod.object({
    pattern: zod
        .string()
        .describe(
            'Mined log template with variable tokens masked, e.g. \"Connected to <ip> in <num>ms\". Tokens: <uuid>, <ip>, <hex>, <num>, plus <\*> for word positions Drain found to vary.'
        ),
    count: zod
        .number()
        .describe(
            'Occurrences of this pattern within the sample. When `sampled` is true this is a sample count, not the full-window total — prefer `estimated_count` for display.'
        ),
    estimated_count: zod
        .number()
        .describe(
            'Estimated occurrences across the full window, extrapolated from the sample (`count \/ scanned_count \* total_count`). Equals `count` when the window was not sampled.'
        ),
    volume_share_pct: zod.number().describe('Share of the sampled log volume this pattern represents (0–100).'),
    error_count: zod
        .number()
        .describe(
            'Sampled occurrences at severity \"error\" or \"fatal\". Prefer `estimated_error_count` for display.'
        ),
    estimated_error_count: zod
        .number()
        .describe(
            'Estimated error\/fatal occurrences across the full window, extrapolated from the sample. Equals `error_count` when the window was not sampled.'
        ),
    first_seen: zod.string().describe('ISO 8601 timestamp of the earliest sampled occurrence.'),
    last_seen: zod.string().describe('ISO 8601 timestamp of the latest sampled occurrence.'),
    examples: zod
        .array(_LogPatternExampleApi)
        .describe(
            'Up to 10 distinct sampled log lines that produced this pattern, with severity, service, and timestamp for display.'
        ),
    services: zod.array(zod.string()).describe('Up to 4 distinct service names this pattern was observed in.'),
    sparkline: zod
        .array(zod.number())
        .describe(
            "Estimated occurrences per time bucket, aligned index-for-index with the response's `sparkline_buckets`. Extrapolated from the sample like `estimated_count`, so it shows the volume shape over the window, not exact per-bucket tallies."
        ),
    severity_counts: zod
        .record(zod.string(), zod.number())
        .describe(
            'Sampled occurrences keyed by lowercased severity (\"trace\" through \"fatal\"). Raw sample counts, not extrapolated — severity dominance is a proportion, so scaling would not change it.'
        ),
    match_regex: zod
        .string()
        .nullable()
        .describe(
            "RE2-safe regex over raw log bodies that matches lines of this pattern, compiled from the template and validated against the pattern's own examples before being offered. Null when the template lacks literal content or validation failed — never trust an unvalidated predicate. Use with the message\/regex log property filter."
        ),
    match_literal: zod
        .string()
        .nullable()
        .describe(
            'Longest literal run in the template, for plain-text (icontains) filtering when `match_regex` is null. Null when the template has no usable literal content.'
        ),
})

export type _LogPatternApi = zod.input<typeof _LogPatternApi>
export type _LogPatternApiOutput = zod.output<typeof _LogPatternApi>

export const _LogsPatternsSparklineBucketApi = zod.object({
    start: zod.string().describe('Bucket start (ISO 8601, inclusive).'),
    end: zod.string().describe('Bucket end (ISO 8601, exclusive).'),
})

export type _LogsPatternsSparklineBucketApi = zod.input<typeof _LogsPatternsSparklineBucketApi>
export type _LogsPatternsSparklineBucketApiOutput = zod.output<typeof _LogsPatternsSparklineBucketApi>

export const _LogsPatternsResponseApi = zod.object({
    patterns: zod.array(_LogPatternApi).describe('Mined patterns ordered by `count` descending.'),
    scanned_count: zod
        .number()
        .describe('Number of log rows fed to the miner (the sample size, capped at the sample limit).'),
    total_count: zod
        .number()
        .describe(
            'Total log rows matching the filters in the window, before sampling. Use with `scanned_count` to scale per-pattern counts when `sampled` is true.'
        ),
    sampled: zod
        .boolean()
        .describe(
            'True when the window held more rows than the sample cap, so patterns were mined from a deterministic, evenly-distributed sample rather than every matching row.'
        ),
    sample_coverage_pct: zod
        .number()
        .describe(
            "Share of the window's log rows that were eligible for sampling (0–100). Below 100, the scan was bounded to evenly-spaced time slices across the window to keep the query within its execution budget; rows outside the slices could not appear in the sample."
        ),
    sparkline_buckets: zod
        .array(_LogsPatternsSparklineBucketApi)
        .describe(
            "Time buckets that every pattern's `sparkline` aligns to. When the scan was bounded to time slices, the buckets are the slices themselves (evenly spaced, gaps between them were never eligible for sampling); otherwise they divide the window uniformly."
        ),
})

export type _LogsPatternsResponseApi = zod.input<typeof _LogsPatternsResponseApi>
export type _LogsPatternsResponseApiOutput = zod.output<typeof _LogsPatternsResponseApi>

export const _LogsPatternsDiffRequestApi = zod.object({
    query: _LogsPatternsBodyApi.describe(
        'The patterns query for the current (foreground) window: date range plus any severity\/service\/search\/property filters. The same filters are applied to the baseline window.'
    ),
    baselineDateRange: _DateRangeApi
        .optional()
        .describe(
            'Baseline window to compare against. Omit to default to the current window shifted back exactly one week, which absorbs daily and weekly log-volume cycles. Pass an explicit range to compare against a specific period, e.g. pre-deploy or pre-incident.'
        ),
})

export type _LogsPatternsDiffRequestApi = zod.input<typeof _LogsPatternsDiffRequestApi>
export type _LogsPatternsDiffRequestApiOutput = zod.output<typeof _LogsPatternsDiffRequestApi>

export const _LogPatternDiffEntryClassificationEnumApi = zod
    .enum(['new', 'rate_shift', 'gone', 'unchanged'])
    .describe('\* `new` - new\n\* `rate_shift` - rate_shift\n\* `gone` - gone\n\* `unchanged` - unchanged')

export type _LogPatternDiffEntryClassificationEnumApi = zod.input<typeof _LogPatternDiffEntryClassificationEnumApi>
export type _LogPatternDiffEntryClassificationEnumApiOutput = zod.output<
    typeof _LogPatternDiffEntryClassificationEnumApi
>

export const _LogPatternDiffEntryApi = zod.object({
    classification: _LogPatternDiffEntryClassificationEnumApi.describe(
        '\"new\": appears only in the current window and clears the novelty floor (at least ~1% volume share, or any error\/fatal occurrences). \"rate_shift\": present in both windows with the per-second rate changed by at least 2x either way, backed by enough samples on both sides to trust the estimates. \"gone\": cleared the floor in the baseline but absent from the current window. \"unchanged\" means \"no confident claim\", not \"provably identical\" — sampled mining cannot prove a below-floor template is genuinely new or gone.\n\n\* `new` - new\n\* `rate_shift` - rate_shift\n\* `gone` - gone\n\* `unchanged` - unchanged'
    ),
    rate_ratio: zod
        .number()
        .nullable()
        .describe(
            'Current-window rate divided by baseline rate, both normalized per second so windows of different lengths compare fairly. 4.0 means 4x faster now; 0.25 means quartered. Null when the pattern is missing from either window.'
        ),
    pattern: _LogPatternApi.describe(
        'The mined pattern with full stats. Taken from the current window, or from the baseline window for \"gone\" entries. When template wobble split one message across several near-identical templates, this is the highest-volume representative and the entry\'s classification reflects their combined counts.'
    ),
    baseline_estimated_count: zod
        .number()
        .nullable()
        .describe(
            'Estimated occurrences across the baseline window (extrapolated like `estimated_count`). Null when the pattern was not seen in the baseline sample.'
        ),
    baseline_volume_share_pct: zod
        .number()
        .nullable()
        .describe('Share of the baseline sample this pattern represented (0-100). Null when absent from the baseline.'),
})

export type _LogPatternDiffEntryApi = zod.input<typeof _LogPatternDiffEntryApi>
export type _LogPatternDiffEntryApiOutput = zod.output<typeof _LogPatternDiffEntryApi>

export const _LogsPatternsDiffWindowApi = zod.object({
    scanned_count: zod.number().describe('Log rows fed to the miner for this window (sample size).'),
    total_count: zod.number().describe('Total log rows matching the filters in this window.'),
    sampled: zod.boolean().describe("True when this window's counts are extrapolated from a sample rather than exact."),
    sample_coverage_pct: zod
        .number()
        .describe(
            "Share of this window's rows eligible for sampling (0-100); below 100 the scan was time-slice bounded."
        ),
    date_from: zod.string().describe('Resolved window start (ISO 8601, inclusive).'),
    date_to: zod.string().describe('Resolved window end (ISO 8601, exclusive).'),
})

export type _LogsPatternsDiffWindowApi = zod.input<typeof _LogsPatternsDiffWindowApi>
export type _LogsPatternsDiffWindowApiOutput = zod.output<typeof _LogsPatternsDiffWindowApi>

export const _LogsPatternsDiffResponseApi = zod.object({
    entries: zod
        .array(_LogPatternDiffEntryApi)
        .describe(
            'Classified diff entries, most interesting first: \"new\" (by estimated count), then \"rate_shift\" (by shift magnitude), then \"gone\", then \"unchanged\". A pattern in the baseline is matched to the current window by literal-content fingerprint, so a placeholder widening between runs does not read as one pattern vanishing and another appearing.'
        ),
    current: _LogsPatternsDiffWindowApi.describe('Mining metadata for the current window.'),
    baseline: _LogsPatternsDiffWindowApi.describe(
        'Mining metadata for the baseline window. Check `total_count` before trusting a wall of \"new\" entries: an empty or tiny baseline (e.g. logging only started this week) makes everything look new.'
    ),
})

export type _LogsPatternsDiffResponseApi = zod.input<typeof _LogsPatternsDiffResponseApi>
export type _LogsPatternsDiffResponseApiOutput = zod.output<typeof _LogsPatternsDiffResponseApi>

export const OrderByEnumApi = zod
    .enum(['latest', 'earliest'])
    .describe('\* `latest` - latest\n\* `earliest` - earliest')

export type OrderByEnumApi = zod.input<typeof OrderByEnumApi>
export type OrderByEnumApiOutput = zod.output<typeof OrderByEnumApi>

export const _logsQueryBodyApiSeverityLevelsDefault = []
export const _logsQueryBodyApiServiceNamesDefault = []
export const _logsQueryBodyApiFilterGroupDefault = []
export const _logsQueryBodyApiLimitDefault = 100
export const _logsQueryBodyApiExcludeAttributesDefault = false
export const _logsQueryBodyApiCustomColumnsDefault = []

export const _LogsQueryBodyApi = zod.object({
    dateRange: _DateRangeApi.optional().describe('Date range for the query. Defaults to last hour.'),
    severityLevels: zod
        .array(SeverityLevelsEnumApi)
        .default(_logsQueryBodyApiSeverityLevelsDefault)
        .describe('Filter by log severity levels.'),
    serviceNames: zod
        .array(zod.string())
        .default(_logsQueryBodyApiServiceNamesDefault)
        .describe('Filter by service names.'),
    orderBy: OrderByEnumApi.optional().describe(
        'Order results by timestamp.\n\n\* `latest` - latest\n\* `earliest` - earliest'
    ),
    searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
    filterGroup: zod
        .array(_LogPropertyFilterApi)
        .default(_logsQueryBodyApiFilterGroupDefault)
        .describe('Property filters for the query.'),
    limit: zod.number().default(_logsQueryBodyApiLimitDefault).describe('Max results (1-1000).'),
    after: zod.string().optional().describe('Pagination cursor from previous response.'),
    excludeAttributes: zod
        .boolean()
        .default(_logsQueryBodyApiExcludeAttributesDefault)
        .describe(
            'Omit the per-log attributes and resource_attributes maps from results to keep payloads compact. Defaults to false.'
        ),
    customColumns: zod
        .array(zod.string())
        .default(_logsQueryBodyApiCustomColumnsDefault)
        .describe(
            "Custom column expressions evaluated per log row. Each entry is either a source-prefixed shorthand (`attributes.<key>`, `resource_attributes.<key>`, `body.<json.path>`) or a scalar HogQL expression (`upper(level)`, `coalesce(attributes['a'], attributes['b'])`). Aggregations and subqueries are rejected. Values come back on each result row keyed by the aliases echoed in the response `columns` field."
        ),
    personId: zod
        .string()
        .optional()
        .describe(
            "Scope results to one person (UUID or numeric ID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id log attribute keys."
        ),
})

export type _LogsQueryBodyApi = zod.input<typeof _LogsQueryBodyApi>
export type _LogsQueryBodyApiOutput = zod.output<typeof _LogsQueryBodyApi>

export const _LogsQueryRequestApi = zod.object({
    query: _LogsQueryBodyApi.describe('The logs query to execute.'),
})

export type _LogsQueryRequestApi = zod.input<typeof _LogsQueryRequestApi>
export type _LogsQueryRequestApiOutput = zod.output<typeof _LogsQueryRequestApi>

export const _LogEntryApi = zod.object({
    uuid: zod.string(),
    timestamp: zod.string().describe('ISO 8601 timestamp of the original log event.'),
    observed_timestamp: zod
        .string()
        .describe('ISO 8601 timestamp the log pipeline observed the event (may differ from `timestamp`).'),
    body: zod.string(),
    severity_text: zod
        .string()
        .describe('Log severity as a string (e.g. \"info\", \"error\"). Preferred over severity_number.'),
    severity_number: zod
        .number()
        .describe(
            'Log severity as a numeric code. Redundant with severity_text; kept for OpenTelemetry compatibility.'
        ),
    level: zod.string().describe('ClickHouse alias for severity_text. Redundant; prefer severity_text.'),
    trace_id: zod
        .string()
        .describe('Trace ID. Returns \"00000000000000000000000000000000\" when not set (padding, not null).'),
    span_id: zod.string().describe('Span ID. Returns \"0000000000000000\" when not set (padding, not null).'),
    trace_flags: zod.number().optional().describe('OpenTelemetry trace flags.'),
    attributes: zod
        .record(zod.string(), zod.string())
        .describe(
            'Log-level attributes as a string-keyed map. Values are strings (numeric\/datetime attributes are also accessible via materialized columns).'
        ),
    resource_attributes: zod
        .record(zod.string(), zod.string())
        .describe(
            'Resource-level attributes (service.name, k8s.\*, host.hostname, etc.) as a string-keyed map. Repeats across all logs from the same pod\/host.'
        ),
    event_name: zod.string().optional().describe('OpenTelemetry event name, if set.'),
})

export type _LogEntryApi = zod.input<typeof _LogEntryApi>
export type _LogEntryApiOutput = zod.output<typeof _LogEntryApi>

export const _LogsQueryResponseApi = zod.object({
    query: zod
        .record(zod.string(), zod.unknown())
        .describe('The parsed query that was executed, echoed back for confirmation.'),
    results: zod.array(_LogEntryApi).describe('Log entries matching the query.'),
    hasMore: zod.boolean().describe('True if more results exist beyond this page.'),
    nextCursor: zod
        .string()
        .nullish()
        .describe(
            'Opaque cursor to pass as `after` in the next request to fetch the next page. Null when hasMore is false.'
        ),
    maxExportableLogs: zod
        .number()
        .describe('Maximum number of rows the `export` endpoint will produce — informational.'),
    columns: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Aliases for the requested `customColumns`, in request order. Each result row carries its custom column values under these keys. Null when no custom columns were requested.'
        ),
})

export type _LogsQueryResponseApi = zod.input<typeof _LogsQueryResponseApi>
export type _LogsQueryResponseApiOutput = zod.output<typeof _LogsQueryResponseApi>

export const logsRetentionRuleApiNameMax = 255

export const logsRetentionRuleApiEnabledDefault = false
export const logsRetentionRuleApiPriorityMin = 0

export const LogsRetentionRuleApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this retention rule.'),
    name: zod.string().max(logsRetentionRuleApiNameMax).describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(logsRetentionRuleApiEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(logsRetentionRuleApiPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    config: zod
        .unknown()
        .describe(
            'Retention rule JSON. Required keys: `retention_days` (integer — how long matching logs are kept; must be a tier the organization is entitled to, same as the team-wide Logs retention setting) and `filter_group` (PropertyGroupFilter shape — an AND\/OR tree of property predicates evaluated per record to decide which logs this rule matches). Example: `{\"retention_days\":30,\"filter_group\":{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\"}]}]}}`. Logs matching no enabled rule keep the environment\'s default retention.'
        ),
    version: zod.number().describe('Incremented on each update for worker cache coherency.'),
    created_by: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type LogsRetentionRuleApi = zod.input<typeof LogsRetentionRuleApi>
export type LogsRetentionRuleApiOutput = zod.output<typeof LogsRetentionRuleApi>

export const PaginatedLogsRetentionRuleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LogsRetentionRuleApi),
})

export type PaginatedLogsRetentionRuleListApi = zod.input<typeof PaginatedLogsRetentionRuleListApi>
export type PaginatedLogsRetentionRuleListApiOutput = zod.output<typeof PaginatedLogsRetentionRuleListApi>

export const patchedLogsRetentionRuleApiNameMax = 255

export const patchedLogsRetentionRuleApiEnabledDefault = false
export const patchedLogsRetentionRuleApiPriorityMin = 0

export const PatchedLogsRetentionRuleApi = zod.object({
    id: zod.uuid().optional().describe('Unique identifier for this retention rule.'),
    name: zod.string().max(patchedLogsRetentionRuleApiNameMax).optional().describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(patchedLogsRetentionRuleApiEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(patchedLogsRetentionRuleApiPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Retention rule JSON. Required keys: `retention_days` (integer — how long matching logs are kept; must be a tier the organization is entitled to, same as the team-wide Logs retention setting) and `filter_group` (PropertyGroupFilter shape — an AND\/OR tree of property predicates evaluated per record to decide which logs this rule matches). Example: `{\"retention_days\":30,\"filter_group\":{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\"}]}]}}`. Logs matching no enabled rule keep the environment\'s default retention.'
        ),
    version: zod.number().optional().describe('Incremented on each update for worker cache coherency.'),
    created_by: zod.number().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedLogsRetentionRuleApi = zod.input<typeof PatchedLogsRetentionRuleApi>
export type PatchedLogsRetentionRuleApiOutput = zod.output<typeof PatchedLogsRetentionRuleApi>

export const LogsRetentionRuleReorderApi = zod.object({
    ordered_ids: zod
        .array(zod.uuid())
        .describe(
            'Rule IDs in the desired evaluation order (first element is highest priority \/ lowest order index).'
        ),
})

export type LogsRetentionRuleReorderApi = zod.input<typeof LogsRetentionRuleReorderApi>
export type LogsRetentionRuleReorderApiOutput = zod.output<typeof LogsRetentionRuleReorderApi>

export const RuleTypeEnumApi = zod
    .enum(['severity_sampling', 'path_drop', 'rate_limit'])
    .describe(
        '\* `severity_sampling` - Severity-based reduction\n\* `path_drop` - Path exclusion\n\* `rate_limit` - Rate limit'
    )

export type RuleTypeEnumApi = zod.input<typeof RuleTypeEnumApi>
export type RuleTypeEnumApiOutput = zod.output<typeof RuleTypeEnumApi>

export const logsSamplingRuleApiNameMax = 255

export const logsSamplingRuleApiEnabledDefault = false
export const logsSamplingRuleApiPriorityMin = 0

export const logsSamplingRuleApiScopeServiceMax = 512

export const logsSamplingRuleApiScopePathPatternMax = 1024

export const LogsSamplingRuleApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this sampling rule.'),
    name: zod.string().max(logsSamplingRuleApiNameMax).describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(logsSamplingRuleApiEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(logsSamplingRuleApiPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    rule_type: RuleTypeEnumApi.describe(
        'Rule kind: severity_sampling, path_drop, or rate_limit (caps matching log volume at ingestion).\n\n\* `severity_sampling` - Severity-based reduction\n\* `path_drop` - Path exclusion\n\* `rate_limit` - Rate limit'
    ),
    scope_service: zod
        .string()
        .max(logsSamplingRuleApiScopeServiceMax)
        .nullish()
        .describe('Optional legacy service-name scope; new rules use `config.filter_group` for matching instead.'),
    scope_path_pattern: zod
        .string()
        .max(logsSamplingRuleApiScopePathPatternMax)
        .nullish()
        .describe('Optional regex matched against a path-like log attribute when present.'),
    scope_attribute_filters: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe(
            'Optional list of predicates over string attributes, e.g. [{\"key\":\"http.route\",\"op\":\"eq\",\"value\":\"\/api\"}].'
        ),
    config: zod
        .unknown()
        .describe(
            'Type-specific JSON. For path_drop: object with optional `filter_group` (PropertyGroupFilter shape — AND\/OR tree of property predicates evaluated per record) and\/or legacy `patterns` (list of regex strings) + `match_attribute_key` (string). When both are present a record is dropped if EITHER matches. Filter group example: `{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\"}]}]}`. Every group in `filter_group` must contain at least one filter — empty groups never match, so the rule would never apply. For severity_sampling: object with `actions` per severity level and optional `always_keep`. For rate_limit: object with EITHER `logs_per_second` (integer 1–1000000, optional `burst_logs` integer ≥ logs_per_second, max 10000000) OR `kb_per_second` (integer 1–1000000 = 1 GB\/s, optional `burst_kb` integer ≥ kb_per_second, max 10000000) — not both. Plus optional `filter_group` to narrow which logs the cap applies to. KB-mode charges each log its own uncompressed byte size, matching how billing measures ingested bytes.'
        ),
    version: zod.number().describe('Incremented on each update for worker cache coherency.'),
    created_by: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type LogsSamplingRuleApi = zod.input<typeof LogsSamplingRuleApi>
export type LogsSamplingRuleApiOutput = zod.output<typeof LogsSamplingRuleApi>

export const PaginatedLogsSamplingRuleListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LogsSamplingRuleApi),
})

export type PaginatedLogsSamplingRuleListApi = zod.input<typeof PaginatedLogsSamplingRuleListApi>
export type PaginatedLogsSamplingRuleListApiOutput = zod.output<typeof PaginatedLogsSamplingRuleListApi>

export const patchedLogsSamplingRuleApiNameMax = 255

export const patchedLogsSamplingRuleApiEnabledDefault = false
export const patchedLogsSamplingRuleApiPriorityMin = 0

export const patchedLogsSamplingRuleApiScopeServiceMax = 512

export const patchedLogsSamplingRuleApiScopePathPatternMax = 1024

export const PatchedLogsSamplingRuleApi = zod.object({
    id: zod.uuid().optional().describe('Unique identifier for this sampling rule.'),
    name: zod.string().max(patchedLogsSamplingRuleApiNameMax).optional().describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(patchedLogsSamplingRuleApiEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(patchedLogsSamplingRuleApiPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    rule_type: RuleTypeEnumApi.optional().describe(
        'Rule kind: severity_sampling, path_drop, or rate_limit (caps matching log volume at ingestion).\n\n\* `severity_sampling` - Severity-based reduction\n\* `path_drop` - Path exclusion\n\* `rate_limit` - Rate limit'
    ),
    scope_service: zod
        .string()
        .max(patchedLogsSamplingRuleApiScopeServiceMax)
        .nullish()
        .describe('Optional legacy service-name scope; new rules use `config.filter_group` for matching instead.'),
    scope_path_pattern: zod
        .string()
        .max(patchedLogsSamplingRuleApiScopePathPatternMax)
        .nullish()
        .describe('Optional regex matched against a path-like log attribute when present.'),
    scope_attribute_filters: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe(
            'Optional list of predicates over string attributes, e.g. [{\"key\":\"http.route\",\"op\":\"eq\",\"value\":\"\/api\"}].'
        ),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Type-specific JSON. For path_drop: object with optional `filter_group` (PropertyGroupFilter shape — AND\/OR tree of property predicates evaluated per record) and\/or legacy `patterns` (list of regex strings) + `match_attribute_key` (string). When both are present a record is dropped if EITHER matches. Filter group example: `{\"type\":\"AND\",\"values\":[{\"type\":\"AND\",\"values\":[{\"key\":\"service.name\",\"operator\":\"exact\",\"value\":\"api\"}]}]}`. Every group in `filter_group` must contain at least one filter — empty groups never match, so the rule would never apply. For severity_sampling: object with `actions` per severity level and optional `always_keep`. For rate_limit: object with EITHER `logs_per_second` (integer 1–1000000, optional `burst_logs` integer ≥ logs_per_second, max 10000000) OR `kb_per_second` (integer 1–1000000 = 1 GB\/s, optional `burst_kb` integer ≥ kb_per_second, max 10000000) — not both. Plus optional `filter_group` to narrow which logs the cap applies to. KB-mode charges each log its own uncompressed byte size, matching how billing measures ingested bytes.'
        ),
    version: zod.number().optional().describe('Incremented on each update for worker cache coherency.'),
    created_by: zod.number().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedLogsSamplingRuleApi = zod.input<typeof PatchedLogsSamplingRuleApi>
export type PatchedLogsSamplingRuleApiOutput = zod.output<typeof PatchedLogsSamplingRuleApi>

export const LogsSamplingRuleSimulateResponseApi = zod.object({
    estimated_reduction_pct: zod
        .number()
        .describe(
            'Rough percent of log volume this rule would drop (0–100). Stub until ClickHouse-backed estimate ships.'
        ),
    notes: zod.string().describe('Human-readable caveats for the estimate.'),
})

export type LogsSamplingRuleSimulateResponseApi = zod.input<typeof LogsSamplingRuleSimulateResponseApi>
export type LogsSamplingRuleSimulateResponseApiOutput = zod.output<typeof LogsSamplingRuleSimulateResponseApi>

export const LogsSamplingRuleReorderApi = zod.object({
    ordered_ids: zod
        .array(zod.uuid())
        .describe(
            'Rule IDs in the desired evaluation order (first element is highest priority \/ lowest order index).'
        ),
})

export type LogsSamplingRuleReorderApi = zod.input<typeof LogsSamplingRuleReorderApi>
export type LogsSamplingRuleReorderApiOutput = zod.output<typeof LogsSamplingRuleReorderApi>

export const _LogsServicesBodyApi = zod.object({
    dateRange: _DateRangeApi.optional().describe('Date range for the services aggregation. Defaults to last hour.'),
    severityLevels: zod.array(SeverityLevelsEnumApi).optional().describe('Filter by log severity levels.'),
    serviceNames: zod.array(zod.string()).optional().describe('Restrict the aggregation to these service names.'),
    searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
    filterGroup: zod.array(_LogPropertyFilterApi).optional().describe('Property filters for the query.'),
})

export type _LogsServicesBodyApi = zod.input<typeof _LogsServicesBodyApi>
export type _LogsServicesBodyApiOutput = zod.output<typeof _LogsServicesBodyApi>

export const _LogsServicesRequestApi = zod.object({
    query: _LogsServicesBodyApi.describe('The services aggregation query to execute.'),
})

export type _LogsServicesRequestApi = zod.input<typeof _LogsServicesRequestApi>
export type _LogsServicesRequestApiOutput = zod.output<typeof _LogsServicesRequestApi>

export const _LogsServiceSeverityBreakdownApi = zod.object({
    debug: zod.number(),
    info: zod.number(),
    warn: zod.number(),
    error: zod.number(),
})

export type _LogsServiceSeverityBreakdownApi = zod.input<typeof _LogsServiceSeverityBreakdownApi>
export type _LogsServiceSeverityBreakdownApiOutput = zod.output<typeof _LogsServiceSeverityBreakdownApi>

export const _LogsServiceActiveRuleApi = zod.object({
    rule_id: zod.uuid(),
    rule_name: zod.string(),
    summary_string: zod.string(),
})

export type _LogsServiceActiveRuleApi = zod.input<typeof _LogsServiceActiveRuleApi>
export type _LogsServiceActiveRuleApiOutput = zod.output<typeof _LogsServiceActiveRuleApi>

export const _LogsServiceAggregateApi = zod.object({
    service_name: zod
        .string()
        .describe('Service name, or \"(no value)\" \/ \"(no service)\" placeholder for unset entries.'),
    log_count: zod.number().describe('Total log entries from this service in the window.'),
    error_count: zod.number().describe('Count of logs at severity \"error\" or \"fatal\".'),
    error_rate: zod
        .number()
        .describe('Pre-computed error_count \/ log_count, rounded to 4 decimals. Useful for ranking noisy services.'),
    volume_share_pct: zod
        .number()
        .optional()
        .describe('Share of total log volume in the window for this service (0–100).'),
    severity_breakdown: _LogsServiceSeverityBreakdownApi
        .optional()
        .describe('Counts by coarse severity bucket (debug, info, warn, error+fatal).'),
    active_rules: zod
        .array(_LogsServiceActiveRuleApi)
        .optional()
        .describe('Enabled sampling rules whose scope includes this service.'),
})

export type _LogsServiceAggregateApi = zod.input<typeof _LogsServiceAggregateApi>
export type _LogsServiceAggregateApiOutput = zod.output<typeof _LogsServiceAggregateApi>

export const _LogsServicesSparklineBucketApi = zod.object({
    time: zod.string().describe('Bucket start time (ISO 8601).'),
    service_name: zod.string(),
    count: zod.number(),
})

export type _LogsServicesSparklineBucketApi = zod.input<typeof _LogsServicesSparklineBucketApi>
export type _LogsServicesSparklineBucketApiOutput = zod.output<typeof _LogsServicesSparklineBucketApi>

export const _LogsServicesSummaryApi = zod.object({
    top_services_count: zod
        .number()
        .describe('Number of top services included in the volume_share aggregate (up to 5).'),
    top_services_volume_share_pct: zod
        .number()
        .describe('Combined volume share (percent) of the top services by log_count.'),
})

export type _LogsServicesSummaryApi = zod.input<typeof _LogsServicesSummaryApi>
export type _LogsServicesSummaryApiOutput = zod.output<typeof _LogsServicesSummaryApi>

export const _LogsServicesResponseApi = zod.object({
    services: zod
        .array(_LogsServiceAggregateApi)
        .describe('Per-service aggregates, ordered by log_count descending. Capped at 25 services.'),
    sparkline: zod
        .array(_LogsServicesSparklineBucketApi)
        .describe('Time-bucketed counts broken down by service, for plotting volume over time.'),
    summary: _LogsServicesSummaryApi.optional().describe('Roll-up stats for the Services tab header.'),
})

export type _LogsServicesResponseApi = zod.input<typeof _LogsServicesResponseApi>
export type _LogsServicesResponseApiOutput = zod.output<typeof _LogsServicesResponseApi>

export const SparklineBreakdownByEnumApi = zod
    .enum(['severity', 'service'])
    .describe('\* `severity` - severity\n\* `service` - service')

export type SparklineBreakdownByEnumApi = zod.input<typeof SparklineBreakdownByEnumApi>
export type SparklineBreakdownByEnumApiOutput = zod.output<typeof SparklineBreakdownByEnumApi>

export const _logsSparklineBodyApiSeverityLevelsDefault = []
export const _logsSparklineBodyApiServiceNamesDefault = []
export const _logsSparklineBodyApiFilterGroupDefault = []

export const _LogsSparklineBodyApi = zod.object({
    dateRange: _DateRangeApi.optional().describe('Date range for the sparkline. Defaults to last hour.'),
    severityLevels: zod
        .array(SeverityLevelsEnumApi)
        .default(_logsSparklineBodyApiSeverityLevelsDefault)
        .describe('Filter by log severity levels.'),
    serviceNames: zod
        .array(zod.string())
        .default(_logsSparklineBodyApiServiceNamesDefault)
        .describe('Filter by service names.'),
    searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
    filterGroup: zod
        .array(_LogPropertyFilterApi)
        .default(_logsSparklineBodyApiFilterGroupDefault)
        .describe('Property filters for the query.'),
    sparklineBreakdownBy: SparklineBreakdownByEnumApi.optional().describe(
        'Break down sparkline by \"severity\" (default) or \"service\".\n\n\* `severity` - severity\n\* `service` - service'
    ),
    personId: zod
        .string()
        .optional()
        .describe(
            "Scope results to one person (UUID or numeric ID). Expanded server-side to the person's distinct IDs and matched against the team's configured distinct-id log attribute keys."
        ),
})

export type _LogsSparklineBodyApi = zod.input<typeof _LogsSparklineBodyApi>
export type _LogsSparklineBodyApiOutput = zod.output<typeof _LogsSparklineBodyApi>

export const _LogsSparklineRequestApi = zod.object({
    query: _LogsSparklineBodyApi.describe('The sparkline query to execute.'),
})

export type _LogsSparklineRequestApi = zod.input<typeof _LogsSparklineRequestApi>
export type _LogsSparklineRequestApiOutput = zod.output<typeof _LogsSparklineRequestApi>

export const _LogsSparklineBucketApi = zod.object({
    time: zod.string().describe('Bucket start time (ISO 8601).'),
    severity: zod
        .string()
        .optional()
        .describe(
            'Severity label when sparklineBreakdownBy=\"severity\". Present only for severity-broken-down sparklines.'
        ),
    service: zod
        .string()
        .optional()
        .describe(
            'Service name when sparklineBreakdownBy=\"service\". Present only for service-broken-down sparklines.'
        ),
    count: zod.number(),
    bytes_uncompressed: zod.number().optional().describe('Sum of uncompressed bytes for the bucket.'),
})

export type _LogsSparklineBucketApi = zod.input<typeof _LogsSparklineBucketApi>
export type _LogsSparklineBucketApiOutput = zod.output<typeof _LogsSparklineBucketApi>

export const _LogsSparklineResponseApi = zod.object({
    results: zod
        .array(_LogsSparklineBucketApi)
        .describe(
            'Time-bucketed log counts. Each bucket carries either `severity` or `service` depending on breakdown.'
        ),
})

export type _LogsSparklineResponseApi = zod.input<typeof _LogsSparklineResponseApi>
export type _LogsSparklineResponseApiOutput = zod.output<typeof _LogsSparklineResponseApi>

export const _LogAttributeValueApi = zod.object({
    id: zod.string().describe('Attribute value (used as the identifier).'),
    name: zod.string().describe('Display name — currently identical to `id`.'),
    count: zod
        .number()
        .optional()
        .describe(
            'Number of log records with this attribute value, scoped to the current date range, service, and resource filters.'
        ),
})

export type _LogAttributeValueApi = zod.input<typeof _LogAttributeValueApi>
export type _LogAttributeValueApiOutput = zod.output<typeof _LogAttributeValueApi>

export const _LogsValuesResponseApi = zod.object({
    results: zod.array(_LogAttributeValueApi).describe('Distinct values observed for the requested attribute.'),
    refreshing: zod.boolean().describe('Always false — reserved for future cached-value refresh signalling.'),
})

export type _LogsValuesResponseApi = zod.input<typeof _LogsValuesResponseApi>
export type _LogsValuesResponseApiOutput = zod.output<typeof _LogsValuesResponseApi>

export const LogsViewColumnTypeEnumApi = zod
    .enum(['timestamp', 'level', 'source', 'trace_id', 'span_id', 'message', 'custom'])
    .describe(
        '\* `timestamp` - timestamp\n\* `level` - level\n\* `source` - source\n\* `trace_id` - trace_id\n\* `span_id` - span_id\n\* `message` - message\n\* `custom` - custom'
    )

export type LogsViewColumnTypeEnumApi = zod.input<typeof LogsViewColumnTypeEnumApi>
export type LogsViewColumnTypeEnumApiOutput = zod.output<typeof LogsViewColumnTypeEnumApi>

export const logsViewColumnApiWidthMax = 2000

export const LogsViewColumnApi = zod.object({
    id: zod
        .string()
        .describe(
            'Client-generated stable identity for list operations (React keys, reorder). Never interpreted by the server.'
        ),
    type: LogsViewColumnTypeEnumApi.describe(
        'Column type. Built-in types resolve client-side from log row fields; `custom` columns are computed server-side from `expression`.\n\n\* `timestamp` - timestamp\n\* `level` - level\n\* `source` - source\n\* `trace_id` - trace_id\n\* `span_id` - span_id\n\* `message` - message\n\* `custom` - custom'
    ),
    name: zod
        .string()
        .optional()
        .describe(
            "Header label override. Defaults to the built-in type's label, or to the expression for custom columns."
        ),
    expression: zod
        .string()
        .optional()
        .describe(
            "Only meaningful for `type: custom`: a source-prefixed shorthand (`attributes.<key>`, `resource_attributes.<key>`, `body.<json.path>`) or a scalar HogQL expression, sent verbatim in the logs query's `customColumns`."
        ),
    width: zod
        .number()
        .min(1)
        .max(logsViewColumnApiWidthMax)
        .optional()
        .describe(
            'Column width in pixels (1–2000). Omitted for the default width; ignored for the flex message column.'
        ),
})

export type LogsViewColumnApi = zod.input<typeof LogsViewColumnApi>
export type LogsViewColumnApiOutput = zod.output<typeof LogsViewColumnApi>

export const logsViewApiNameMax = 400

export const LogsViewApi = zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(logsViewApiNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    columns: zod
        .array(LogsViewColumnApi)
        .nullish()
        .describe(
            'Ordered column configuration for the logs table (LogsColumnConfig[]). Order is array index. Null means the view has no column preference and the client renders its default column set. Omitting the field on update leaves the saved configuration unchanged; send null to clear it.'
        ),
    pinned: zod.boolean().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type LogsViewApi = zod.input<typeof LogsViewApi>
export type LogsViewApiOutput = zod.output<typeof LogsViewApi>

export const PaginatedLogsViewListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LogsViewApi),
})

export type PaginatedLogsViewListApi = zod.input<typeof PaginatedLogsViewListApi>
export type PaginatedLogsViewListApiOutput = zod.output<typeof PaginatedLogsViewListApi>

export const patchedLogsViewApiNameMax = 400

export const PatchedLogsViewApi = zod.object({
    id: zod.uuid().optional(),
    short_id: zod.string().optional(),
    name: zod.string().max(patchedLogsViewApiNameMax).optional(),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    columns: zod
        .array(LogsViewColumnApi)
        .nullish()
        .describe(
            'Ordered column configuration for the logs table (LogsColumnConfig[]). Order is array index. Null means the view has no column preference and the client renders its default column set. Omitting the field on update leaves the saved configuration unchanged; send null to clear it.'
        ),
    pinned: zod.boolean().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedLogsViewApi = zod.input<typeof PatchedLogsViewApi>
export type PatchedLogsViewApiOutput = zod.output<typeof PatchedLogsViewApi>

export const PropertyOperatorApi = zod.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'starts_with',
    'not_starts_with',
    'ends_with',
    'not_ends_with',
    'regex',
    'not_regex',
    'gt',
    'gte',
    'lt',
    'lte',
    'is_set',
    'is_not_set',
    'is_date_exact',
    'is_date_before',
    'is_date_after',
    'between',
    'not_between',
    'min',
    'max',
    'in',
    'not_in',
    'is_cleaned_path_exact',
    'flag_evaluates_to',
    'semver_eq',
    'semver_neq',
    'semver_gt',
    'semver_gte',
    'semver_lt',
    'semver_lte',
    'semver_tilde',
    'semver_caret',
    'semver_wildcard',
    'icontains_multi',
    'not_icontains_multi',
])

export type PropertyOperatorApi = zod.input<typeof PropertyOperatorApi>
export type PropertyOperatorApiOutput = zod.output<typeof PropertyOperatorApi>

export const eventPropertyFilterApiOperatorDefault = `exact`
export const eventPropertyFilterApiTypeDefault = `event`

export const EventPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(eventPropertyFilterApiOperatorDefault),
    type: zod.literal('event').default(eventPropertyFilterApiTypeDefault).describe('Event properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventPropertyFilterApi = zod.input<typeof EventPropertyFilterApi>
export type EventPropertyFilterApiOutput = zod.output<typeof EventPropertyFilterApi>

export const personPropertyFilterApiTypeDefault = `person`

export const PersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('person').default(personPropertyFilterApiTypeDefault).describe('Person properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonPropertyFilterApi = zod.input<typeof PersonPropertyFilterApi>
export type PersonPropertyFilterApiOutput = zod.output<typeof PersonPropertyFilterApi>

export const personMetadataPropertyFilterApiTypeDefault = `person_metadata`

export const PersonMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('person_metadata')
        .default(personMetadataPropertyFilterApiTypeDefault)
        .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonMetadataPropertyFilterApi = zod.input<typeof PersonMetadataPropertyFilterApi>
export type PersonMetadataPropertyFilterApiOutput = zod.output<typeof PersonMetadataPropertyFilterApi>

export const Key10Api = zod.enum(['tag_name', 'text', 'href', 'selector'])

export type Key10Api = zod.input<typeof Key10Api>
export type Key10ApiOutput = zod.output<typeof Key10Api>

export const elementPropertyFilterApiTypeDefault = `element`

export const ElementPropertyFilterApi = zod.object({
    key: Key10Api,
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('element').default(elementPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ElementPropertyFilterApi = zod.input<typeof ElementPropertyFilterApi>
export type ElementPropertyFilterApiOutput = zod.output<typeof ElementPropertyFilterApi>

export const eventMetadataPropertyFilterApiTypeDefault = `event_metadata`

export const EventMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('event_metadata').default(eventMetadataPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventMetadataPropertyFilterApi = zod.input<typeof EventMetadataPropertyFilterApi>
export type EventMetadataPropertyFilterApiOutput = zod.output<typeof EventMetadataPropertyFilterApi>

export const sessionPropertyFilterApiTypeDefault = `session`

export const SessionPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('session').default(sessionPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SessionPropertyFilterApi = zod.input<typeof SessionPropertyFilterApi>
export type SessionPropertyFilterApiOutput = zod.output<typeof SessionPropertyFilterApi>

export const cohortPropertyFilterApiKeyDefault = `id`
export const cohortPropertyFilterApiOperatorDefault = `in`
export const cohortPropertyFilterApiTypeDefault = `cohort`

export const CohortPropertyFilterApi = zod.object({
    cohort_name: zod.union([zod.string(), zod.null()]).optional(),
    key: zod.literal('id').default(cohortPropertyFilterApiKeyDefault),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(cohortPropertyFilterApiOperatorDefault),
    type: zod.literal('cohort').default(cohortPropertyFilterApiTypeDefault),
    value: zod.number(),
})

export type CohortPropertyFilterApi = zod.input<typeof CohortPropertyFilterApi>
export type CohortPropertyFilterApiOutput = zod.output<typeof CohortPropertyFilterApi>

export const DurationTypeApi = zod.enum(['duration', 'active_seconds', 'inactive_seconds'])

export type DurationTypeApi = zod.input<typeof DurationTypeApi>
export type DurationTypeApiOutput = zod.output<typeof DurationTypeApi>

export const recordingPropertyFilterApiTypeDefault = `recording`

export const RecordingPropertyFilterApi = zod.object({
    key: zod.union([DurationTypeApi, zod.string()]),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('recording').default(recordingPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RecordingPropertyFilterApi = zod.input<typeof RecordingPropertyFilterApi>
export type RecordingPropertyFilterApiOutput = zod.output<typeof RecordingPropertyFilterApi>

export const logEntryPropertyFilterApiTypeDefault = `log_entry`

export const LogEntryPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('log_entry').default(logEntryPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogEntryPropertyFilterApi = zod.input<typeof LogEntryPropertyFilterApi>
export type LogEntryPropertyFilterApiOutput = zod.output<typeof LogEntryPropertyFilterApi>

export const groupPropertyFilterApiTypeDefault = `group`

export const GroupPropertyFilterApi = zod.object({
    group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
    group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('group').default(groupPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type GroupPropertyFilterApi = zod.input<typeof GroupPropertyFilterApi>
export type GroupPropertyFilterApiOutput = zod.output<typeof GroupPropertyFilterApi>

export const featurePropertyFilterApiTypeDefault = `feature`

export const FeaturePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('feature')
        .default(featurePropertyFilterApiTypeDefault)
        .describe('Event property with \"$feature\/\" prepended'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type FeaturePropertyFilterApi = zod.input<typeof FeaturePropertyFilterApi>
export type FeaturePropertyFilterApiOutput = zod.output<typeof FeaturePropertyFilterApi>

export const flagPropertyFilterApiOperatorDefault = `flag_evaluates_to`
export const flagPropertyFilterApiTypeDefault = `flag`

export const FlagPropertyFilterApi = zod.object({
    key: zod.string().describe('The key should be the flag ID'),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod
        .literal('flag_evaluates_to')
        .default(flagPropertyFilterApiOperatorDefault)
        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
    type: zod.literal('flag').default(flagPropertyFilterApiTypeDefault).describe('Feature flag dependency'),
    value: zod.union([zod.boolean(), zod.string()]).describe('The value can be true, false, or a variant name'),
})

export type FlagPropertyFilterApi = zod.input<typeof FlagPropertyFilterApi>
export type FlagPropertyFilterApiOutput = zod.output<typeof FlagPropertyFilterApi>

export const hogQLPropertyFilterApiTypeDefault = `hogql`

export const HogQLPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    type: zod.literal('hogql').default(hogQLPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type HogQLPropertyFilterApi = zod.input<typeof HogQLPropertyFilterApi>
export type HogQLPropertyFilterApiOutput = zod.output<typeof HogQLPropertyFilterApi>

export const emptyPropertyFilterApiTypeDefault = `empty`

export const EmptyPropertyFilterApi = zod.object({
    type: zod.literal('empty').default(emptyPropertyFilterApiTypeDefault),
})

export type EmptyPropertyFilterApi = zod.input<typeof EmptyPropertyFilterApi>
export type EmptyPropertyFilterApiOutput = zod.output<typeof EmptyPropertyFilterApi>

export const dataWarehousePropertyFilterApiTypeDefault = `data_warehouse`

export const DataWarehousePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse').default(dataWarehousePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePropertyFilterApi = zod.input<typeof DataWarehousePropertyFilterApi>
export type DataWarehousePropertyFilterApiOutput = zod.output<typeof DataWarehousePropertyFilterApi>

export const dataWarehousePersonPropertyFilterApiTypeDefault = `data_warehouse_person_property`

export const DataWarehousePersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse_person_property').default(dataWarehousePersonPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePersonPropertyFilterApi = zod.input<typeof DataWarehousePersonPropertyFilterApi>
export type DataWarehousePersonPropertyFilterApiOutput = zod.output<typeof DataWarehousePersonPropertyFilterApi>

export const errorTrackingIssueFilterApiTypeDefault = `error_tracking_issue`

export const ErrorTrackingIssueFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('error_tracking_issue').default(errorTrackingIssueFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ErrorTrackingIssueFilterApi = zod.input<typeof ErrorTrackingIssueFilterApi>
export type ErrorTrackingIssueFilterApiOutput = zod.output<typeof ErrorTrackingIssueFilterApi>

export const LogPropertyFilterTypeApi = zod.enum(['log', 'log_attribute', 'log_resource_attribute'])

export type LogPropertyFilterTypeApi = zod.input<typeof LogPropertyFilterTypeApi>
export type LogPropertyFilterTypeApiOutput = zod.output<typeof LogPropertyFilterTypeApi>

export const LogPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: LogPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogPropertyFilterApi = zod.input<typeof LogPropertyFilterApi>
export type LogPropertyFilterApiOutput = zod.output<typeof LogPropertyFilterApi>

export const metricPropertyFilterApiTypeDefault = `metric_attribute`

export const MetricPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('metric_attribute').default(metricPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type MetricPropertyFilterApi = zod.input<typeof MetricPropertyFilterApi>
export type MetricPropertyFilterApiOutput = zod.output<typeof MetricPropertyFilterApi>

export const SpanPropertyFilterTypeApi = zod.enum(['span', 'span_attribute', 'span_resource_attribute'])

export type SpanPropertyFilterTypeApi = zod.input<typeof SpanPropertyFilterTypeApi>
export type SpanPropertyFilterTypeApiOutput = zod.output<typeof SpanPropertyFilterTypeApi>

export const SpanPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: SpanPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SpanPropertyFilterApi = zod.input<typeof SpanPropertyFilterApi>
export type SpanPropertyFilterApiOutput = zod.output<typeof SpanPropertyFilterApi>

export const revenueAnalyticsPropertyFilterApiTypeDefault = `revenue_analytics`

export const RevenueAnalyticsPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('revenue_analytics').default(revenueAnalyticsPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RevenueAnalyticsPropertyFilterApi = zod.input<typeof RevenueAnalyticsPropertyFilterApi>
export type RevenueAnalyticsPropertyFilterApiOutput = zod.output<typeof RevenueAnalyticsPropertyFilterApi>

export const accountCustomPropertyFilterApiTypeDefault = `account_custom_property`

export const AccountCustomPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('account_custom_property')
        .default(accountCustomPropertyFilterApiTypeDefault)
        .describe('Customer analytics account custom property — the key is the property definition id'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type AccountCustomPropertyFilterApi = zod.input<typeof AccountCustomPropertyFilterApi>
export type AccountCustomPropertyFilterApiOutput = zod.output<typeof AccountCustomPropertyFilterApi>

export const workflowVariablePropertyFilterApiTypeDefault = `workflow_variable`

export const WorkflowVariablePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('workflow_variable').default(workflowVariablePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type WorkflowVariablePropertyFilterApi = zod.input<typeof WorkflowVariablePropertyFilterApi>
export type WorkflowVariablePropertyFilterApiOutput = zod.output<typeof WorkflowVariablePropertyFilterApi>
