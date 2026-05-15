// AUTO-GENERATED from products/user_interviews/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    UserInterviewTopicsCreateBody,
    UserInterviewTopicsGenerateLinksCreateParams,
    UserInterviewTopicsIntervieweesCreateBody,
    UserInterviewTopicsIntervieweesCreateParams,
    UserInterviewTopicsIntervieweesListParams,
    UserInterviewTopicsIntervieweesListQueryParams,
    UserInterviewTopicsListQueryParams,
    UserInterviewTopicsSendInvitesCreateBody,
    UserInterviewTopicsSendInvitesCreateParams,
} from '@/generated/user_interviews/api'
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

const UserInterviewTopicsGenerateLinksSchema = UserInterviewTopicsGenerateLinksCreateParams.omit({ project_id: true })

const userInterviewTopicsGenerateLinks = (): ToolBase<
    typeof UserInterviewTopicsGenerateLinksSchema,
    Schemas.PaginatedInterviewLinkList
> => ({
    name: 'user-interview-topics-generate-links',
    schema: UserInterviewTopicsGenerateLinksSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsGenerateLinksSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedInterviewLinkList>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/generate_links/`,
        })
        return result
    },
})

const UserInterviewTopicsIntervieweesCreateSchema = UserInterviewTopicsIntervieweesCreateParams.omit({
    project_id: true,
}).extend(UserInterviewTopicsIntervieweesCreateBody.shape)

const userInterviewTopicsIntervieweesCreate = (): ToolBase<
    typeof UserInterviewTopicsIntervieweesCreateSchema,
    Schemas.IntervieweeContext
> => ({
    name: 'user-interview-topics-interviewees-create',
    schema: UserInterviewTopicsIntervieweesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsIntervieweesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.interviewee_identifier !== undefined) {
            body['interviewee_identifier'] = params.interviewee_identifier
        }
        if (params.agent_context !== undefined) {
            body['agent_context'] = params.agent_context
        }
        const result = await context.api.request<Schemas.IntervieweeContext>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsIntervieweesListSchema = UserInterviewTopicsIntervieweesListParams.omit({
    project_id: true,
}).extend(UserInterviewTopicsIntervieweesListQueryParams.shape)

const userInterviewTopicsIntervieweesList = (): ToolBase<
    typeof UserInterviewTopicsIntervieweesListSchema,
    WithPostHogUrl<Schemas.PaginatedIntervieweeContextList>
> => ({
    name: 'user-interview-topics-interviewees-list',
    schema: UserInterviewTopicsIntervieweesListSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsIntervieweesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedIntervieweeContextList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/user_interviews')
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

const UserInterviewTopicsSendInvitesSchema = UserInterviewTopicsSendInvitesCreateParams.omit({
    project_id: true,
}).extend(UserInterviewTopicsSendInvitesCreateBody.shape)

const userInterviewTopicsSendInvites = (): ToolBase<
    typeof UserInterviewTopicsSendInvitesSchema,
    Schemas.PaginatedInterviewInviteResultList
> => ({
    name: 'user-interview-topics-send-invites',
    schema: UserInterviewTopicsSendInvitesSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsSendInvitesSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.subject !== undefined) {
            body['subject'] = params.subject
        }
        if (params.reply_to !== undefined) {
            body['reply_to'] = params.reply_to
        }
        if (params.send_async !== undefined) {
            body['send_async'] = params.send_async
        }
        const result = await context.api.request<Schemas.PaginatedInterviewInviteResultList>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/send_invites/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'user-interview-topics-create': userInterviewTopicsCreate,
    'user-interview-topics-generate-links': userInterviewTopicsGenerateLinks,
    'user-interview-topics-interviewees-create': userInterviewTopicsIntervieweesCreate,
    'user-interview-topics-interviewees-list': userInterviewTopicsIntervieweesList,
    'user-interview-topics-list': userInterviewTopicsList,
    'user-interview-topics-send-invites': userInterviewTopicsSendInvites,
}
