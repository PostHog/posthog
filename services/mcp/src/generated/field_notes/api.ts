/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const FieldNotesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FieldNotesListQueryParams = /* @__PURE__ */ zod.object({
    field_note_status: zod
        .enum(['acknowledged', 'dismissed', 'pending', 'resolved'])
        .optional()
        .describe('Filter to field notes in this lifecycle state (e.g. `pending` for unaddressed feedback).'),
    host: zod.string().optional().describe('Filter to field notes made on this hostname (e.g. `app.example.com`).'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const FieldNotesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this field note.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const FieldNotesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this field note.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const fieldNotesPartialUpdateBodyCommentMax = 5000

export const fieldNotesPartialUpdateBodyUrlMax = 2048

export const fieldNotesPartialUpdateBodyHostMax = 255

export const fieldNotesPartialUpdateBodyPathnameMax = 2048

export const fieldNotesPartialUpdateBodySelectorMax = 4096

export const fieldNotesPartialUpdateBodyElementTextMax = 2048

export const fieldNotesPartialUpdateBodyElementChainMax = 20000

export const fieldNotesPartialUpdateBodyScreenshotUrlMax = 2048

export const FieldNotesPartialUpdateBody = /* @__PURE__ */ zod.object({
    comment: zod
        .string()
        .max(fieldNotesPartialUpdateBodyCommentMax)
        .optional()
        .describe('The note the user wrote about the element.'),
    field_note_status: zod
        .enum(['pending', 'acknowledged', 'resolved', 'dismissed'])
        .describe(
            '* `pending` - Pending\n* `acknowledged` - Acknowledged\n* `resolved` - Resolved\n* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the field note: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n* `pending` - Pending\n* `acknowledged` - Acknowledged\n* `resolved` - Resolved\n* `dismissed` - Dismissed'
        ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the field note.'),
    url: zod
        .string()
        .max(fieldNotesPartialUpdateBodyUrlMax)
        .optional()
        .describe('Full URL of the page the field note was made on.'),
    host: zod
        .string()
        .max(fieldNotesPartialUpdateBodyHostMax)
        .optional()
        .describe('Hostname of the page, used to scope field notes to a site.'),
    pathname: zod.string().max(fieldNotesPartialUpdateBodyPathnameMax).nullish().describe('Path portion of the URL.'),
    selector: zod
        .string()
        .max(fieldNotesPartialUpdateBodySelectorMax)
        .optional()
        .describe('CSS selector that locates the element on the page.'),
    element_text: zod
        .string()
        .max(fieldNotesPartialUpdateBodyElementTextMax)
        .nullish()
        .describe('Visible text of the element, if any.'),
    element_chain: zod
        .string()
        .max(fieldNotesPartialUpdateBodyElementChainMax)
        .nullish()
        .describe('Serialized autocapture-style element chain from the element up to the document root.'),
    element_context: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Structured element metadata (inferred selectors, attributes, component hints).'),
    viewport: zod
        .object({
            width: zod.number().optional().describe('Viewport width in pixels.'),
            height: zod.number().optional().describe('Viewport height in pixels.'),
        })
        .nullish()
        .describe('Viewport size when the field note was made, as {width, height}.'),
    screenshot_url: zod
        .string()
        .max(fieldNotesPartialUpdateBodyScreenshotUrlMax)
        .nullish()
        .describe('URL of an uploaded screenshot captured with the field_note.'),
})
