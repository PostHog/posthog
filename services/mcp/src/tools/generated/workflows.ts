// AUTO-GENERATED from products/workflows/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HogFlowsListQueryParams,
    HogFlowsLogsRetrieveParams,
    HogFlowsLogsRetrieveQueryParams,
    HogFlowsMetricsRetrieveParams,
    HogFlowsMetricsRetrieveQueryParams,
    HogFlowsRetrieveParams,
} from '@/generated/workflows/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WorkflowsListSchema = HogFlowsListQueryParams

const workflowsList = (): ToolBase<typeof WorkflowsListSchema, WithPostHogUrl<Schemas.PaginatedHogFlowMinimalList>> =>
    withUiApp('workflow-list', {
        name: 'workflows-list',
        schema: WorkflowsListSchema,
        handler: async (context: Context, params: z.infer<typeof WorkflowsListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedHogFlowMinimalList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/`,
                query: {
                    created_at: params.created_at,
                    created_by: params.created_by,
                    id: params.id,
                    limit: params.limit,
                    offset: params.offset,
                    updated_at: params.updated_at,
                },
            })
            return await withPostHogUrl(context, result, '/pipeline/destinations')
        },
    })

const WorkflowsGetSchema = HogFlowsRetrieveParams.omit({ project_id: true })

const workflowsGet = (): ToolBase<typeof WorkflowsGetSchema, WithPostHogUrl<Schemas.HogFlow>> =>
    withUiApp('workflow', {
        name: 'workflows-get',
        schema: WorkflowsGetSchema,
        handler: async (context: Context, params: z.infer<typeof WorkflowsGetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.HogFlow>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/pipeline/destinations/hog-${result.id}`)
        },
    })

const HogFlowsLogsRetrieveSchema = HogFlowsLogsRetrieveParams.omit({ project_id: true }).extend(
    HogFlowsLogsRetrieveQueryParams.shape
)

const hogFlowsLogsRetrieve = (): ToolBase<typeof HogFlowsLogsRetrieveSchema, unknown> => ({
    name: 'hog-flows-logs-retrieve',
    schema: HogFlowsLogsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof HogFlowsLogsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/logs/`,
            query: {
                after: params.after,
                before: params.before,
                instance_id: params.instance_id,
                level: params.level,
                limit: params.limit,
                search: params.search,
            },
        })
        return result
    },
})

const HogFlowsMetricsRetrieveSchema = HogFlowsMetricsRetrieveParams.omit({ project_id: true }).extend(
    HogFlowsMetricsRetrieveQueryParams.shape
)

const hogFlowsMetricsRetrieve = (): ToolBase<typeof HogFlowsMetricsRetrieveSchema, Schemas.AppMetricsResponse> => ({
    name: 'hog-flows-metrics-retrieve',
    schema: HogFlowsMetricsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof HogFlowsMetricsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AppMetricsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.id))}/metrics/`,
            query: {
                after: params.after,
                before: params.before,
                breakdown_by: params.breakdown_by,
                instance_id: params.instance_id,
                interval: params.interval,
                kind: params.kind,
                name: params.name,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'workflows-list': workflowsList,
    'workflows-get': workflowsGet,
    'hog-flows-logs-retrieve': hogFlowsLogsRetrieve,
    'hog-flows-metrics-retrieve': hogFlowsMetricsRetrieve,
}
