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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'posthog-support-ticket-create': posthogSupportTicketCreate,
}
