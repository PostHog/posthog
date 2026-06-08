/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Publish a pre-rendered PNG image and get back a durable signed URL that can be posted to Slack.
 */
export const ChartImagesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const chartImagesCreateBodyTitleDefault = ``

export const ChartImagesCreateBody = /* @__PURE__ */ zod.object({
    image_base64: zod
        .string()
        .describe('Base64-encoded PNG image bytes to publish. Must decode to a PNG no larger than 5 MiB.'),
    title: zod
        .string()
        .default(chartImagesCreateBodyTitleDefault)
        .describe('Optional title used to build a readable filename for the published image.'),
    insight_short_id: zod
        .string()
        .nullish()
        .describe('Optional short id of the insight this image visualizes, recorded for provenance.'),
})
