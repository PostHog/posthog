// AUTO-GENERATED from products/user_interviews/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/user_interviews/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UserInterviewTopicsAddIntervieweeSchema = () => {
    const UserInterviewTopicsAddIntervieweeCreateBody = orvalSchemas.UserInterviewTopicsAddIntervieweeCreateBody()
    const UserInterviewTopicsAddIntervieweeCreateParams = orvalSchemas.UserInterviewTopicsAddIntervieweeCreateParams()
    return UserInterviewTopicsAddIntervieweeCreateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsAddIntervieweeCreateBody.shape
    )
}

const userInterviewTopicsAddInterviewee = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsAddIntervieweeSchema>,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-add-interviewee',
    schema: UserInterviewTopicsAddIntervieweeSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsAddIntervieweeSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.identifier !== undefined) {
            body['identifier'] = params.identifier
        }
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/add_interviewee/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsCreateSchema = () => {
    const UserInterviewTopicsCreateBody = orvalSchemas.UserInterviewTopicsCreateBody()
    return UserInterviewTopicsCreateBody
}

const userInterviewTopicsCreate = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsCreateSchema>,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-create',
    schema: UserInterviewTopicsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsCreateSchema>>) => {
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
        if (params.invite_subject !== undefined) {
            body['invite_subject'] = params.invite_subject
        }
        if (params.invite_message !== undefined) {
            body['invite_message'] = params.invite_message
        }
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsGenerateLinksSchema = () => {
    const UserInterviewTopicsGenerateLinksCreateParams = orvalSchemas.UserInterviewTopicsGenerateLinksCreateParams()
    return UserInterviewTopicsGenerateLinksCreateParams.omit({ project_id: true })
}

const userInterviewTopicsGenerateLinks = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsGenerateLinksSchema>,
    Schemas.PaginatedInterviewLinkList
> => ({
    name: 'user-interview-topics-generate-links',
    schema: UserInterviewTopicsGenerateLinksSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsGenerateLinksSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedInterviewLinkList>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/generate_links/`,
        })
        return result
    },
})

const UserInterviewTopicsIntervieweesBulkCreateSchema = () => {
    const UserInterviewTopicsIntervieweesBulkCreateBody = orvalSchemas.UserInterviewTopicsIntervieweesBulkCreateBody()
    const UserInterviewTopicsIntervieweesBulkCreateParams =
        orvalSchemas.UserInterviewTopicsIntervieweesBulkCreateParams()
    return UserInterviewTopicsIntervieweesBulkCreateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsIntervieweesBulkCreateBody.shape
    )
}

const userInterviewTopicsIntervieweesBulkCreate = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsIntervieweesBulkCreateSchema>,
    Schemas.BulkIntervieweeContextResponse
> => ({
    name: 'user-interview-topics-interviewees-bulk-create',
    schema: UserInterviewTopicsIntervieweesBulkCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof UserInterviewTopicsIntervieweesBulkCreateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.items !== undefined) {
            body['items'] = params.items
        }
        const result = await context.api.request<Schemas.BulkIntervieweeContextResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/bulk/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsIntervieweesCreateSchema = () => {
    const UserInterviewTopicsIntervieweesCreateBody = orvalSchemas.UserInterviewTopicsIntervieweesCreateBody()
    const UserInterviewTopicsIntervieweesCreateParams = orvalSchemas.UserInterviewTopicsIntervieweesCreateParams()
    return UserInterviewTopicsIntervieweesCreateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsIntervieweesCreateBody.shape
    )
}

const userInterviewTopicsIntervieweesCreate = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsIntervieweesCreateSchema>,
    Schemas.IntervieweeContext
> => ({
    name: 'user-interview-topics-interviewees-create',
    schema: UserInterviewTopicsIntervieweesCreateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof UserInterviewTopicsIntervieweesCreateSchema>>
    ) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsIntervieweesDestroySchema = () => {
    const UserInterviewTopicsIntervieweesDestroyParams = orvalSchemas.UserInterviewTopicsIntervieweesDestroyParams()
    return UserInterviewTopicsIntervieweesDestroyParams.omit({ project_id: true })
}

const userInterviewTopicsIntervieweesDestroy = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsIntervieweesDestroySchema>,
    unknown
> => ({
    name: 'user-interview-topics-interviewees-destroy',
    schema: UserInterviewTopicsIntervieweesDestroySchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof UserInterviewTopicsIntervieweesDestroySchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const UserInterviewTopicsIntervieweesListSchema = () => {
    const UserInterviewTopicsIntervieweesListParams = orvalSchemas.UserInterviewTopicsIntervieweesListParams()
    const UserInterviewTopicsIntervieweesListQueryParams = orvalSchemas.UserInterviewTopicsIntervieweesListQueryParams()
    return UserInterviewTopicsIntervieweesListParams.omit({ project_id: true }).extend(
        UserInterviewTopicsIntervieweesListQueryParams.shape
    )
}

const userInterviewTopicsIntervieweesList = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsIntervieweesListSchema>,
    WithPostHogUrl<Schemas.PaginatedIntervieweeContextList>
> => ({
    name: 'user-interview-topics-interviewees-list',
    schema: UserInterviewTopicsIntervieweesListSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof UserInterviewTopicsIntervieweesListSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedIntervieweeContextList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/user_interviews')
    },
})

const UserInterviewTopicsIntervieweesPartialUpdateSchema = () => {
    const UserInterviewTopicsIntervieweesPartialUpdateBody =
        orvalSchemas.UserInterviewTopicsIntervieweesPartialUpdateBody()
    const UserInterviewTopicsIntervieweesPartialUpdateParams =
        orvalSchemas.UserInterviewTopicsIntervieweesPartialUpdateParams()
    return UserInterviewTopicsIntervieweesPartialUpdateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsIntervieweesPartialUpdateBody.omit({ interviewee_identifier: true }).shape
    )
}

const userInterviewTopicsIntervieweesPartialUpdate = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsIntervieweesPartialUpdateSchema>,
    Schemas.IntervieweeContext
> => ({
    name: 'user-interview-topics-interviewees-partial-update',
    schema: UserInterviewTopicsIntervieweesPartialUpdateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof UserInterviewTopicsIntervieweesPartialUpdateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.agent_context !== undefined) {
            body['agent_context'] = params.agent_context
        }
        const result = await context.api.request<Schemas.IntervieweeContext>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.topic_id))}/interviewees/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsLinksCsvSchema = () => {
    const UserInterviewTopicsLinksCsvCreateParams = orvalSchemas.UserInterviewTopicsLinksCsvCreateParams()
    return UserInterviewTopicsLinksCsvCreateParams.omit({ project_id: true })
}

const userInterviewTopicsLinksCsv = (): ToolBase<ReturnType<typeof UserInterviewTopicsLinksCsvSchema>, unknown> => ({
    name: 'user-interview-topics-links-csv',
    schema: UserInterviewTopicsLinksCsvSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsLinksCsvSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/links_csv/`,
        })
        return result
    },
})

const UserInterviewTopicsListSchema = () => {
    const UserInterviewTopicsListQueryParams = orvalSchemas.UserInterviewTopicsListQueryParams()
    return UserInterviewTopicsListQueryParams
}

const userInterviewTopicsList = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsListSchema>,
    WithPostHogUrl<Schemas.PaginatedUserInterviewTopicList>
> => ({
    name: 'user-interview-topics-list',
    schema: UserInterviewTopicsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedUserInterviewTopicList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return await withPostHogUrl(context, result, '/user_interviews')
    },
})

const UserInterviewTopicsPartialUpdateSchema = () => {
    const UserInterviewTopicsPartialUpdateBody = orvalSchemas.UserInterviewTopicsPartialUpdateBody()
    const UserInterviewTopicsPartialUpdateParams = orvalSchemas.UserInterviewTopicsPartialUpdateParams()
    return UserInterviewTopicsPartialUpdateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsPartialUpdateBody.shape
    )
}

const userInterviewTopicsPartialUpdate = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsPartialUpdateSchema>,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-partial-update',
    schema: UserInterviewTopicsPartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsPartialUpdateSchema>>) => {
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
        if (params.invite_subject !== undefined) {
            body['invite_subject'] = params.invite_subject
        }
        if (params.invite_message !== undefined) {
            body['invite_message'] = params.invite_message
        }
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsPreviewInviteSchema = () => {
    const UserInterviewTopicsPreviewInviteCreateBody = orvalSchemas.UserInterviewTopicsPreviewInviteCreateBody()
    const UserInterviewTopicsPreviewInviteCreateParams = orvalSchemas.UserInterviewTopicsPreviewInviteCreateParams()
    return UserInterviewTopicsPreviewInviteCreateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsPreviewInviteCreateBody.shape
    )
}

const userInterviewTopicsPreviewInvite = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsPreviewInviteSchema>,
    Schemas.PreviewInviteResult
> =>
    withUiApp('invite-email-preview', {
        name: 'user-interview-topics-preview-invite',
        schema: UserInterviewTopicsPreviewInviteSchema(),
        handler: async (
            context: Context,
            params: z.infer<ReturnType<typeof UserInterviewTopicsPreviewInviteSchema>>
        ) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.interviewee_identifier !== undefined) {
                body['interviewee_identifier'] = params.interviewee_identifier
            }
            const result = await context.api.request<Schemas.PreviewInviteResult>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/preview_invite/`,
                body,
            })
            return result
        },
    })

const UserInterviewTopicsRemoveIntervieweeSchema = () => {
    const UserInterviewTopicsRemoveIntervieweeCreateBody = orvalSchemas.UserInterviewTopicsRemoveIntervieweeCreateBody()
    const UserInterviewTopicsRemoveIntervieweeCreateParams =
        orvalSchemas.UserInterviewTopicsRemoveIntervieweeCreateParams()
    return UserInterviewTopicsRemoveIntervieweeCreateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsRemoveIntervieweeCreateBody.shape
    )
}

const userInterviewTopicsRemoveInterviewee = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsRemoveIntervieweeSchema>,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-remove-interviewee',
    schema: UserInterviewTopicsRemoveIntervieweeSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof UserInterviewTopicsRemoveIntervieweeSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.identifier !== undefined) {
            body['identifier'] = params.identifier
        }
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/remove_interviewee/`,
            body,
        })
        return result
    },
})

const UserInterviewTopicsRetrieveSchema = () => {
    const UserInterviewTopicsRetrieveParams = orvalSchemas.UserInterviewTopicsRetrieveParams()
    return UserInterviewTopicsRetrieveParams.omit({ project_id: true })
}

const userInterviewTopicsRetrieve = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsRetrieveSchema>,
    Schemas.UserInterviewTopic
> => ({
    name: 'user-interview-topics-retrieve',
    schema: UserInterviewTopicsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UserInterviewTopic>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const UserInterviewTopicsSendInvitesSchema = () => {
    const UserInterviewTopicsSendInvitesCreateBody = orvalSchemas.UserInterviewTopicsSendInvitesCreateBody()
    const UserInterviewTopicsSendInvitesCreateParams = orvalSchemas.UserInterviewTopicsSendInvitesCreateParams()
    return UserInterviewTopicsSendInvitesCreateParams.omit({ project_id: true }).extend(
        UserInterviewTopicsSendInvitesCreateBody.shape
    )
}

const userInterviewTopicsSendInvites = (): ToolBase<
    ReturnType<typeof UserInterviewTopicsSendInvitesSchema>,
    Schemas.PaginatedInterviewInviteResultList
> => ({
    name: 'user-interview-topics-send-invites',
    schema: UserInterviewTopicsSendInvitesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewTopicsSendInvitesSchema>>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interview_topics/${encodeURIComponent(String(params.id))}/send_invites/`,
            body,
        })
        return result
    },
})

const UserInterviewsListSchema = () => {
    const UserInterviewsListQueryParams = orvalSchemas.UserInterviewsListQueryParams()
    return UserInterviewsListQueryParams
}

const userInterviewsList = (): ToolBase<
    ReturnType<typeof UserInterviewsListSchema>,
    WithPostHogUrl<Schemas.PaginatedUserInterviewList>
> => ({
    name: 'user-interviews-list',
    schema: UserInterviewsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedUserInterviewList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interviews/`,
            query: {
                classifications: params.classifications,
                limit: params.limit,
                offset: params.offset,
                topic: params.topic,
            },
        })
        return await withPostHogUrl(context, result, '/user_interviews')
    },
})

const UserInterviewsPartialUpdateSchema = () => {
    const UserInterviewsPartialUpdateBody = orvalSchemas.UserInterviewsPartialUpdateBody()
    const UserInterviewsPartialUpdateParams = orvalSchemas.UserInterviewsPartialUpdateParams()
    return UserInterviewsPartialUpdateParams.omit({ project_id: true }).extend(
        UserInterviewsPartialUpdateBody.omit({ interviewee_emails: true, summary: true, audio: true }).shape
    )
}

const userInterviewsPartialUpdate = (): ToolBase<
    ReturnType<typeof UserInterviewsPartialUpdateSchema>,
    Schemas.UserInterview
> => ({
    name: 'user-interviews-partial-update',
    schema: UserInterviewsPartialUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewsPartialUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.classifications !== undefined) {
            body['classifications'] = params.classifications
        }
        const result = await context.api.request<Schemas.UserInterview>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interviews/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const UserInterviewsRetrieveSchema = () => {
    const UserInterviewsRetrieveParams = orvalSchemas.UserInterviewsRetrieveParams()
    return UserInterviewsRetrieveParams.omit({ project_id: true })
}

const userInterviewsRetrieve = (): ToolBase<
    ReturnType<typeof UserInterviewsRetrieveSchema>,
    Schemas.UserInterview
> => ({
    name: 'user-interviews-retrieve',
    schema: UserInterviewsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UserInterview>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interviews/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const UserInterviewsSearchSchema = () => {
    const UserInterviewsSearchCreateBody = orvalSchemas.UserInterviewsSearchCreateBody()
    return UserInterviewsSearchCreateBody
}

const userInterviewsSearch = (): ToolBase<
    ReturnType<typeof UserInterviewsSearchSchema>,
    Schemas.UserInterviewSearchResult[]
> => ({
    name: 'user-interviews-search',
    schema: UserInterviewsSearchSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof UserInterviewsSearchSchema>>) => {
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
        if (params.classifications !== undefined) {
            body['classifications'] = params.classifications
        }
        if (params.limit !== undefined) {
            body['limit'] = params.limit
        }
        const result = await context.api.request<Schemas.UserInterviewSearchResult[]>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/user_interviews/search/`,
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
    'user-interview-topics-preview-invite': userInterviewTopicsPreviewInvite,
    'user-interview-topics-remove-interviewee': userInterviewTopicsRemoveInterviewee,
    'user-interview-topics-retrieve': userInterviewTopicsRetrieve,
    'user-interview-topics-send-invites': userInterviewTopicsSendInvites,
    'user-interviews-list': userInterviewsList,
    'user-interviews-partial-update': userInterviewsPartialUpdate,
    'user-interviews-retrieve': userInterviewsRetrieve,
    'user-interviews-search': userInterviewsSearch,
}
