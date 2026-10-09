import { dayjs } from 'lib/dayjs'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import type { ExperimentHealthFindingActionKind, ExperimentHealthFindingCode } from './experimentHealthFindingEvents'
import { SAMPLE_RATIO_MISMATCH_DESCRIPTION, getTotalExposures, hasSampleRatioMismatch } from './exposureHealth'

/** A finding of the health panel: one from the server, or one the page reads from the exposure answer. */
export type HealthPanelFinding = Pick<ExperimentHealthFindingApi, 'subcode' | 'severity' | 'title' | 'detail'> & {
    code: ExperimentHealthFindingCode
    actions: ExperimentHealthFindingActionKind[]
}

export interface ExposureHealthInput {
    exposures: ExperimentExposureQueryResponse | null | undefined
    isExperimentDraft: boolean
    /** Null before launch. */
    hoursSinceStart: number | null
}

// A new experiment often has no exposure in its first hours, so the finding waits as long as the
// experiments scout does.
export const ZERO_EXPOSURES_GRACE_HOURS = 24

export function hoursSinceStart(startDate: string | null | undefined): number | null {
    return startDate ? dayjs().diff(startDate, 'hour', true) : null
}

// The server's health checks read no exposures, so the page derives these three from the exposure
// answer. The bias text matches products/experiments/backend/health/checks/bias_risk.py.
function exposureFindings({
    exposures,
    isExperimentDraft,
    hoursSinceStart,
}: ExposureHealthInput): HealthPanelFinding[] {
    if (isExperimentDraft || !exposures) {
        return []
    }
    const findings: HealthPanelFinding[] = []
    // The exposure query returns a series for every configured variant, with zero counts when
    // nobody was exposed, so only the total tells an experiment without exposures apart.
    if (
        getTotalExposures(exposures) === 0 &&
        hoursSinceStart !== null &&
        hoursSinceStart >= ZERO_EXPOSURES_GRACE_HOURS
    ) {
        findings.push({
            code: 'zero_exposures',
            subcode: null,
            severity: 'warning',
            title: 'No users exposed',
            detail: 'No users have been exposed to this experiment, so it shows no results. Users are counted when the exposure event is sent for them. Check that your code evaluates the linked feature flag and that the exposure criteria match the events you send.',
            actions: ['edit_exposure_criteria'],
        })
    }
    if (hasSampleRatioMismatch(exposures)) {
        findings.push({
            code: 'srm',
            subcode: null,
            severity: 'warning',
            title: 'Users are not split across variants as configured',
            detail: SAMPLE_RATIO_MISMATCH_DESCRIPTION,
            actions: [],
        })
    }
    if (exposures.bias_risk) {
        findings.push({
            code: 'bias_risk_multiple_excluded',
            subcode: null,
            severity: 'warning',
            title: 'Setup likely introduced bias',
            detail: `${exposures.bias_risk.multiple_variant_percentage.toFixed(1)}% of users were exposed to multiple variants. With an uneven variant split and the Exclude handling, these users were dropped more often from the smaller variant, so its metrics can be biased. Use an even split and control exposure with the overall rollout, or switch the handling to First seen.`,
            actions: ['adjust_distribution', 'use_first_seen_variant'],
        })
    }
    return findings
}

/**
 * The findings of the health panel, or null when the server sent no health findings. Null means that
 * the reader does not have the health findings flag, or that a local flag write dropped stale findings.
 * The page then shows its separate warnings instead of the panel.
 */
export function healthPanelFindings(
    health: ExperimentHealthApi | null | undefined,
    exposureInput: ExposureHealthInput
): HealthPanelFinding[] | null {
    if (!health) {
        return null
    }
    const serverCodes = new Set<string>(health.findings.map((finding) => finding.code))
    return [...health.findings, ...exposureFindings(exposureInput).filter(({ code }) => !serverCodes.has(code))]
}
