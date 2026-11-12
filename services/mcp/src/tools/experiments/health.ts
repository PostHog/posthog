import type { Schemas } from '@/api/generated'
import {
    ExperimentNotStartedError,
    findRecoverableApiError,
    PostHogApiError,
    PostHogValidationError,
    wrapError,
} from '@/lib/errors'
import { AnalyticsEvent, buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import type { ExperimentHealthDetails } from '@/schema/experiments'
import type { Context } from '@/tools/types'

// The same flag shows the health panel in the app. Agents get the configuration checks only for the
// people who see that panel, so a customer's agent does not report findings the customer cannot see.
const EXPERIMENT_HEALTH_FINDINGS_FLAG = 'experiment-health-findings'

/** `flag_off` also covers a failed or late flag check, because then the caller may not be in the flag. */
export type ConfigHealthOutcome = 'read' | 'flag_off' | 'failed' | 'timed_out'

export type ExposureHealthOutcome = 'read' | 'not_started' | 'failed'

export type ConfigHealthRead = {
    health: Schemas.ExperimentHealth | null
    outcome: ConfigHealthOutcome
}

async function configHealthEnabled(context: Context): Promise<boolean> {
    try {
        const analyticsContext = await context.stateManager.getAnalyticsContext().catch(() => undefined)
        return await isFeatureFlagEnabled(
            EXPERIMENT_HEALTH_FINDINGS_FLAG,
            await context.getDistinctId(),
            analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : undefined
        )
    } catch {
        return false
    }
}

function whenAborted(signal: AbortSignal): Promise<void> {
    return new Promise((resolve) => {
        if (signal.aborted) {
            resolve()
            return
        }
        signal.addEventListener('abort', () => resolve(), { once: true })
    })
}

export async function readConfigHealth(
    context: Context,
    projectId: string,
    experimentId: number,
    timeoutMs?: number
): Promise<ConfigHealthRead> {
    const signal = timeoutMs === undefined ? undefined : AbortSignal.timeout(timeoutMs)
    const gate = configHealthEnabled(context)
    const enabled = await (signal ? Promise.race([gate, whenAborted(signal).then(() => false)]) : gate)
    if (!enabled) {
        return { health: null, outcome: 'flag_off' }
    }
    const health = await context.api
        .experiments({ projectId })
        .getHealth({ experimentId, signal })
        .catch(() => null)
    if (health?.success) {
        return { health: health.data, outcome: 'read' }
    }
    return { health: null, outcome: signal?.aborted ? 'timed_out' : 'failed' }
}

export function exposureHealthOutcome(error: Error | null): ExposureHealthOutcome {
    if (error === null) {
        return 'read'
    }
    return error instanceof ExperimentNotStartedError ? 'not_started' : 'failed'
}

/** One sentence per source whose checks did not run, so that the agent does not read a missing check as passed. */
export function healthNotRun(
    configOutcome: ConfigHealthOutcome,
    exposureOutcome: ExposureHealthOutcome,
    exposureError: Error | null
): string[] {
    return [
        ...(configOutcome === 'failed' || configOutcome === 'timed_out'
            ? ['The configuration checks did not run.']
            : []),
        ...(exposureOutcome === 'not_started'
            ? ['The exposure checks did not run: the experiment has not started.']
            : []),
        ...(exposureOutcome === 'failed' && exposureError
            ? [`The exposure checks did not run: ${exposureError.message}`]
            : []),
    ]
}

/**
 * A 400 from /query/ means the exposure query was built wrong on this side. Dropping the typed cause keeps it out
 * of handleToolError's 4xx short-circuit so it is still captured as an exception. Every other failure keeps its
 * cause: a 404, 403 or 429 is the agent's or the caller's to recover from.
 */
export function experimentReadError(message: string, error: Error): Error {
    const apiError = findRecoverableApiError(error)
    const isOwnQueryBug =
        apiError instanceof PostHogValidationError || (apiError instanceof PostHogApiError && apiError.status === 400)
    return isOwnQueryBug ? new Error(message) : wrapError(message, error)
}

/**
 * A results call with findings, followed by an experiment-health-get call on the same experiment, shows that the
 * overview leads agents to the details.
 */
export function trackHealthReturned(
    context: Context,
    {
        toolName,
        experimentId,
        details,
        configOutcome,
        exposureOutcome,
    }: {
        toolName: 'experiment-results-get' | 'experiment-health-get'
        experimentId: number
        details: ExperimentHealthDetails
        configOutcome: ConfigHealthOutcome
        exposureOutcome: ExposureHealthOutcome
    }
): void {
    void context.trackEvent(AnalyticsEvent.MCP_EXPERIMENT_HEALTH_RETURNED, {
        tool_name: toolName,
        experiment_id: experimentId,
        health_finding_codes: details.findings.map((finding) => finding.code),
        health_finding_count: details.findings.length,
        // pinned: `code:subcode:severity:reason` and `key:status:reason`, the formats of `experiment health checked`.
        health_findings: details.findings.map(({ code, subcode, severity, reason }) =>
            [code, subcode ?? '', severity, reason ?? ''].join(':')
        ),
        health_checks: details.checks.map(({ key, status, reason }) =>
            [key, status, status === 'not_checked' ? (reason ?? '') : ''].join(':')
        ),
        configuration_checks_outcome: configOutcome,
        exposure_checks_outcome: exposureOutcome,
    })
}
