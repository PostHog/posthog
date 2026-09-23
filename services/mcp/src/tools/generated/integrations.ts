// AUTO-GENERATED from products/integrations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/integrations/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const IntegrationDeleteSchema = () => {
    const IntegrationsDestroyParams = orvalSchemas.IntegrationsDestroyParams()
    return IntegrationsDestroyParams.omit({ project_id: true })
}

const integrationDelete = (): ToolBase<ReturnType<typeof IntegrationDeleteSchema>, unknown> => ({
    name: 'integration-delete',
    schema: IntegrationDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const IntegrationGetSchema = () => {
    const IntegrationsRetrieveParams = orvalSchemas.IntegrationsRetrieveParams()
    return IntegrationsRetrieveParams.omit({ project_id: true })
}

const integrationGet = (): ToolBase<ReturnType<typeof IntegrationGetSchema>, Schemas.IntegrationConfig> => ({
    name: 'integration-get',
    schema: IntegrationGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.IntegrationConfig>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'kind',
            'display_name',
            'errors',
            'created_at',
            'created_by',
        ]) as typeof result
        return filtered
    },
})

const IntegrationsChannelsRetrieveSchema = () => {
    const IntegrationsChannelsRetrieveParams = orvalSchemas.IntegrationsChannelsRetrieveParams()
    const IntegrationsChannelsRetrieveQueryParams = orvalSchemas.IntegrationsChannelsRetrieveQueryParams()
    return IntegrationsChannelsRetrieveParams.omit({ project_id: true }).extend(
        IntegrationsChannelsRetrieveQueryParams.shape
    )
}

const integrationsChannelsRetrieve = (): ToolBase<
    ReturnType<typeof IntegrationsChannelsRetrieveSchema>,
    Schemas.SlackChannelsResponse
> => ({
    name: 'integrations-channels-retrieve',
    schema: IntegrationsChannelsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationsChannelsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SlackChannelsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/channels/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const IntegrationsGithubReposRetrieveSchema = () => {
    const IntegrationsGithubReposRetrieveParams = orvalSchemas.IntegrationsGithubReposRetrieveParams()
    const IntegrationsGithubReposRetrieveQueryParams = orvalSchemas.IntegrationsGithubReposRetrieveQueryParams()
    return IntegrationsGithubReposRetrieveParams.omit({ project_id: true }).extend(
        IntegrationsGithubReposRetrieveQueryParams.shape
    )
}

const integrationsGithubReposRetrieve = (): ToolBase<
    ReturnType<typeof IntegrationsGithubReposRetrieveSchema>,
    Schemas.GitHubReposResponse
> => ({
    name: 'integrations-github-repos-retrieve',
    schema: IntegrationsGithubReposRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationsGithubReposRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GitHubReposResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/github_repos/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const IntegrationsJiraProjectsRetrieveSchema = () => {
    const IntegrationsJiraProjectsRetrieveParams = orvalSchemas.IntegrationsJiraProjectsRetrieveParams()
    return IntegrationsJiraProjectsRetrieveParams.omit({ project_id: true })
}

const integrationsJiraProjectsRetrieve = (): ToolBase<
    ReturnType<typeof IntegrationsJiraProjectsRetrieveSchema>,
    Schemas.JiraProjectsResponse
> => ({
    name: 'integrations-jira-projects-retrieve',
    schema: IntegrationsJiraProjectsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationsJiraProjectsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.JiraProjectsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/jira_projects/`,
        })
        return result
    },
})

const IntegrationsLinearTeamsRetrieveSchema = () => {
    const IntegrationsLinearTeamsRetrieveParams = orvalSchemas.IntegrationsLinearTeamsRetrieveParams()
    return IntegrationsLinearTeamsRetrieveParams.omit({ project_id: true })
}

const integrationsLinearTeamsRetrieve = (): ToolBase<
    ReturnType<typeof IntegrationsLinearTeamsRetrieveSchema>,
    Schemas.LinearTeamsResponse
> => ({
    name: 'integrations-linear-teams-retrieve',
    schema: IntegrationsLinearTeamsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationsLinearTeamsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LinearTeamsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/linear_teams/`,
        })
        return result
    },
})

const IntegrationsListSchema = () => {
    const IntegrationsListQueryParams = orvalSchemas.IntegrationsListQueryParams()
    return IntegrationsListQueryParams
}

const integrationsList = (): ToolBase<
    ReturnType<typeof IntegrationsListSchema>,
    WithPostHogUrl<Schemas.PaginatedIntegrationConfigList>
> => ({
    name: 'integrations-list',
    schema: IntegrationsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedIntegrationConfigList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/`,
            query: {
                kind: params.kind,
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, ['id', 'kind', 'display_name', 'errors', 'created_at', 'created_by'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/settings/environment-integrations')
    },
})

const IntegrationsUsersRetrieveSchema = () => {
    const IntegrationsUsersRetrieveParams = orvalSchemas.IntegrationsUsersRetrieveParams()
    const IntegrationsUsersRetrieveQueryParams = orvalSchemas.IntegrationsUsersRetrieveQueryParams()
    return IntegrationsUsersRetrieveParams.omit({ project_id: true }).extend(IntegrationsUsersRetrieveQueryParams.shape)
}

const integrationsUsersRetrieve = (): ToolBase<
    ReturnType<typeof IntegrationsUsersRetrieveSchema>,
    Schemas.SlackUsersResponse
> => ({
    name: 'integrations-users-retrieve',
    schema: IntegrationsUsersRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof IntegrationsUsersRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SlackUsersResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/users/`,
            query: {
                force_refresh: params.force_refresh,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                user_id: params.user_id,
            },
        })
        return result
    },
})

const PosthogConnectionForwardSchema = () => {
    const PosthogConnectionsForwardCreateBody = orvalSchemas.PosthogConnectionsForwardCreateBody()
    const PosthogConnectionsForwardCreateParams = orvalSchemas.PosthogConnectionsForwardCreateParams()
    return PosthogConnectionsForwardCreateParams.omit({ project_id: true }).extend(
        PosthogConnectionsForwardCreateBody.shape
    )
}

const posthogConnectionForward = (): ToolBase<
    ReturnType<typeof PosthogConnectionForwardSchema>,
    Schemas.PostHogConnectionForwardResponse
> => ({
    name: 'posthog-connection-forward',
    schema: PosthogConnectionForwardSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogConnectionForwardSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.method !== undefined) {
            body['method'] = params.method
        }
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.data !== undefined) {
            body['data'] = params.data
        }
        const result = await context.api.request<Schemas.PostHogConnectionForwardResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_connections/${encodeURIComponent(String(params.id))}/forward/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'integration-delete': integrationDelete,
    'integration-get': integrationGet,
    'integrations-channels-retrieve': integrationsChannelsRetrieve,
    'integrations-github-repos-retrieve': integrationsGithubReposRetrieve,
    'integrations-jira-projects-retrieve': integrationsJiraProjectsRetrieve,
    'integrations-linear-teams-retrieve': integrationsLinearTeamsRetrieve,
    'integrations-list': integrationsList,
    'integrations-users-retrieve': integrationsUsersRetrieve,
    'posthog-connection-forward': posthogConnectionForward,
}
