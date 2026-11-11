import type { z } from 'zod'

import type { ExperimentHealthSummary } from '@/schema/experiments'
import { collectHealth, transformExperimentHealth } from '@/schema/experiments'
import { ExperimentHealthGetSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { experimentReadError, healthNotRun, readConfigHealth, trackHealthReturned } from './health'

const schema = ExperimentHealthGetSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<ExperimentHealthSummary>

/**
 * `experiment-health-get` returns the health checks in full, without the metric queries of
 * `experiment-results-get`, whose response carries only an overview of the same findings.
 */
export const getHealthHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const [exposureRead, configRead] = await Promise.all([
        context.api.experiments({ projectId }).getExposures({ experimentId: params.id, refresh: false }),
        readConfigHealth(context, projectId, params.id),
    ])

    // A draft has no exposures, but its configuration checks still run, so they are returned alone.
    if (!exposureRead.success && !configRead.health) {
        throw experimentReadError(`Failed to get experiment health: ${exposureRead.error.message}`, exposureRead.error)
    }
    const exposures = exposureRead.success ? exposureRead.data.exposures : null

    const health = collectHealth(
        [configRead.health ?? {}, { findings: exposures?.health_findings, checks: exposures?.health_checks }],
        healthNotRun(configRead.outcome, exposureRead.success ? undefined : exposureRead.error)
    )
    trackHealthReturned(context, {
        tool: 'experiment-health-get',
        experimentId: params.id,
        details: health,
        configOutcome: configRead.outcome,
        exposureOutcome: exposureRead.success ? 'read' : 'failed',
    })

    return withPostHogUrl(
        context,
        transformExperimentHealth(params.id, health, configRead.health?.setup ?? null),
        `/experiments/${params.id}`
    )
}

export default (): ToolBase<typeof schema, Result> => ({
    name: 'experiment-health-get',
    schema,
    handler: getHealthHandler,
})
