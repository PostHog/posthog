import type { z } from 'zod'

import { EndpointRunSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EndpointRunSchema

type Params = z.infer<typeof schema>

export const runHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.endpoints({ projectId }).run({
        name: params.name,
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to run endpoint: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'endpoint-run',
    schema,
    handler: runHandler,
})

export default tool
