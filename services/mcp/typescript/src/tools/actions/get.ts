import type { z } from 'zod'

import { ActionGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionGetSchema

type Params = z.infer<typeof schema>

export const getHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { actionId } = params
    const projectId = await context.stateManager.getProjectId()
    const actionResult = await context.api.actions({ projectId }).get({ actionId })
    if (!actionResult.success) {
        throw new Error(`Failed to get action: ${actionResult.error.message}`)
    }

    return {
        ...actionResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${actionResult.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'action-get',
    schema,
    handler: getHandler,
})

export default tool
