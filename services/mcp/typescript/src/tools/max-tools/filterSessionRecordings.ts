import type { z } from 'zod'

import { MaxFilterSessionRecordingsToolArgsSchema } from '@/schema/max-tools'
import type { Context, ToolBase } from '@/tools/types'

const schema = MaxFilterSessionRecordingsToolArgsSchema

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.maxTools({ projectId }).invoke({
        toolName: 'filter_session_recordings',
        args: params,
    })
    if (!result.success) {
        throw new Error(`phai-filter-session-recordings failed: ${result.error.message}`)
    }
    return { content: result.data.content, artifact: result.data.artifact }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'phai-filter-session-recordings',
    schema,
    handler,
})

export default tool
