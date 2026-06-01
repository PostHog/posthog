// AUTO-GENERATED from services/mcp/definitions/agent_stack.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AgentApplicationsCreateBody,
    AgentApplicationsDestroyParams,
    AgentApplicationsEnvKeysClearParams,
    AgentApplicationsEnvKeysGetParams,
    AgentApplicationsEnvKeysListParams,
    AgentApplicationsListQueryParams,
    AgentApplicationsPartialUpdateBody,
    AgentApplicationsPartialUpdateParams,
    AgentApplicationsPreviewProxyParams,
    AgentApplicationsPreviewProxyQueryParams,
    AgentApplicationsRetrieveParams,
    AgentApplicationsRevisionsArchiveCreateParams,
    AgentApplicationsRevisionsBundleRetrieveParams,
    AgentApplicationsRevisionsBundleUpdateBody,
    AgentApplicationsRevisionsBundleUpdateParams,
    AgentApplicationsRevisionsCloneFromCreateBody,
    AgentApplicationsRevisionsCloneFromCreateParams,
    AgentApplicationsRevisionsCreateBody,
    AgentApplicationsRevisionsCreateParams,
    AgentApplicationsRevisionsFileDestroyParams,
    AgentApplicationsRevisionsFileDestroyQueryParams,
    AgentApplicationsRevisionsFileRetrieveParams,
    AgentApplicationsRevisionsFileRetrieveQueryParams,
    AgentApplicationsRevisionsFileUpdateBody,
    AgentApplicationsRevisionsFileUpdateParams,
    AgentApplicationsRevisionsFileUpdateQueryParams,
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
    AgentApplicationsRevisionsSystemPromptParams,
    AgentApplicationsRevisionsValidateCreateParams,
    AgentApplicationsSessionsListParams,
    AgentApplicationsSessionsListQueryParams,
    AgentApplicationsSessionsRetrieveParams,
    AgentApplicationsSessionsRetrieveQueryParams,
    AgentApplicationsSetEnvCreateBody,
    AgentApplicationsSetEnvCreateParams,
    AgentCustomToolTemplatesCreateBody,
    AgentCustomToolTemplatesListQueryParams,
    AgentCustomToolTemplatesNameArchiveCreateBody,
    AgentCustomToolTemplatesNameArchiveCreateParams,
    AgentCustomToolTemplatesNameDuplicateCreateBody,
    AgentCustomToolTemplatesNameDuplicateCreateParams,
    AgentCustomToolTemplatesNamePublishCreateBody,
    AgentCustomToolTemplatesNamePublishCreateParams,
    AgentCustomToolTemplatesNameRetrieveParams,
    AgentCustomToolTemplatesNameRetrieveQueryParams,
    AgentCustomToolTemplatesNameUsagesListParams,
    AgentCustomToolTemplatesNameUsagesListQueryParams,
    AgentCustomToolTemplatesNameVersionsListParams,
    AgentSkillTemplatesCreateBody,
    AgentSkillTemplatesListQueryParams,
    AgentSkillTemplatesNameArchiveCreateBody,
    AgentSkillTemplatesNameArchiveCreateParams,
    AgentSkillTemplatesNameDuplicateCreateBody,
    AgentSkillTemplatesNameDuplicateCreateParams,
    AgentSkillTemplatesNameFilesCreateBody,
    AgentSkillTemplatesNameFilesCreateParams,
    AgentSkillTemplatesNameFilesDestroyParams,
    AgentSkillTemplatesNameFilesRenameCreateBody,
    AgentSkillTemplatesNameFilesRenameCreateParams,
    AgentSkillTemplatesNamePublishCreateBody,
    AgentSkillTemplatesNamePublishCreateParams,
    AgentSkillTemplatesNameRetrieveParams,
    AgentSkillTemplatesNameRetrieveQueryParams,
    AgentSkillTemplatesNameUsagesListParams,
    AgentSkillTemplatesNameUsagesListQueryParams,
    AgentSkillTemplatesNameVersionsListParams,
} from '@/generated/agent_stack/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
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

const AgentApplicationsEnvKeysClearSchema = AgentApplicationsEnvKeysClearParams.omit({ project_id: true })

const agentApplicationsEnvKeysClear = (): ToolBase<typeof AgentApplicationsEnvKeysClearSchema, unknown> => ({
    name: 'agent-applications-env-keys-clear',
    schema: AgentApplicationsEnvKeysClearSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsEnvKeysClearSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/env_keys/${encodeURIComponent(String(params.key))}/`,
        })
        return result
    },
})

const AgentApplicationsEnvKeysGetSchema = AgentApplicationsEnvKeysGetParams.omit({ project_id: true })

const agentApplicationsEnvKeysGet = (): ToolBase<
    typeof AgentApplicationsEnvKeysGetSchema,
    Schemas.AgentApplicationEnvKeyStatus
> => ({
    name: 'agent-applications-env-keys-get',
    schema: AgentApplicationsEnvKeysGetSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsEnvKeysGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplicationEnvKeyStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/env_keys/${encodeURIComponent(String(params.key))}/`,
        })
        return result
    },
})

const AgentApplicationsEnvKeysListSchema = AgentApplicationsEnvKeysListParams.omit({ project_id: true })

const agentApplicationsEnvKeysList = (): ToolBase<
    typeof AgentApplicationsEnvKeysListSchema,
    Schemas.AgentApplicationEnvKeysResponse
> => ({
    name: 'agent-applications-env-keys-list',
    schema: AgentApplicationsEnvKeysListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsEnvKeysListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplicationEnvKeysResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/env_keys/`,
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

const AgentApplicationsPreviewProxySchema = AgentApplicationsPreviewProxyParams.omit({ project_id: true }).extend(
    AgentApplicationsPreviewProxyQueryParams.omit({ format: true }).shape
)

const agentApplicationsPreviewProxy = (): ToolBase<
    typeof AgentApplicationsPreviewProxySchema,
    Schemas.AgentApplication
> => ({
    name: 'agent-applications-preview-proxy',
    schema: AgentApplicationsPreviewProxySchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsPreviewProxySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/preview-proxy/${encodeURIComponent(String(params.rest))}/`,
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
        if (params.files !== undefined) {
            body['files'] = params.files
        }
        if (params.mode !== undefined) {
            body['mode'] = params.mode
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

const AgentApplicationsRevisionsFileDestroySchema = AgentApplicationsRevisionsFileDestroyParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsFileDestroyQueryParams.shape)

const agentApplicationsRevisionsFileDestroy = (): ToolBase<
    typeof AgentApplicationsRevisionsFileDestroySchema,
    unknown
> => ({
    name: 'agent-applications-revisions-file-destroy',
    schema: AgentApplicationsRevisionsFileDestroySchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsFileDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/file/`,
            query: {
                path: params.path,
            },
        })
        return result
    },
})

const AgentApplicationsRevisionsFileRetrieveSchema = AgentApplicationsRevisionsFileRetrieveParams.omit({
    project_id: true,
}).extend(AgentApplicationsRevisionsFileRetrieveQueryParams.shape)

const agentApplicationsRevisionsFileRetrieve = (): ToolBase<
    typeof AgentApplicationsRevisionsFileRetrieveSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-file-retrieve',
    schema: AgentApplicationsRevisionsFileRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsFileRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/file/`,
            query: {
                path: params.path,
            },
        })
        return result
    },
})

const AgentApplicationsRevisionsFileUpdateSchema = AgentApplicationsRevisionsFileUpdateParams.omit({ project_id: true })
    .extend(AgentApplicationsRevisionsFileUpdateQueryParams.shape)
    .extend(AgentApplicationsRevisionsFileUpdateBody.shape)

const agentApplicationsRevisionsFileUpdate = (): ToolBase<
    typeof AgentApplicationsRevisionsFileUpdateSchema,
    Schemas.AgentRevision
> => ({
    name: 'agent-applications-revisions-file-update',
    schema: AgentApplicationsRevisionsFileUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsRevisionsFileUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        const result = await context.api.request<Schemas.AgentRevision>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.application_id))}/revisions/${encodeURIComponent(String(params.id))}/file/`,
            body,
            query: {
                path: params.path,
            },
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

const AgentApplicationsSetEnvCreateSchema = AgentApplicationsSetEnvCreateParams.omit({ project_id: true }).extend(
    AgentApplicationsSetEnvCreateBody.shape
)

const agentApplicationsSetEnvCreate = (): ToolBase<
    typeof AgentApplicationsSetEnvCreateSchema,
    Schemas.AgentApplication
> => ({
    name: 'agent-applications-set-env-create',
    schema: AgentApplicationsSetEnvCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentApplicationsSetEnvCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.env !== undefined) {
            body['env'] = params.env
        }
        const result = await context.api.request<Schemas.AgentApplication>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_applications/${encodeURIComponent(String(params.id))}/set_env/`,
            body,
        })
        return result
    },
})

const AgentCustomToolTemplatesCreateSchema = AgentCustomToolTemplatesCreateBody

const agentCustomToolTemplatesCreate = (): ToolBase<
    typeof AgentCustomToolTemplatesCreateSchema,
    Schemas.CustomToolTemplateDetail
> => ({
    name: 'agent-custom-tool-templates-create',
    schema: AgentCustomToolTemplatesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        if (params.compiled_js !== undefined) {
            body['compiled_js'] = params.compiled_js
        }
        if (params.args_schema !== undefined) {
            body['args_schema'] = params.args_schema
        }
        if (params.returns_schema !== undefined) {
            body['returns_schema'] = params.returns_schema
        }
        if (params.requires_secrets !== undefined) {
            body['requires_secrets'] = params.requires_secrets
        }
        const result = await context.api.request<Schemas.CustomToolTemplateDetail>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/`,
            body,
        })
        return result
    },
})

const AgentCustomToolTemplatesListSchema = AgentCustomToolTemplatesListQueryParams

const agentCustomToolTemplatesList = (): ToolBase<
    typeof AgentCustomToolTemplatesListSchema,
    WithPostHogUrl<Schemas.CustomToolTemplateSummary[]>
> => ({
    name: 'agent-custom-tool-templates-list',
    schema: AgentCustomToolTemplatesListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CustomToolTemplateSummary[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/`,
            query: {
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/agent_applications')
    },
})

const AgentCustomToolTemplatesNameArchiveCreateSchema = AgentCustomToolTemplatesNameArchiveCreateParams.omit({
    project_id: true,
}).extend(AgentCustomToolTemplatesNameArchiveCreateBody.shape)

const agentCustomToolTemplatesNameArchiveCreate = (): ToolBase<
    typeof AgentCustomToolTemplatesNameArchiveCreateSchema,
    unknown
> => ({
    name: 'agent-custom-tool-templates-name-archive-create',
    schema: AgentCustomToolTemplatesNameArchiveCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesNameArchiveCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        if (params.compiled_js !== undefined) {
            body['compiled_js'] = params.compiled_js
        }
        if (params.args_schema !== undefined) {
            body['args_schema'] = params.args_schema
        }
        if (params.returns_schema !== undefined) {
            body['returns_schema'] = params.returns_schema
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/name/${encodeURIComponent(String(params.name))}/archive/`,
            body,
        })
        return result
    },
})

const AgentCustomToolTemplatesNameDuplicateCreateSchema = AgentCustomToolTemplatesNameDuplicateCreateParams.omit({
    project_id: true,
}).extend(AgentCustomToolTemplatesNameDuplicateCreateBody.shape)

const agentCustomToolTemplatesNameDuplicateCreate = (): ToolBase<
    typeof AgentCustomToolTemplatesNameDuplicateCreateSchema,
    Schemas.CustomToolTemplateDetail
> => ({
    name: 'agent-custom-tool-templates-name-duplicate-create',
    schema: AgentCustomToolTemplatesNameDuplicateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesNameDuplicateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.CustomToolTemplateDetail>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/name/${encodeURIComponent(String(params.name))}/duplicate/`,
            body,
        })
        return result
    },
})

const AgentCustomToolTemplatesNamePublishCreateSchema = AgentCustomToolTemplatesNamePublishCreateParams.omit({
    project_id: true,
}).extend(AgentCustomToolTemplatesNamePublishCreateBody.shape)

const agentCustomToolTemplatesNamePublishCreate = (): ToolBase<
    typeof AgentCustomToolTemplatesNamePublishCreateSchema,
    Schemas.CustomToolTemplateDetail
> => ({
    name: 'agent-custom-tool-templates-name-publish-create',
    schema: AgentCustomToolTemplatesNamePublishCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesNamePublishCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.source !== undefined) {
            body['source'] = params.source
        }
        if (params.edits !== undefined) {
            body['edits'] = params.edits
        }
        if (params.compiled_js !== undefined) {
            body['compiled_js'] = params.compiled_js
        }
        if (params.args_schema !== undefined) {
            body['args_schema'] = params.args_schema
        }
        if (params.returns_schema !== undefined) {
            body['returns_schema'] = params.returns_schema
        }
        if (params.requires_secrets !== undefined) {
            body['requires_secrets'] = params.requires_secrets
        }
        const result = await context.api.request<Schemas.CustomToolTemplateDetail>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/name/${encodeURIComponent(String(params.name))}/publish/`,
            body,
        })
        return result
    },
})

const AgentCustomToolTemplatesNameRetrieveSchema = AgentCustomToolTemplatesNameRetrieveParams.omit({
    project_id: true,
}).extend(AgentCustomToolTemplatesNameRetrieveQueryParams.shape)

const agentCustomToolTemplatesNameRetrieve = (): ToolBase<
    typeof AgentCustomToolTemplatesNameRetrieveSchema,
    Schemas.CustomToolTemplateDetail
> => ({
    name: 'agent-custom-tool-templates-name-retrieve',
    schema: AgentCustomToolTemplatesNameRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesNameRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CustomToolTemplateDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/name/${encodeURIComponent(String(params.name))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const AgentCustomToolTemplatesNameUsagesListSchema = AgentCustomToolTemplatesNameUsagesListParams.omit({
    project_id: true,
}).extend(AgentCustomToolTemplatesNameUsagesListQueryParams.shape)

const agentCustomToolTemplatesNameUsagesList = (): ToolBase<
    typeof AgentCustomToolTemplatesNameUsagesListSchema,
    Schemas.CustomToolTemplateUsage[]
> => ({
    name: 'agent-custom-tool-templates-name-usages-list',
    schema: AgentCustomToolTemplatesNameUsagesListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesNameUsagesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CustomToolTemplateUsage[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/name/${encodeURIComponent(String(params.name))}/usages/`,
            query: {
                pinned_version: params.pinned_version,
            },
        })
        return result
    },
})

const AgentCustomToolTemplatesNameVersionsListSchema = AgentCustomToolTemplatesNameVersionsListParams.omit({
    project_id: true,
})

const agentCustomToolTemplatesNameVersionsList = (): ToolBase<
    typeof AgentCustomToolTemplatesNameVersionsListSchema,
    Schemas.TemplateVersionEntry[]
> => ({
    name: 'agent-custom-tool-templates-name-versions-list',
    schema: AgentCustomToolTemplatesNameVersionsListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentCustomToolTemplatesNameVersionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TemplateVersionEntry[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_custom_tool_templates/name/${encodeURIComponent(String(params.name))}/versions/`,
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

const AgentSkillTemplatesCreateSchema = AgentSkillTemplatesCreateBody

const agentSkillTemplatesCreate = (): ToolBase<
    typeof AgentSkillTemplatesCreateSchema,
    Schemas.SkillTemplateDetail
> => ({
    name: 'agent-skill-templates-create',
    schema: AgentSkillTemplatesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.license !== undefined) {
            body['license'] = params.license
        }
        if (params.compatibility !== undefined) {
            body['compatibility'] = params.compatibility
        }
        if (params.files !== undefined) {
            body['files'] = params.files
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.allowed_tools !== undefined) {
            body['allowed_tools'] = params.allowed_tools
        }
        const result = await context.api.request<Schemas.SkillTemplateDetail>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/`,
            body,
        })
        return result
    },
})

const AgentSkillTemplatesListSchema = AgentSkillTemplatesListQueryParams

const agentSkillTemplatesList = (): ToolBase<
    typeof AgentSkillTemplatesListSchema,
    WithPostHogUrl<Schemas.SkillTemplateSummary[]>
> => ({
    name: 'agent-skill-templates-list',
    schema: AgentSkillTemplatesListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SkillTemplateSummary[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/`,
            query: {
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/agent_applications')
    },
})

const AgentSkillTemplatesNameArchiveCreateSchema = AgentSkillTemplatesNameArchiveCreateParams.omit({
    project_id: true,
}).extend(AgentSkillTemplatesNameArchiveCreateBody.shape)

const agentSkillTemplatesNameArchiveCreate = (): ToolBase<
    typeof AgentSkillTemplatesNameArchiveCreateSchema,
    unknown
> => ({
    name: 'agent-skill-templates-name-archive-create',
    schema: AgentSkillTemplatesNameArchiveCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameArchiveCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.license !== undefined) {
            body['license'] = params.license
        }
        if (params.compatibility !== undefined) {
            body['compatibility'] = params.compatibility
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/archive/`,
            body,
        })
        return result
    },
})

const AgentSkillTemplatesNameDuplicateCreateSchema = AgentSkillTemplatesNameDuplicateCreateParams.omit({
    project_id: true,
}).extend(AgentSkillTemplatesNameDuplicateCreateBody.shape)

const agentSkillTemplatesNameDuplicateCreate = (): ToolBase<
    typeof AgentSkillTemplatesNameDuplicateCreateSchema,
    Schemas.SkillTemplateDetail
> => ({
    name: 'agent-skill-templates-name-duplicate-create',
    schema: AgentSkillTemplatesNameDuplicateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameDuplicateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.SkillTemplateDetail>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/duplicate/`,
            body,
        })
        return result
    },
})

const AgentSkillTemplatesNameFilesCreateSchema = AgentSkillTemplatesNameFilesCreateParams.omit({
    project_id: true,
}).extend(AgentSkillTemplatesNameFilesCreateBody.shape)

const agentSkillTemplatesNameFilesCreate = (): ToolBase<
    typeof AgentSkillTemplatesNameFilesCreateSchema,
    Schemas.SkillTemplateFile
> => ({
    name: 'agent-skill-templates-name-files-create',
    schema: AgentSkillTemplatesNameFilesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameFilesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.content_type !== undefined) {
            body['content_type'] = params.content_type
        }
        const result = await context.api.request<Schemas.SkillTemplateFile>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/files/`,
            body,
        })
        return result
    },
})

const AgentSkillTemplatesNameFilesDestroySchema = AgentSkillTemplatesNameFilesDestroyParams.omit({ project_id: true })

const agentSkillTemplatesNameFilesDestroy = (): ToolBase<
    typeof AgentSkillTemplatesNameFilesDestroySchema,
    unknown
> => ({
    name: 'agent-skill-templates-name-files-destroy',
    schema: AgentSkillTemplatesNameFilesDestroySchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameFilesDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/files/${encodeURIComponent(String(params.file_path))}/`,
        })
        return result
    },
})

const AgentSkillTemplatesNameFilesRenameCreateSchema = AgentSkillTemplatesNameFilesRenameCreateParams.omit({
    project_id: true,
}).extend(AgentSkillTemplatesNameFilesRenameCreateBody.shape)

const agentSkillTemplatesNameFilesRenameCreate = (): ToolBase<
    typeof AgentSkillTemplatesNameFilesRenameCreateSchema,
    Schemas.SkillTemplateFile
> => ({
    name: 'agent-skill-templates-name-files-rename-create',
    schema: AgentSkillTemplatesNameFilesRenameCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameFilesRenameCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.from_path !== undefined) {
            body['from_path'] = params.from_path
        }
        if (params.to_path !== undefined) {
            body['to_path'] = params.to_path
        }
        const result = await context.api.request<Schemas.SkillTemplateFile>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/files-rename/`,
            body,
        })
        return result
    },
})

const AgentSkillTemplatesNamePublishCreateSchema = AgentSkillTemplatesNamePublishCreateParams.omit({
    project_id: true,
}).extend(AgentSkillTemplatesNamePublishCreateBody.shape)

const agentSkillTemplatesNamePublishCreate = (): ToolBase<
    typeof AgentSkillTemplatesNamePublishCreateSchema,
    Schemas.SkillTemplateDetail
> => ({
    name: 'agent-skill-templates-name-publish-create',
    schema: AgentSkillTemplatesNamePublishCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNamePublishCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.edits !== undefined) {
            body['edits'] = params.edits
        }
        if (params.license !== undefined) {
            body['license'] = params.license
        }
        if (params.compatibility !== undefined) {
            body['compatibility'] = params.compatibility
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.allowed_tools !== undefined) {
            body['allowed_tools'] = params.allowed_tools
        }
        const result = await context.api.request<Schemas.SkillTemplateDetail>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/publish/`,
            body,
        })
        return result
    },
})

const AgentSkillTemplatesNameRetrieveSchema = AgentSkillTemplatesNameRetrieveParams.omit({ project_id: true }).extend(
    AgentSkillTemplatesNameRetrieveQueryParams.shape
)

const agentSkillTemplatesNameRetrieve = (): ToolBase<
    typeof AgentSkillTemplatesNameRetrieveSchema,
    Schemas.SkillTemplateDetail
> => ({
    name: 'agent-skill-templates-name-retrieve',
    schema: AgentSkillTemplatesNameRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SkillTemplateDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const AgentSkillTemplatesNameUsagesListSchema = AgentSkillTemplatesNameUsagesListParams.omit({
    project_id: true,
}).extend(AgentSkillTemplatesNameUsagesListQueryParams.shape)

const agentSkillTemplatesNameUsagesList = (): ToolBase<
    typeof AgentSkillTemplatesNameUsagesListSchema,
    Schemas.SkillTemplateUsage[]
> => ({
    name: 'agent-skill-templates-name-usages-list',
    schema: AgentSkillTemplatesNameUsagesListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameUsagesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SkillTemplateUsage[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/usages/`,
            query: {
                pinned_version: params.pinned_version,
            },
        })
        return result
    },
})

const AgentSkillTemplatesNameVersionsListSchema = AgentSkillTemplatesNameVersionsListParams.omit({ project_id: true })

const agentSkillTemplatesNameVersionsList = (): ToolBase<
    typeof AgentSkillTemplatesNameVersionsListSchema,
    Schemas.TemplateVersionEntry[]
> => ({
    name: 'agent-skill-templates-name-versions-list',
    schema: AgentSkillTemplatesNameVersionsListSchema,
    handler: async (context: Context, params: z.infer<typeof AgentSkillTemplatesNameVersionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TemplateVersionEntry[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_skill_templates/name/${encodeURIComponent(String(params.name))}/versions/`,
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
    'agent-applications-list': agentApplicationsList,
    'agent-applications-partial-update': agentApplicationsPartialUpdate,
    'agent-applications-preview-proxy': agentApplicationsPreviewProxy,
    'agent-applications-retrieve': agentApplicationsRetrieve,
    'agent-applications-revisions-archive-create': agentApplicationsRevisionsArchiveCreate,
    'agent-applications-revisions-bundle-retrieve': agentApplicationsRevisionsBundleRetrieve,
    'agent-applications-revisions-bundle-update': agentApplicationsRevisionsBundleUpdate,
    'agent-applications-revisions-clone-from-create': agentApplicationsRevisionsCloneFromCreate,
    'agent-applications-revisions-create': agentApplicationsRevisionsCreate,
    'agent-applications-revisions-file-destroy': agentApplicationsRevisionsFileDestroy,
    'agent-applications-revisions-file-retrieve': agentApplicationsRevisionsFileRetrieve,
    'agent-applications-revisions-file-update': agentApplicationsRevisionsFileUpdate,
    'agent-applications-revisions-freeze-create': agentApplicationsRevisionsFreezeCreate,
    'agent-applications-revisions-list': agentApplicationsRevisionsList,
    'agent-applications-revisions-manifest-retrieve': agentApplicationsRevisionsManifestRetrieve,
    'agent-applications-revisions-new-draft-create': agentApplicationsRevisionsNewDraftCreate,
    'agent-applications-revisions-partial-update': agentApplicationsRevisionsPartialUpdate,
    'agent-applications-revisions-promote-create': agentApplicationsRevisionsPromoteCreate,
    'agent-applications-revisions-retrieve': agentApplicationsRevisionsRetrieve,
    'agent-applications-revisions-system-prompt': agentApplicationsRevisionsSystemPrompt,
    'agent-applications-revisions-validate-create': agentApplicationsRevisionsValidateCreate,
    'agent-applications-sessions-list': agentApplicationsSessionsList,
    'agent-applications-sessions-retrieve': agentApplicationsSessionsRetrieve,
    'agent-applications-set-env-create': agentApplicationsSetEnvCreate,
    'agent-custom-tool-templates-create': agentCustomToolTemplatesCreate,
    'agent-custom-tool-templates-list': agentCustomToolTemplatesList,
    'agent-custom-tool-templates-name-archive-create': agentCustomToolTemplatesNameArchiveCreate,
    'agent-custom-tool-templates-name-duplicate-create': agentCustomToolTemplatesNameDuplicateCreate,
    'agent-custom-tool-templates-name-publish-create': agentCustomToolTemplatesNamePublishCreate,
    'agent-custom-tool-templates-name-retrieve': agentCustomToolTemplatesNameRetrieve,
    'agent-custom-tool-templates-name-usages-list': agentCustomToolTemplatesNameUsagesList,
    'agent-custom-tool-templates-name-versions-list': agentCustomToolTemplatesNameVersionsList,
    'agent-native-tools-list': agentNativeToolsList,
    'agent-skill-templates-create': agentSkillTemplatesCreate,
    'agent-skill-templates-list': agentSkillTemplatesList,
    'agent-skill-templates-name-archive-create': agentSkillTemplatesNameArchiveCreate,
    'agent-skill-templates-name-duplicate-create': agentSkillTemplatesNameDuplicateCreate,
    'agent-skill-templates-name-files-create': agentSkillTemplatesNameFilesCreate,
    'agent-skill-templates-name-files-destroy': agentSkillTemplatesNameFilesDestroy,
    'agent-skill-templates-name-files-rename-create': agentSkillTemplatesNameFilesRenameCreate,
    'agent-skill-templates-name-publish-create': agentSkillTemplatesNamePublishCreate,
    'agent-skill-templates-name-retrieve': agentSkillTemplatesNameRetrieve,
    'agent-skill-templates-name-usages-list': agentSkillTemplatesNameUsagesList,
    'agent-skill-templates-name-versions-list': agentSkillTemplatesNameVersionsList,
}
