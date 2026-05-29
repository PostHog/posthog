// AUTO-GENERATED from products/user_interviews/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    UserInterviewTopicsAddIntervieweeCreateBody,
    UserInterviewTopicsAddIntervieweeCreateParams,
    UserInterviewTopicsCreateBody,
    UserInterviewTopicsGenerateLinksCreateParams,
    UserInterviewTopicsIntervieweesBulkCreateBody,
    UserInterviewTopicsIntervieweesBulkCreateParams,
    UserInterviewTopicsIntervieweesCreateBody,
    UserInterviewTopicsIntervieweesCreateParams,
    UserInterviewTopicsIntervieweesDestroyParams,
    UserInterviewTopicsIntervieweesListParams,
    UserInterviewTopicsIntervieweesListQueryParams,
    UserInterviewTopicsIntervieweesPartialUpdateBody,
    UserInterviewTopicsIntervieweesPartialUpdateParams,
    UserInterviewTopicsLinksCsvCreateParams,
    UserInterviewTopicsListQueryParams,
    UserInterviewTopicsPartialUpdateBody,
    UserInterviewTopicsPartialUpdateParams,
    UserInterviewTopicsRemoveIntervieweeCreateBody,
    UserInterviewTopicsRemoveIntervieweeCreateParams,
    UserInterviewTopicsRetrieveParams,
    UserInterviewTopicsSendInvitesCreateBody,
    UserInterviewTopicsSendInvitesCreateParams,
    UserInterviewsListQueryParams,
    UserInterviewsRetrieveParams,
    UserInterviewsSearchCreateBody,
} from '@/generated/user_interviews/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UserInterviewTopicsAddIntervieweeSchema = UserInterviewTopicsAddIntervieweeCreateParams.omit({
    project_id: true,
}).extend(UserInterviewTopicsAddIntervieweeCreateBody.shape)

const userInterviewTopicsAddInterviewee = (): ToolBase<
    typeof UserInterviewTopicsAddIntervieweeSchema,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-add-interviewee',
    schema: UserInterviewTopicsAddIntervieweeSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsAddIntervieweeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.identifier !== undefined) {
            body['identifier'] = params.identifier
        }
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/add_interviewee/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsCreateSchema = UserInterviewTopicsCreateBody

const userInterviewTopicsCreate = (): ToolBase<typeof UserInterviewTopicsCreateSchema, Schemas.UserInterviewTopic> => ({
    name: 'user-interview-topics-create',
    schema: UserInterviewTopicsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
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

const UserInterviewTopicsIntervieweesBulkCreateSchema = UserInterviewTopicsIntervieweesBulkCreateParams.omit({
    project_id: true,
}).extend(UserInterviewTopicsIntervieweesBulkCreateBody.shape)

const userInterviewTopicsIntervieweesBulkCreate = (): ToolBase<
    typeof UserInterviewTopicsIntervieweesBulkCreateSchema,
    Schemas.BulkIntervieweeContextResponse
> => ({
    name: 'user-interview-topics-interviewees-bulk-create',
    schema: UserInterviewTopicsIntervieweesBulkCreateSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsIntervieweesBulkCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.items !== undefined) {
            body['items'] = params.items
        }
        const result = await context.api.request<Schemas.BulkIntervieweeContextResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/bulk/`,
            body,
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

const UserInterviewTopicsIntervieweesDestroySchema = UserInterviewTopicsIntervieweesDestroyParams.omit({
    project_id: true,
})

const userInterviewTopicsIntervieweesDestroy = (): ToolBase<
    typeof UserInterviewTopicsIntervieweesDestroySchema,
    unknown
> => ({
    name: 'user-interview-topics-interviewees-destroy',
    schema: UserInterviewTopicsIntervieweesDestroySchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsIntervieweesDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/${encodeURIComponent(String(params.id))}/`,
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

const UserInterviewTopicsIntervieweesPartialUpdateSchema = UserInterviewTopicsIntervieweesPartialUpdateParams.omit({
    project_id: true,
}).extend(UserInterviewTopicsIntervieweesPartialUpdateBody.omit({ interviewee_identifier: true }).shape)

const userInterviewTopicsIntervieweesPartialUpdate = (): ToolBase<
    typeof UserInterviewTopicsIntervieweesPartialUpdateSchema,
    Schemas.IntervieweeContext
> => ({
    name: 'user-interview-topics-interviewees-partial-update',
    schema: UserInterviewTopicsIntervieweesPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsIntervieweesPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.agent_context !== undefined) {
            body['agent_context'] = params.agent_context
        }
        const result = await context.api.request<Schemas.IntervieweeContext>({
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsLinksCsvSchema = UserInterviewTopicsLinksCsvCreateParams.omit({ project_id: true })

const userInterviewTopicsLinksCsv = (): ToolBase<typeof UserInterviewTopicsLinksCsvSchema, unknown> => ({
    name: 'user-interview-topics-links-csv',
    schema: UserInterviewTopicsLinksCsvSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsLinksCsvSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/links_csv/`,
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

const UserInterviewTopicsPartialUpdateSchema = UserInterviewTopicsPartialUpdateParams.omit({ project_id: true }).extend(
    UserInterviewTopicsPartialUpdateBody.shape
)

const userInterviewTopicsPartialUpdate = (): ToolBase<
    typeof UserInterviewTopicsPartialUpdateSchema,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-partial-update',
    schema: UserInterviewTopicsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
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
            method: 'PATCH',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsRemoveIntervieweeSchema = UserInterviewTopicsRemoveIntervieweeCreateParams.omit({
    project_id: true,
}).extend(UserInterviewTopicsRemoveIntervieweeCreateBody.shape)

const userInterviewTopicsRemoveInterviewee = (): ToolBase<
    typeof UserInterviewTopicsRemoveIntervieweeSchema,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-remove-interviewee',
    schema: UserInterviewTopicsRemoveIntervieweeSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsRemoveIntervieweeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.identifier !== undefined) {
            body['identifier'] = params.identifier
        }
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/remove_interviewee/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsRetrieveSchema = UserInterviewTopicsRetrieveParams.omit({ project_id: true })

const userInterviewTopicsRetrieve = (): ToolBase<
    typeof UserInterviewTopicsRetrieveSchema,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-retrieve',
    schema: UserInterviewTopicsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewTopicsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
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
                topic: params.topic,
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

const UserInterviewsSearchSchema = UserInterviewsSearchCreateBody

const userInterviewsSearch = (): ToolBase<typeof UserInterviewsSearchSchema, Schemas.UserInterviewSearchResult[]> => ({
    name: 'user-interviews-search',
    schema: UserInterviewsSearchSchema,
    handler: async (context: Context, params: z.infer<typeof UserInterviewsSearchSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.document_types !== undefined) {
            body['document_types'] = params.document_types
        }
        if (params.topic_id !== undefined) {
            body['topic_id'] = params.topic_id
        }
        if (params.limit !== undefined) {
            body['limit'] = params.limit
        }
        const result = await context.api.request<Schemas.UserInterviewSearchResult[]>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/user_interviews/search/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'user-interview-topics-add-interviewee': userInterviewTopicsAddInterviewee,
    'user-interview-topics-create': userInterviewTopicsCreate,
    'user-interview-topics-generate-links': userInterviewTopicsGenerateLinks,
    'user-interview-topics-interviewees-bulk-create': userInterviewTopicsIntervieweesBulkCreate,
    'user-interview-topics-interviewees-create': userInterviewTopicsIntervieweesCreate,
    'user-interview-topics-interviewees-destroy': userInterviewTopicsIntervieweesDestroy,
    'user-interview-topics-interviewees-list': userInterviewTopicsIntervieweesList,
    'user-interview-topics-interviewees-partial-update': userInterviewTopicsIntervieweesPartialUpdate,
    'user-interview-topics-links-csv': userInterviewTopicsLinksCsv,
    'user-interview-topics-list': userInterviewTopicsList,
    'user-interview-topics-partial-update': userInterviewTopicsPartialUpdate,
    'user-interview-topics-remove-interviewee': userInterviewTopicsRemoveInterviewee,
    'user-interview-topics-retrieve': userInterviewTopicsRetrieve,
    'user-interview-topics-send-invites': userInterviewTopicsSendInvites,
    'user-interviews-list': userInterviewsList,
    'user-interviews-retrieve': userInterviewsRetrieve,
    'user-interviews-search': userInterviewsSearch,
}
