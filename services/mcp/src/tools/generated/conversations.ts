// AUTO-GENERATED from products/conversations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/conversations/api'
import {
    withPostHogUrl,
    withAgentNote,
    pickResponseFields,
    type WithPostHogUrl,
    type WithAgentNote,
} from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ConversationsTicketsListSchema = () => {
    const ConversationsTicketsListQueryParams = orvalSchemas.ConversationsTicketsListQueryParams()
    return ConversationsTicketsListQueryParams
}

const conversationsTicketsList = (): ToolBase<
    ReturnType<typeof ConversationsTicketsListSchema>,
    WithPostHogUrl<Schemas.PaginatedTicketList>
> => ({
    name: 'conversations-tickets-list',
    schema: ConversationsTicketsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsTicketsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTicketList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/`,
            query: {
                ai_triage_result: params.ai_triage_result,
                assignee: params.assignee,
                channel_detail: params.channel_detail,
                channel_source: params.channel_source,
                date_from: params.date_from,
                date_to: params.date_to,
                distinct_ids: params.distinct_ids,
                emails: params.emails,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                priority: params.priority,
                search: params.search,
                sla: params.sla,
                snoozed: params.snoozed,
                status: params.status,
                tags: params.tags,
                tags_all: params.tags_all,
                tags_exclude: params.tags_exclude,
                view: params.view,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'ticket_number',
                    'status',
                    'priority',
                    'channel_source',
                    'assignee',
                    'last_message_text',
                    'message_count',
                    'unread_team_count',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/support/tickets')
    },
})

const ConversationsTicketsMessagesRetrieveSchema = () => {
    const ConversationsTicketsMessagesListParams = orvalSchemas.ConversationsTicketsMessagesListParams()
    const ConversationsTicketsMessagesListQueryParams = orvalSchemas.ConversationsTicketsMessagesListQueryParams()
    return ConversationsTicketsMessagesListParams.omit({ project_id: true }).extend(
        ConversationsTicketsMessagesListQueryParams.shape
    )
}

const conversationsTicketsMessagesRetrieve = (): ToolBase<
    ReturnType<typeof ConversationsTicketsMessagesRetrieveSchema>,
    Schemas.PaginatedTicketMessageList
> => ({
    name: 'conversations-tickets-messages-retrieve',
    schema: ConversationsTicketsMessagesRetrieveSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ConversationsTicketsMessagesRetrieveSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTicketMessageList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/${encodeURIComponent(String(params.id))}/messages/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const ConversationsTicketsNotesDestroySchema = () => {
    const ConversationsTicketsNotesDestroyParams = orvalSchemas.ConversationsTicketsNotesDestroyParams()
    return ConversationsTicketsNotesDestroyParams.omit({ project_id: true })
}

const conversationsTicketsNotesDestroy = (): ToolBase<
    ReturnType<typeof ConversationsTicketsNotesDestroySchema>,
    unknown
> => ({
    name: 'conversations-tickets-notes-destroy',
    schema: ConversationsTicketsNotesDestroySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsTicketsNotesDestroySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/${encodeURIComponent(String(params.id))}/notes/${encodeURIComponent(String(params.message_id))}/`,
        })
        return result
    },
})

const ConversationsTicketsNotesPartialUpdateSchema = () => {
    const ConversationsTicketsNotesPartialUpdateBody = orvalSchemas.ConversationsTicketsNotesPartialUpdateBody()
    const ConversationsTicketsNotesPartialUpdateParams = orvalSchemas.ConversationsTicketsNotesPartialUpdateParams()
    return ConversationsTicketsNotesPartialUpdateParams.omit({ project_id: true }).extend(
        ConversationsTicketsNotesPartialUpdateBody.shape
    )
}

const conversationsTicketsNotesPartialUpdate = (): ToolBase<
    ReturnType<typeof ConversationsTicketsNotesPartialUpdateSchema>,
    Schemas.TicketMessage
> => ({
    name: 'conversations-tickets-notes-partial-update',
    schema: ConversationsTicketsNotesPartialUpdateSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof ConversationsTicketsNotesPartialUpdateSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.message !== undefined) {
            body['message'] = params.message
        }
        if (params.rich_content !== undefined) {
            body['rich_content'] = params.rich_content
        }
        const result = await context.api.request<Schemas.TicketMessage>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/${encodeURIComponent(String(params.id))}/notes/${encodeURIComponent(String(params.message_id))}/`,
            body,
        })
        return result
    },
})

const ConversationsTicketsReplyCreateSchema = () => {
    const ConversationsTicketsReplyCreateBody = orvalSchemas.ConversationsTicketsReplyCreateBody()
    const ConversationsTicketsReplyCreateParams = orvalSchemas.ConversationsTicketsReplyCreateParams()
    return ConversationsTicketsReplyCreateParams.omit({ project_id: true }).extend(
        ConversationsTicketsReplyCreateBody.shape
    )
}

const conversationsTicketsReplyCreate = (): ToolBase<
    ReturnType<typeof ConversationsTicketsReplyCreateSchema>,
    Schemas.TicketMessage
> => ({
    name: 'conversations-tickets-reply-create',
    schema: ConversationsTicketsReplyCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsTicketsReplyCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.message !== undefined) {
            body['message'] = params.message
        }
        if (params.is_private !== undefined) {
            body['is_private'] = params.is_private
        }
        if (params.rich_content !== undefined) {
            body['rich_content'] = params.rich_content
        }
        const result = await context.api.request<Schemas.TicketMessage>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/${encodeURIComponent(String(params.id))}/reply/`,
            body,
        })
        return result
    },
})

const ConversationsTicketsRetrieveSchema = () => {
    const ConversationsTicketsRetrieveParams = orvalSchemas.ConversationsTicketsRetrieveParams()
    return ConversationsTicketsRetrieveParams.omit({ project_id: true })
}

const conversationsTicketsRetrieve = (): ToolBase<
    ReturnType<typeof ConversationsTicketsRetrieveSchema>,
    WithAgentNote<WithPostHogUrl<Schemas.Ticket>>
> => ({
    name: 'conversations-tickets-retrieve',
    schema: ConversationsTicketsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsTicketsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Ticket>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'ticket_number',
            'status',
            'priority',
            'channel_source',
            'channel_detail',
            'assignee',
            'last_message_text',
            'message_count',
            'unread_team_count',
            'tags',
            'sla_due_at',
            'anonymous_traits',
            'session_context',
            'session_id',
            'person',
            'email_from',
            'email_to',
            'email_subject',
            'distinct_id',
            'created_at',
            'updated_at',
        ]) as typeof result
        return withAgentNote(
            await withPostHogUrl(context, filtered, `/support/tickets/${filtered.id}`),
            "The PostHog Assistant may have investigated this ticket and written self-driving reports into the Inbox. To surface them, call inbox-reports-list with source_id set to this ticket's `id` and source_product=conversations (add include_all_statuses=true to include dismissed ones). Those reports hold the investigation and findings; the ticket's own messages do not."
        )
    },
})

const ConversationsTicketsUpdateSchema = () => {
    const ConversationsTicketsPartialUpdateBody = orvalSchemas.ConversationsTicketsPartialUpdateBody()
    const ConversationsTicketsPartialUpdateParams = orvalSchemas.ConversationsTicketsPartialUpdateParams()
    return ConversationsTicketsPartialUpdateParams.omit({ project_id: true }).extend(
        ConversationsTicketsPartialUpdateBody.shape
    )
}

const conversationsTicketsUpdate = (): ToolBase<
    ReturnType<typeof ConversationsTicketsUpdateSchema>,
    WithPostHogUrl<Schemas.Ticket>
> => ({
    name: 'conversations-tickets-update',
    schema: ConversationsTicketsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsTicketsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.priority !== undefined) {
            body['priority'] = params.priority
        }
        if (params.assignee !== undefined) {
            body['assignee'] = params.assignee
        }
        if (params.sla_due_at !== undefined) {
            body['sla_due_at'] = params.sla_due_at
        }
        if (params.snoozed_until !== undefined) {
            body['snoozed_until'] = params.snoozed_until
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.Ticket>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/support/tickets/${result.id}`)
    },
})

const ConversationsViewsCreateSchema = () => {
    const ConversationsViewsCreateBody = orvalSchemas.ConversationsViewsCreateBody()
    return ConversationsViewsCreateBody
}

const conversationsViewsCreate = (): ToolBase<
    ReturnType<typeof ConversationsViewsCreateSchema>,
    WithPostHogUrl<Schemas.TicketView>
> => ({
    name: 'conversations-views-create',
    schema: ConversationsViewsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsViewsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.is_favorited !== undefined) {
            body['is_favorited'] = params.is_favorited
        }
        const result = await context.api.request<Schemas.TicketView>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/views/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'short_id',
            'name',
            'filters',
            'is_favorited',
            'created_at',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/support/tickets?view=${filtered.short_id}`)
    },
})

const ConversationsViewsListSchema = () => {
    const ConversationsViewsListQueryParams = orvalSchemas.ConversationsViewsListQueryParams()
    return ConversationsViewsListQueryParams
}

const conversationsViewsList = (): ToolBase<
    ReturnType<typeof ConversationsViewsListSchema>,
    WithPostHogUrl<Schemas.PaginatedTicketViewList>
> => ({
    name: 'conversations-views-list',
    schema: ConversationsViewsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsViewsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTicketViewList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/views/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) => pickResponseFields(item, ['short_id', 'name'])),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/support/tickets')
    },
})

const ConversationsViewsRetrieveSchema = () => {
    const ConversationsViewsRetrieveParams = orvalSchemas.ConversationsViewsRetrieveParams()
    return ConversationsViewsRetrieveParams.omit({ project_id: true }).extend({
        short_id: ConversationsViewsRetrieveParams.shape['short_id'].describe(
            'Short identifier of the view, as returned by conversations-views-list.'
        ),
    })
}

const conversationsViewsRetrieve = (): ToolBase<
    ReturnType<typeof ConversationsViewsRetrieveSchema>,
    WithPostHogUrl<Schemas.TicketView>
> => ({
    name: 'conversations-views-retrieve',
    schema: ConversationsViewsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsViewsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TicketView>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/views/${encodeURIComponent(String(params.short_id))}/`,
        })
        const filtered = pickResponseFields(result, [
            'short_id',
            'name',
            'filters',
            'is_favorited',
            'created_at',
            'created_by',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/support/tickets?view=${filtered.short_id}`)
    },
})

const ConversationsViewsUpdateSchema = () => {
    const ConversationsViewsPartialUpdateBody = orvalSchemas.ConversationsViewsPartialUpdateBody()
    const ConversationsViewsPartialUpdateParams = orvalSchemas.ConversationsViewsPartialUpdateParams()
    return ConversationsViewsPartialUpdateParams.omit({ project_id: true })
        .extend(ConversationsViewsPartialUpdateBody.shape)
        .extend({
            short_id: ConversationsViewsPartialUpdateParams.shape['short_id'].describe(
                'Short identifier of the view, as returned by conversations-views-list.'
            ),
        })
}

const conversationsViewsUpdate = (): ToolBase<
    ReturnType<typeof ConversationsViewsUpdateSchema>,
    WithPostHogUrl<Schemas.TicketView>
> => ({
    name: 'conversations-views-update',
    schema: ConversationsViewsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ConversationsViewsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.is_favorited !== undefined) {
            body['is_favorited'] = params.is_favorited
        }
        const result = await context.api.request<Schemas.TicketView>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/views/${encodeURIComponent(String(params.short_id))}/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'short_id',
            'name',
            'filters',
            'is_favorited',
            'created_at',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/support/tickets?view=${filtered.short_id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'conversations-tickets-list': conversationsTicketsList,
    'conversations-tickets-messages-retrieve': conversationsTicketsMessagesRetrieve,
    'conversations-tickets-notes-destroy': conversationsTicketsNotesDestroy,
    'conversations-tickets-notes-partial-update': conversationsTicketsNotesPartialUpdate,
    'conversations-tickets-reply-create': conversationsTicketsReplyCreate,
    'conversations-tickets-retrieve': conversationsTicketsRetrieve,
    'conversations-tickets-update': conversationsTicketsUpdate,
    'conversations-views-create': conversationsViewsCreate,
    'conversations-views-list': conversationsViewsList,
    'conversations-views-retrieve': conversationsViewsRetrieve,
    'conversations-views-update': conversationsViewsUpdate,
}
