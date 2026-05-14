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

export const uptimeIncidentsCreateBodyNameMax = 255

export const UptimeIncidentsCreateBody = /* @__PURE__ */ zod.object({
    monitor_id: zod.uuid().describe('ID of the monitor this incident is attached to.'),
    name: zod.string().max(uptimeIncidentsCreateBodyNameMax).describe('Short, human-readable incident title.'),
    description: zod.string().optional().describe('Longer description of the incident, shown publicly.'),
    started_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('When the incident started. Defaults to the time the incident was created.'),
})

export const uptimeIncidentsPartialUpdateBodyNameMax = 255

export const UptimeIncidentsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(uptimeIncidentsPartialUpdateBodyNameMax).optional().describe('Updated incident title.'),
    description: zod.string().optional().describe('Updated description of the incident.'),
    started_at: zod.iso.datetime({ offset: true }).optional().describe('Updated start time of the incident.'),
    resolved_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When the incident was resolved. Null means the incident is still ongoing.'),
    resolution_note: zod.string().optional().describe('Note explaining how the incident was resolved.'),
})

/**
 * Mark the incident as resolved with a required resolution note. The note is shown on the public status page.
 */
export const UptimeIncidentsResolveCreateBody = /* @__PURE__ */ zod.object({
    resolution_note: zod
        .string()
        .describe('Required note explaining how the incident was resolved. Shown on the public status page.'),
})

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

/**
 * Patch any subset of title, slug, monitor_ids on the page.
 */
export const uptimeStatusPagesPartialUpdateBodyTitleMax = 255

export const uptimeStatusPagesPartialUpdateBodySlugMax = 64

export const UptimeStatusPagesPartialUpdateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(uptimeStatusPagesPartialUpdateBodyTitleMax)
        .optional()
        .describe('Human-readable title of the status page, shown publicly above the monitor list.'),
    slug: zod
        .string()
        .max(uptimeStatusPagesPartialUpdateBodySlugMax)
        .optional()
        .describe('URL slug used in the public URL \/status\/<slug>. Must be globally unique.'),
    monitor_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('Ordered list of monitor IDs to display on this status page. Order is preserved.'),
})
