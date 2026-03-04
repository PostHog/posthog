import type { z } from 'zod'

import type { ExperimentResultsSummary } from '@/schema/experiments'
import { transformExperimentResults } from '@/schema/experiments'
import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentResultsGetSchema

type Params = z.infer<typeof schema>
type Result = ExperimentResultsSummary

/**
 * Get experiment results including metrics and exposures data
 * This tool fetches the experiment details and executes the necessary queries
 * to get metrics results (both primary and secondary) and exposure data
 */
export const getResultsHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.experiments({ projectId }).getMetricResults({
        experimentId: params.experimentId,
        refresh: params.refresh,
    })

    if (!result.success) {
        throw new Error(`Failed to get experiment results: ${result.error.message}`)
    }

    const { experiment, primaryMetricsResults, secondaryMetricsResults, exposures } = result.data

    return transformExperimentResults({
        experiment,
        primaryMetricsResults,
        secondaryMetricsResults,
        exposures,
    })
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'experiment-results-get',
    schema,
    handler: getResultsHandler,
})

export default tool
