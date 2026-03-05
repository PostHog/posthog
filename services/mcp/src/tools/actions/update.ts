import type { z } from 'zod'

import { ACTION_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { ActionUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.actions({ projectId }).update({
        actionId: params.actionId,
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to update action: ${result.error.message}`)
    }

    return {
        ...result.data,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${result.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'action-update',
    schema,
    handler: updateHandler,
    _meta: {
        ui: {
            resourceUri: ACTION_RESOURCE_URI,
        },
    },
})

export default tool
