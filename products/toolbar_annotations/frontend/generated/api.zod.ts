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
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsCreateBodyCommentMax = 5000

export const toolbarAnnotationsCreateBodyUrlMax = 2048

export const toolbarAnnotationsCreateBodyHostMax = 255

export const toolbarAnnotationsCreateBodyPathnameMax = 2048

export const toolbarAnnotationsCreateBodySelectorMax = 4096

export const toolbarAnnotationsCreateBodyElementTextMax = 2048

export const toolbarAnnotationsCreateBodyElementChainMax = 20000

export const ToolbarAnnotationsCreateBody = /* @__PURE__ */ zod.object({
    comment: zod
        .string()
        .max(toolbarAnnotationsCreateBodyCommentMax)
        .describe('The annotation note the user wrote about the element.'),
    annotation_status: zod
        .enum(['pending', 'acknowledged', 'resolved', 'dismissed'])
        .describe(
            '\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the annotation: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the annotation.'),
    url: zod
        .string()
        .max(toolbarAnnotationsCreateBodyUrlMax)
        .describe('Full URL of the page the annotation was made on.'),
    host: zod
        .string()
        .max(toolbarAnnotationsCreateBodyHostMax)
        .describe('Hostname of the page, used to scope annotations to a site.'),
    pathname: zod.string().max(toolbarAnnotationsCreateBodyPathnameMax).nullish().describe('Path portion of the URL.'),
    selector: zod
        .string()
        .max(toolbarAnnotationsCreateBodySelectorMax)
        .describe('CSS selector that locates the annotated element on the page.'),
    element_text: zod
        .string()
        .max(toolbarAnnotationsCreateBodyElementTextMax)
        .nullish()
        .describe('Visible text of the annotated element, if any.'),
    element_chain: zod
        .string()
        .max(toolbarAnnotationsCreateBodyElementChainMax)
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

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const toolbarAnnotationsUpdateBodyCommentMax = 5000

export const toolbarAnnotationsUpdateBodyUrlMax = 2048

export const toolbarAnnotationsUpdateBodyHostMax = 255

export const toolbarAnnotationsUpdateBodyPathnameMax = 2048

export const toolbarAnnotationsUpdateBodySelectorMax = 4096

export const toolbarAnnotationsUpdateBodyElementTextMax = 2048

export const toolbarAnnotationsUpdateBodyElementChainMax = 20000

export const ToolbarAnnotationsUpdateBody = /* @__PURE__ */ zod.object({
    comment: zod
        .string()
        .max(toolbarAnnotationsUpdateBodyCommentMax)
        .describe('The annotation note the user wrote about the element.'),
    annotation_status: zod
        .enum(['pending', 'acknowledged', 'resolved', 'dismissed'])
        .describe(
            '\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the annotation: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the annotation.'),
    url: zod
        .string()
        .max(toolbarAnnotationsUpdateBodyUrlMax)
        .describe('Full URL of the page the annotation was made on.'),
    host: zod
        .string()
        .max(toolbarAnnotationsUpdateBodyHostMax)
        .describe('Hostname of the page, used to scope annotations to a site.'),
    pathname: zod.string().max(toolbarAnnotationsUpdateBodyPathnameMax).nullish().describe('Path portion of the URL.'),
    selector: zod
        .string()
        .max(toolbarAnnotationsUpdateBodySelectorMax)
        .describe('CSS selector that locates the annotated element on the page.'),
    element_text: zod
        .string()
        .max(toolbarAnnotationsUpdateBodyElementTextMax)
        .nullish()
        .describe('Visible text of the annotated element, if any.'),
    element_chain: zod
        .string()
        .max(toolbarAnnotationsUpdateBodyElementChainMax)
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

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
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
            '\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        )
        .optional()
        .describe(
            'Lifecycle of the annotation: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
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
