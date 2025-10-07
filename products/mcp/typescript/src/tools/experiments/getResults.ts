import { ExperimentResultsResponseSchema } from '@/schema/experiments'
import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ExperimentResultsGetSchema

type Params = z.infer<typeof schema>

/**
 * Get experiment results including metrics and exposures data
 * This tool fetches the experiment details and executes the necessary queries
 * to get metrics results (both primary and secondary) and exposure data
 */
export const getResultsHandler = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.experiments({ projectId }).getMetricResults({
        experimentId: params.experimentId,
        refresh: params.refresh,
    })

    if (!result.success) {
        throw new Error(`Failed to get experiment results: ${result.error.message}`)
    }

    const { experiment, primaryMetricsResults, secondaryMetricsResults, exposures } = result.data

    // Format the response using the schema
    const parsedExperiment = ExperimentResultsResponseSchema.parse({
        experiment,
        primaryMetricsResults,
        secondaryMetricsResults,
        exposures,
    })

    return {
        content: [
            {
                type: 'text',
                text: JSON.stringify(parsedExperiment, null, 2),
            },
        ],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-results-get',
    schema,
    handler: getResultsHandler,
})

export default tool
