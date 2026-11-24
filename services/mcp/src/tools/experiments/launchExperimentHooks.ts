/**
 * Puts the draft's configuration findings in the `experiment-launch` result, because an agent that launches through the
 * MCP doesn't see the health panel of the experiment page. No outcome of the read stops the launch.
 */
import { collectHealth, preLaunchHealth } from '@/schema/experiments'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

import { type ConfigHealthRead, configHealthNotRun, readConfigHealth, trackHealthReturned } from './health'

// beforeRequest hands its read to afterResponse in the params. The launch request sends only the id.
type LaunchParams = { id: number; draftHealth?: ConfigHealthRead }

// The launch waits for this read.
const DRAFT_HEALTH_TIMEOUT_MS = 10_000

// Some checks run only on a draft, such as the one for a flag without calls, so the read comes before the launch.
async function beforeRequest<T extends LaunchParams>(context: Context, params: T): Promise<T> {
    const projectId = await context.stateManager.getProjectId()
    return { ...params, draftHealth: await readConfigHealth(context, projectId, params.id, DRAFT_HEALTH_TIMEOUT_MS) }
}

function afterResponse(context: Context, params: LaunchParams, result: unknown): unknown {
    const read = params.draftHealth
    if (!read) {
        return result
    }
    const details = collectHealth([read.health ?? {}], configHealthNotRun(read.outcome))
    trackHealthReturned(context, {
        toolName: 'experiment-launch',
        experimentId: params.id,
        details,
        configOutcome: read.outcome,
        exposureOutcome: 'not_started',
    })
    if (read.outcome === 'flag_off') {
        return result
    }
    // First, so that the findings survive a client that cuts the end of a long result.
    return { pre_launch_health: preLaunchHealth(details), ...(result as Record<string, unknown>) }
}

export default { beforeRequest, afterResponse } satisfies ToolHooks<LaunchParams>
