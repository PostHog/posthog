import type { z } from 'zod'

import { EndpointGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EndpointGetSchema

type Params = z.infer<typeof schema>

export const getHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.endpoints({ projectId }).get({
        name: params.name,
        version: params.version,
    })

    if (!result.success) {
        throw new Error(`Failed to get endpoint: ${result.error.message}`)
    }

    const endpointWithUrl = {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/pipeline/endpoints/${result.data.name}`,
    }

    return endpointWithUrl
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'endpoint-get',
    schema,
    handler: getHandler,
})

export default tool
