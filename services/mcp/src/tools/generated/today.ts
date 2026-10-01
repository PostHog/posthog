// AUTO-GENERATED from products/today/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/today/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const TodayBriefingWriteSchema = () => {
    const TodayBriefingWriteCreateBody = orvalSchemas.TodayBriefingWriteCreateBody()
    return TodayBriefingWriteCreateBody
}

const todayBriefingWrite = (): ToolBase<ReturnType<typeof TodayBriefingWriteSchema>, Schemas.Briefing> => ({
    name: 'today-briefing-write',
    schema: TodayBriefingWriteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TodayBriefingWriteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.briefing_id !== undefined) {
            body['briefing_id'] = params.briefing_id
        }
        if (params.headline !== undefined) {
            body['headline'] = params.headline
        }
        if (params.paragraphs !== undefined) {
            body['paragraphs'] = params.paragraphs
        }
        if (params.items !== undefined) {
            body['items'] = params.items
        }
        const result = await context.api.request<Schemas.Briefing>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/today/briefing/write/`,
            body,
        })
        return result
    },
})

const TodayBriefingGetSchema = () => {
    const TodayBriefingRetrieveQueryParams = orvalSchemas.TodayBriefingRetrieveQueryParams()
    return TodayBriefingRetrieveQueryParams
}

const todayBriefingGet = (): ToolBase<ReturnType<typeof TodayBriefingGetSchema>, Schemas.Briefing> => ({
    name: 'today-briefing-get',
    schema: TodayBriefingGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TodayBriefingGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Briefing>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/today/briefing/`,
            query: {
                timezone: params.timezone,
            },
        })
        return result
    },
})

const TodayCandidatesListSchema = () => {
    const TodayCandidatesRetrieveQueryParams = orvalSchemas.TodayCandidatesRetrieveQueryParams()
    return TodayCandidatesRetrieveQueryParams
}

const todayCandidatesList = (): ToolBase<ReturnType<typeof TodayCandidatesListSchema>, Schemas.CandidateList> => ({
    name: 'today-candidates-list',
    schema: TodayCandidatesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TodayCandidatesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CandidateList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/today/candidates/`,
            query: {
                timezone: params.timezone,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'today-briefing-write': todayBriefingWrite,
    'today-briefing-get': todayBriefingGet,
    'today-candidates-list': todayCandidatesList,
}
