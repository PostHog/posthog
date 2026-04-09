// AUTO-GENERATED from products/conversations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ConversationsTicketsListQueryParams,
    ConversationsTicketsPartialUpdateBody,
    ConversationsTicketsPartialUpdateParams,
    ConversationsTicketsRetrieveParams,
    ConversationsTicketsSuggestReplyCreateParams,
} from '@/generated/conversations/api'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ConversationsTicketsListSchema = ConversationsTicketsListQueryParams

const conversationsTicketsList = (): ToolBase<
    typeof ConversationsTicketsListSchema,
    WithPostHogUrl<Schemas.PaginatedTicketList>
> => ({
    name: 'conversations-tickets-list',
    schema: ConversationsTicketsListSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsTicketsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTicketList>({
            method: 'GET',
            path: `/api/projects/${projectId}/conversations/tickets/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: result.results.map((item: any) =>
                omitResponseFields(item, [
                    'anonymous_traits',
                    'session_context',
                    'person',
                    'slack_channel_id',
                    'slack_thread_ts',
                    'slack_team_id',
                    'email_from',
                    'email_to',
                    'email_subject',
                    'distinct_id',
                    'session_id',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/conversations/tickets')
    },
})

const ConversationsTicketsRetrieveSchema = ConversationsTicketsRetrieveParams.omit({ project_id: true })

const conversationsTicketsRetrieve = (): ToolBase<
    typeof ConversationsTicketsRetrieveSchema,
    WithPostHogUrl<Schemas.Ticket>
> => ({
    name: 'conversations-tickets-retrieve',
    schema: ConversationsTicketsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsTicketsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Ticket>({
            method: 'GET',
            path: `/api/projects/${projectId}/conversations/tickets/${params.id}/`,
        })
        return await withPostHogUrl(context, result, `/conversations/tickets/${result.id}`)
    },
})

const ConversationsTicketsPartialUpdateSchema = ConversationsTicketsPartialUpdateParams.omit({
    project_id: true,
}).extend(ConversationsTicketsPartialUpdateBody.shape)

const conversationsTicketsPartialUpdate = (): ToolBase<
    typeof ConversationsTicketsPartialUpdateSchema,
    WithPostHogUrl<Schemas.Ticket>
> => ({
    name: 'conversations-tickets-partial-update',
    schema: ConversationsTicketsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsTicketsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.priority !== undefined) {
            body['priority'] = params.priority
        }
        if (params.escalation_reason !== undefined) {
            body['escalation_reason'] = params.escalation_reason
        }
        if (params.sla_due_at !== undefined) {
            body['sla_due_at'] = params.sla_due_at
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        const result = await context.api.request<Schemas.Ticket>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/conversations/tickets/${params.id}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/conversations/tickets/${result.id}`)
    },
})

const ConversationsTicketsSuggestReplyCreateSchema = ConversationsTicketsSuggestReplyCreateParams.omit({
    project_id: true,
})

const conversationsTicketsSuggestReplyCreate = (): ToolBase<
    typeof ConversationsTicketsSuggestReplyCreateSchema,
    Schemas.SuggestReplyResponse
> => ({
    name: 'conversations-tickets-suggest-reply-create',
    schema: ConversationsTicketsSuggestReplyCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsTicketsSuggestReplyCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SuggestReplyResponse>({
            method: 'POST',
            path: `/api/projects/${projectId}/conversations/tickets/${params.id}/suggest_reply/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'conversations-tickets-list': conversationsTicketsList,
    'conversations-tickets-retrieve': conversationsTicketsRetrieve,
    'conversations-tickets-partial-update': conversationsTicketsPartialUpdate,
    'conversations-tickets-suggest-reply-create': conversationsTicketsSuggestReplyCreate,
}
