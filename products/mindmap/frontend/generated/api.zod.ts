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

export const mindmapEdgesCreateBodySourceMax = 12

export const mindmapEdgesCreateBodyTargetMax = 12

export const MindmapEdgesCreateBody = /* @__PURE__ */ zod.object({
    source: zod.string().max(mindmapEdgesCreateBodySourceMax).describe('Source post-it short_id'),
    target: zod.string().max(mindmapEdgesCreateBodyTargetMax).describe('Target post-it short_id'),
})

export const mindmapPostitsCreateBodyTitleMax = 256

export const mindmapPostitsCreateBodyEmojiMax = 8

export const mindmapPostitsCreateBodyNotebookShortIdMax = 12

export const MindmapPostitsCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(mindmapPostitsCreateBodyTitleMax).describe('Short title shown on the post-it'),
    body: zod.string().optional().describe('Longer optional body text'),
    color: zod
        .enum(['yellow', 'pink', 'blue', 'green', 'purple', 'orange', 'gray'])
        .describe(
            '\* `yellow` - Yellow\n\* `pink` - Pink\n\* `blue` - Blue\n\* `green` - Green\n\* `purple` - Purple\n\* `orange` - Orange\n\* `gray` - Gray'
        )
        .optional()
        .describe(
            'Sticky-note background color\n\n\* `yellow` - Yellow\n\* `pink` - Pink\n\* `blue` - Blue\n\* `green` - Green\n\* `purple` - Purple\n\* `orange` - Orange\n\* `gray` - Gray'
        ),
    emoji: zod.string().max(mindmapPostitsCreateBodyEmojiMax).optional().describe('Optional single emoji'),
    position_x: zod.number().optional().describe('X coordinate on the canvas'),
    position_y: zod.number().optional().describe('Y coordinate on the canvas'),
    notebook_short_id: zod
        .string()
        .max(mindmapPostitsCreateBodyNotebookShortIdMax)
        .nullish()
        .describe('Notebook short_id this post-it links to (clicking opens it)'),
})

export const mindmapPostitsUpdateBodyTitleMax = 256

export const mindmapPostitsUpdateBodyEmojiMax = 8

export const mindmapPostitsUpdateBodyNotebookShortIdMax = 12

export const MindmapPostitsUpdateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(mindmapPostitsUpdateBodyTitleMax).describe('Short title shown on the post-it'),
    body: zod.string().optional().describe('Longer optional body text'),
    color: zod
        .enum(['yellow', 'pink', 'blue', 'green', 'purple', 'orange', 'gray'])
        .describe(
            '\* `yellow` - Yellow\n\* `pink` - Pink\n\* `blue` - Blue\n\* `green` - Green\n\* `purple` - Purple\n\* `orange` - Orange\n\* `gray` - Gray'
        )
        .optional()
        .describe(
            'Sticky-note background color\n\n\* `yellow` - Yellow\n\* `pink` - Pink\n\* `blue` - Blue\n\* `green` - Green\n\* `purple` - Purple\n\* `orange` - Orange\n\* `gray` - Gray'
        ),
    emoji: zod.string().max(mindmapPostitsUpdateBodyEmojiMax).optional().describe('Optional single emoji'),
    position_x: zod.number().optional().describe('X coordinate on the canvas'),
    position_y: zod.number().optional().describe('Y coordinate on the canvas'),
    notebook_short_id: zod
        .string()
        .max(mindmapPostitsUpdateBodyNotebookShortIdMax)
        .nullish()
        .describe('Notebook short_id this post-it links to (clicking opens it)'),
})

export const mindmapPostitsPartialUpdateBodyTitleMax = 256

export const mindmapPostitsPartialUpdateBodyEmojiMax = 8

export const mindmapPostitsPartialUpdateBodyNotebookShortIdMax = 12

export const MindmapPostitsPartialUpdateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(mindmapPostitsPartialUpdateBodyTitleMax)
        .optional()
        .describe('Short title shown on the post-it'),
    body: zod.string().optional().describe('Longer optional body text'),
    color: zod
        .enum(['yellow', 'pink', 'blue', 'green', 'purple', 'orange', 'gray'])
        .describe(
            '\* `yellow` - Yellow\n\* `pink` - Pink\n\* `blue` - Blue\n\* `green` - Green\n\* `purple` - Purple\n\* `orange` - Orange\n\* `gray` - Gray'
        )
        .optional()
        .describe(
            'Sticky-note background color\n\n\* `yellow` - Yellow\n\* `pink` - Pink\n\* `blue` - Blue\n\* `green` - Green\n\* `purple` - Purple\n\* `orange` - Orange\n\* `gray` - Gray'
        ),
    emoji: zod.string().max(mindmapPostitsPartialUpdateBodyEmojiMax).optional().describe('Optional single emoji'),
    position_x: zod.number().optional().describe('X coordinate on the canvas'),
    position_y: zod.number().optional().describe('Y coordinate on the canvas'),
    notebook_short_id: zod
        .string()
        .max(mindmapPostitsPartialUpdateBodyNotebookShortIdMax)
        .nullish()
        .describe('Notebook short_id this post-it links to (clicking opens it)'),
})

export const mindmapPostitsBulkPositionCreateBodyUpdatesItemShortIdMax = 12

export const MindmapPostitsBulkPositionCreateBody = /* @__PURE__ */ zod.object({
    updates: zod.array(
        zod.object({
            short_id: zod
                .string()
                .max(mindmapPostitsBulkPositionCreateBodyUpdatesItemShortIdMax)
                .describe('Post-it short_id'),
            position_x: zod.number().describe('New X coordinate'),
            position_y: zod.number().describe('New Y coordinate'),
        })
    ),
})
