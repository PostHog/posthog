import type { z } from 'zod'

import { EndpointCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EndpointCreateSchema

type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.endpoints({ projectId }).create({
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to create endpoint: ${result.error.message}`)
    }

    const endpointWithUrl = {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/pipeline/endpoints/${result.data.name}`,
    }

    return endpointWithUrl
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'endpoint-create',
    schema,
    handler: createHandler,
})

export default tool
