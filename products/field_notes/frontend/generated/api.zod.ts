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
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesCreateBodyCommentMax = 5000

export const fieldNotesCreateBodyUrlMax = 2048

export const fieldNotesCreateBodyHostMax = 255

export const fieldNotesCreateBodyPathnameMax = 2048

export const fieldNotesCreateBodySelectorMax = 4096

export const fieldNotesCreateBodyElementTextMax = 2048

export const fieldNotesCreateBodyElementChainMax = 20000

export const fieldNotesCreateBodyScreenshotUrlMax = 2048

export const FieldNotesCreateBody = /* @__PURE__ */ zod.object({
    comment: zod.string().max(fieldNotesCreateBodyCommentMax).describe('The note the user wrote about the element.'),
    field_note_status: zod
        .enum(['pending', 'acknowledged', 'resolved', 'dismissed'])
        .describe(
            '\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the field note: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the field note.'),
    url: zod.string().max(fieldNotesCreateBodyUrlMax).describe('Full URL of the page the field note was made on.'),
    host: zod
        .string()
        .max(fieldNotesCreateBodyHostMax)
        .describe('Hostname of the page, used to scope field notes to a site.'),
    pathname: zod.string().max(fieldNotesCreateBodyPathnameMax).nullish().describe('Path portion of the URL.'),
    selector: zod
        .string()
        .max(fieldNotesCreateBodySelectorMax)
        .describe('CSS selector that locates the element on the page.'),
    element_text: zod
        .string()
        .max(fieldNotesCreateBodyElementTextMax)
        .nullish()
        .describe('Visible text of the element, if any.'),
    element_chain: zod
        .string()
        .max(fieldNotesCreateBodyElementChainMax)
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
        .max(fieldNotesCreateBodyScreenshotUrlMax)
        .nullish()
        .describe('URL of an uploaded screenshot captured with the field_note.'),
})

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const fieldNotesUpdateBodyCommentMax = 5000

export const fieldNotesUpdateBodyUrlMax = 2048

export const fieldNotesUpdateBodyHostMax = 255

export const fieldNotesUpdateBodyPathnameMax = 2048

export const fieldNotesUpdateBodySelectorMax = 4096

export const fieldNotesUpdateBodyElementTextMax = 2048

export const fieldNotesUpdateBodyElementChainMax = 20000

export const fieldNotesUpdateBodyScreenshotUrlMax = 2048

export const FieldNotesUpdateBody = /* @__PURE__ */ zod.object({
    comment: zod.string().max(fieldNotesUpdateBodyCommentMax).describe('The note the user wrote about the element.'),
    field_note_status: zod
        .enum(['pending', 'acknowledged', 'resolved', 'dismissed'])
        .describe(
            '\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the field note: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the field note.'),
    url: zod.string().max(fieldNotesUpdateBodyUrlMax).describe('Full URL of the page the field note was made on.'),
    host: zod
        .string()
        .max(fieldNotesUpdateBodyHostMax)
        .describe('Hostname of the page, used to scope field notes to a site.'),
    pathname: zod.string().max(fieldNotesUpdateBodyPathnameMax).nullish().describe('Path portion of the URL.'),
    selector: zod
        .string()
        .max(fieldNotesUpdateBodySelectorMax)
        .describe('CSS selector that locates the element on the page.'),
    element_text: zod
        .string()
        .max(fieldNotesUpdateBodyElementTextMax)
        .nullish()
        .describe('Visible text of the element, if any.'),
    element_chain: zod
        .string()
        .max(fieldNotesUpdateBodyElementChainMax)
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
        .max(fieldNotesUpdateBodyScreenshotUrlMax)
        .nullish()
        .describe('URL of an uploaded screenshot captured with the field_note.'),
})

/**
 * Create, read, update, and resolve toolbar field notes — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
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
            '\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the field note: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
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
