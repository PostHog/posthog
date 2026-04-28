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
 * DEBUG-only proxy that forwards SQL to the ClickHouse `autoresearch` user. SQL safety comes entirely from the CH user's grants + readonly=2 profile; the endpoint does not parse or filter SQL.
 * @summary Run a read-only query against the autoresearch test cluster
 */
export const queryPerformanceProxyExecuteTestCreateBodySqlMax = 65536

export const QueryPerformanceProxyExecuteTestCreateBody = /* @__PURE__ */ zod.object({
    sql: zod
        .string()
        .max(queryPerformanceProxyExecuteTestCreateBodySqlMax)
        .describe('ClickHouse SQL to run against the test cluster.'),
})
