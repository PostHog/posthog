// AUTO-GENERATED from products/user_interviews/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { UserInterviewTopicsCreateBody, UserInterviewTopicsListQueryParams } from '@/generated/user_interviews/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UserInterviewTopicsCreateSchema = UserInterviewTopicsCreateBody

const userInterviewTopicsCreate = (): ToolBase<typeof UserInterviewTopicsCreateSchema, Schemas.UserInterviewTopic> => ({
    name: 'user-interview-topics-create',
    schema: UserInterviewTopicsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.interviewee_cohort !== undefined) {
            body['interviewee_cohort'] = params.interviewee_cohort
        }
        if (params.interviewee_emails !== undefined) {
            body['interviewee_emails'] = params.interviewee_emails
        }
        if (params.interviewee_distinct_ids !== undefined) {
            body['interviewee_distinct_ids'] = params.interviewee_distinct_ids
        }
        if (params.topic !== undefined) {
            body['topic'] = params.topic
        }
        if (params.agent_context !== undefined) {
            body['agent_context'] = params.agent_context
        }
        if (params.questions !== undefined) {
            body['questions'] = params.questions
        }
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsListSchema = UserInterviewTopicsListQueryParams

const userInterviewTopicsList = (): ToolBase<
    typeof UserInterviewTopicsListSchema,
    WithPostHogUrl<Schemas.PaginatedUserInterviewTopicList>
> => ({
    name: 'user-interview-topics-list',
    schema: UserInterviewTopicsListSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedUserInterviewTopicList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/user_interviews')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'user-interview-topics-create': userInterviewTopicsCreate,
    'user-interview-topics-list': userInterviewTopicsList,
}
