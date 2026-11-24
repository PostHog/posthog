/**
 * Puts the draft's configuration findings in the `experiment-launch` result, because an agent that launches through the
 * MCP doesn't see the health panel of the experiment page. No outcome of the read stops the launch.
 */
import type { Schemas } from '@/api/generated'
import { collectHealth, preLaunchHealth } from '@/schema/experiments'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

import { type ConfigHealthRead, configHealthNotRun, readConfigHealth, trackHealthReturned } from './health'

// beforeRequest hands its read to afterResponse in the params. The launch request sends only the id.
type LaunchParams = { id: number; draftHealth?: ConfigHealthRead }

// The launch waits for this read, so a slow read must not hold it.
const DRAFT_HEALTH_TIMEOUT_MS = 10_000

// A flag that serves variants before the launch is the state that a running experiment needs, so after the launch
// this finding and its advice to launch or to disable the flag no longer apply.
const RESOLVED_BY_LAUNCH: ReadonlySet<string> = new Set(['flag_live_before_launch'])

// The check that reported a resolved finding goes too, or the summary counts a finding that the result doesn't list.
function afterLaunch(health: Schemas.ExperimentHealth | null): Pick<Schemas.ExperimentHealth, 'findings' | 'checks'> {
    // The API client returns any 2xx body unchecked, such as `{}` or the text of an HTML page. A missing list then
    // reports that no check ran.
    const findings = health?.findings ?? []
    const checks = health?.checks ?? []
    const resolved = findings.filter((finding) => RESOLVED_BY_LAUNCH.has(finding.code))
    const resolvedChecks = new Set<string>(resolved.map((finding) => finding.check))
    return {
        findings: findings.filter((finding) => !RESOLVED_BY_LAUNCH.has(finding.code)),
        checks: checks.filter((check) => !resolvedChecks.has(check.key)),
    }
}

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
    try {
        const details = collectHealth([afterLaunch(read.health)], configHealthNotRun(read.outcome))
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
    } catch {
        // The launch already happened, so a health body that this code can't read must not fail the call.
        return result
    }
}

export default { beforeRequest, afterResponse } satisfies ToolHooks<LaunchParams>
