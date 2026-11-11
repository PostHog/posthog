import type { Schemas } from '@/api/generated'
import { findRecoverableApiError, PostHogApiError, PostHogValidationError, wrapError } from '@/lib/errors'
import { AnalyticsEvent, buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import type { ExperimentHealthDetails } from '@/schema/experiments'
import type { Context } from '@/tools/types'

// The same flag shows the health panel in the app. Agents get the configuration checks only for the
// people who see that panel, so a customer's agent does not report findings the customer cannot see.
const EXPERIMENT_HEALTH_FINDINGS_FLAG = 'experiment-health-findings'

/** `flag_off` also covers a failed flag check, because then the caller may not be in the flag. */
export type ConfigHealthOutcome = 'read' | 'flag_off' | 'failed' | 'timed_out'

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

/** Reads the configuration checks of `/health/`. A failed read returns no checks rather than failing the tool. */
export async function readConfigHealth(
    context: Context,
    projectId: string,
    experimentId: number,
    timeoutMs?: number
): Promise<ConfigHealthRead> {
    if (!(await configHealthEnabled(context))) {
        return { health: null, outcome: 'flag_off' }
    }
    const signal = timeoutMs === undefined ? undefined : AbortSignal.timeout(timeoutMs)
    const health = await context.api
        .experiments({ projectId })
        .getHealth({ experimentId, signal })
        .catch(() => null)
    if (health?.success) {
        return { health: health.data, outcome: 'read' }
    }
    return { health: null, outcome: signal?.aborted ? 'timed_out' : 'failed' }
}

/** The sentences that tell the agent which checks did not run, so that it does not read a missing check as passed. */
export function healthNotRun(configOutcome: ConfigHealthOutcome, exposureError?: Error): string[] {
    return [
        ...(configOutcome === 'failed' || configOutcome === 'timed_out'
            ? ['The configuration checks did not run.']
            : []),
        ...(exposureError ? [`The exposure checks did not run: ${exposureError.message}`] : []),
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
 * Records what health an agent got and from which tool. A results call with findings followed by an
 * experiment-health-get call on the same experiment and session shows that the overview leads agents to the details.
 */
export function trackHealthReturned(
    context: Context,
    {
        tool,
        experimentId,
        details,
        configOutcome,
        exposureOutcome,
    }: {
        tool: 'experiment-results-get' | 'experiment-health-get'
        experimentId: number
        details: ExperimentHealthDetails
        configOutcome: ConfigHealthOutcome
        exposureOutcome: 'read' | 'failed'
    }
): void {
    const severityCount = (severity: string): number =>
        details.findings.filter((finding) => finding.severity === severity).length
    void context.trackEvent(AnalyticsEvent.MCP_EXPERIMENT_HEALTH_RETURNED, {
        tool,
        experiment_id: experimentId,
        finding_count: details.findings.length,
        critical_count: severityCount('critical'),
        warning_count: severityCount('warning'),
        info_count: severityCount('info'),
        finding_codes: details.findings.map((finding) => finding.code),
        check_count: details.checks.length,
        not_checked_count: details.checks.filter((check) => check.status === 'not_checked').length,
        configuration_checks: configOutcome,
        exposure_checks: exposureOutcome,
    })
}
