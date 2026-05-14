// AUTO-GENERATED from products/notifications/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { NotificationsListQueryParams, NotificationsSendConciergeCreateBody } from '@/generated/notifications/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const NotificationsListSchema = NotificationsListQueryParams

const notificationsList = (): ToolBase<
    typeof NotificationsListSchema,
    WithPostHogUrl<Schemas.PaginatedNotificationEventList>
> => ({
    name: 'notifications-list',
    schema: NotificationsListSchema,
    handler: async (context: Context, params: z.infer<typeof NotificationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedNotificationEventList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/notifications/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/notifications')
    },
})

const NotificationsSendConciergeSchema = NotificationsSendConciergeCreateBody

const notificationsSendConcierge = (): ToolBase<
    typeof NotificationsSendConciergeSchema,
    Schemas.SendConciergeNotificationResponse
> => ({
    name: 'notifications-send-concierge',
    schema: NotificationsSendConciergeSchema,
    handler: async (context: Context, params: z.infer<typeof NotificationsSendConciergeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.target_user_ids !== undefined) {
            body['target_user_ids'] = params.target_user_ids
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.priority !== undefined) {
            body['priority'] = params.priority
        }
        if (params.notification_style !== undefined) {
            body['notification_style'] = params.notification_style
        }
        if (params.skill !== undefined) {
            body['skill'] = params.skill
        }
        if (params.long_form_wizard_text !== undefined) {
            body['long_form_wizard_text'] = params.long_form_wizard_text
        }
        const result = await context.api.request<Schemas.SendConciergeNotificationResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/notifications/send_concierge/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'notifications-list': notificationsList,
    'notifications-send-concierge': notificationsSendConcierge,
}
