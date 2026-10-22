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
 * Create an uptime monitor.
 */
export const uptimeMonitorsCreateBodyUrlMax = 2048

export const uptimeMonitorsCreateBodyIntervalSecondsMin = 60
export const uptimeMonitorsCreateBodyIntervalSecondsMax = 86400

export const uptimeMonitorsCreateBodyTimeoutSecondsMax = 30

export const UptimeMonitorsCreateBody = /* @__PURE__ */ zod.object({
    url: zod.url().max(uptimeMonitorsCreateBodyUrlMax).describe('The http or https URL to check.'),
    name: zod.string().describe('Display name for the monitor.'),
    method: zod
        .enum(['GET', 'HEAD'])
        .describe('\* `GET` - GET\n\* `HEAD` - HEAD')
        .optional()
        .describe('HTTP method used for each check.\n\n\* `GET` - GET\n\* `HEAD` - HEAD'),
    interval_seconds: zod
        .number()
        .min(uptimeMonitorsCreateBodyIntervalSecondsMin)
        .max(uptimeMonitorsCreateBodyIntervalSecondsMax)
        .optional()
        .describe('Seconds between checks, a whole number of minutes from 60 to 86400.'),
    timeout_seconds: zod
        .number()
        .min(1)
        .max(uptimeMonitorsCreateBodyTimeoutSecondsMax)
        .optional()
        .describe('Seconds to wait for a response before the check fails, from 1 to 30.'),
    enabled: zod.boolean().optional().describe('Whether checks run for this monitor.'),
})

/**
 * Change some fields of an uptime monitor.
 */
export const uptimeMonitorsPartialUpdateBodyUrlMax = 2048

export const uptimeMonitorsPartialUpdateBodyIntervalSecondsMin = 60
export const uptimeMonitorsPartialUpdateBodyIntervalSecondsMax = 86400

export const uptimeMonitorsPartialUpdateBodyTimeoutSecondsMax = 30

export const UptimeMonitorsPartialUpdateBody = /* @__PURE__ */ zod.object({
    url: zod.url().max(uptimeMonitorsPartialUpdateBodyUrlMax).optional().describe('The http or https URL to check.'),
    name: zod.string().nullish().describe('Display name for the monitor.'),
    method: zod
        .union([zod.enum(['GET', 'HEAD']).describe('\* `GET` - GET\n\* `HEAD` - HEAD'), zod.null()])
        .optional()
        .describe('HTTP method used for each check.\n\n\* `GET` - GET\n\* `HEAD` - HEAD'),
    interval_seconds: zod
        .number()
        .min(uptimeMonitorsPartialUpdateBodyIntervalSecondsMin)
        .max(uptimeMonitorsPartialUpdateBodyIntervalSecondsMax)
        .nullish()
        .describe('Seconds between checks, a whole number of minutes from 60 to 86400.'),
    timeout_seconds: zod
        .number()
        .min(1)
        .max(uptimeMonitorsPartialUpdateBodyTimeoutSecondsMax)
        .nullish()
        .describe('Seconds to wait for a response before the check fails, from 1 to 30.'),
    enabled: zod.boolean().nullish().describe('Whether checks run for this monitor.'),
})
