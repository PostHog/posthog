// AUTO-GENERATED from products/notifications/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/notifications/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const NotificationsListSchema = () => {
    const NotificationsListQueryParams = orvalSchemas.NotificationsListQueryParams()
    return NotificationsListQueryParams.extend({
        read: NotificationsListQueryParams.shape['read'].default(false).optional(),
    })
}

const notificationsList = (): ToolBase<
    ReturnType<typeof NotificationsListSchema>,
    WithPostHogUrl<Schemas.PaginatedNotificationEventList>
> => ({
    name: 'notifications-list',
    schema: NotificationsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof NotificationsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedNotificationEventList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notifications/`,
            query: {
                archived: params.archived,
                created_after: params.created_after,
                created_before: params.created_before,
                limit: params.limit,
                notification_type: params.notification_type,
                offset: params.offset,
                read: params.read,
                resource_id: params.resource_id,
                resource_type: params.resource_type,
                target_id: params.target_id,
                target_type: params.target_type,
            },
        })
        return await withPostHogUrl(context, result, '/')
    },
})

const NotificationsMarkReadSchema = () => {
    const NotificationsMarkReadBulkCreateBody = orvalSchemas.NotificationsMarkReadBulkCreateBody()
    return NotificationsMarkReadBulkCreateBody
}

const notificationsMarkRead = (): ToolBase<ReturnType<typeof NotificationsMarkReadSchema>, unknown> => ({
    name: 'notifications-mark-read',
    schema: NotificationsMarkReadSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof NotificationsMarkReadSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.notification_ids !== undefined) {
            body['notification_ids'] = params.notification_ids
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/notifications/mark_read_bulk/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'notifications-list': notificationsList,
    'notifications-mark-read': notificationsMarkRead,
}
