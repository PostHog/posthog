// AUTO-GENERATED from products/integrations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    IntegrationsDestroyParams,
    IntegrationsList2QueryParams,
    IntegrationsRetrieve2Params,
} from '@/generated/integrations/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const IntegrationsListSchema = IntegrationsList2QueryParams

const integrationsList = (): ToolBase<
    typeof IntegrationsListSchema,
    WithPostHogUrl<Schemas.PaginatedIntegrationList>
> => ({
    name: 'integrations-list',
    schema: IntegrationsListSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedIntegrationList>({
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

const IntegrationGetSchema = IntegrationsRetrieve2Params.omit({ project_id: true })

const integrationGet = (): ToolBase<typeof IntegrationGetSchema, Schemas.Integration> => ({
    name: 'integration-get',
    schema: IntegrationGetSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Integration>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'integrations-list': integrationsList,
    'integration-get': integrationGet,
    'integration-delete': integrationDelete,
}
