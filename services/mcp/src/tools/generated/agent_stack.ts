// AUTO-GENERATED from services/mcp/definitions/agent_stack.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AgentApplicationsDisableRevisionCreateBody,
    AgentApplicationsDisableRevisionCreateParams,
    AgentApplicationsEnvPartialUpdateBody,
    AgentApplicationsEnvPartialUpdateParams,
    AgentApplicationsListQueryParams,
    AgentApplicationsPreviewCreateBody,
    AgentApplicationsPreviewCreateParams,
    AgentApplicationsPromoteCreateBody,
    AgentApplicationsPromoteCreateParams,
    AgentApplicationsRetrieveParams,
    AgentApplicationsRevisionsListParams,
    AgentApplicationsRevisionsListQueryParams,
    AgentApplicationsRevisionsRetrieveParams,
    AgentApplicationsSessionsCancelParams,
    AgentApplicationsSessionsListParams,
    AgentApplicationsSessionsLogsParams,
    AgentApplicationsSessionsRetrieveParams,
} from '@/generated/agent_stack/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AgentApplicationsDisableRevisionCreateSchema = AgentApplicationsDisableRevisionCreateParams.omit({
    project_id: true,
}).extend(AgentApplicationsDisableRevisionCreateBody.shape)

const agentApplicationsDisableRevisionCreate = (): ToolBase<
    typeof AgentApplicationsDisableRevisionCreateSchema,
    Schemas.AgentApplicationRevision
> => ({
    name: 'agent-applications-disable-revision-create',
    schema: AgentApplicationsDisableRevisionCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsDisableRevisionCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.revision_id !== undefined) {
            body['revision_id'] = params.revision_id
        }
        const result = await context.api.request<Schemas.AgentApplicationRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/disable_revision/`,
            body,
        })
        return result
    },
})

const AgentApplicationsEnvPartialUpdateSchema = AgentApplicationsEnvPartialUpdateParams.omit({
    project_id: true,
}).extend(AgentApplicationsEnvPartialUpdateBody.shape)

const agentApplicationsEnvPartialUpdate = (): ToolBase<
    typeof AgentApplicationsEnvPartialUpdateSchema,
    Schemas.AgentApplication
> => ({
    name: 'agent-applications-env-partial-update',
    schema: AgentApplicationsEnvPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsEnvPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.slug !== undefined) {
            body['slug'] = params.slug
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/env/`,
            body,
        })
        return result
    },
})

const AgentApplicationsListSchema = AgentApplicationsListQueryParams

const agentApplicationsList = (): ToolBase<
    typeof AgentApplicationsListSchema,
    WithPostHogUrl<Schemas.PaginatedAgentApplicationList>
> => ({
    name: 'agent-applications-list',
    schema: AgentApplicationsListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAgentApplicationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/agent_applications')
    },
})

const AgentApplicationsPreviewCreateSchema = AgentApplicationsPreviewCreateParams.omit({ project_id: true }).extend(
    AgentApplicationsPreviewCreateBody.shape
)

const agentApplicationsPreviewCreate = (): ToolBase<
    typeof AgentApplicationsPreviewCreateSchema,
    Schemas.AgentApplicationRevision
> => ({
    name: 'agent-applications-preview-create',
    schema: AgentApplicationsPreviewCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsPreviewCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.revision_id !== undefined) {
            body['revision_id'] = params.revision_id
        }
        const result = await context.api.request<Schemas.AgentApplicationRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/preview/`,
            body,
        })
        return result
    },
})

const AgentApplicationsPromoteCreateSchema = AgentApplicationsPromoteCreateParams.omit({ project_id: true }).extend(
    AgentApplicationsPromoteCreateBody.shape
)

const agentApplicationsPromoteCreate = (): ToolBase<
    typeof AgentApplicationsPromoteCreateSchema,
    Schemas.AgentApplicationRevision
> => ({
    name: 'agent-applications-promote-create',
    schema: AgentApplicationsPromoteCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsPromoteCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.revision_id !== undefined) {
            body['revision_id'] = params.revision_id
        }
        const result = await context.api.request<Schemas.AgentApplicationRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/promote/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRetrieveSchema = AgentApplicationsRetrieveParams.omit({ project_id: true })

const agentApplicationsRetrieve = (): ToolBase<typeof AgentApplicationsRetrieveSchema, Schemas.AgentApplication> => ({
    name: 'agent-applications-retrieve',
    schema: AgentApplicationsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsListSchema = AgentApplicationsRevisionsListParams.omit({ project_id: true }).extend(
    AgentApplicationsRevisionsListQueryParams.shape
)

const agentApplicationsRevisionsList = (): ToolBase<
    typeof AgentApplicationsRevisionsListSchema,
    WithPostHogUrl<Schemas.PaginatedAgentApplicationRevisionList>
> => ({
    name: 'agent-applications-revisions-list',
    schema: AgentApplicationsRevisionsListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAgentApplicationRevisionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/`,
            query: {
                deployment_status: params.deployment_status,
                limit: params.limit,
                offset: params.offset,
                state: params.state,
            },
        })
        return await withPostHogUrl(context, result, '/agent_applications')
    },
})

const AgentApplicationsRevisionsRetrieveSchema = AgentApplicationsRevisionsRetrieveParams.omit({ project_id: true })

const agentApplicationsRevisionsRetrieve = (): ToolBase<
    typeof AgentApplicationsRevisionsRetrieveSchema,
    Schemas.AgentApplicationRevision
> => ({
    name: 'agent-applications-revisions-retrieve',
    schema: AgentApplicationsRevisionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplicationRevision>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AgentApplicationsSessionsCancelSchema = AgentApplicationsSessionsCancelParams.omit({ project_id: true })

const agentApplicationsSessionsCancel = (): ToolBase<typeof AgentApplicationsSessionsCancelSchema, unknown> => ({
    name: 'agent-applications-sessions-cancel',
    schema: AgentApplicationsSessionsCancelSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSessionsCancelSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/sessions/${encodeURIComponent(String(params.id))}/cancel/`,
        })
        return result
    },
})

const AgentApplicationsSessionsListSchema = AgentApplicationsSessionsListParams.omit({ project_id: true })

const agentApplicationsSessionsList = (): ToolBase<typeof AgentApplicationsSessionsListSchema, unknown> => ({
    name: 'agent-applications-sessions-list',
    schema: AgentApplicationsSessionsListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSessionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/sessions/`,
        })
        return await withPostHogUrl(context, result, '/agent_applications')
    },
})

const AgentApplicationsSessionsLogsSchema = AgentApplicationsSessionsLogsParams.omit({ project_id: true })

const agentApplicationsSessionsLogs = (): ToolBase<typeof AgentApplicationsSessionsLogsSchema, unknown> => ({
    name: 'agent-applications-sessions-logs',
    schema: AgentApplicationsSessionsLogsSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSessionsLogsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/sessions/${encodeURIComponent(String(params.id))}/logs/`,
        })
        return result
    },
})

const AgentApplicationsSessionsRetrieveSchema = AgentApplicationsSessionsRetrieveParams.omit({ project_id: true })

const agentApplicationsSessionsRetrieve = (): ToolBase<typeof AgentApplicationsSessionsRetrieveSchema, unknown> => ({
    name: 'agent-applications-sessions-retrieve',
    schema: AgentApplicationsSessionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSessionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/sessions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'agent-applications-disable-revision-create': agentApplicationsDisableRevisionCreate,
    'agent-applications-env-partial-update': agentApplicationsEnvPartialUpdate,
    'agent-applications-list': agentApplicationsList,
    'agent-applications-preview-create': agentApplicationsPreviewCreate,
    'agent-applications-promote-create': agentApplicationsPromoteCreate,
    'agent-applications-retrieve': agentApplicationsRetrieve,
    'agent-applications-revisions-list': agentApplicationsRevisionsList,
    'agent-applications-revisions-retrieve': agentApplicationsRevisionsRetrieve,
    'agent-applications-sessions-cancel': agentApplicationsSessionsCancel,
    'agent-applications-sessions-list': agentApplicationsSessionsList,
    'agent-applications-sessions-logs': agentApplicationsSessionsLogs,
    'agent-applications-sessions-retrieve': agentApplicationsSessionsRetrieve,
}
