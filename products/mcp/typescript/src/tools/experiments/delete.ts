import type { z } from 'zod'

import { ExperimentDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentDeleteSchema

type Params = z.infer<typeof schema>

export const deleteHandler: ToolBase<typeof schema>['handler'] = async (context: Context, { experimentId }: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const deleteResult = await context.api.experiments({ projectId }).delete({
        experimentId,
    })

    if (!deleteResult.success) {
        throw new Error(`Failed to delete experiment: ${deleteResult.error.message}`)
    }

    return deleteResult.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-delete',
    schema,
    handler: deleteHandler,
})

export default tool
