// AUTO-GENERATED from products/notifications/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { NotificationsListQueryParams, NotificationsRetrieveParams } from '@/generated/notifications/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const NotificationsGetSchema = NotificationsRetrieveParams.omit({ project_id: true })

const notificationsGet = (): ToolBase<typeof NotificationsGetSchema, Schemas.NotificationEvent> => ({
    name: 'notifications-get',
    schema: NotificationsGetSchema,
    handler: async (context: Context, params: z.infer<typeof NotificationsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.NotificationEvent>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/notifications/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'notifications-get': notificationsGet,
    'notifications-list': notificationsList,
}
