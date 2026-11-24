import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { ExperimentResultsSummary } from '@/schema/experiments'
import { collectHealth, transformExperimentResults } from '@/schema/experiments'
import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { experimentReadError, healthNotRun, readConfigHealth, trackHealthReturned } from './health'

const schema = ExperimentResultsGetSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<ExperimentResultsSummary>

// The results wait for the health read, so a slow read must not hold them. The limit covers the
// flag check and the retries too. When it runs out, the response keeps the exposure checks only.
const CONFIG_HEALTH_TIMEOUT_MS = 10_000

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

    const [result, configRead] = await Promise.all([
        context.api.experiments({ projectId }).getMetricResults({
            experimentId: params.id,
            refresh: params.refresh,
        }),
        readConfigHealth(context, projectId, params.id, CONFIG_HEALTH_TIMEOUT_MS),
    ])

    if (!result.success) {
        throw experimentReadError(`Failed to get experiment results: ${result.error.message}`, result.error)
    }

    const {
        experiment,
        primaryMetricEntries,
        secondaryMetricEntries,
        primaryMetricsResults,
        secondaryMetricsResults,
        exposures,
    } = result.data

    const health = collectHealth(
        [configRead.health ?? {}, { findings: exposures.health_findings, checks: exposures.health_checks }],
        healthNotRun(configRead.outcome, 'read', null)
    )
    trackHealthReturned(context, {
        toolName: 'experiment-results-get',
        experimentId: params.id,
        details: health,
        configOutcome: configRead.outcome,
        exposureOutcome: 'read',
    })

    return withPostHogUrl(
        context,
        transformExperimentResults({
            experiment,
            primaryMetricEntries,
            secondaryMetricEntries,
            primaryMetricsResults,
            secondaryMetricsResults,
            exposures,
            health,
        }),
        `/experiments/${params.id}`
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('experiment-results', {
        name: 'experiment-results-get',
        schema,
        handler: getResultsHandler,
    })
