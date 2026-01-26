import type { z } from 'zod'

import { MaxSearchErrorTrackingIssuesToolArgsSchema } from '@/schema/max-tools'
import type { Context, ToolBase } from '@/tools/types'

const schema = MaxSearchErrorTrackingIssuesToolArgsSchema

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.maxTools({ projectId }).invoke({
        toolName: 'search_error_tracking_issues',
        args: params,
    })
    if (!result.success) {
        throw new Error(`phai-search-error-tracking-issues failed: ${result.error.message}`)
    }
    return { content: result.data.content, artifact: result.data.artifact }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'phai-search-error-tracking-issues',
    schema,
    handler,
})

export default tool
