// AUTO-GENERATED from services/mcp/definitions/agent_stack.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AgentApplicationsCreateBody,
    AgentApplicationsDestroyParams,
    AgentApplicationsListQueryParams,
    AgentApplicationsPartialUpdateBody,
    AgentApplicationsPartialUpdateParams,
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
    AgentApplicationsRevisionsValidateCreateParams,
    AgentApplicationsSetEnvCreateBody,
    AgentApplicationsSetEnvCreateParams,
} from '@/generated/agent_stack/api'
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
    'agent-applications-list': agentApplicationsList,
    'agent-applications-partial-update': agentApplicationsPartialUpdate,
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
    'agent-applications-revisions-validate-create': agentApplicationsRevisionsValidateCreate,
    'agent-applications-set-env-create': agentApplicationsSetEnvCreate,
    'agent-native-tools-list': agentNativeToolsList,
}
