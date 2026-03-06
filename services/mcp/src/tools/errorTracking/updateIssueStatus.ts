import type { z } from 'zod'

import { ErrorTrackingUpdateIssueStatusSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ErrorTrackingUpdateIssueStatusSchema

type Params = z.infer<typeof schema>

export const updateIssueStatusHandler: ToolBase<typeof schema>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { issueId, status } = params
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.request({
        method: 'PATCH',
        path: `/api/environments/${projectId}/error_tracking/issues/${issueId}/`,
        body: { status },
    })

    return result
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'update-issue-status',
    schema,
    handler: updateIssueStatusHandler,
})

export default tool
