import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { findRecoverableApiError, PostHogApiError, PostHogValidationError, wrapError } from '@/lib/errors'
import { buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import { withUiApp } from '@/resources/ui-apps'
import type { ExperimentResultsSummary } from '@/schema/experiments'
import { transformExperimentResults } from '@/schema/experiments'
import { ExperimentResultsGetSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentResultsGetSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<ExperimentResultsSummary>

// The same flag shows the health panel in the app. Agents get the configuration checks only for the
// people who see that panel, so a customer's agent does not report findings the customer cannot see.
const EXPERIMENT_HEALTH_FINDINGS_FLAG = 'experiment-health-findings'

// The results wait for the health read, so a slow read must not hold them. The limit covers the
// retries too. When it runs out, the response keeps the exposure checks only.
const CONFIG_HEALTH_TIMEOUT_MS = 10_000

async function readConfigHealth(
    context: Context,
    projectId: string,
    experimentId: number
): Promise<Schemas.ExperimentHealth | null> {
    try {
        const analyticsContext = await context.stateManager.getAnalyticsContext().catch(() => undefined)
        const enabled = await isFeatureFlagEnabled(
            EXPERIMENT_HEALTH_FINDINGS_FLAG,
            await context.getDistinctId(),
            analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : undefined
        )
        if (!enabled) {
            return null
        }
        const health = await context.api
            .experiments({ projectId })
            .getHealth({ experimentId, signal: AbortSignal.timeout(CONFIG_HEALTH_TIMEOUT_MS) })
        return health.success ? health.data : null
    } catch {
        return null
    }
}

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

    const [result, configHealth] = await Promise.all([
        context.api.experiments({ projectId }).getMetricResults({
            experimentId: params.id,
            refresh: params.refresh,
        }),
        readConfigHealth(context, projectId, params.id),
    ])

    if (!result.success) {
        const message = `Failed to get experiment results: ${result.error.message}`
        // A 400 from /query/ means the exposure query was built wrong on this side. Dropping
        // the typed cause keeps it out of handleToolError's 4xx short-circuit so it is still
        // captured as an exception. Every other failure keeps its cause: a 404, 403 or 429
        // is the agent's or the caller's to recover from.
        const apiError = findRecoverableApiError(result.error)
        const isOwnQueryBug =
            apiError instanceof PostHogValidationError ||
            (apiError instanceof PostHogApiError && apiError.status === 400)
        throw isOwnQueryBug ? new Error(message) : wrapError(message, result.error)
    }

    const {
        experiment,
        primaryMetricEntries,
        secondaryMetricEntries,
        primaryMetricsResults,
        secondaryMetricsResults,
        exposures,
    } = result.data

    return withPostHogUrl(
        context,
        transformExperimentResults({
            experiment,
            primaryMetricEntries,
            secondaryMetricEntries,
            primaryMetricsResults,
            secondaryMetricsResults,
            exposures,
            configHealth,
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
