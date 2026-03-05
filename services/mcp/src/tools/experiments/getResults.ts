import type { z } from 'zod'

import { EXPERIMENT_RESULTS_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { ExperimentResultsResponseSchema } from '@/schema/experiments'
import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentResultsGetSchema

type Params = z.infer<typeof schema>

/**
 * Get experiment results including metrics and exposures data
 * This tool fetches the experiment details and executes the necessary queries
 * to get metrics results (both primary and secondary) and exposure data
 */
export const getResultsHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
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
        ...parsedExperiment,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/experiments/${params.experimentId}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-results-get',
    schema,
    handler: getResultsHandler,
    _meta: {
        ui: {
            resourceUri: EXPERIMENT_RESULTS_RESOURCE_URI,
        },
    },
})

export default tool
