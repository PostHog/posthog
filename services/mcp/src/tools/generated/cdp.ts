// AUTO-GENERATED from products/cdp/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/cdp/api'
import { McpEventFiltersSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpEventsPreviewSchema = () => {
    const McpEventSubscriptionsPreviewBody = orvalSchemas.McpEventSubscriptionsPreviewBody()
    return McpEventSubscriptionsPreviewBody.extend({ filters: McpEventFiltersSchema })
}

const mcpEventsPreview = (): ToolBase<ReturnType<typeof McpEventsPreviewSchema>, Schemas.MCPEventPreview> => ({
    name: 'mcp-events-preview',
    schema: McpEventsPreviewSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpEventsPreviewSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.project_id !== undefined) {
            body['project_id'] = params.project_id
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        const result = await context.api.request<Schemas.MCPEventPreview>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_event_subscriptions/preview/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-events-preview': mcpEventsPreview,
}
