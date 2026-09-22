// AUTO-GENERATED from products/mcp_registry/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/mcp_registry/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpRegistryDiscoverSchema = () => {
    const McpRegistryServersDiscoverRetrieveQueryParams = orvalSchemas.McpRegistryServersDiscoverRetrieveQueryParams()
    return McpRegistryServersDiscoverRetrieveQueryParams
}

const mcpRegistryDiscover = (): ToolBase<
    ReturnType<typeof McpRegistryDiscoverSchema>,
    Schemas.MCPDiscoverResponse
> => ({
    name: 'mcp-registry-discover',
    schema: McpRegistryDiscoverSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpRegistryDiscoverSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MCPDiscoverResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_registry/servers/discover/`,
            query: {
                intent: params.intent,
                limit: params.limit,
                version: params.version,
            },
        })
        return result
    },
})

const McpRegistryServerGetSchema = () => {
    const McpRegistryServersRetrieveParams = orvalSchemas.McpRegistryServersRetrieveParams()
    return McpRegistryServersRetrieveParams.omit({ project_id: true })
}

const mcpRegistryServerGet = (): ToolBase<
    ReturnType<typeof McpRegistryServerGetSchema>,
    Schemas.MCPRegistryServerDetail
> => ({
    name: 'mcp-registry-server-get',
    schema: McpRegistryServerGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof McpRegistryServerGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MCPRegistryServerDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_registry/servers/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-registry-discover': mcpRegistryDiscover,
    'mcp-registry-server-get': mcpRegistryServerGet,
}
