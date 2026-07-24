// AUTO-GENERATED from services/mcp/definitions/agent_platform.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AgentApplicationsCreateBody,
    AgentApplicationsDestroyParams,
    AgentApplicationsInvokeBody,
    AgentApplicationsInvokeParams,
    AgentApplicationsListQueryParams,
    AgentApplicationsListenParams,
    AgentApplicationsListenQueryParams,
    AgentApplicationsPartialUpdateBody,
    AgentApplicationsPartialUpdateParams,
    AgentApplicationsPreviewProxyBody,
    AgentApplicationsPreviewProxyParams,
    AgentApplicationsPreviewProxyQueryParams,
    AgentApplicationsRetrieveParams,
    AgentApplicationsRevisionsAgentMdUpdateBody,
    AgentApplicationsRevisionsAgentMdUpdateParams,
    AgentApplicationsRevisionsArchiveCreateParams,
    AgentApplicationsRevisionsBundleRetrieveParams,
    AgentApplicationsRevisionsBundleUpdateBody,
    AgentApplicationsRevisionsBundleUpdateParams,
    AgentApplicationsRevisionsCloneFromCreateBody,
    AgentApplicationsRevisionsCloneFromCreateParams,
    AgentApplicationsRevisionsCreateBody,
    AgentApplicationsRevisionsCreateParams,
    AgentApplicationsRevisionsCronFireCreateBody,
    AgentApplicationsRevisionsCronFireCreateParams,
    AgentApplicationsRevisionsFreezeCreateParams,
    AgentApplicationsRevisionsListParams,
    AgentApplicationsRevisionsListQueryParams,
    AgentApplicationsRevisionsManifestRetrieveParams,
    AgentApplicationsRevisionsNewDraftCreateBody,
    AgentApplicationsRevisionsNewDraftCreateParams,
    AgentApplicationsRevisionsPartialUpdateBody,
    AgentApplicationsRevisionsPartialUpdateParams,
    AgentApplicationsRevisionsPromoteCreateParams,
    AgentApplicationsRevisionsRetrieveParams,
    AgentApplicationsRevisionsSkillRefsUpdateBody,
    AgentApplicationsRevisionsSkillRefsUpdateParams,
    AgentApplicationsRevisionsSlackManifestParams,
    AgentApplicationsRevisionsSpecUpdateBody,
    AgentApplicationsRevisionsSpecUpdateParams,
    AgentApplicationsRevisionsSystemPromptParams,
    AgentApplicationsRevisionsToolsDestroyParams,
    AgentApplicationsRevisionsToolsDryRunCreateBody,
    AgentApplicationsRevisionsToolsDryRunCreateParams,
    AgentApplicationsRevisionsToolsUpdateBody,
    AgentApplicationsRevisionsToolsUpdateParams,
    AgentApplicationsRevisionsValidateCreateParams,
    AgentApplicationsSendBody,
    AgentApplicationsSendParams,
    AgentApplicationsSessionLogsParams,
    AgentApplicationsSessionLogsQueryParams,
    AgentApplicationsSessionsListParams,
    AgentApplicationsSessionsListQueryParams,
    AgentApplicationsSessionsRetrieveParams,
    AgentApplicationsSessionsRetrieveQueryParams,
    AgentApplicationsSpecSchemaQueryParams,
    AgentRevisionsEnvKeysClearParams,
    AgentRevisionsEnvKeysGetParams,
    AgentRevisionsEnvKeysListParams,
} from '@/generated/agent_platform/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AgentApplicationsCreateSchema = AgentApplicationsCreateBody

const agentApplicationsCreate = (): ToolBase<typeof AgentApplicationsCreateSchema, Schemas.AgentApplication> => ({
    name: 'agent-applications-create',
    schema: AgentApplicationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsCreateSchema>) => {
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
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/`,
            body,
        })
        return result
    },
})

const AgentApplicationsDestroySchema = AgentApplicationsDestroyParams.omit({ project_id: true })

const agentApplicationsDestroy = (): ToolBase<typeof AgentApplicationsDestroySchema, unknown> => ({
    name: 'agent-applications-destroy',
    schema: AgentApplicationsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AgentApplicationsEnvKeysClearSchema = AgentRevisionsEnvKeysClearParams.omit({ project_id: true })

const agentApplicationsEnvKeysClear = (): ToolBase<typeof AgentApplicationsEnvKeysClearSchema, unknown> => ({
    name: 'agent-applications-env-keys-clear',
    schema: AgentApplicationsEnvKeysClearSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsEnvKeysClearSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/env_keys/${encodeURIComponent(String(params.key))}/`,
        })
        return result
    },
})

const AgentApplicationsEnvKeysGetSchema = AgentRevisionsEnvKeysGetParams.omit({ project_id: true })

const agentApplicationsEnvKeysGet = (): ToolBase<
    typeof AgentApplicationsEnvKeysGetSchema,
    Schemas.AgentRevisionEnvKeyStatus
> => ({
    name: 'agent-applications-env-keys-get',
    schema: AgentApplicationsEnvKeysGetSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsEnvKeysGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevisionEnvKeyStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/env_keys/${encodeURIComponent(String(params.key))}/`,
        })
        return result
    },
})

const AgentApplicationsEnvKeysListSchema = AgentRevisionsEnvKeysListParams.omit({ project_id: true })

const agentApplicationsEnvKeysList = (): ToolBase<
    typeof AgentApplicationsEnvKeysListSchema,
    Schemas.AgentRevisionEnvKeysResponse
> => ({
    name: 'agent-applications-env-keys-list',
    schema: AgentApplicationsEnvKeysListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsEnvKeysListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevisionEnvKeysResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/env_keys/`,
        })
        return result
    },
})

const AgentApplicationsInvokeSchema = AgentApplicationsInvokeParams.omit({ project_id: true }).extend(
    AgentApplicationsInvokeBody.shape
)

const agentApplicationsInvoke = (): ToolBase<typeof AgentApplicationsInvokeSchema, Schemas.AgentInvokeResponse> => ({
    name: 'agent-applications-invoke',
    schema: AgentApplicationsInvokeSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsInvokeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.message !== undefined) {
            body['message'] = params.message
        }
        if (params.external_key !== undefined) {
            body['external_key'] = params.external_key
        }
        const result = await context.api.request<Schemas.AgentInvokeResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/invoke/`,
            body,
        })
        return result
    },
})

const AgentApplicationsListSchema = AgentApplicationsListQueryParams

const agentApplicationsList = (): ToolBase<
    typeof AgentApplicationsListSchema,
    Schemas.PaginatedAgentApplicationList
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
        return result
    },
})

const AgentApplicationsListenSchema = AgentApplicationsListenParams.omit({ project_id: true }).extend(
    AgentApplicationsListenQueryParams.shape
)

const agentApplicationsListen = (): ToolBase<typeof AgentApplicationsListenSchema, Schemas.AgentListenResponse> => ({
    name: 'agent-applications-listen',
    schema: AgentApplicationsListenSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsListenSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentListenResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/listen/`,
            query: {
                cursor: params.cursor,
                max_chars: params.max_chars,
                session_id: params.session_id,
            },
        })
        return result
    },
})

const AgentApplicationsModelsSchema = z.object({})

const agentApplicationsModels = (): ToolBase<typeof AgentApplicationsModelsSchema, Schemas.AgentApplication> => ({
    name: 'agent-applications-models',
    schema: AgentApplicationsModelsSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsModelsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/models/`,
        })
        return result
    },
})

const AgentApplicationsPartialUpdateSchema = AgentApplicationsPartialUpdateParams.omit({ project_id: true }).extend(
    AgentApplicationsPartialUpdateBody.shape
)

const agentApplicationsPartialUpdate = (): ToolBase<
    typeof AgentApplicationsPartialUpdateSchema,
    Schemas.AgentApplication
> => ({
    name: 'agent-applications-partial-update',
    schema: AgentApplicationsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsPartialUpdateSchema>) => {
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
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const AgentApplicationsPreviewProxySchema = AgentApplicationsPreviewProxyParams.omit({ project_id: true })
    .extend(AgentApplicationsPreviewProxyQueryParams.omit({ format: true }).shape)
    .extend(AgentApplicationsPreviewProxyBody.shape)

const agentApplicationsPreviewProxy = (): ToolBase<typeof AgentApplicationsPreviewProxySchema, unknown> => ({
    name: 'agent-applications-preview-proxy',
    schema: AgentApplicationsPreviewProxySchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsPreviewProxySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.message !== undefined) {
            body['message'] = params.message
        }
        if (params.session_id !== undefined) {
            body['session_id'] = params.session_id
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/preview-proxy/${encodeURIComponent(String(params.rest))}/`,
            body,
            query: {
                revision_id: params.revision_id,
            },
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

const AgentApplicationsRevisionsAgentMdUpdateSchema = AgentApplicationsRevisionsAgentMdUpdateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsAgentMdUpdateBody.shape)

const agentApplicationsRevisionsAgentMdUpdate = (): ToolBase<
    typeof AgentApplicationsRevisionsAgentMdUpdateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-agent-md-update',
    schema: AgentApplicationsRevisionsAgentMdUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsAgentMdUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/agent_md/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsArchiveCreateSchema = AgentApplicationsRevisionsArchiveCreateParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsArchiveCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsArchiveCreateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-archive-create',
    schema: AgentApplicationsRevisionsArchiveCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsArchiveCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/archive/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsBundleRetrieveSchema = AgentApplicationsRevisionsBundleRetrieveParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsBundleRetrieve = (): ToolBase<
    typeof AgentApplicationsRevisionsBundleRetrieveSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-bundle-retrieve',
    schema: AgentApplicationsRevisionsBundleRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsBundleRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/bundle/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsBundleUpdateSchema = AgentApplicationsRevisionsBundleUpdateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsBundleUpdateBody.shape)

const agentApplicationsRevisionsBundleUpdate = (): ToolBase<
    typeof AgentApplicationsRevisionsBundleUpdateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-bundle-update',
    schema: AgentApplicationsRevisionsBundleUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsBundleUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.agent_md !== undefined) {
            body['agent_md'] = params.agent_md
        }
        if (params.tools !== undefined) {
            body['tools'] = params.tools
        }
        if (params.spec !== undefined) {
            body['spec'] = params.spec
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/bundle/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsCloneFromCreateSchema = AgentApplicationsRevisionsCloneFromCreateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsCloneFromCreateBody.shape)

const agentApplicationsRevisionsCloneFromCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsCloneFromCreateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-clone-from-create',
    schema: AgentApplicationsRevisionsCloneFromCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsCloneFromCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source_revision_id !== undefined) {
            body['source_revision_id'] = params.source_revision_id
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/clone_from/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsCreateSchema = AgentApplicationsRevisionsCreateParams.omit({ project_id: true }).extend(
    AgentApplicationsRevisionsCreateBody.shape
)

const agentApplicationsRevisionsCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsCreateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-create',
    schema: AgentApplicationsRevisionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.parent_revision !== undefined) {
            body['parent_revision'] = params.parent_revision
        }
        if (params.bundle_uri !== undefined) {
            body['bundle_uri'] = params.bundle_uri
        }
        if (params.spec !== undefined) {
            body['spec'] = params.spec
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsCronFireCreateSchema = AgentApplicationsRevisionsCronFireCreateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsCronFireCreateBody.shape)

const agentApplicationsRevisionsCronFireCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsCronFireCreateSchema,
    Schemas.AgentRevisionCronFireResponse
> => ({
    name: 'agent-applications-revisions-cron-fire-create',
    schema: AgentApplicationsRevisionsCronFireCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsCronFireCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.cron_name !== undefined) {
            body['cron_name'] = params.cron_name
        }
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        const result = await context.api.request<Schemas.AgentRevisionCronFireResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/cron/fire/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsFreezeCreateSchema = AgentApplicationsRevisionsFreezeCreateParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsFreezeCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsFreezeCreateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-freeze-create',
    schema: AgentApplicationsRevisionsFreezeCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsFreezeCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/freeze/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsListSchema = AgentApplicationsRevisionsListParams.omit({ project_id: true }).extend(
    AgentApplicationsRevisionsListQueryParams.shape
)

const agentApplicationsRevisionsList = (): ToolBase<
    typeof AgentApplicationsRevisionsListSchema,
    Schemas.PaginatedAgentRevisionList
> => ({
    name: 'agent-applications-revisions-list',
    schema: AgentApplicationsRevisionsListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAgentRevisionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const AgentApplicationsRevisionsManifestRetrieveSchema = AgentApplicationsRevisionsManifestRetrieveParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsManifestRetrieve = (): ToolBase<
    typeof AgentApplicationsRevisionsManifestRetrieveSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-manifest-retrieve',
    schema: AgentApplicationsRevisionsManifestRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsManifestRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/manifest/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsNewDraftCreateSchema = AgentApplicationsRevisionsNewDraftCreateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsNewDraftCreateBody.shape)

const agentApplicationsRevisionsNewDraftCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsNewDraftCreateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-new-draft-create',
    schema: AgentApplicationsRevisionsNewDraftCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsNewDraftCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.application_id !== undefined) {
            body['application_id'] = params.application_id
        }
        if (params.source_revision_id !== undefined) {
            body['source_revision_id'] = params.source_revision_id
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/new_draft/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsPartialUpdateSchema = AgentApplicationsRevisionsPartialUpdateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsPartialUpdateBody.shape)

const agentApplicationsRevisionsPartialUpdate = (): ToolBase<
    typeof AgentApplicationsRevisionsPartialUpdateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-partial-update',
    schema: AgentApplicationsRevisionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.parent_revision !== undefined) {
            body['parent_revision'] = params.parent_revision
        }
        if (params.bundle_uri !== undefined) {
            body['bundle_uri'] = params.bundle_uri
        }
        if (params.spec !== undefined) {
            body['spec'] = params.spec
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsPromoteCreateSchema = AgentApplicationsRevisionsPromoteCreateParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsPromoteCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsPromoteCreateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-promote-create',
    schema: AgentApplicationsRevisionsPromoteCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsPromoteCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/promote/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsRetrieveSchema = AgentApplicationsRevisionsRetrieveParams.omit({ project_id: true })

const agentApplicationsRevisionsRetrieve = (): ToolBase<
    typeof AgentApplicationsRevisionsRetrieveSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-retrieve',
    schema: AgentApplicationsRevisionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsSkillRefsUpdateSchema = AgentApplicationsRevisionsSkillRefsUpdateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsSkillRefsUpdateBody.shape)

const agentApplicationsRevisionsSkillRefsUpdate = (): ToolBase<
    typeof AgentApplicationsRevisionsSkillRefsUpdateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-skill-refs-update',
    schema: AgentApplicationsRevisionsSkillRefsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsSkillRefsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.skill_refs !== undefined) {
            body['skill_refs'] = params.skill_refs
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/skill_refs/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsSlackManifestSchema = AgentApplicationsRevisionsSlackManifestParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsSlackManifest = (): ToolBase<
    typeof AgentApplicationsRevisionsSlackManifestSchema,
    Schemas.AgentRevisionSlackManifestResponse
> => ({
    name: 'agent-applications-revisions-slack-manifest',
    schema: AgentApplicationsRevisionsSlackManifestSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsSlackManifestSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevisionSlackManifestResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/slack_manifest/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsSpecUpdateSchema = AgentApplicationsRevisionsSpecUpdateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsSpecUpdateBody.shape)

const agentApplicationsRevisionsSpecUpdate = (): ToolBase<
    typeof AgentApplicationsRevisionsSpecUpdateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-spec-update',
    schema: AgentApplicationsRevisionsSpecUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsSpecUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.spec !== undefined) {
            body['spec'] = params.spec
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/spec/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsSystemPromptSchema = AgentApplicationsRevisionsSystemPromptParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsSystemPrompt = (): ToolBase<
    typeof AgentApplicationsRevisionsSystemPromptSchema,
    Schemas.AgentRevisionSystemPromptResponse
> => ({
    name: 'agent-applications-revisions-system-prompt',
    schema: AgentApplicationsRevisionsSystemPromptSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsSystemPromptSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevisionSystemPromptResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/system_prompt/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsToolsDestroySchema = AgentApplicationsRevisionsToolsDestroyParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsToolsDestroy = (): ToolBase<
    typeof AgentApplicationsRevisionsToolsDestroySchema,
    unknown
> => ({
    name: 'agent-applications-revisions-tools-destroy',
    schema: AgentApplicationsRevisionsToolsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsToolsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/tools/${encodeURIComponent(String(params.tool_id))}/`,
        })
        return result
    },
})

const AgentApplicationsRevisionsToolsDryRunCreateSchema = AgentApplicationsRevisionsToolsDryRunCreateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsToolsDryRunCreateBody.shape)

const agentApplicationsRevisionsToolsDryRunCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsToolsDryRunCreateSchema,
    Schemas.AgentRevisionDryRunToolResponse
> => ({
    name: 'agent-applications-revisions-tools-dry-run-create',
    schema: AgentApplicationsRevisionsToolsDryRunCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsToolsDryRunCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.args !== undefined) {
            body['args'] = params.args
        }
        if (params.mock_secrets !== undefined) {
            body['mock_secrets'] = params.mock_secrets
        }
        const result = await context.api.request<Schemas.AgentRevisionDryRunToolResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/tools/${encodeURIComponent(String(params.tool_id))}/dry_run/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsToolsUpdateSchema = AgentApplicationsRevisionsToolsUpdateParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsToolsUpdateBody.shape)

const agentApplicationsRevisionsToolsUpdate = (): ToolBase<
    typeof AgentApplicationsRevisionsToolsUpdateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-tools-update',
    schema: AgentApplicationsRevisionsToolsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsToolsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.args_schema !== undefined) {
            body['args_schema'] = params.args_schema
        }
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/tools/${encodeURIComponent(String(params.tool_id))}/`,
            body,
        })
        return result
    },
})

const AgentApplicationsRevisionsValidateCreateSchema = AgentApplicationsRevisionsValidateCreateParams.omit({
    project_id: true,
})

const agentApplicationsRevisionsValidateCreate = (): ToolBase<
    typeof AgentApplicationsRevisionsValidateCreateSchema,
    Schemas.AgentRevisionValidateResponse
> => ({
    name: 'agent-applications-revisions-validate-create',
    schema: AgentApplicationsRevisionsValidateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsValidateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevisionValidateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/validate/`,
        })
        return result
    },
})

const AgentApplicationsSendSchema = AgentApplicationsSendParams.omit({ project_id: true }).extend(
    AgentApplicationsSendBody.shape
)

const agentApplicationsSend = (): ToolBase<typeof AgentApplicationsSendSchema, Schemas.AgentSendResponse> => ({
    name: 'agent-applications-send',
    schema: AgentApplicationsSendSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSendSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.session_id !== undefined) {
            body['session_id'] = params.session_id
        }
        if (params.message !== undefined) {
            body['message'] = params.message
        }
        const result = await context.api.request<Schemas.AgentSendResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/send/`,
            body,
        })
        return result
    },
})

const AgentApplicationsSessionLogsSchema = AgentApplicationsSessionLogsParams.omit({ project_id: true }).extend(
    AgentApplicationsSessionLogsQueryParams.shape
)

const agentApplicationsSessionLogs = (): ToolBase<
    typeof AgentApplicationsSessionLogsSchema,
    Schemas.AgentApplicationSessionLogsResponse
> => ({
    name: 'agent-applications-session-logs',
    schema: AgentApplicationsSessionLogsSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSessionLogsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplicationSessionLogsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/sessions/${encodeURIComponent(String(params.session_id))}/logs/`,
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

const AgentApplicationsSessionsListSchema = AgentApplicationsSessionsListParams.omit({ project_id: true }).extend(
    AgentApplicationsSessionsListQueryParams.shape
)

const agentApplicationsSessionsList = (): ToolBase<
    typeof AgentApplicationsSessionsListSchema,
    Schemas.AgentApplicationSessionsListResponse
> => ({
    name: 'agent-applications-sessions-list',
    schema: AgentApplicationsSessionsListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSessionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplicationSessionsListResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/sessions/`,
            query: {
                created_after: params.created_after,
                created_before: params.created_before,
                limit: params.limit,
                offset: params.offset,
                revision_id: params.revision_id,
                state: params.state,
            },
        })
        return result
    },
})

const AgentApplicationsSessionsRetrieveSchema = AgentApplicationsSessionsRetrieveParams.omit({
    project_id: true,
}).extend(AgentApplicationsSessionsRetrieveQueryParams.shape)

const agentApplicationsSessionsRetrieve = (): ToolBase<
    typeof AgentApplicationsSessionsRetrieveSchema,
    Schemas.AgentApplicationSessionsRetrieveResponse
> => ({
    name: 'agent-applications-sessions-retrieve',
    schema: AgentApplicationsSessionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSessionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplicationSessionsRetrieveResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/sessions/${encodeURIComponent(String(params.session_id))}/`,
            query: {
                last_n: params.last_n,
            },
        })
        return result
    },
})

const AgentApplicationsSpecSchemaSchema = AgentApplicationsSpecSchemaQueryParams

const agentApplicationsSpecSchema = (): ToolBase<
    typeof AgentApplicationsSpecSchemaSchema,
    Schemas.AgentApplication
> => ({
    name: 'agent-applications-spec-schema',
    schema: AgentApplicationsSpecSchemaSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSpecSchemaSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/spec_schema/`,
            query: {
                section: params.section,
            },
        })
        return result
    },
})

const AgentNativeToolsListSchema = z.object({})

const agentNativeToolsList = (): ToolBase<
    typeof AgentNativeToolsListSchema,
    Schemas.AgentNativeToolsListResponse[]
> => ({
    name: 'agent-native-tools-list',
    schema: AgentNativeToolsListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof AgentNativeToolsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentNativeToolsListResponse[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_native_tools/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'agent-applications-create': agentApplicationsCreate,
    'agent-applications-destroy': agentApplicationsDestroy,
    'agent-applications-env-keys-clear': agentApplicationsEnvKeysClear,
    'agent-applications-env-keys-get': agentApplicationsEnvKeysGet,
    'agent-applications-env-keys-list': agentApplicationsEnvKeysList,
    'agent-applications-invoke': agentApplicationsInvoke,
    'agent-applications-list': agentApplicationsList,
    'agent-applications-listen': agentApplicationsListen,
    'agent-applications-models': agentApplicationsModels,
    'agent-applications-partial-update': agentApplicationsPartialUpdate,
    'agent-applications-preview-proxy': agentApplicationsPreviewProxy,
    'agent-applications-retrieve': agentApplicationsRetrieve,
    'agent-applications-revisions-agent-md-update': agentApplicationsRevisionsAgentMdUpdate,
    'agent-applications-revisions-archive-create': agentApplicationsRevisionsArchiveCreate,
    'agent-applications-revisions-bundle-retrieve': agentApplicationsRevisionsBundleRetrieve,
    'agent-applications-revisions-bundle-update': agentApplicationsRevisionsBundleUpdate,
    'agent-applications-revisions-clone-from-create': agentApplicationsRevisionsCloneFromCreate,
    'agent-applications-revisions-create': agentApplicationsRevisionsCreate,
    'agent-applications-revisions-cron-fire-create': agentApplicationsRevisionsCronFireCreate,
    'agent-applications-revisions-freeze-create': agentApplicationsRevisionsFreezeCreate,
    'agent-applications-revisions-list': agentApplicationsRevisionsList,
    'agent-applications-revisions-manifest-retrieve': agentApplicationsRevisionsManifestRetrieve,
    'agent-applications-revisions-new-draft-create': agentApplicationsRevisionsNewDraftCreate,
    'agent-applications-revisions-partial-update': agentApplicationsRevisionsPartialUpdate,
    'agent-applications-revisions-promote-create': agentApplicationsRevisionsPromoteCreate,
    'agent-applications-revisions-retrieve': agentApplicationsRevisionsRetrieve,
    'agent-applications-revisions-skill-refs-update': agentApplicationsRevisionsSkillRefsUpdate,
    'agent-applications-revisions-slack-manifest': agentApplicationsRevisionsSlackManifest,
    'agent-applications-revisions-spec-update': agentApplicationsRevisionsSpecUpdate,
    'agent-applications-revisions-system-prompt': agentApplicationsRevisionsSystemPrompt,
    'agent-applications-revisions-tools-destroy': agentApplicationsRevisionsToolsDestroy,
    'agent-applications-revisions-tools-dry-run-create': agentApplicationsRevisionsToolsDryRunCreate,
    'agent-applications-revisions-tools-update': agentApplicationsRevisionsToolsUpdate,
    'agent-applications-revisions-validate-create': agentApplicationsRevisionsValidateCreate,
    'agent-applications-send': agentApplicationsSend,
    'agent-applications-session-logs': agentApplicationsSessionLogs,
    'agent-applications-sessions-list': agentApplicationsSessionsList,
    'agent-applications-sessions-retrieve': agentApplicationsSessionsRetrieve,
    'agent-applications-spec-schema': agentApplicationsSpecSchema,
    'agent-native-tools-list': agentNativeToolsList,
}
