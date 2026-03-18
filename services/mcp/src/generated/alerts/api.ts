/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const AlertsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AlertsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const AlertsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const alertsCreateBodyConfigOneTypeDefault = `TrendsAlertConfig`

export const AlertsCreateBody = /* @__PURE__ */ zod.object({
    insight: zod
        .number()
        .describe('Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object.'),
    name: zod.string().optional().describe('Human-readable name for the alert.'),
    subscribed_users: zod
        .array(zod.number())
        .describe('User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object.'),
    threshold: zod
        .object({
            id: zod.string().optional(),
            created_at: zod.iso.datetime({}).optional(),
            name: zod.string().optional().describe('Optional name for the threshold.'),
            configuration: zod
                .object({
                    bounds: zod
                        .object({
                            lower: zod
                                .number()
                                .nullish()
                                .describe('Alert fires when the value drops below this number.'),
                            upper: zod.number().nullish().describe('Alert fires when the value exceeds this number.'),
                        })
                        .nullish(),
                    type: zod.enum(['absolute', 'percentage']),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage).'
                ),
        })
        .describe('Threshold configuration with bounds and type for evaluating the alert.'),
    condition: zod
        .object({
            type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
        })
        .nullish()
        .describe(
            'Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease.'
        ),
    enabled: zod.boolean().optional().describe('Whether the alert is actively being evaluated.'),
    config: zod
        .object({
            check_ongoing_interval: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                ),
            series_index: zod.number().describe("Zero-based index of the series in the insight's query to monitor."),
            type: zod.enum(['TrendsAlertConfig']).default(alertsCreateBodyConfigOneTypeDefault),
        })
        .nullish()
        .describe(
            'Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval).'
        ),
    calculation_interval: zod
        .union([
            zod
                .enum(['hourly', 'daily', 'weekly', 'monthly'])
                .describe('* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the alert is checked: hourly, daily, weekly, or monthly.\n\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        ),
    snoozed_until: zod
        .string()
        .nullish()
        .describe(
            "Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze."
        ),
    skip_weekend: zod.boolean().nullish().describe('Skip alert evaluation on weekends (Saturday and Sunday).'),
})

export const AlertsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AlertsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const alertsPartialUpdateBodyConfigOneTypeDefault = `TrendsAlertConfig`

export const AlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    insight: zod
        .number()
        .optional()
        .describe('Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object.'),
    name: zod.string().optional().describe('Human-readable name for the alert.'),
    subscribed_users: zod
        .array(zod.number())
        .optional()
        .describe('User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object.'),
    threshold: zod
        .object({
            id: zod.string().optional(),
            created_at: zod.iso.datetime({}).optional(),
            name: zod.string().optional().describe('Optional name for the threshold.'),
            configuration: zod
                .object({
                    bounds: zod
                        .object({
                            lower: zod
                                .number()
                                .nullish()
                                .describe('Alert fires when the value drops below this number.'),
                            upper: zod.number().nullish().describe('Alert fires when the value exceeds this number.'),
                        })
                        .nullish(),
                    type: zod.enum(['absolute', 'percentage']),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage).'
                ),
        })
        .optional()
        .describe('Threshold configuration with bounds and type for evaluating the alert.'),
    condition: zod
        .object({
            type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
        })
        .nullish()
        .describe(
            'Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease.'
        ),
    enabled: zod.boolean().optional().describe('Whether the alert is actively being evaluated.'),
    config: zod
        .object({
            check_ongoing_interval: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                ),
            series_index: zod.number().describe("Zero-based index of the series in the insight's query to monitor."),
            type: zod.enum(['TrendsAlertConfig']).default(alertsPartialUpdateBodyConfigOneTypeDefault),
        })
        .nullish()
        .describe(
            'Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval).'
        ),
    calculation_interval: zod
        .union([
            zod
                .enum(['hourly', 'daily', 'weekly', 'monthly'])
                .describe('* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the alert is checked: hourly, daily, weekly, or monthly.\n\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        ),
    snoozed_until: zod
        .string()
        .nullish()
        .describe(
            "Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze."
        ),
    skip_weekend: zod.boolean().nullish().describe('Skip alert evaluation on weekends (Saturday and Sunday).'),
})

export const AlertsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
