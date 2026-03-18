// AUTO-GENERATED from services/mcp/definitions/activity_logs.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ActivityLogsListSchema = z.object({})

const activityLogsList = (): ToolBase<
    typeof ActivityLogsListSchema,
    Schemas.PaginatedActivityLogList & { _posthogUrl: string }
> => ({
    name: 'activity-logs-list',
    schema: ActivityLogsListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof ActivityLogsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedActivityLogList>({
            method: 'GET',
            path: `/api/projects/${projectId}/activity_log/`,
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
