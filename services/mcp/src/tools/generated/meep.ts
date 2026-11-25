// AUTO-GENERATED from products/meep/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/meep/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MeepTopicListSchema = () => {
    const MeepTopicsListQueryParams = orvalSchemas.MeepTopicsListQueryParams()
    return MeepTopicsListQueryParams
}

const meepTopicList = (): ToolBase<ReturnType<typeof MeepTopicListSchema>, Schemas.PaginatedMeepTopicList> => ({
    name: 'meep-topic-list',
    schema: MeepTopicListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTopicListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMeepTopicList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const MeepTopicGetSchema = () => {
    const MeepTopicsRetrieveParams = orvalSchemas.MeepTopicsRetrieveParams()
    return MeepTopicsRetrieveParams.omit({ project_id: true })
}

const meepTopicGet = (): ToolBase<ReturnType<typeof MeepTopicGetSchema>, Schemas.MeepTopicDetails> => ({
    name: 'meep-topic-get',
    schema: MeepTopicGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTopicGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MeepTopicDetails>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const MeepScoutCreateSchema = () => {
    const MeepTopicsCreateScoutBody = orvalSchemas.MeepTopicsCreateScoutBody()
    const MeepTopicsCreateScoutParams = orvalSchemas.MeepTopicsCreateScoutParams()
    return MeepTopicsCreateScoutParams.omit({ project_id: true }).extend(MeepTopicsCreateScoutBody.shape)
}

const meepScoutCreate = (): ToolBase<ReturnType<typeof MeepScoutCreateSchema>, Schemas.MeepScout> => ({
    name: 'meep-scout-create',
    schema: MeepScoutCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepScoutCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.instructions !== undefined) {
            body['instructions'] = params.instructions
        }
        if (params.cron !== undefined) {
            body['cron'] = params.cron
        }
        const result = await context.api.request<Schemas.MeepScout>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/scouts/`,
            body,
        })
        return result
    },
})

const MeepScoutSetEnabledSchema = () => {
    const MeepTopicsSetScoutEnabledBody = orvalSchemas.MeepTopicsSetScoutEnabledBody()
    const MeepTopicsSetScoutEnabledParams = orvalSchemas.MeepTopicsSetScoutEnabledParams()
    return MeepTopicsSetScoutEnabledParams.omit({ project_id: true }).extend(MeepTopicsSetScoutEnabledBody.shape)
}

const meepScoutSetEnabled = (): ToolBase<ReturnType<typeof MeepScoutSetEnabledSchema>, Schemas.MeepScout> => ({
    name: 'meep-scout-set-enabled',
    schema: MeepScoutSetEnabledSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepScoutSetEnabledSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.scout_id !== undefined) {
            body['scout_id'] = params.scout_id
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        const result = await context.api.request<Schemas.MeepScout>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/scout-status/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'meep-topic-list': meepTopicList,
    'meep-topic-get': meepTopicGet,
    'meep-scout-create': meepScoutCreate,
    'meep-scout-set-enabled': meepScoutSetEnabled,
}
