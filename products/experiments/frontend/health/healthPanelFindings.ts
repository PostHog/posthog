import { dayjs } from 'lib/dayjs'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import type { ExperimentHealthFindingActionKind, ExperimentHealthFindingCode } from './experimentHealthFindingEvents'

/** A finding of the health panel, from the experiment read or from the exposure answer. */
export type HealthPanelFinding = Pick<ExperimentHealthFindingApi, 'subcode' | 'severity' | 'title' | 'detail'> & {
    code: ExperimentHealthFindingCode
    actions: ExperimentHealthFindingActionKind[]
}

export function hoursSinceStart(startDate: string | null | undefined): number | null {
    return startDate ? dayjs().diff(startDate, 'hour', true) : null
}

/**
 * The findings of the health panel, or null when the server sent no health findings. Null means that
 * the reader does not have the health findings flag, or that a local flag write dropped stale findings.
 * The page then shows its separate warnings instead of the panel.
 */
export function healthPanelFindings(
    health: ExperimentHealthApi | null | undefined,
    exposures: ExperimentExposureQueryResponse | null | undefined,
    isExperimentDraft: boolean
): HealthPanelFinding[] | null {
    if (!health) {
        return null
    }
    // A reset to draft keeps the previous exposure answer in the page, so a draft shows none of its findings.
    const exposureFindings = isExperimentDraft ? [] : (exposures?.health_findings ?? [])
    const experimentCodes = new Set<string>(health.findings.map((finding) => finding.code))
    return [...health.findings, ...exposureFindings.filter(({ code }) => !experimentCodes.has(code))]
}
