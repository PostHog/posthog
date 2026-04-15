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

export const logsAlertsCreateBodyThresholdCountMax = 2147483647

export const logsAlertsCreateBodyThresholdOperatorDefault = `above`
export const logsAlertsCreateBodyWindowMinutesMin = 0
export const logsAlertsCreateBodyWindowMinutesMax = 2147483647

export const logsAlertsCreateBodyEvaluationPeriodsDefault = 1
export const logsAlertsCreateBodyEvaluationPeriodsMax = 10

export const logsAlertsCreateBodyDatapointsToAlarmDefault = 1
export const logsAlertsCreateBodyDatapointsToAlarmMax = 10

export const logsAlertsCreateBodyCooldownMinutesMin = 0
export const logsAlertsCreateBodyCooldownMinutesMax = 2147483647

export const LogsAlertsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsAlertsCreateBodyNameMax),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsCreateBodyThresholdCountMax),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsCreateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsCreateBodyWindowMinutesMin)
        .max(logsAlertsCreateBodyWindowMinutesMax)
        .optional(),
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
        .max(logsAlertsCreateBodyCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
})

export const logsAlertsUpdateBodyNameMax = 255

export const logsAlertsUpdateBodyThresholdCountMax = 2147483647

export const logsAlertsUpdateBodyThresholdOperatorDefault = `above`
export const logsAlertsUpdateBodyWindowMinutesMin = 0
export const logsAlertsUpdateBodyWindowMinutesMax = 2147483647

export const logsAlertsUpdateBodyEvaluationPeriodsDefault = 1
export const logsAlertsUpdateBodyEvaluationPeriodsMax = 10

export const logsAlertsUpdateBodyDatapointsToAlarmDefault = 1
export const logsAlertsUpdateBodyDatapointsToAlarmMax = 10

export const logsAlertsUpdateBodyCooldownMinutesMin = 0
export const logsAlertsUpdateBodyCooldownMinutesMax = 2147483647

export const LogsAlertsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsAlertsUpdateBodyNameMax),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsUpdateBodyThresholdCountMax),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsUpdateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsUpdateBodyWindowMinutesMin)
        .max(logsAlertsUpdateBodyWindowMinutesMax)
        .optional(),
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
        .max(logsAlertsUpdateBodyCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
})

export const logsAlertsPartialUpdateBodyNameMax = 255

export const logsAlertsPartialUpdateBodyThresholdCountMax = 2147483647

export const logsAlertsPartialUpdateBodyThresholdOperatorDefault = `above`
export const logsAlertsPartialUpdateBodyWindowMinutesMin = 0
export const logsAlertsPartialUpdateBodyWindowMinutesMax = 2147483647

export const logsAlertsPartialUpdateBodyEvaluationPeriodsDefault = 1
export const logsAlertsPartialUpdateBodyEvaluationPeriodsMax = 10

export const logsAlertsPartialUpdateBodyDatapointsToAlarmDefault = 1
export const logsAlertsPartialUpdateBodyDatapointsToAlarmMax = 10

export const logsAlertsPartialUpdateBodyCooldownMinutesMin = 0
export const logsAlertsPartialUpdateBodyCooldownMinutesMax = 2147483647

export const LogsAlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(logsAlertsPartialUpdateBodyNameMax).optional(),
    enabled: zod.boolean().optional(),
    filters: zod
        .unknown()
        .optional()
        .describe(
            'Filter criteria — subset of LogsViewerFilters. Must contain at least one of: severityLevels (list of severity strings), serviceNames (list of service name strings), or filterGroup (property filter group object).'
        ),
    threshold_count: zod.number().min(1).max(logsAlertsPartialUpdateBodyThresholdCountMax).optional(),
    threshold_operator: zod
        .enum(['above', 'below'])
        .describe('* `above` - Above\n* `below` - Below')
        .default(logsAlertsPartialUpdateBodyThresholdOperatorDefault)
        .describe(
            'Whether the alert fires when the count is above or below the threshold.\n\n* `above` - Above\n* `below` - Below'
        ),
    window_minutes: zod
        .number()
        .min(logsAlertsPartialUpdateBodyWindowMinutesMin)
        .max(logsAlertsPartialUpdateBodyWindowMinutesMax)
        .optional(),
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
        .max(logsAlertsPartialUpdateBodyCooldownMinutesMax)
        .optional(),
    snooze_until: zod.iso.datetime({}).nullish(),
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
