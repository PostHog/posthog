// AUTO-GENERATED from products/mcp_store/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/mcp_store/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpConnectionToolsListSchema = () => {
    const McpServerInstallationsToolsRetrieveParams = orvalSchemas.McpServerInstallationsToolsRetrieveParams()
    return McpServerInstallationsToolsRetrieveParams.omit({ project_id: true })
}

const mcpConnectionToolsList = (): ToolBase<
    ReturnType<typeof McpConnectionToolsListSchema>,
    WithPostHogUrl<Schemas.PaginatedMCPServerInstallationToolList>
> => ({
    name: 'mcp-connection-tools-list',
    schema: McpConnectionToolsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpConnectionToolsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPServerInstallationToolList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_server_installations/${encodeURIComponent(String(params.id))}/tools/`,
        })
        return await withPostHogUrl(context, result, '/settings/mcp-servers')
    },
})

const McpConnectionsListSchema = () => {
    const McpServerInstallationsListQueryParams = orvalSchemas.McpServerInstallationsListQueryParams()
    return McpServerInstallationsListQueryParams
}

const mcpConnectionsList = (): ToolBase<
    ReturnType<typeof McpConnectionsListSchema>,
    WithPostHogUrl<Schemas.PaginatedMCPServerInstallationList>
> => ({
    name: 'mcp-connections-list',
    schema: McpConnectionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpConnectionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPServerInstallationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_server_installations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/settings/mcp-servers')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-connection-tools-list': mcpConnectionToolsList,
    'mcp-connections-list': mcpConnectionsList,
}
