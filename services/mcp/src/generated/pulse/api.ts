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
 * Forwards SQL to the restricted autoresearch ClickHouse user for query-performance analysis (query_log_archive and related tables). Read-only; row and time limited.
 * @summary Run a read-only query against the autoresearch test cluster
 */
export const queryPerformanceProxyExecuteTestCreateBodySqlMax = 65536

export const QueryPerformanceProxyExecuteTestCreateBody = /* @__PURE__ */ zod.object({
    sql: zod
        .string()
        .max(queryPerformanceProxyExecuteTestCreateBodySqlMax)
        .describe('ClickHouse SQL to run against the test cluster.'),
})
