/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const LlmAnalyticsSentimentCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsSentimentCreateBodyIdsMax = 5

export const llmAnalyticsSentimentCreateBodyAnalysisLevelDefault = `trace`
export const llmAnalyticsSentimentCreateBodyForceRefreshDefault = false

export const LlmAnalyticsSentimentCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.string()).min(1).max(llmAnalyticsSentimentCreateBodyIdsMax),
    analysis_level: zod
        .enum(['trace', 'generation'])
        .describe('* `trace` - trace\n* `generation` - generation')
        .default(llmAnalyticsSentimentCreateBodyAnalysisLevelDefault),
    force_refresh: zod.boolean().default(llmAnalyticsSentimentCreateBodyForceRefreshDefault),
    date_from: zod.string().nullish(),
    date_to: zod.string().nullish(),
})
