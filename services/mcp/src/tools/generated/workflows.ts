// AUTO-GENERATED from products/workflows/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { HogFlowsListQueryParams, HogFlowsRetrieveParams } from '@/generated/workflows/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsListSchema = HogFlowsListQueryParams

const workflowsList = (): ToolBase<
    typeof WorkflowsListSchema,
    Schemas.PaginatedHogFlowMinimalList & { _posthogUrl: string }
> => ({
    name: 'workflows-list',
    schema: WorkflowsListSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedHogFlowMinimalList>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_flows/`,
            query: {
                created_at: params.created_at,
                created_by: params.created_by,
                id: params.id,
                limit: params.limit,
                offset: params.offset,
                updated_at: params.updated_at,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/workflows`,
        }
    },
})

const WorkflowsGetSchema = HogFlowsRetrieveParams.omit({ project_id: true })

const workflowsGet = (): ToolBase<typeof WorkflowsGetSchema, Schemas.HogFlow> => ({
    name: 'workflows-get',
    schema: WorkflowsGetSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogFlow>({
            method: 'GET',
            path: `/api/projects/${projectId}/hog_flows/${params.id}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-list': workflowsList,
    'workflows-get': workflowsGet,
}
