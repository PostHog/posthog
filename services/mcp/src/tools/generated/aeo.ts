// AUTO-GENERATED from products/aeo/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/aeo/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AeoPromptsArchiveSchema = () => {
    const AeoPromptsDestroyParams = orvalSchemas.AeoPromptsDestroyParams()
    return AeoPromptsDestroyParams.omit({ project_id: true }).extend({
        id: AeoPromptsDestroyParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsArchive = (): ToolBase<ReturnType<typeof AeoPromptsArchiveSchema>, unknown> => ({
    name: 'aeo-prompts-archive',
    schema: AeoPromptsArchiveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsArchiveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AeoPromptsChecksListSchema = () => {
    const AeoPromptsChecksParams = orvalSchemas.AeoPromptsChecksParams()
    const AeoPromptsChecksQueryParams = orvalSchemas.AeoPromptsChecksQueryParams()
    return AeoPromptsChecksParams.omit({ project_id: true })
        .extend(AeoPromptsChecksQueryParams.shape)
        .extend({ id: AeoPromptsChecksParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.') })
}

const aeoPromptsChecksList = (): ToolBase<
    ReturnType<typeof AeoPromptsChecksListSchema>,
    WithPostHogUrl<Schemas.PaginatedAEOPromptCheckList>
> => ({
    name: 'aeo-prompts-checks-list',
    schema: AeoPromptsChecksListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsChecksListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAEOPromptCheckList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/checks/`,
            query: {
                engine: params.engine,
                limit: params.limit,
                offset: params.offset,
                version: params.version,
            },
        })
        return await withPostHogUrl(context, result, '/web/content-autopilot')
    },
})

const AeoPromptsGetSchema = () => {
    const AeoPromptsRetrieveParams = orvalSchemas.AeoPromptsRetrieveParams()
    return AeoPromptsRetrieveParams.omit({ project_id: true }).extend({
        id: AeoPromptsRetrieveParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsGet = (): ToolBase<ReturnType<typeof AeoPromptsGetSchema>, Schemas.AEOPrompt> => ({
    name: 'aeo-prompts-get',
    schema: AeoPromptsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPrompt>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AeoPromptsImportSchema = () => {
    const AeoPromptsBulkImportBody = orvalSchemas.AeoPromptsBulkImportBody()
    return AeoPromptsBulkImportBody
}

const aeoPromptsImport = (): ToolBase<ReturnType<typeof AeoPromptsImportSchema>, Schemas.AEOPromptImportResult> => ({
    name: 'aeo-prompts-import',
    schema: AeoPromptsImportSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsImportSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.prompts !== undefined) {
            body['prompts'] = params.prompts
        }
        const result = await context.api.request<Schemas.AEOPromptImportResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/bulk_import/`,
            body,
        })
        return result
    },
})

const AeoPromptsListSchema = () => {
    const AeoPromptsListQueryParams = orvalSchemas.AeoPromptsListQueryParams()
    return AeoPromptsListQueryParams
}

const aeoPromptsList = (): ToolBase<
    ReturnType<typeof AeoPromptsListSchema>,
    WithPostHogUrl<Schemas.PaginatedAEOPromptList>
> => ({
    name: 'aeo-prompts-list',
    schema: AeoPromptsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAEOPromptList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/`,
            query: {
                active: params.active,
                include_archived: params.include_archived,
                limit: params.limit,
                offset: params.offset,
                topic: params.topic,
            },
        })
        return await withPostHogUrl(context, result, '/web/content-autopilot')
    },
})

const AeoPromptsStatsGetSchema = () => {
    const AeoPromptsStatsParams = orvalSchemas.AeoPromptsStatsParams()
    return AeoPromptsStatsParams.omit({ project_id: true }).extend({
        id: AeoPromptsStatsParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsStatsGet = (): ToolBase<ReturnType<typeof AeoPromptsStatsGetSchema>, Schemas.AEOPromptStats> => ({
    name: 'aeo-prompts-stats-get',
    schema: AeoPromptsStatsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsStatsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptStats>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/stats/`,
        })
        return result
    },
})

const AeoPromptsTopicsListSchema = () => z.object({})

const aeoPromptsTopicsList = (): ToolBase<ReturnType<typeof AeoPromptsTopicsListSchema>, Schemas.AEOPromptTopic[]> => ({
    name: 'aeo-prompts-topics-list',
    schema: AeoPromptsTopicsListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof AeoPromptsTopicsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptTopic[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/topics/`,
        })
        return result
    },
})

const AeoPromptsUpdateSchema = () => {
    const AeoPromptsPartialUpdateBody = orvalSchemas.AeoPromptsPartialUpdateBody()
    const AeoPromptsPartialUpdateParams = orvalSchemas.AeoPromptsPartialUpdateParams()
    return AeoPromptsPartialUpdateParams.omit({ project_id: true })
        .extend(AeoPromptsPartialUpdateBody.shape)
        .extend({
            id: AeoPromptsPartialUpdateParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
        })
}

const aeoPromptsUpdate = (): ToolBase<ReturnType<typeof AeoPromptsUpdateSchema>, Schemas.AEOPrompt> => ({
    name: 'aeo-prompts-update',
    schema: AeoPromptsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.active !== undefined) {
            body['active'] = params.active
        }
        if (params.topic !== undefined) {
            body['topic'] = params.topic
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.version_description !== undefined) {
            body['version_description'] = params.version_description
        }
        if (params.current_version !== undefined) {
            body['current_version'] = params.current_version
        }
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        const result = await context.api.request<Schemas.AEOPrompt>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const AeoPromptsVersionsListSchema = () => {
    const AeoPromptsVersionsParams = orvalSchemas.AeoPromptsVersionsParams()
    return AeoPromptsVersionsParams.omit({ project_id: true }).extend({
        id: AeoPromptsVersionsParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsVersionsList = (): ToolBase<
    ReturnType<typeof AeoPromptsVersionsListSchema>,
    Schemas.AEOPromptVersion[]
> => ({
    name: 'aeo-prompts-versions-list',
    schema: AeoPromptsVersionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsVersionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptVersion[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/versions/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'aeo-prompts-archive': aeoPromptsArchive,
    'aeo-prompts-checks-list': aeoPromptsChecksList,
    'aeo-prompts-get': aeoPromptsGet,
    'aeo-prompts-import': aeoPromptsImport,
    'aeo-prompts-list': aeoPromptsList,
    'aeo-prompts-stats-get': aeoPromptsStatsGet,
    'aeo-prompts-topics-list': aeoPromptsTopicsList,
    'aeo-prompts-update': aeoPromptsUpdate,
    'aeo-prompts-versions-list': aeoPromptsVersionsList,
}
