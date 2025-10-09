import { ExperimentGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ExperimentGetSchema

type Params = z.infer<typeof schema>

export const getHandler = async (context: Context, { experimentId }: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.experiments({ projectId }).get({
        experimentId: experimentId,
    })

    if (!result.success) {
        throw new Error(`Failed to get experiment: ${result.error.message}`)
    }

    return { content: [{ type: 'text', text: JSON.stringify(result.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-get',
    schema,
    handler: getHandler,
})

export default tool
