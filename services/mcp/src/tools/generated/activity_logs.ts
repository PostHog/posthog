// AUTO-GENERATED from services/mcp/definitions/activity_logs.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ActivityLogListQueryParams } from '@/generated/activity_logs/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ActivityLogsListSchema = ActivityLogListQueryParams

const activityLogsList = (): ToolBase<
    typeof ActivityLogsListSchema,
    Schemas.PaginatedActivityLogList & { _posthogUrl: string }
> => ({
    name: 'activity-logs-list',
    schema: ActivityLogsListSchema,
    handler: async (context: Context, params: z.infer<typeof ActivityLogsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedActivityLogList>({
            method: 'GET',
            path: `/api/projects/${projectId}/activity_log/`,
            query: {
                item_id: params.item_id,
                page: params.page,
                page_size: params.page_size,
                scope: params.scope,
                scopes: params.scopes,
                user: params.user,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/activity`,
        }
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'activity-logs-list': activityLogsList,
}
