// AUTO-GENERATED from products/conversations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ConversationsTicketsListQueryParams,
    ConversationsTicketsPartialUpdateBody,
    ConversationsTicketsPartialUpdateParams,
    ConversationsTicketsRetrieveParams,
} from '@/generated/conversations/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ConversationsTicketsListSchema = ConversationsTicketsListQueryParams

const conversationsTicketsList = (): ToolBase<
    typeof ConversationsTicketsListSchema,
    Schemas.PaginatedTicketList & { _posthogUrl: string }
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
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/conversations`,
        }
    },
})

const ConversationsTicketsRetrieveSchema = ConversationsTicketsRetrieveParams.omit({ project_id: true })

const conversationsTicketsRetrieve = (): ToolBase<typeof ConversationsTicketsRetrieveSchema, Schemas.Ticket> => ({
    name: 'conversations-tickets-retrieve',
    schema: ConversationsTicketsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ConversationsTicketsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Ticket>({
            method: 'GET',
            path: `/api/projects/${projectId}/conversations/tickets/${params.id}/`,
        })
        return result
    },
})

const ConversationsTicketsPartialUpdateSchema = ConversationsTicketsPartialUpdateParams.omit({
    project_id: true,
}).extend(ConversationsTicketsPartialUpdateBody.shape)

const conversationsTicketsPartialUpdate = (): ToolBase<
    typeof ConversationsTicketsPartialUpdateSchema,
    Schemas.Ticket
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
        if (params.anonymous_traits !== undefined) {
            body['anonymous_traits'] = params.anonymous_traits
        }
        if (params.ai_resolved !== undefined) {
            body['ai_resolved'] = params.ai_resolved
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
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'conversations-tickets-list': conversationsTicketsList,
    'conversations-tickets-retrieve': conversationsTicketsRetrieve,
    'conversations-tickets-partial-update': conversationsTicketsPartialUpdate,
}
