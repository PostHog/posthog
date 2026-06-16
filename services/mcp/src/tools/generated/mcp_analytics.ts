// AUTO-GENERATED from products/mcp_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { McpAnalyticsSessionsGenerateIntentParams } from '@/generated/mcp_analytics/api'
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/recompute/`,
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/intent_clusters/`,
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/sessions/${encodeURIComponent(String(params.id))}/generate_intent/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-analytics-intent-clusters-recompute': mcpAnalyticsIntentClustersRecompute,
    'mcp-analytics-intent-clusters-retrieve': mcpAnalyticsIntentClustersRetrieve,
    'mcp-analytics-sessions-generate-intent': mcpAnalyticsSessionsGenerateIntent,
}
