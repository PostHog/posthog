import type { z } from 'zod'

import type { Experiment } from '@/schema/experiments'
import { ExperimentGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentGetSchema

type Params = z.infer<typeof schema>
type Result = Experiment

export const getHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    { experimentId }: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.experiments({ projectId }).get({
        experimentId: experimentId,
    })

    if (!result.success) {
        throw new Error(`Failed to get experiment: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'experiment-get',
    schema,
    handler: getHandler,
})

export default tool
