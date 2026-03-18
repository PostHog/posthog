import type { z } from 'zod'

import { EXPERIMENT_RESOURCE_URI } from '@/resources/ui-apps-constants'
import type { Experiment } from '@/schema/experiments'
import { ExperimentCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentCreateSchema

type Params = z.infer<typeof schema>
type Result = Experiment & { __posthogUrl: string }

/**
 * Create a comprehensive A/B test experiment with guided setup
 * This tool helps users create well-configured experiments through conversation
 */
export const createExperimentHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.experiments({ projectId }).create(params)

    if (!result.success) {
        throw new Error(`Failed to create experiment: ${result.error.message}`)
    }

    const experiment = result.data
    return {
        ...experiment,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/experiments/${experiment.id}`,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'experiment-create',
    schema,
    handler: createExperimentHandler,
    _meta: {
        ui: {
            resourceUri: EXPERIMENT_RESOURCE_URI,
        },
    },
})

export default tool
