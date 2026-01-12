import type { z } from 'zod'

import { ActionDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionDeleteSchema

type Params = z.infer<typeof schema>

export const deleteHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { actionId } = params
    const projectId = await context.stateManager.getProjectId()
    
    console.info(`[MCP] Deleting action ${actionId} in project ${projectId}`)
    
    const result = await context.api.actions({ projectId }).delete({ actionId })
    if (!result.success) {
        console.error(`[MCP] Failed to delete action ${actionId}: ${result.error.message}`)
        throw new Error(`Failed to delete action: ${result.error.message}`)
    }

    console.info(`[MCP] Successfully deleted action ${actionId} in project ${projectId}`)
    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'action-delete',
    schema,
    handler: deleteHandler,
})

export default tool
