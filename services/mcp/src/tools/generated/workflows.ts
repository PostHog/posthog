// AUTO-GENERATED from products/workflows/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import { HogFlowsListQueryParams, HogFlowsRetrieveParams } from '@/generated/workflows/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsListSchema = HogFlowsListQueryParams

const workflowsList = (): ToolBase<typeof WorkflowsListSchema> => ({
    name: 'workflows-list',
    schema: WorkflowsListSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
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
        return result
    },
})

const WorkflowsGetSchema = HogFlowsRetrieveParams.omit({ project_id: true })

const workflowsGet = (): ToolBase<typeof WorkflowsGetSchema> => ({
    name: 'workflows-get',
    schema: WorkflowsGetSchema,
    handler: async (context: Context, params: z.infer<typeof WorkflowsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
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
