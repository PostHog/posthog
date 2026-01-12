import type { z } from 'zod'

import { ActionDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionDeleteSchema

type Params = z.infer<typeof schema>

export const deleteHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { actionId } = params
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.actions({ projectId }).delete({ actionId })
    if (!result.success) {
        throw new Error(`Failed to delete action: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'action-delete',
    schema,
    handler: deleteHandler,
})

export default tool
