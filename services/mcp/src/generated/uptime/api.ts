/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 25 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Incidents for the team, ongoing first, then most recently started.
 */
export const UptimeIncidentsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeIncidentsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    monitor_id: zod.string().optional().describe('When provided, only incidents for this monitor are returned.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const UptimeIncidentsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const uptimeIncidentsCreateBodyNameMax = 255

export const UptimeIncidentsCreateBody = /* @__PURE__ */ zod.object({
    monitor_id: zod.string().describe('ID of the monitor this incident is attached to.'),
    name: zod.string().max(uptimeIncidentsCreateBodyNameMax).describe('Short, human-readable incident title.'),
    description: zod.string().optional().describe('Longer description of the incident, shown publicly.'),
    started_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('When the incident started. Defaults to the time the incident was created.'),
})

export const UptimeIncidentsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeIncidentsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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

export const UptimeIncidentsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Reopen the incident, clearing resolved_at and the resolution note so it shows as ongoing again.
 */
export const UptimeIncidentsReopenCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Mark the incident as resolved with a required resolution note. The note is shown on the public status page.
 */
export const UptimeIncidentsResolveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeIncidentsResolveCreateBody = /* @__PURE__ */ zod.object({
    resolution_note: zod
        .string()
        .describe('Required note explaining how the incident was resolved. Shown on the public status page.'),
})

export const UptimeMonitorsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const UptimeMonitorsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const uptimeMonitorsCreateBodyNameMax = 255

export const uptimeMonitorsCreateBodyUrlMax = 2048

export const UptimeMonitorsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(uptimeMonitorsCreateBodyNameMax).describe('Human-readable name of the monitor.'),
    url: zod.url().max(uptimeMonitorsCreateBodyUrlMax).describe('HTTP(S) URL to ping every 5 minutes.'),
})

/**
 * Same data as the summary list, but for one monitor by id.
 */
export const UptimeMonitorsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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

export const UptimeMonitorsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsPingNowCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsPingsListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsPingsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create multiple monitors in a single atomic transaction. Used by the URL-suggester bulk add.
 */
export const UptimeMonitorsBulkCreateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsBulkCreateCreateQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

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
export const UptimeMonitorsReorderCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod
        .array(zod.string())
        .describe('Monitor IDs in their desired display order. Position 0 renders first.'),
})

/**
 * Suggest pingable URLs derived from $pageview events, excluding hosts already monitored.
 */
export const UptimeMonitorsSuggestedUrlsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsSuggestedUrlsListQueryParams = /* @__PURE__ */ zod.object({
    days: zod.number().optional().describe('Look-back window in days. Defaults to 30.'),
    limit: zod.number().optional().describe('Maximum number of suggestions to return. Defaults to 20.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Per-monitor status, 30-day uptime, 24h latency, last ping, and 30 daily status buckets.
 */
export const UptimeMonitorsSummaryListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeMonitorsSummaryListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const UptimeStatusPagesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeStatusPagesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create a draft status page with default title, color, and slug. Returns the new draft.
 */
export const UptimeStatusPagesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UptimeStatusPagesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Patch any subset of title, slug, monitor_ids on the page.
 */
export const UptimeStatusPagesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
        .describe('URL slug used in the public URL /status/<slug>. Must be globally unique.'),
    monitor_ids: zod
        .array(zod.string())
        .optional()
        .describe('Ordered list of monitor IDs to display on this status page. Order is preserved.'),
})

export const UptimeStatusPagesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Publish the status page. Makes it accessible at /status/<slug> without authentication.
 */
export const UptimeStatusPagesPublishCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Revert the status page to draft and remove public access.
 */
export const UptimeStatusPagesUnpublishCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
