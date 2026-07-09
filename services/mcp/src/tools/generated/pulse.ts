// AUTO-GENERATED from products/pulse/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { QueryPerformanceProxyExecuteTestCreateBody } from '@/generated/pulse/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const QueryPerformanceExecuteSqlSchema = QueryPerformanceProxyExecuteTestCreateBody

const queryPerformanceExecuteSql = (): ToolBase<
    typeof QueryPerformanceExecuteSqlSchema,
    Schemas.ExecuteTestClusterResponse
> => ({
    name: 'query-performance-execute-sql',
    schema: QueryPerformanceExecuteSqlSchema,
    handler: async (context: Context, params: z.infer<typeof QueryPerformanceExecuteSqlSchema>) => {
        const body: Record<string, unknown> = {}
        if (params.sql !== undefined) {
            body['sql'] = params.sql
        }
        const result = await context.api.request<Schemas.ExecuteTestClusterResponse>({
            method: 'POST',
            path: `/api/query_performance_proxy/execute-test/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'query-performance-execute-sql': queryPerformanceExecuteSql,
}
