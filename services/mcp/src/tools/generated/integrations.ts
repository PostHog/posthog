// AUTO-GENERATED from products/integrations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    IntegrationsChannelsRetrieveParams,
    IntegrationsDestroyParams,
    IntegrationsListQueryParams,
    IntegrationsRetrieveParams,
} from '@/generated/integrations/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const IntegrationDeleteSchema = IntegrationsDestroyParams.omit({ project_id: true })

const integrationDelete = (): ToolBase<typeof IntegrationDeleteSchema, unknown> => ({
    name: 'integration-delete',
    schema: IntegrationDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const IntegrationGetSchema = IntegrationsRetrieveParams.omit({ project_id: true })

const integrationGet = (): ToolBase<typeof IntegrationGetSchema, Schemas.IntegrationConfig> => ({
    name: 'integration-get',
    schema: IntegrationGetSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.IntegrationConfig>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const IntegrationsChannelsRetrieveSchema = IntegrationsChannelsRetrieveParams.omit({ project_id: true })

const integrationsChannelsRetrieve = (): ToolBase<
    typeof IntegrationsChannelsRetrieveSchema,
    Schemas.SlackChannelsResponse
> => ({
    name: 'integrations-channels-retrieve',
    schema: IntegrationsChannelsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationsChannelsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SlackChannelsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/channels/`,
        })
        return result
    },
})

const IntegrationsListSchema = IntegrationsListQueryParams

const integrationsList = (): ToolBase<
    typeof IntegrationsListSchema,
    WithPostHogUrl<Schemas.PaginatedIntegrationConfigList>
> => ({
    name: 'integrations-list',
    schema: IntegrationsListSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedIntegrationConfigList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/settings/integrations')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'integration-delete': integrationDelete,
    'integration-get': integrationGet,
    'integrations-channels-retrieve': integrationsChannelsRetrieve,
    'integrations-list': integrationsList,
}
