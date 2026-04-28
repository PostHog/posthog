// AUTO-GENERATED from products/conversations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ConversationsTicketsListQueryParams,
    ConversationsTicketsPartialUpdateBody,
    ConversationsTicketsPartialUpdateParams,
    ConversationsTicketsRetrieveParams,
} from '@/generated/conversations/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/conversations/tickets/`,
            query: {
                assignee: params.assignee,
                channel_detail: params.channel_detail,
                channel_source: params.channel_source,
                date_from: params.date_from,
                date_to: params.date_to,
                distinct_ids: params.distinct_ids,
                limit: params.limit,
                offset: params.offset,
                order_by: params.order_by,
                priority: params.priority,
                search: params.search,
                sla: params.sla,
                status: params.status,
                tags: params.tags,
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
        return await withPostHogUrl(context, filtered, `/conversations/tickets/${filtered.id}`)
    },
})

const ConversationsTicketsUpdateSchema = ConversationsTicketsPartialUpdateParams.omit({ project_id: true }).extend(
    ConversationsTicketsPartialUpdateBody.shape
)

const conversationsTicketsUpdate = (): ToolBase<
    typeof ConversationsTicketsUpdateSchema,
    WithPostHogUrl<Schemas.Ticket>
> => ({
    name: 'conversations-tickets-update',
    schema: ConversationsTicketsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsTicketsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.priority !== undefined) {
            body['priority'] = params.priority
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
        return await withPostHogUrl(context, result, `/conversations/tickets/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'conversations-tickets-list': conversationsTicketsList,
    'conversations-tickets-retrieve': conversationsTicketsRetrieve,
    'conversations-tickets-update': conversationsTicketsUpdate,
}
