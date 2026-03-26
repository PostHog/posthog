import type { z } from 'zod'

import { EXPERIMENT_RESOURCE_URI } from '@/resources/ui-apps-constants'
import type { Experiment } from '@/schema/experiments'
import { ExperimentGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentGetSchema

type Params = z.infer<typeof schema>
type Result = Experiment & { __posthogUrl: string }

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

    return {
        ...result.data,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/experiments/${result.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'experiment-get',
    schema,
    handler: getHandler,
    _meta: {
        ui: {
            resourceUri: EXPERIMENT_RESOURCE_URI,
        },
    },
})

export default tool
