// AUTO-GENERATED from products/deployments/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    DeploymentProjectsDeploymentsDeployCreateBody,
    DeploymentProjectsDeploymentsDeployCreateParams,
    DeploymentProjectsDeploymentsEventsListParams,
    DeploymentProjectsDeploymentsEventsListQueryParams,
    DeploymentProjectsDeploymentsListParams,
    DeploymentProjectsDeploymentsListQueryParams,
    DeploymentProjectsDeploymentsRetrieveParams,
    DeploymentProjectsListQueryParams,
    DeploymentProjectsRetrieveParams,
} from '@/generated/deployments/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DeploymentProjectsGetSchema = DeploymentProjectsRetrieveParams.omit({ project_id: true })

const deploymentProjectsGet = (): ToolBase<
    typeof DeploymentProjectsGetSchema,
    WithPostHogUrl<Schemas.DeploymentProject>
> => ({
    name: 'deployment-projects-get',
    schema: DeploymentProjectsGetSchema,
    handler: async (context: Context, params: z.infer<typeof DeploymentProjectsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DeploymentProject>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/deployment_projects/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/deployments/${result.id}`)
    },
})

const DeploymentProjectsListSchema = DeploymentProjectsListQueryParams

const deploymentProjectsList = (): ToolBase<
    typeof DeploymentProjectsListSchema,
    WithPostHogUrl<Schemas.PaginatedDeploymentProjectList>
> => ({
    name: 'deployment-projects-list',
    schema: DeploymentProjectsListSchema,
    handler: async (context: Context, params: z.infer<typeof DeploymentProjectsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDeploymentProjectList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/deployment_projects/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/deployments')
    },
})

const DeploymentsDeploySchema = DeploymentProjectsDeploymentsDeployCreateParams.omit({ project_id: true }).extend(
    DeploymentProjectsDeploymentsDeployCreateBody.shape
)

const deploymentsDeploy = (): ToolBase<typeof DeploymentsDeploySchema, Schemas.DeploymentDeployResponse> => ({
    name: 'deployments-deploy',
    schema: DeploymentsDeploySchema,
    handler: async (context: Context, params: z.infer<typeof DeploymentsDeploySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.branch !== undefined) {
            body['branch'] = params.branch
        }
        const result = await context.api.request<Schemas.DeploymentDeployResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/deployment_projects/${encodeURIComponent(String(params.deployment_project_id))}/deployments/deploy/`,
            body,
        })
        return result
    },
})

const DeploymentsEventsSchema = DeploymentProjectsDeploymentsEventsListParams.omit({ project_id: true }).extend(
    DeploymentProjectsDeploymentsEventsListQueryParams.shape
)

const deploymentsEvents = (): ToolBase<
    typeof DeploymentsEventsSchema,
    WithPostHogUrl<Schemas.PaginatedDeploymentEventList>
> => ({
    name: 'deployments-events',
    schema: DeploymentsEventsSchema,
    handler: async (context: Context, params: z.infer<typeof DeploymentsEventsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDeploymentEventList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/deployment_projects/${encodeURIComponent(String(params.deployment_project_id))}/deployments/${encodeURIComponent(String(params.id))}/events/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/deployments')
    },
})

const DeploymentsGetSchema = DeploymentProjectsDeploymentsRetrieveParams.omit({ project_id: true })

const deploymentsGet = (): ToolBase<typeof DeploymentsGetSchema, WithPostHogUrl<Schemas.Deployment>> =>
    withUiApp('deployment', {
        name: 'deployments-get',
        schema: DeploymentsGetSchema,
        handler: async (context: Context, params: z.infer<typeof DeploymentsGetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Deployment>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/deployment_projects/${encodeURIComponent(String(params.deployment_project_id))}/deployments/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/deployments/${result.id}`)
        },
    })

const DeploymentsListSchema = DeploymentProjectsDeploymentsListParams.omit({ project_id: true }).extend(
    DeploymentProjectsDeploymentsListQueryParams.shape
)

const deploymentsList = (): ToolBase<typeof DeploymentsListSchema, WithPostHogUrl<Schemas.PaginatedDeploymentList>> =>
    withUiApp('deployment-list', {
        name: 'deployments-list',
        schema: DeploymentsListSchema,
        handler: async (context: Context, params: z.infer<typeof DeploymentsListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedDeploymentList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/deployment_projects/${encodeURIComponent(String(params.deployment_project_id))}/deployments/`,
                query: {
                    author: params.author,
                    limit: params.limit,
                    offset: params.offset,
                    ordering: params.ordering,
                    search: params.search,
                    status: params.status,
                },
            })
            return await withPostHogUrl(context, result, '/deployments')
        },
    })

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'deployment-projects-get': deploymentProjectsGet,
    'deployment-projects-list': deploymentProjectsList,
    'deployments-deploy': deploymentsDeploy,
    'deployments-events': deploymentsEvents,
    'deployments-get': deploymentsGet,
    'deployments-list': deploymentsList,
}
