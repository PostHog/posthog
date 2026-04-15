// AUTO-GENERATED from products/logs/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const QueryLogsSchema = z.object({})

const queryLogs = (): ToolBase<typeof QueryLogsSchema, unknown> => ({
    name: 'query-logs',
    schema: QueryLogsSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof QueryLogsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/logs/query/`,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const LogsAttributesListSchema = z.object({})

const logsAttributesList = (): ToolBase<typeof LogsAttributesListSchema, unknown> => ({
    name: 'logs-attributes-list',
    schema: LogsAttributesListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof LogsAttributesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/logs/attributes/`,
        })
        const filtered = pickResponseFields(result, ['results', 'count']) as typeof result
        return filtered
    },
})

const LogsAttributeValuesListSchema = z.object({})

const logsAttributeValuesList = (): ToolBase<typeof LogsAttributeValuesListSchema, unknown> => ({
    name: 'logs-attribute-values-list',
    schema: LogsAttributeValuesListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof LogsAttributeValuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/logs/values/`,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'query-logs': queryLogs,
    'logs-attributes-list': logsAttributesList,
    'logs-attribute-values-list': logsAttributeValuesList,
}
