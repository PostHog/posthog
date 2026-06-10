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
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const ToolbarAnnotationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ToolbarAnnotationsListQueryParams = /* @__PURE__ */ zod.object({
    annotation_status: zod
        .enum(['acknowledged', 'dismissed', 'pending', 'resolved'])
        .optional()
        .describe('Filter to annotations in this lifecycle state (e.g. `pending` for unaddressed feedback).'),
    host: zod.string().optional().describe('Filter to annotations made on this hostname (e.g. `app.example.com`).'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const ToolbarAnnotationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this toolbar annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
points at on their own site, surfaced to coding agents over MCP.
 */
export const ToolbarAnnotationsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this toolbar annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const toolbarAnnotationsPartialUpdateBodyCommentMax = 5000

export const toolbarAnnotationsPartialUpdateBodyUrlMax = 2048

export const toolbarAnnotationsPartialUpdateBodyHostMax = 255

export const toolbarAnnotationsPartialUpdateBodyPathnameMax = 2048

export const toolbarAnnotationsPartialUpdateBodySelectorMax = 4096

export const toolbarAnnotationsPartialUpdateBodyElementTextMax = 2048

export const toolbarAnnotationsPartialUpdateBodyElementChainMax = 20000

export const ToolbarAnnotationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    comment: zod
        .string()
        .max(toolbarAnnotationsPartialUpdateBodyCommentMax)
        .optional()
        .describe('The annotation note the user wrote about the element.'),
    annotation_status: zod
        .enum(['pending', 'acknowledged', 'resolved', 'dismissed'])
        .describe(
            '* `pending` - Pending\n* `acknowledged` - Acknowledged\n* `resolved` - Resolved\n* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the annotation: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n* `pending` - Pending\n* `acknowledged` - Acknowledged\n* `resolved` - Resolved\n* `dismissed` - Dismissed'
        ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the annotation.'),
    url: zod
        .string()
        .max(toolbarAnnotationsPartialUpdateBodyUrlMax)
        .optional()
        .describe('Full URL of the page the annotation was made on.'),
    host: zod
        .string()
        .max(toolbarAnnotationsPartialUpdateBodyHostMax)
        .optional()
        .describe('Hostname of the page, used to scope annotations to a site.'),
    pathname: zod
        .string()
        .max(toolbarAnnotationsPartialUpdateBodyPathnameMax)
        .nullish()
        .describe('Path portion of the URL.'),
    selector: zod
        .string()
        .max(toolbarAnnotationsPartialUpdateBodySelectorMax)
        .optional()
        .describe('CSS selector that locates the annotated element on the page.'),
    element_text: zod
        .string()
        .max(toolbarAnnotationsPartialUpdateBodyElementTextMax)
        .nullish()
        .describe('Visible text of the annotated element, if any.'),
    element_chain: zod
        .string()
        .max(toolbarAnnotationsPartialUpdateBodyElementChainMax)
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
        .describe('Viewport size when the annotation was made, as {width, height}.'),
    screenshot_url: zod.string().nullish().describe('URL of an uploaded screenshot captured with the annotation.'),
})
