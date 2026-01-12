import type { z } from 'zod'

import { ActionGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.actions({ projectId }).list({ params: params.data })

    if (!result.success) {
        throw new Error(`Failed to get actions: ${result.error.message}`)
    }

    return {
        actions: result.data.map((action) => ({
            ...action,
            url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${action.id}`,
        })),
        count: result.data.length,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'actions-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
