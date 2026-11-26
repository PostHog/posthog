import type { ExperimentExposureHealthCheck, ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type { ExperimentHealthApi, ExperimentHealthCheckResultApi } from '../generated/api.schemas'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'

/** An exposure check from an answer cached before the server added a field has no description, values or rule. */
export type HealthPanelCheck = ExperimentHealthCheckResultApi | ExperimentExposureHealthCheck

/** A check in the list of checks. A check that reported a finding shows as that finding instead. */
export type ListedHealthCheck = HealthPanelCheck & { status: Exclude<HealthPanelCheck['status'], 'finding'> }

export type ExposureChecksState = 'not_launched' | 'pending' | 'missing' | 'ready'

export type HealthChipState =
    | { kind: 'hidden' }
    | {
          kind: 'issues'
          count: number
          hasCritical: boolean
      }

// The flag history check only lets the checks of changes since launch look. When it can't read the history, they say
// they couldn't check and its note says why, so its own row would tell the reader nothing.
const UNLISTED_CHECKS: ReadonlySet<HealthPanelCheck['key']> = new Set(['flag_history'])

const CHECK_STATUS_ORDER: Record<HealthPanelCheck['status'], number> = {
    finding: 0,
    not_checked: 1,
    passed: 2,
    not_applicable: 3,
}

export function healthPanelChecks(
    health: ExperimentHealthApi | null,
    exposures: ExperimentExposureQueryResponse | null | undefined,
    isExperimentDraft: boolean
): HealthPanelCheck[] | null {
    if (!health) {
        return null
    }
    // A reset to draft keeps the previous exposure answer in the page, as for the findings.
    const exposureChecks = isExperimentDraft ? [] : (exposures?.health_checks ?? [])
    // A server from before the checks were reported sends none, for example while a deploy rolls out.
    return [...(health.checks ?? []), ...exposureChecks]
        .filter((check) => !UNLISTED_CHECKS.has(check.key))
        .sort((a, b) => CHECK_STATUS_ORDER[a.status] - CHECK_STATUS_ORDER[b.status])
}

export function exposureChecksState(
    isExperimentLaunched: boolean,
    exposures: ExperimentExposureQueryResponse | null | undefined,
    exposuresLoading: boolean
): ExposureChecksState {
    if (!isExperimentLaunched) {
        return 'not_launched'
    }
    if (exposures?.health_checks) {
        return 'ready'
    }
    // A failed load, or an answer cached before the server reported the checks.
    return exposuresLoading ? 'pending' : 'missing'
}

export function listedHealthChecks(checks: HealthPanelCheck[]): ListedHealthCheck[] {
    return checks.filter((check): check is ListedHealthCheck => check.status !== 'finding')
}

export function countHealthChecks(checks: HealthPanelCheck[], status: HealthPanelCheck['status']): number {
    return checks.filter((check) => check.status === status).length
}

export function healthChipState(findings: HealthPanelFinding[] | null): HealthChipState {
    const issues = healthIssues(findings)
    // A note needs no action, so the header marks only an experiment with an issue to fix.
    return issues.length > 0
        ? {
              kind: 'issues',
              count: issues.length,
              hasCritical: issues.some((finding) => finding.severity === 'critical'),
          }
        : { kind: 'hidden' }
}
