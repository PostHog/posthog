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
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.request !== undefined) {
            body['request'] = params.request
        }
        if (params.details !== undefined) {
            body['details'] = params.details
        }
        if (params.already_checked !== undefined) {
            body['already_checked'] = params.already_checked
        }
        if (params.error !== undefined) {
            body['error'] = params.error
        }
        if (params.filing_reason !== undefined) {
            body['filing_reason'] = params.filing_reason
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

const PosthogSupportDraftSendSchema = () => {
    const PosthogSupportDraftsSendCreateParams = orvalSchemas.PosthogSupportDraftsSendCreateParams()
    return PosthogSupportDraftsSendCreateParams.omit({ project_id: true })
}

const posthogSupportDraftSend = (): ToolBase<
    ReturnType<typeof PosthogSupportDraftSendSchema>,
    Schemas.PostHogSupportSentTicket
> => ({
    name: 'posthog-support-draft-send',
    schema: PosthogSupportDraftSendSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof PosthogSupportDraftSendSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PostHogSupportSentTicket>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/posthog_support/drafts/${encodeURIComponent(String(params.draft_id))}/send/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'posthog-support-draft-create': posthogSupportDraftCreate,
    'posthog-support-draft-send': posthogSupportDraftSend,
}
