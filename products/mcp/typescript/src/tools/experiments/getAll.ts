import { ExperimentGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ExperimentGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler = async (context: Context, _params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const results = await context.api.experiments({ projectId }).list()

    if (!results.success) {
        throw new Error(`Failed to get experiments: ${results.error.message}`)
    }

    return { content: [{ type: 'text', text: JSON.stringify(results.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
