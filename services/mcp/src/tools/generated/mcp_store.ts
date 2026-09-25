// AUTO-GENERATED from products/mcp_store/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/mcp_store/api'
import { withPostHogUrl, withPageOffsets, type WithPostHogUrl, type WithPageOffsets } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpConnectionToolsListSchema = () => {
    const McpServerInstallationsToolsRetrieveParams = orvalSchemas.McpServerInstallationsToolsRetrieveParams()
    return McpServerInstallationsToolsRetrieveParams.omit({ project_id: true })
}

const mcpConnectionToolsList = (): ToolBase<
    ReturnType<typeof McpConnectionToolsListSchema>,
    WithPostHogUrl<WithPageOffsets<Schemas.PaginatedMCPServerInstallationToolList>>
> => ({
    name: 'mcp-connection-tools-list',
    schema: McpConnectionToolsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpConnectionToolsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMCPServerInstallationToolList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_server_installations/${encodeURIComponent(String(params.id))}/tools/`,
        })
        const paged = withPageOffsets(result)
        return await withPostHogUrl(context, paged, '/settings/mcp-servers')
    },
})

const McpConnectionsListSchema = () => {
    const McpServerInstallationsListQueryParams = orvalSchemas.McpServerInstallationsListQueryParams()
    return McpServerInstallationsListQueryParams
}

const mcpConnectionsList = (): ToolBase<
    ReturnType<typeof McpConnectionsListSchema>,
    WithPostHogUrl<WithPageOffsets<Schemas.PaginatedMCPServerInstallationList>>
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
        const paged = withPageOffsets(result)
        return await withPostHogUrl(context, paged, '/settings/mcp-servers')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-connection-tools-list': mcpConnectionToolsList,
    'mcp-connections-list': mcpConnectionsList,
}
