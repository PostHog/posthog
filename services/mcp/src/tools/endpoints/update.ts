import type { z } from 'zod'

import { EndpointUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EndpointUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { name, data } = params
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.endpoints({ projectId }).update({
        name,
        data,
    })

    if (!result.success) {
        throw new Error(`Failed to update endpoint: ${result.error.message}`)
    }

    const endpointWithUrl = {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/pipeline/endpoints/${result.data.name}`,
    }

    return endpointWithUrl
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'endpoint-update',
    schema,
    handler: updateHandler,
})

export default tool
