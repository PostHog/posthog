// AUTO-GENERATED from products/conversations/mcp/posthog_support.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/posthog_support/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PosthogSupportTicketCreateSchema = () => {
    const PosthogSupportTicketsCreateBody = orvalSchemas.PosthogSupportTicketsCreateBody()
    return PosthogSupportTicketsCreateBody
}

const posthogSupportTicketCreate = (): ToolBase<
    ReturnType<typeof PosthogSupportTicketCreateSchema>,
    Schemas.PostHogSupportTicketCreated
> => ({
    name: 'posthog-support-ticket-create',
    schema: PosthogSupportTicketCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportTicketCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_type !== undefined) {
            body['request_type'] = params.request_type
        }
        if (params.subject !== undefined) {
            body['subject'] = params.subject
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.expected !== undefined) {
            body['expected'] = params.expected
        }
        if (params.actual !== undefined) {
            body['actual'] = params.actual
        }
        if (params.already_tried !== undefined) {
            body['already_tried'] = params.already_tried
        }
        if (params.deletion_query !== undefined) {
            body['deletion_query'] = params.deletion_query
        }
        if (params.expected_event_count !== undefined) {
            body['expected_event_count'] = params.expected_event_count
        }
        if (params.deletion_consent !== undefined) {
            body['deletion_consent'] = params.deletion_consent
        }
        const result = await context.api.request<Schemas.PostHogSupportTicketCreated>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_support/tickets/`,
            body,
        })
        return result
    },
})

const PosthogSupportTicketsListSchema = () => {
    const PosthogSupportTicketsListQueryParams = orvalSchemas.PosthogSupportTicketsListQueryParams()
    return PosthogSupportTicketsListQueryParams
}

const posthogSupportTicketsList = (): ToolBase<
    ReturnType<typeof PosthogSupportTicketsListSchema>,
    Schemas.PostHogSupportTicketList[]
> => ({
    name: 'posthog-support-tickets-list',
    schema: PosthogSupportTicketsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportTicketsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PostHogSupportTicketList[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_support/tickets/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                status: params.status,
            },
        })
        return result
    },
})

const PosthogSupportTicketGetSchema = () => {
    const PosthogSupportTicketsRetrieveParams = orvalSchemas.PosthogSupportTicketsRetrieveParams()
    return PosthogSupportTicketsRetrieveParams.omit({ project_id: true }).extend({
        id: PosthogSupportTicketsRetrieveParams.shape['id'].describe(
            'Ticket ID from posthog-support-tickets-list or from posthog-support-ticket-create.'
        ),
    })
}

const posthogSupportTicketGet = (): ToolBase<
    ReturnType<typeof PosthogSupportTicketGetSchema>,
    Schemas.PostHogSupportTicketDetail
> => ({
    name: 'posthog-support-ticket-get',
    schema: PosthogSupportTicketGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportTicketGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PostHogSupportTicketDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_support/tickets/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'posthog-support-ticket-create': posthogSupportTicketCreate,
    'posthog-support-tickets-list': posthogSupportTicketsList,
    'posthog-support-ticket-get': posthogSupportTicketGet,
}
