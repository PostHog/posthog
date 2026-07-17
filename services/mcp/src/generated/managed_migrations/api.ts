/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List batch import (managed migration) jobs across all teams. PostHog staff only.
 */
export const ManagedMigrationsSupportListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod.string().optional().describe('Which field to use when ordering the results.'),
    search: zod.string().optional().describe('A search term.'),
    status: zod
        .enum(['completed', 'failed', 'paused', 'running'])
        .optional()
        .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
    team_id: zod.number().optional(),
})

/**
 * Get one batch import job with its raw worker state and import config. PostHog staff only.
 */
export const ManagedMigrationsSupportRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this batch import.'),
})
