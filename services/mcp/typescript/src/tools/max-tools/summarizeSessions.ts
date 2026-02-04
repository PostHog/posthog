import type { z } from 'zod'

import { MaxSummarizeSessionsToolArgsSchema } from '@/schema/max-tools'
import type { Context, ToolBase } from '@/tools/types'

const schema = MaxSummarizeSessionsToolArgsSchema

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.maxTools({ projectId }).invoke({
        toolName: 'summarize_sessions',
        args: params,
    })
    if (!result.success) {
        throw new Error(`phai-summarize-sessions failed: ${result.error.message}`)
    }
    return { content: result.data.content, artifact: result.data.artifact }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'phai-summarize-sessions',
    schema,
    handler,
})

export default tool
