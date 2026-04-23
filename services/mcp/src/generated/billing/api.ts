/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const BillingListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Endpoint to fetch spend data (proxy to billing service).
 */
export const BillingSpendRetrieveQueryParams = /* @__PURE__ */ zod.object({
    breakdowns: zod.string().nullish(),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    start_date: zod.string().nullish(),
    team_ids: zod.string().nullish(),
    usage_types: zod.string().nullish(),
})

export const BillingUsageRetrieveQueryParams = /* @__PURE__ */ zod.object({
    breakdowns: zod.string().nullish(),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    start_date: zod.string().nullish(),
    team_ids: zod.string().nullish(),
    usage_types: zod.string().nullish(),
})
