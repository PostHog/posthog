import type { z } from 'zod'

import { EndpointGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EndpointGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.endpoints({ projectId }).list({
        params: {
            is_active: params.data?.is_active,
            limit: params.data?.limit,
            offset: params.data?.offset,
        },
    })

    if (!result.success) {
        throw new Error(`Failed to list endpoints: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'endpoints-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
