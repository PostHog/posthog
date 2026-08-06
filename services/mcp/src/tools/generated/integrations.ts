// AUTO-GENERATED from products/integrations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    IntegrationsChannelsRetrieveParams,
    IntegrationsChannelsRetrieveQueryParams,
    IntegrationsDestroyParams,
    IntegrationsGithubReposRetrieveParams,
    IntegrationsGithubReposRetrieveQueryParams,
    IntegrationsJiraProjectsRetrieveParams,
    IntegrationsLinearTeamsRetrieveParams,
    IntegrationsListQueryParams,
    IntegrationsRetrieveParams,
    PosthogConnectionsForwardCreateBody,
    PosthogConnectionsForwardCreateParams,
} from '@/generated/integrations/api'
import { getConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import {
    executeConfirmedAction,
    prepareConfirmedAction,
    type PrepareConfirmedActionResult,
} from '@/tools/confirmed-action-runtime'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
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

const IntegrationsChannelsRetrieveSchema = IntegrationsChannelsRetrieveParams.omit({ project_id: true }).extend(
    IntegrationsChannelsRetrieveQueryParams.shape
)

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
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const IntegrationsGithubReposRetrieveSchema = IntegrationsGithubReposRetrieveParams.omit({ project_id: true }).extend(
    IntegrationsGithubReposRetrieveQueryParams.shape
)

const integrationsGithubReposRetrieve = (): ToolBase<
    typeof IntegrationsGithubReposRetrieveSchema,
    Schemas.GitHubReposResponse
> => ({
    name: 'integrations-github-repos-retrieve',
    schema: IntegrationsGithubReposRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationsGithubReposRetrieveSchema>) => {
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

const IntegrationsJiraProjectsRetrieveSchema = IntegrationsJiraProjectsRetrieveParams.omit({ project_id: true })

const integrationsJiraProjectsRetrieve = (): ToolBase<
    typeof IntegrationsJiraProjectsRetrieveSchema,
    Schemas.JiraProjectsResponse
> => ({
    name: 'integrations-jira-projects-retrieve',
    schema: IntegrationsJiraProjectsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationsJiraProjectsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.JiraProjectsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/jira_projects/`,
        })
        return result
    },
})

const IntegrationsLinearTeamsRetrieveSchema = IntegrationsLinearTeamsRetrieveParams.omit({ project_id: true })

const integrationsLinearTeamsRetrieve = (): ToolBase<
    typeof IntegrationsLinearTeamsRetrieveSchema,
    Schemas.LinearTeamsResponse
> => ({
    name: 'integrations-linear-teams-retrieve',
    schema: IntegrationsLinearTeamsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof IntegrationsLinearTeamsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LinearTeamsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/integrations/${encodeURIComponent(String(params.id))}/linear_teams/`,
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

const PosthogConnectionForwardSchema = PosthogConnectionsForwardCreateParams.omit({ project_id: true }).extend(
    PosthogConnectionsForwardCreateBody.shape
)

const PosthogConnectionForwardSchemaExecute = z.strictObject({
    confirmation_hash: z
        .string()
        .describe('The confirmation_hash returned by the matching -prepare tool. Pass it back verbatim.'),
    confirmation: z.string().describe('The literal string "confirm", typed by the user in chat. Required to proceed.'),
})

const posthogConnectionForwardPrepare = (): ToolBase<
    typeof PosthogConnectionForwardSchema,
    PrepareConfirmedActionResult
> => ({
    name: 'posthog-connection-forward-prepare',
    schema: PosthogConnectionForwardSchema,
    handler: async (context: Context, params: z.infer<typeof PosthogConnectionForwardSchema>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        return await prepareConfirmedAction(context, {
            args: params,
            purpose: 'posthog-connection-forward',
            actionLabel: 'forward request through PostHog connection',
            messageTemplate:
                "About to forward a {method} request to `{path}` in another PostHog project through this connection. It runs against the connected project with the creator's granted scopes, and a write there changes that project's data the same as a direct write would. Reply 'confirm' to send it.\n",
            codec: __runtime.codec,
            stash: __runtime.stash,
            boundScope: { projectId: String(__scopeProjectId) },
        })
    },
})

const posthogConnectionForwardExecute = (): ToolBase<
    typeof PosthogConnectionForwardSchemaExecute,
    Schemas.PostHogConnectionForwardResponse
> => ({
    name: 'posthog-connection-forward-execute',
    schema: PosthogConnectionForwardSchemaExecute,
    handler: async (context: Context, confirmationParams: z.infer<typeof PosthogConnectionForwardSchemaExecute>) => {
        const __runtime = getConfirmedActionRuntime()
        const __scopeProjectId = await context.stateManager.getProjectId()
        const __guard = await executeConfirmedAction<z.infer<typeof PosthogConnectionForwardSchema>>(context, {
            incomingArgs: confirmationParams,
            purpose: 'posthog-connection-forward',
            codec: __runtime.codec,
            ledger: __runtime.ledger,
            stash: __runtime.stash,
            expectedScope: { projectId: String(__scopeProjectId) },
        })
        if (!__guard.ok) {
            return __guard.result as never
        }
        const params = __guard.verifiedArgs
        const projectId = __scopeProjectId
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
    'posthog-connection-forward-prepare': posthogConnectionForwardPrepare,
    'posthog-connection-forward-execute': posthogConnectionForwardExecute,
}
