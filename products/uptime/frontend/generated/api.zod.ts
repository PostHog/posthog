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

export const uptimeMonitorsCreateBodyNameMax = 255

export const uptimeMonitorsCreateBodyUrlMax = 2048

export const UptimeMonitorsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(uptimeMonitorsCreateBodyNameMax).describe('Human-readable name of the monitor.'),
    url: zod.url().max(uptimeMonitorsCreateBodyUrlMax).describe('HTTP(S) URL to ping every 5 minutes.'),
})

export const uptimeMonitorsPartialUpdateBodyNameMax = 255

export const uptimeMonitorsPartialUpdateBodyUrlMax = 2048

export const UptimeMonitorsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(uptimeMonitorsPartialUpdateBodyNameMax)
        .optional()
        .describe('New human-readable name of the monitor.'),
    url: zod
        .url()
        .max(uptimeMonitorsPartialUpdateBodyUrlMax)
        .optional()
        .describe('New HTTP(S) URL to ping every 5 minutes.'),
})

/**
 * Create multiple monitors in a single atomic transaction. Used by the URL-suggester bulk add.
 */
export const uptimeMonitorsBulkCreateCreateBodyMonitorsItemNameMax = 255

export const uptimeMonitorsBulkCreateCreateBodyMonitorsItemUrlMax = 2048

export const UptimeMonitorsBulkCreateCreateBody = /* @__PURE__ */ zod.object({
    monitors: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(uptimeMonitorsBulkCreateCreateBodyMonitorsItemNameMax)
                    .describe('Human-readable name of the monitor.'),
                url: zod
                    .url()
                    .max(uptimeMonitorsBulkCreateCreateBodyMonitorsItemUrlMax)
                    .describe('HTTP(S) URL to ping every 5 minutes.'),
            })
        )
        .describe('List of monitors to create. All-or-nothing: created atomically.'),
})

/**
 * Persist the user-controlled display order. Position 0 renders first.
 */
export const UptimeMonitorsReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod
        .array(zod.uuid())
        .describe('Monitor IDs in their desired display order. Position 0 renders first.'),
})
