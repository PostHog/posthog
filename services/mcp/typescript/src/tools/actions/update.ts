import type { z } from 'zod'

import { ActionUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { actionId, data } = params
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.actions({ projectId }).update({
        actionId,
        data,
    })

    if (!result.success) {
        throw new Error(`Failed to update action: ${result.error.message}`)
    }

    return {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${result.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'action-update',
    schema,
    handler: updateHandler,
})

export default tool
