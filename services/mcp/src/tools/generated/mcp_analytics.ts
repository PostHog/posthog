// AUTO-GENERATED from products/mcp_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    McpAnalyticsSessionsGenerateIntentParams,
    McpAnalyticsSessionsListQueryParams,
    McpAnalyticsSessionsToolCallsParams,
    McpAnalyticsSessionsToolCallsQueryParams,
} from '@/generated/mcp_analytics/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpAnalyticsIntentClustersRecomputeSchema = z.object({})

const mcpAnalyticsIntentClustersRecompute = (): ToolBase<
    typeof McpAnalyticsIntentClustersRecomputeSchema,
    unknown
> => ({
    name: 'mcp-analytics-intent-clusters-recompute',
    schema: McpAnalyticsIntentClustersRecomputeSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsIntentClustersRecomputeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/recompute/`,
        })
        return result
    },
})

const McpAnalyticsIntentClustersRetrieveSchema = z.object({})

const mcpAnalyticsIntentClustersRetrieve = (): ToolBase<
    typeof McpAnalyticsIntentClustersRetrieveSchema,
    Schemas.MCPIntentClusterSnapshot[]
> => ({
    name: 'mcp-analytics-intent-clusters-retrieve',
    schema: McpAnalyticsIntentClustersRetrieveSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsIntentClustersRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MCPIntentClusterSnapshot[]>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/`,
        })
        return result
    },
})

const McpAnalyticsSessionsGenerateIntentSchema = McpAnalyticsSessionsGenerateIntentParams.omit({ project_id: true })

const mcpAnalyticsSessionsGenerateIntent = (): ToolBase<
    typeof McpAnalyticsSessionsGenerateIntentSchema,
    Schemas.MCPSessionIntent
> => ({
    name: 'mcp-analytics-sessions-generate-intent',
    schema: McpAnalyticsSessionsGenerateIntentSchema,
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsSessionsGenerateIntentSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MCPSessionIntent>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/${encodeURIComponent(String(params.id))}/generate_intent/`,
        })
        return result
    },
})

const McpAnalyticsSessionsListSchema = McpAnalyticsSessionsListQueryParams

const mcpAnalyticsSessionsList = (): ToolBase<
    typeof McpAnalyticsSessionsListSchema,
    WithPostHogUrl<Schemas.PaginatedMCPSessionList>
> => ({
    name: 'mcp-analytics-sessions-list',
    schema: McpAnalyticsSessionsListSchema,
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsSessionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPSessionList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/mcp-analytics')
    },
})

const McpAnalyticsSessionsToolCallsSchema = McpAnalyticsSessionsToolCallsParams.omit({ project_id: true }).extend(
    McpAnalyticsSessionsToolCallsQueryParams.shape
)

const mcpAnalyticsSessionsToolCalls = (): ToolBase<
    typeof McpAnalyticsSessionsToolCallsSchema,
    Schemas.PaginatedMCPToolCallList
> => ({
    name: 'mcp-analytics-sessions-tool-calls',
    schema: McpAnalyticsSessionsToolCallsSchema,
    handler: async (context: Context, params: z.infer<typeof McpAnalyticsSessionsToolCallsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPToolCallList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/${encodeURIComponent(String(params.id))}/tool_calls/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-analytics-intent-clusters-recompute': mcpAnalyticsIntentClustersRecompute,
    'mcp-analytics-intent-clusters-retrieve': mcpAnalyticsIntentClustersRetrieve,
    'mcp-analytics-sessions-generate-intent': mcpAnalyticsSessionsGenerateIntent,
    'mcp-analytics-sessions-list': mcpAnalyticsSessionsList,
    'mcp-analytics-sessions-tool-calls': mcpAnalyticsSessionsToolCalls,
}
