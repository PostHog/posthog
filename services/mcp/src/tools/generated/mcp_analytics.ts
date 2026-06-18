// AUTO-GENERATED from products/mcp_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    McpAnalyticsFeedbackCreateBody,
    McpAnalyticsMissingCapabilitiesCreateBody,
    McpAnalyticsSessionsGenerateIntentParams,
} from '@/generated/mcp_analytics/api'
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

const McpFeedbackSubmitSchema = McpAnalyticsFeedbackCreateBody.omit({
    mcp_client_name: true,
    mcp_client_version: true,
    mcp_protocol_version: true,
    mcp_transport: true,
    mcp_session_id: true,
    mcp_trace_id: true,
})

const mcpFeedbackSubmit = (): ToolBase<typeof McpFeedbackSubmitSchema, Schemas.MCPAnalyticsSubmission> => ({
    name: 'mcp-feedback-submit',
    schema: McpFeedbackSubmitSchema,
    handler: async (context: Context, params: z.infer<typeof McpFeedbackSubmitSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.attempted_tool !== undefined) {
            body['attempted_tool'] = params.attempted_tool
        }
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        if (params.feedback !== undefined) {
            body['feedback'] = params.feedback
        }
        if (params.category !== undefined) {
            body['category'] = params.category
        }
        const result = await context.api.request<Schemas.MCPAnalyticsSubmission>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/feedback/`,
            body,
        })
        return result
    },
})

const McpMissingCapabilityReportSchema = McpAnalyticsMissingCapabilitiesCreateBody.omit({
    mcp_client_name: true,
    mcp_client_version: true,
    mcp_protocol_version: true,
    mcp_transport: true,
    mcp_session_id: true,
    mcp_trace_id: true,
})

const mcpMissingCapabilityReport = (): ToolBase<
    typeof McpMissingCapabilityReportSchema,
    Schemas.MCPAnalyticsSubmission
> => ({
    name: 'mcp-missing-capability-report',
    schema: McpMissingCapabilityReportSchema,
    handler: async (context: Context, params: z.infer<typeof McpMissingCapabilityReportSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.attempted_tool !== undefined) {
            body['attempted_tool'] = params.attempted_tool
        }
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        if (params.missing_capability !== undefined) {
            body['missing_capability'] = params.missing_capability
        }
        if (params.blocked !== undefined) {
            body['blocked'] = params.blocked
        }
        const result = await context.api.request<Schemas.MCPAnalyticsSubmission>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_analytics/missing_capabilities/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-analytics-intent-clusters-recompute': mcpAnalyticsIntentClustersRecompute,
    'mcp-analytics-intent-clusters-retrieve': mcpAnalyticsIntentClustersRetrieve,
    'mcp-analytics-sessions-generate-intent': mcpAnalyticsSessionsGenerateIntent,
    'mcp-feedback-submit': mcpFeedbackSubmit,
    'mcp-missing-capability-report': mcpMissingCapabilityReport,
}
