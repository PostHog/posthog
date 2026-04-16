// AUTO-GENERATED from products/logs/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import {
    LogsAttributesRetrieveQueryParams,
    LogsQueryCreateBody,
    LogsSparklineCreateBody,
    LogsValuesRetrieveQueryParams,
} from '@/generated/logs/api'
import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const QueryLogsSchema = LogsQueryCreateBody

const queryLogs = (): ToolBase<typeof QueryLogsSchema, unknown> => ({
    name: 'query-logs',
    schema: QueryLogsSchema,
    handler: async (context: Context, params: z.infer<typeof QueryLogsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/logs/query/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const LogsAttributesListSchema = LogsAttributesRetrieveQueryParams

const logsAttributesList = (): ToolBase<typeof LogsAttributesListSchema, unknown> => ({
    name: 'logs-attributes-list',
    schema: LogsAttributesListSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAttributesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/logs/attributes/`,
            query: {
                attribute_type: params.attribute_type,
                dateRange: params.dateRange,
                filterGroup: params.filterGroup,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                serviceNames: params.serviceNames,
            },
        })
        const filtered = pickResponseFields(result, ['results', 'count']) as typeof result
        return filtered
    },
})

const LogsAttributeValuesListSchema = LogsValuesRetrieveQueryParams

const logsAttributeValuesList = (): ToolBase<typeof LogsAttributeValuesListSchema, unknown> => ({
    name: 'logs-attribute-values-list',
    schema: LogsAttributeValuesListSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAttributeValuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/logs/values/`,
            query: {
                attribute_type: params.attribute_type,
                dateRange: params.dateRange,
                filterGroup: params.filterGroup,
                key: params.key,
                serviceNames: params.serviceNames,
                value: params.value,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const LogsSparklineQuerySchema = LogsSparklineCreateBody

const logsSparklineQuery = (): ToolBase<typeof LogsSparklineQuerySchema, unknown> => ({
    name: 'logs-sparkline-query',
    schema: LogsSparklineQuerySchema,
    handler: async (context: Context, params: z.infer<typeof LogsSparklineQuerySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/logs/sparkline/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'query-logs': queryLogs,
    'logs-attributes-list': logsAttributesList,
    'logs-attribute-values-list': logsAttributeValuesList,
    'logs-sparkline-query': logsSparklineQuery,
}
