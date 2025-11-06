import { ExperimentCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ExperimentCreateSchema

type Params = z.infer<typeof schema>

/**
 * Create a comprehensive A/B test experiment with guided setup
 * This tool helps users create well-configured experiments through conversation
 */
export const createExperimentHandler = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.experiments({ projectId }).create(params)

    if (!result.success) {
        throw new Error(`Failed to create experiment: ${result.error.message}`)
    }

    const experiment = result.data
    const experimentWithUrl = {
        ...experiment,
        url: `${context.api.getProjectBaseUrl(projectId)}/experiments/${experiment.id}`,
    }

    return {
        content: [
            {
                type: 'text',
                text: JSON.stringify(experimentWithUrl, null, 2),
            },
        ],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-create',
    schema,
    handler: createExperimentHandler,
})

export default tool
