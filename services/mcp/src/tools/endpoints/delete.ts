import type { z } from 'zod'

import { EndpointDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EndpointDeleteSchema

type Params = z.infer<typeof schema>

export const deleteHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.endpoints({ projectId }).delete({
        name: params.name,
    })

    if (!result.success) {
        throw new Error(`Failed to delete endpoint: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'endpoint-delete',
    schema,
    handler: deleteHandler,
})

export default tool
