import type { z } from 'zod'

import type { ExperimentHealthSummary } from '@/schema/experiments'
import { collectHealth, transformExperimentHealth } from '@/schema/experiments'
import { ExperimentHealthGetSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import {
    experimentReadError,
    exposureHealthOutcome,
    healthNotRun,
    readConfigHealth,
    trackHealthReturned,
} from './health'

const schema = ExperimentHealthGetSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<ExperimentHealthSummary>

export const getHealthHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const [exposureRead, configRead] = await Promise.all([
        context.api.experiments({ projectId }).getExposures({ experimentId: params.id, refresh: false }),
        readConfigHealth(context, projectId, params.id),
    ])
    const exposureError = exposureRead.success ? null : exposureRead.error
    const exposureOutcome = exposureHealthOutcome(exposureError)

    // A draft has no exposures, which is an answer, not a failure. Any other failed exposure read fails the tool,
    // unless the configuration checks ran.
    if (exposureError && exposureOutcome === 'failed' && !configRead.health) {
        throw experimentReadError(`Failed to get experiment health: ${exposureError.message}`, exposureError)
    }
    const exposures = exposureRead.success ? exposureRead.data.exposures : null

    const health = collectHealth(
        [configRead.health ?? {}, { findings: exposures?.health_findings, checks: exposures?.health_checks }],
        healthNotRun(configRead.outcome, exposureOutcome, exposureError)
    )
    trackHealthReturned(context, {
        toolName: 'experiment-health-get',
        experimentId: params.id,
        details: health,
        configOutcome: configRead.outcome,
        exposureOutcome,
    })

    return withPostHogUrl(
        context,
        transformExperimentHealth(params.id, health, configRead.health?.setup ?? null, exposures),
        `/experiments/${params.id}`
    )
}

export default (): ToolBase<typeof schema, Result> => ({
    name: 'experiment-health-get',
    schema,
    handler: getHealthHandler,
})
