/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Explain a log entry using AI.

POST /api/environments/:id/logs/explainLogWithAI/
 */
export const logsExplainLogWithAICreateBodyForceRefreshDefault = false

export const LogsExplainLogWithAICreateBody = /* @__PURE__ */ zod.object({
    uuid: zod.string().describe('UUID of the log entry to explain'),
    timestamp: zod.iso.datetime({}).describe('Timestamp of the log entry (used for efficient lookup)'),
    force_refresh: zod
        .boolean()
        .default(logsExplainLogWithAICreateBodyForceRefreshDefault)
        .describe('Force regenerate explanation, bypassing cache'),
})

export const logsViewsCreateBodyNameMax = 400

export const LogsViewsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsViewsCreateBodyNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
})

export const logsViewsUpdateBodyNameMax = 400

export const LogsViewsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsViewsUpdateBodyNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
})

export const logsViewsPartialUpdateBodyNameMax = 400

export const LogsViewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsViewsPartialUpdateBodyNameMax).optional(),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.'
        ),
    pinned: zod.boolean().optional(),
})

export const logsAlertsCreateBodyNameMax = 255

export const logsAlertsCreateBodyEnabledDefault = true
export const logsAlertsCreateBodyThresholdCountDefault = 100

export const logsAlertsCreateBodyThresholdOperatorDefault = `above`
export const logsAlertsCreateBodyWindowMinutesDefault = 5
export const logsAlertsCreateBodyEvaluationPeriodsDefault = 1
export const logsAlertsCreateBodyEvaluationPeriodsMax = 10

export const logsAlertsCreateBodyDatapointsToAlarmDefault = 1
export const logsAlertsCreateBodyDatapointsToAlarmMax = 10

export const logsAlertsCreateBodyCooldownMinutesDefault = 0
export const logsAlertsCreateBodyCooldownMinutesMin = 0

export const LogsAlertsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(logsAlertsCreateBodyNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .default(logsAlertsCreateBodyEnabledDefault)
        .describe('Whether the alert is actively being evaluated. Disabling resets the state to not_firing.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).'
        ),
    threshold_count: zod
        .number()
        .min(1)
        .default(logsAlertsCreateBodyThresholdCountDefault)
        .describe(
            'Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100.'
        ),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsCreateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .default(logsAlertsCreateBodyWindowMinutesDefault)
        .describe('Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsCreateBodyEvaluationPeriodsMax)
        .default(logsAlertsCreateBodyEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsCreateBodyDatapointsToAlarmMax)
        .default(logsAlertsCreateBodyDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsCreateBodyCooldownMinutesMin)
        .default(logsAlertsCreateBodyCooldownMinutesDefault)
        .describe('Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.'),
    snooze_until: zod.iso
        .datetime({})
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
})

export const logsAlertsUpdateBodyNameMax = 255

export const logsAlertsUpdateBodyEnabledDefault = true
export const logsAlertsUpdateBodyThresholdCountDefault = 100

export const logsAlertsUpdateBodyThresholdOperatorDefault = `above`
export const logsAlertsUpdateBodyWindowMinutesDefault = 5
export const logsAlertsUpdateBodyEvaluationPeriodsDefault = 1
export const logsAlertsUpdateBodyEvaluationPeriodsMax = 10

export const logsAlertsUpdateBodyDatapointsToAlarmDefault = 1
export const logsAlertsUpdateBodyDatapointsToAlarmMax = 10

export const logsAlertsUpdateBodyCooldownMinutesDefault = 0
export const logsAlertsUpdateBodyCooldownMinutesMin = 0

export const LogsAlertsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(logsAlertsUpdateBodyNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .default(logsAlertsUpdateBodyEnabledDefault)
        .describe('Whether the alert is actively being evaluated. Disabling resets the state to not_firing.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).'
        ),
    threshold_count: zod
        .number()
        .min(1)
        .default(logsAlertsUpdateBodyThresholdCountDefault)
        .describe(
            'Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100.'
        ),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsUpdateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .default(logsAlertsUpdateBodyWindowMinutesDefault)
        .describe('Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsUpdateBodyEvaluationPeriodsMax)
        .default(logsAlertsUpdateBodyEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsUpdateBodyDatapointsToAlarmMax)
        .default(logsAlertsUpdateBodyDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsUpdateBodyCooldownMinutesMin)
        .default(logsAlertsUpdateBodyCooldownMinutesDefault)
        .describe('Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.'),
    snooze_until: zod.iso
        .datetime({})
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
})

export const logsAlertsPartialUpdateBodyNameMax = 255

export const logsAlertsPartialUpdateBodyEnabledDefault = true
export const logsAlertsPartialUpdateBodyThresholdCountDefault = 100

export const logsAlertsPartialUpdateBodyThresholdOperatorDefault = `above`
export const logsAlertsPartialUpdateBodyWindowMinutesDefault = 5
export const logsAlertsPartialUpdateBodyEvaluationPeriodsDefault = 1
export const logsAlertsPartialUpdateBodyEvaluationPeriodsMax = 10

export const logsAlertsPartialUpdateBodyDatapointsToAlarmDefault = 1
export const logsAlertsPartialUpdateBodyDatapointsToAlarmMax = 10

export const logsAlertsPartialUpdateBodyCooldownMinutesDefault = 0
export const logsAlertsPartialUpdateBodyCooldownMinutesMin = 0

export const LogsAlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(logsAlertsPartialUpdateBodyNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .default(logsAlertsPartialUpdateBodyEnabledDefault)
        .describe('Whether the alert is actively being evaluated. Disabling resets the state to not_firing.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object). May be empty on draft alerts (enabled=false).'
        ),
    threshold_count: zod
        .number()
        .min(1)
        .default(logsAlertsPartialUpdateBodyThresholdCountDefault)
        .describe(
            'Number of matching log entries that constitutes a threshold breach within the evaluation window. Defaults to 100.'
        ),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsPartialUpdateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .default(logsAlertsPartialUpdateBodyWindowMinutesDefault)
        .describe('Time window in minutes over which log entries are counted. Allowed values: 5, 10, 15, 30, 60.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateBodyEvaluationPeriodsMax)
        .default(logsAlertsPartialUpdateBodyEvaluationPeriodsDefault)
        .describe('Total number of check periods in the sliding evaluation window for firing (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsPartialUpdateBodyDatapointsToAlarmMax)
        .default(logsAlertsPartialUpdateBodyDatapointsToAlarmDefault)
        .describe('How many periods within the evaluation window must breach the threshold to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsPartialUpdateBodyCooldownMinutesMin)
        .default(logsAlertsPartialUpdateBodyCooldownMinutesDefault)
        .describe('Minimum minutes between repeated notifications after the alert fires. 0 means no cooldown.'),
    snooze_until: zod.iso
        .datetime({})
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
})

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind (firing, resolved, ...) atomically.
 */
export const LogsAlertsDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['slack', 'webhook'])
        .describe('* `slack` - slack\n* `webhook` - webhook')
        .describe('Destination type — slack or webhook.\n\n* `slack` - slack\n* `webhook` - webhook'),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod.url().optional().describe('HTTPS endpoint to POST to. Required when type=webhook.'),
})

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */

export const LogsAlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    hog_function_ids: zod
        .array(zod.uuid())
        .min(1)
        .describe('HogFunction IDs to delete as one atomic destination group.'),
})

/**
 * Simulate a logs alert on historical data using the full state machine. Read-only — no alert check records are created.
 */

export const logsAlertsSimulateCreateBodyEvaluationPeriodsDefault = 1
export const logsAlertsSimulateCreateBodyEvaluationPeriodsMax = 10

export const logsAlertsSimulateCreateBodyDatapointsToAlarmDefault = 1
export const logsAlertsSimulateCreateBodyDatapointsToAlarmMax = 10

export const logsAlertsSimulateCreateBodyCooldownMinutesDefault = 0
export const logsAlertsSimulateCreateBodyCooldownMinutesMin = 0

export const LogsAlertsSimulateCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().describe('Filter criteria — same format as LogsAlertConfiguration.filters.'),
    threshold_count: zod.number().min(1).describe('Threshold count to evaluate against.'),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod.number().describe('Window size in minutes — determines bucket interval.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(logsAlertsSimulateCreateBodyEvaluationPeriodsMax)
        .default(logsAlertsSimulateCreateBodyEvaluationPeriodsDefault)
        .describe('Total check periods in the N-of-M evaluation window (M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(logsAlertsSimulateCreateBodyDatapointsToAlarmMax)
        .default(logsAlertsSimulateCreateBodyDatapointsToAlarmDefault)
        .describe('How many periods must breach to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(logsAlertsSimulateCreateBodyCooldownMinutesMin)
        .default(logsAlertsSimulateCreateBodyCooldownMinutesDefault)
        .describe('Minutes to wait after firing before sending another notification.'),
    date_from: zod.string().describe("Relative date string for how far back to simulate (e.g. '-24h', '-7d', '-30d')."),
})

export const LogsCountCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the count. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .optional()
                .describe('Filter by log severity levels.'),
            serviceNames: zod.array(zod.string()).optional().describe('Filter by service names.'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"log\", use \"message\". For \"log_attribute\"/\"log_resource_attribute\", use the attribute key (e.g. \"k8s.container.name\").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '\"log\" filters the log body/message. \"log_attribute\" filters log-level attributes. \"log_resource_attribute\" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
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
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .optional()
                .describe('Property filters for the query.'),
        })
        .describe('The count query to execute.'),
})

export const logsCountRangesCreateBodyQueryOneTargetBucketsDefault = 10
export const logsCountRangesCreateBodyQueryOneTargetBucketsMax = 100

export const LogsCountRangesCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe(
                    "Window to bucket. Defaults to last hour. Use a bucket's date_from/date_to from a prior response to recursively narrow into a sub-range."
                ),
            targetBuckets: zod
                .number()
                .min(1)
                .max(logsCountRangesCreateBodyQueryOneTargetBucketsMax)
                .default(logsCountRangesCreateBodyQueryOneTargetBucketsDefault)
                .describe(
                    'Approximate number of buckets to return. The bucket interval is picked adaptively from a fixed list (1/5/10s, 1/2/5/10/15/30/60/120/240/360/720/1440m) to land near this target. Defaults to 10, capped at 100.'
                ),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .optional()
                .describe('Filter by log severity levels. Applied before bucketing.'),
            serviceNames: zod
                .array(zod.string())
                .optional()
                .describe('Filter by service names. Applied before bucketing.'),
            searchTerm: zod
                .string()
                .optional()
                .describe('Full-text search across log bodies. Applied before bucketing.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"log\", use \"message\". For \"log_attribute\"/\"log_resource_attribute\", use the attribute key (e.g. \"k8s.container.name\").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '\"log\" filters the log body/message. \"log_attribute\" filters log-level attributes. \"log_resource_attribute\" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
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
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .optional()
                .describe('Property filters applied before bucketing. Same shape as `query-logs`.'),
        })
        .describe('The bucketed-count query to execute.'),
})

export const logsQueryCreateBodyQueryOneSeverityLevelsDefault = []
export const logsQueryCreateBodyQueryOneServiceNamesDefault = []
export const logsQueryCreateBodyQueryOneFilterGroupDefault = []
export const logsQueryCreateBodyQueryOneLimitDefault = 100

export const LogsQueryCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the query. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .default(logsQueryCreateBodyQueryOneSeverityLevelsDefault)
                .describe('Filter by log severity levels.'),
            serviceNames: zod
                .array(zod.string())
                .default(logsQueryCreateBodyQueryOneServiceNamesDefault)
                .describe('Filter by service names.'),
            orderBy: zod
                .enum(['latest', 'earliest'])
                .describe('* `latest` - latest\n* `earliest` - earliest')
                .optional()
                .describe('Order results by timestamp.\n\n* `latest` - latest\n* `earliest` - earliest'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"log\", use \"message\". For \"log_attribute\"/\"log_resource_attribute\", use the attribute key (e.g. \"k8s.container.name\").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '\"log\" filters the log body/message. \"log_attribute\" filters log-level attributes. \"log_resource_attribute\" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
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
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .default(logsQueryCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            limit: zod.number().default(logsQueryCreateBodyQueryOneLimitDefault).describe('Max results (1-1000).'),
            after: zod.string().optional().describe('Pagination cursor from previous response.'),
        })
        .describe('The logs query to execute.'),
})

export const logsSamplingRulesCreateBodyNameMax = 255

export const logsSamplingRulesCreateBodyEnabledDefault = false
export const logsSamplingRulesCreateBodyPriorityMin = 0

export const logsSamplingRulesCreateBodyScopeServiceMax = 512

export const logsSamplingRulesCreateBodyScopePathPatternMax = 1024

export const LogsSamplingRulesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsSamplingRulesCreateBodyNameMax).describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(logsSamplingRulesCreateBodyEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(logsSamplingRulesCreateBodyPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    rule_type: zod
        .enum(['severity_sampling', 'path_drop', 'rate_limit'])
        .describe('* `severity_sampling` - Severity sampling\n* `path_drop` - Path drop\n* `rate_limit` - Rate limit')
        .describe(
            'Rule kind: severity_sampling, path_drop, or rate_limit (rate_limit reserved for a future release).\n\n* `severity_sampling` - Severity sampling\n* `path_drop` - Path drop\n* `rate_limit` - Rate limit'
        ),
    scope_service: zod
        .string()
        .max(logsSamplingRulesCreateBodyScopeServiceMax)
        .nullish()
        .describe('If set, the rule applies only to this service name; null means all services.'),
    scope_path_pattern: zod
        .string()
        .max(logsSamplingRulesCreateBodyScopePathPatternMax)
        .nullish()
        .describe('Optional regex matched against a path-like log attribute when present.'),
    scope_attribute_filters: zod
        .unknown()
        .optional()
        .describe(
            'Optional list of predicates over string attributes, e.g. [{\"key\":\"http.route\",\"op\":\"eq\",\"value\":\"/api\"}].'
        ),
    config: zod
        .unknown()
        .describe('Type-specific JSON (severity actions, path_drop patterns, or future rate_limit settings).'),
})

export const logsSamplingRulesUpdateBodyNameMax = 255

export const logsSamplingRulesUpdateBodyEnabledDefault = false
export const logsSamplingRulesUpdateBodyPriorityMin = 0

export const logsSamplingRulesUpdateBodyScopeServiceMax = 512

export const logsSamplingRulesUpdateBodyScopePathPatternMax = 1024

export const LogsSamplingRulesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsSamplingRulesUpdateBodyNameMax).describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(logsSamplingRulesUpdateBodyEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(logsSamplingRulesUpdateBodyPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    rule_type: zod
        .enum(['severity_sampling', 'path_drop', 'rate_limit'])
        .describe('* `severity_sampling` - Severity sampling\n* `path_drop` - Path drop\n* `rate_limit` - Rate limit')
        .describe(
            'Rule kind: severity_sampling, path_drop, or rate_limit (rate_limit reserved for a future release).\n\n* `severity_sampling` - Severity sampling\n* `path_drop` - Path drop\n* `rate_limit` - Rate limit'
        ),
    scope_service: zod
        .string()
        .max(logsSamplingRulesUpdateBodyScopeServiceMax)
        .nullish()
        .describe('If set, the rule applies only to this service name; null means all services.'),
    scope_path_pattern: zod
        .string()
        .max(logsSamplingRulesUpdateBodyScopePathPatternMax)
        .nullish()
        .describe('Optional regex matched against a path-like log attribute when present.'),
    scope_attribute_filters: zod
        .unknown()
        .optional()
        .describe(
            'Optional list of predicates over string attributes, e.g. [{\"key\":\"http.route\",\"op\":\"eq\",\"value\":\"/api\"}].'
        ),
    config: zod
        .unknown()
        .describe('Type-specific JSON (severity actions, path_drop patterns, or future rate_limit settings).'),
})

export const logsSamplingRulesPartialUpdateBodyNameMax = 255

export const logsSamplingRulesPartialUpdateBodyEnabledDefault = false
export const logsSamplingRulesPartialUpdateBodyPriorityMin = 0

export const logsSamplingRulesPartialUpdateBodyScopeServiceMax = 512

export const logsSamplingRulesPartialUpdateBodyScopePathPatternMax = 1024

export const LogsSamplingRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(logsSamplingRulesPartialUpdateBodyNameMax)
        .optional()
        .describe('User-visible label for this rule.'),
    enabled: zod
        .boolean()
        .default(logsSamplingRulesPartialUpdateBodyEnabledDefault)
        .describe('When false, the rule is ignored by ingestion and listing UIs that show active rules only.'),
    priority: zod
        .number()
        .min(logsSamplingRulesPartialUpdateBodyPriorityMin)
        .nullish()
        .describe(
            'Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.'
        ),
    rule_type: zod
        .enum(['severity_sampling', 'path_drop', 'rate_limit'])
        .describe('* `severity_sampling` - Severity sampling\n* `path_drop` - Path drop\n* `rate_limit` - Rate limit')
        .optional()
        .describe(
            'Rule kind: severity_sampling, path_drop, or rate_limit (rate_limit reserved for a future release).\n\n* `severity_sampling` - Severity sampling\n* `path_drop` - Path drop\n* `rate_limit` - Rate limit'
        ),
    scope_service: zod
        .string()
        .max(logsSamplingRulesPartialUpdateBodyScopeServiceMax)
        .nullish()
        .describe('If set, the rule applies only to this service name; null means all services.'),
    scope_path_pattern: zod
        .string()
        .max(logsSamplingRulesPartialUpdateBodyScopePathPatternMax)
        .nullish()
        .describe('Optional regex matched against a path-like log attribute when present.'),
    scope_attribute_filters: zod
        .unknown()
        .optional()
        .describe(
            'Optional list of predicates over string attributes, e.g. [{\"key\":\"http.route\",\"op\":\"eq\",\"value\":\"/api\"}].'
        ),
    config: zod
        .unknown()
        .optional()
        .describe('Type-specific JSON (severity actions, path_drop patterns, or future rate_limit settings).'),
})

/**
 * Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).
 */
export const LogsSamplingRulesReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod
        .array(zod.uuid())
        .describe('Rule IDs in the desired evaluation order (first element is highest priority / lowest order index).'),
})

export const LogsServicesCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the services aggregation. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .optional()
                .describe('Filter by log severity levels.'),
            serviceNames: zod
                .array(zod.string())
                .optional()
                .describe('Restrict the aggregation to these service names.'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"log\", use \"message\". For \"log_attribute\"/\"log_resource_attribute\", use the attribute key (e.g. \"k8s.container.name\").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '\"log\" filters the log body/message. \"log_attribute\" filters log-level attributes. \"log_resource_attribute\" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
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
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .optional()
                .describe('Property filters for the query.'),
        })
        .describe('The services aggregation query to execute.'),
})

export const logsSparklineCreateBodyQueryOneSeverityLevelsDefault = []
export const logsSparklineCreateBodyQueryOneServiceNamesDefault = []
export const logsSparklineCreateBodyQueryOneFilterGroupDefault = []

export const LogsSparklineCreateBody = /* @__PURE__ */ zod.object({
    query: zod
        .object({
            dateRange: zod
                .object({
                    date_from: zod
                        .string()
                        .nullish()
                        .describe(
                            'Start of the date range. Accepts ISO 8601 timestamps or relative formats: -7d, -1h, -1mStart, etc.'
                        ),
                    date_to: zod
                        .string()
                        .nullish()
                        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
                })
                .optional()
                .describe('Date range for the sparkline. Defaults to last hour.'),
            severityLevels: zod
                .array(
                    zod
                        .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
                        .describe(
                            '* `trace` - trace\n* `debug` - debug\n* `info` - info\n* `warn` - warn\n* `error` - error\n* `fatal` - fatal'
                        )
                )
                .default(logsSparklineCreateBodyQueryOneSeverityLevelsDefault)
                .describe('Filter by log severity levels.'),
            serviceNames: zod
                .array(zod.string())
                .default(logsSparklineCreateBodyQueryOneServiceNamesDefault)
                .describe('Filter by service names.'),
            searchTerm: zod.string().optional().describe('Full-text search term to filter log bodies.'),
            filterGroup: zod
                .array(
                    zod.object({
                        key: zod
                            .string()
                            .describe(
                                'Attribute key. For type \"log\", use \"message\". For \"log_attribute\"/\"log_resource_attribute\", use the attribute key (e.g. \"k8s.container.name\").'
                            ),
                        type: zod
                            .enum(['log', 'log_attribute', 'log_resource_attribute'])
                            .describe(
                                '* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            )
                            .describe(
                                '\"log\" filters the log body/message. \"log_attribute\" filters log-level attributes. \"log_resource_attribute\" filters resource-level attributes.\n\n* `log` - log\n* `log_attribute` - log_attribute\n* `log_resource_attribute` - log_resource_attribute'
                            ),
                        operator: zod
                            .enum([
                                'exact',
                                'is_not',
                                'icontains',
                                'not_icontains',
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
                                '* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            )
                            .describe(
                                'Comparison operator.\n\n* `exact` - exact\n* `is_not` - is_not\n* `icontains` - icontains\n* `not_icontains` - not_icontains\n* `regex` - regex\n* `not_regex` - not_regex\n* `gt` - gt\n* `lt` - lt\n* `is_date_exact` - is_date_exact\n* `is_date_before` - is_date_before\n* `is_date_after` - is_date_after\n* `is_set` - is_set\n* `is_not_set` - is_not_set'
                            ),
                        value: zod
                            .unknown()
                            .nullish()
                            .describe(
                                'Value to compare against. String, number, or array of strings. Omit for is_set/is_not_set operators.'
                            ),
                    })
                )
                .default(logsSparklineCreateBodyQueryOneFilterGroupDefault)
                .describe('Property filters for the query.'),
            sparklineBreakdownBy: zod
                .enum(['severity', 'service'])
                .describe('* `severity` - severity\n* `service` - service')
                .optional()
                .describe(
                    'Break down sparkline by \"severity\" (default) or \"service\".\n\n* `severity` - severity\n* `service` - service'
                ),
        })
        .describe('The sparkline query to execute.'),
})
