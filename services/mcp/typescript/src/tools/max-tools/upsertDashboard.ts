import type { z } from 'zod'

import { MaxUpsertDashboardToolArgsSchema } from '@/schema/max-tools'
import type { Context, ToolBase } from '@/tools/types'

const schema = MaxUpsertDashboardToolArgsSchema

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.maxTools({ projectId }).invoke({
        toolName: 'upsert_dashboard',
        args: params,
    })
    if (!result.success) {
        throw new Error(`phai-upsert-dashboard failed: ${result.error.message}`)
    }
    return { content: result.data.content, artifact: result.data.artifact }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'phai-upsert-dashboard',
    schema,
    handler,
})

export default tool
