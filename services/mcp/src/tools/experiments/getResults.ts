import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { ExperimentResultsSummary } from '@/schema/experiments'
import { transformExperimentResults } from '@/schema/experiments'
import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentResultsGetSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<ExperimentResultsSummary>

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

    return withPostHogUrl(
        transformExperimentResults({
            experiment,
            primaryMetricsResults,
            secondaryMetricsResults,
            exposures,
        }),
        `${context.api.getProjectBaseUrl(projectId)}/experiments/${params.experimentId}`
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('experiment-results', {
        name: 'experiment-results-get',
        schema,
        handler: getResultsHandler,
    })
