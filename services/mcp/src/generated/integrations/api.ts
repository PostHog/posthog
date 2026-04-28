/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const IntegrationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const IntegrationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const IntegrationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const IntegrationsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const IntegrationsChannelsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this integration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const integrationsChannelsRetrieveQueryForceRefreshDefault = false

export const IntegrationsChannelsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    channel_id: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'When provided, look up only this channel by ID instead of returning the full list. Returns a single-element channels array, or empty if not found / not accessible.'
        ),
    force_refresh: zod
        .boolean()
        .default(integrationsChannelsRetrieveQueryForceRefreshDefault)
        .describe(
            'When true, bypass the 1h Redis cache and fetch fresh channels from Slack. Subject to per-team rate limiting (30/min).'
        ),
})
