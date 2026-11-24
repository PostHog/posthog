/**
 * Hooks for the generated `experiment-launch` tool. An agent that launches through the MCP doesn't see the health panel
 * of the experiment page, so the launch result carries the draft's configuration findings. beforeRequest reads them and
 * afterResponse adds them to the result. The read never stops the launch: a flag that is off, a failed read and a late
 * read all let it go ahead.
 */
import { collectHealth, preLaunchHealth } from '@/schema/experiments'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

import { type ConfigHealthRead, configHealthNotRun, readConfigHealth, trackHealthReturned } from './health'

// beforeRequest hands its read to afterResponse in the params. The launch request sends only the id.
type LaunchParams = { id: number; draftHealth?: ConfigHealthRead }

// The launch waits for this read, so a slow read must not hold it. The limit covers the flag check and the retries too.
const DRAFT_HEALTH_TIMEOUT_MS = 10_000

// The read comes before the launch because some checks run only on a draft, such as the one for a flag without calls.
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
    // Without the flag the customer can't see the findings in the app, so their agent gets none either.
    if (read.outcome === 'flag_off') {
        return result
    }
    // First, so that the findings survive a client that cuts the end of a long result.
    return { pre_launch_health: preLaunchHealth(details), ...(result as Record<string, unknown>) }
}

export default { beforeRequest, afterResponse } satisfies ToolHooks<LaunchParams>
