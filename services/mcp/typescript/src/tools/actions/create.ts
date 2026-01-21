import type { z } from 'zod'

import { ActionCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ActionCreateSchema

type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.actions({ projectId }).create({
        data: params,
    })

    if (!result.success) {
        throw new Error(`Failed to create action: ${result.error.message}`)
    }

    return {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/actions/${result.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'action-create',
    schema,
    handler: createHandler,
})

export default tool
