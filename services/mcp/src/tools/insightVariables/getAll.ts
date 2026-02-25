import type { z } from 'zod'

import { InsightVariableGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = InsightVariableGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.insightVariables({ projectId }).list({
        params: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to list insight variables: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-variable-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
