import type { z } from 'zod'

import { ACTION_LIST_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { ActionGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.actions({ projectId }).list({
        params: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to get actions: ${result.error.message}`)
    }

    const actionsWithUrls = result.data.map((action: { id: number; [key: string]: unknown }) => ({
        ...action,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${action.id}`,
    }))

    return {
        results: actionsWithUrls,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'actions-get-all',
    schema,
    handler: getAllHandler,
    _meta: {
        ui: {
            resourceUri: ACTION_LIST_RESOURCE_URI,
        },
    },
})

export default tool
