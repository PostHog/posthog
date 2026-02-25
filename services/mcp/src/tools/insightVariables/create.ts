import type { z } from 'zod'

import { InsightVariableCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = InsightVariableCreateSchema

type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.insightVariables({ projectId }).create({
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to create insight variable: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-variable-create',
    schema,
    handler: createHandler,
})

export default tool
