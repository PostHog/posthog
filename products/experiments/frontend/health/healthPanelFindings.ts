import { dayjs } from 'lib/dayjs'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import type { ExperimentHealthFindingActionKind, ExperimentHealthFindingCode } from './experimentHealthFindingEvents'

/** A finding of the health panel, from the experiment read or from the exposure answer. */
export type HealthPanelFinding = Pick<ExperimentHealthFindingApi, 'subcode' | 'severity' | 'title' | 'detail'> & {
    code: ExperimentHealthFindingCode
    actions: ExperimentHealthFindingActionKind[]
}

const SEVERITY_ORDER: Record<HealthPanelFinding['severity'], number> = { critical: 0, warning: 1, info: 2 }

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
    // The sort is stable, so findings of one severity keep the order the server sent them in.
    return [...health.findings, ...exposureFindings.filter(({ code }) => !experimentCodes.has(code))].sort(
        (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
    )
}

/** The findings the header chip counts. An info finding states a fact and needs no action, so it is no issue. */
export function healthIssues(findings: HealthPanelFinding[] | null): HealthPanelFinding[] {
    return findings?.filter(({ severity }) => severity !== 'info') ?? []
}
