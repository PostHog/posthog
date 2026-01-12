import type { z } from 'zod'

import { ActionGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()
    const actionsResult = await context.api.actions({ projectId }).list({ params: data ?? {} })
    if (!actionsResult.success) {
        throw new Error(`Failed to get actions: ${actionsResult.error.message}`)
    }

    return actionsResult.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'actions-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
