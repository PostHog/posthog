// AUTO-GENERATED from products/user_interviews/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { UserInterviewsListQueryParams, UserInterviewsRetrieveParams } from '@/generated/user_interviews/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UserInterviewsListSchema = UserInterviewsListQueryParams

const userInterviewsList = (): ToolBase<
    typeof UserInterviewsListSchema,
    WithPostHogUrl<Schemas.PaginatedUserInterviewList>
> => ({
    name: 'user-interviews-list',
    schema: UserInterviewsListSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedUserInterviewList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interviews/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/user_interviews')
    },
})

const UserInterviewsRetrieveSchema = UserInterviewsRetrieveParams.omit({ project_id: true })

const userInterviewsRetrieve = (): ToolBase<typeof UserInterviewsRetrieveSchema, Schemas.UserInterview> => ({
    name: 'user-interviews-retrieve',
    schema: UserInterviewsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UserInterview>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interviews/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'user-interviews-list': userInterviewsList,
    'user-interviews-retrieve': userInterviewsRetrieve,
}
