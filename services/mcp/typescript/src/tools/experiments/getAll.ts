import type { z } from 'zod'

import { ExperimentGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const results = await context.api.experiments({ projectId }).list({
        params: {
            limit: params.data?.limit,
            offset: params.data?.offset,
        },
    })

    if (!results.success) {
        throw new Error(`Failed to get experiments: ${results.error.message}`)
    }

    return results.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
