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

const MeepTopicCreateSchema = () => {
    const MeepTopicsCreateBody = orvalSchemas.MeepTopicsCreateBody()
    return MeepTopicsCreateBody
}

const meepTopicCreate = (): ToolBase<ReturnType<typeof MeepTopicCreateSchema>, Schemas.MeepTopic> => ({
    name: 'meep-topic-create',
    schema: MeepTopicCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTopicCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.mission !== undefined) {
            body['mission'] = params.mission
        }
        const result = await context.api.request<Schemas.MeepTopic>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'meep-topic-list': meepTopicList,
    'meep-topic-get': meepTopicGet,
    'meep-topic-create': meepTopicCreate,
}
