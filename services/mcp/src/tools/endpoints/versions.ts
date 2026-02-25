import type { z } from 'zod'

import { EndpointVersionsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EndpointVersionsSchema

type Params = z.infer<typeof schema>

export const versionsHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.endpoints({ projectId }).versions({
        name: params.name,
        params: {
            limit: params.data?.limit,
            offset: params.data?.offset,
        },
    })

    if (!result.success) {
        throw new Error(`Failed to get endpoint versions: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'endpoint-versions',
    schema,
    handler: versionsHandler,
})

export default tool
