// AUTO-GENERATED from products/conversations/mcp/posthog_support.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/posthog_support/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PosthogSupportDraftCreateSchema = () => {
    const PosthogSupportDraftsCreateBody = orvalSchemas.PosthogSupportDraftsCreateBody()
    return PosthogSupportDraftsCreateBody
}

const posthogSupportDraftCreate = (): ToolBase<
    ReturnType<typeof PosthogSupportDraftCreateSchema>,
    Schemas.PostHogSupportDraft
> => ({
    name: 'posthog-support-draft-create',
    schema: PosthogSupportDraftCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportDraftCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.customer_words !== undefined) {
            body['customer_words'] = params.customer_words
        }
        if (params.filing_reason !== undefined) {
            body['filing_reason'] = params.filing_reason
        }
        if (params.details !== undefined) {
            body['details'] = params.details
        }
        if (params.already_tried !== undefined) {
            body['already_tried'] = params.already_tried
        }
        if (params.agent_name !== undefined) {
            body['agent_name'] = params.agent_name
        }
        const result = await context.api.request<Schemas.PostHogSupportDraft>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_support/drafts/`,
            body,
        })
        return result
    },
})

const PosthogSupportDraftDiscardSchema = () => {
    const PosthogSupportDraftsDiscardCreateParams = orvalSchemas.PosthogSupportDraftsDiscardCreateParams()
    return PosthogSupportDraftsDiscardCreateParams.omit({ project_id: true })
}

const posthogSupportDraftDiscard = (): ToolBase<ReturnType<typeof PosthogSupportDraftDiscardSchema>, unknown> => ({
    name: 'posthog-support-draft-discard',
    schema: PosthogSupportDraftDiscardSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportDraftDiscardSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_support/drafts/${encodeURIComponent(String(params.draft_id))}/discard/`,
        })
        return result
    },
})

const PosthogSupportTicketMessagesSchema = () => {
    const PosthogSupportTicketsMessagesRetrieveParams = orvalSchemas.PosthogSupportTicketsMessagesRetrieveParams()
    const PosthogSupportTicketsMessagesRetrieveQueryParams =
        orvalSchemas.PosthogSupportTicketsMessagesRetrieveQueryParams()
    return PosthogSupportTicketsMessagesRetrieveParams.omit({ project_id: true }).extend(
        PosthogSupportTicketsMessagesRetrieveQueryParams.shape
    )
}

const posthogSupportTicketMessages = (): ToolBase<
    ReturnType<typeof PosthogSupportTicketMessagesSchema>,
    Schemas.PostHogSupportThread
> => ({
    name: 'posthog-support-ticket-messages',
    schema: PosthogSupportTicketMessagesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportTicketMessagesSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PostHogSupportThread>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_support/tickets/${encodeURIComponent(String(params.ticket_id))}/messages/`,
            query: {
                after: params.after,
            },
        })
        return result
    },
})

const PosthogSupportTicketsListSchema = () => {
    const PosthogSupportTicketsRetrieveQueryParams = orvalSchemas.PosthogSupportTicketsRetrieveQueryParams()
    return PosthogSupportTicketsRetrieveQueryParams
}

const posthogSupportTicketsList = (): ToolBase<
    ReturnType<typeof PosthogSupportTicketsListSchema>,
    Schemas.PostHogSupportTicketList
> => ({
    name: 'posthog-support-tickets-list',
    schema: PosthogSupportTicketsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportTicketsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PostHogSupportTicketList>({
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'posthog-support-draft-create': posthogSupportDraftCreate,
    'posthog-support-draft-discard': posthogSupportDraftDiscard,
    'posthog-support-ticket-messages': posthogSupportTicketMessages,
    'posthog-support-tickets-list': posthogSupportTicketsList,
}
