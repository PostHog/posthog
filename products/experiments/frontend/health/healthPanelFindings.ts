import { dayjs } from 'lib/dayjs'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type {
    ExperimentHealthApi,
    ExperimentHealthCheckKeyEnumApi,
    ExperimentHealthFindingApi,
} from '../generated/api.schemas'
import type {
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
} from './experimentHealthFindingEvents'

/** A finding of the health panel, from the experiment read or from the exposure answer. */
export type HealthPanelFinding = Pick<
    ExperimentHealthFindingApi,
    'subcode' | 'reason' | 'severity' | 'title' | 'detail' | 'evidence'
> & {
    code: ExperimentHealthFindingCode
    actions: ExperimentHealthFindingActionKind[]
    /** The check that reported it. Missing on an exposure answer cached before the server added the field. */
    check?: ExperimentHealthCheckKeyEnumApi
    /** The check whose finding names its cause. Missing on an exposure answer cached before the server added it. */
    caused_by?: ExperimentHealthCheckKeyEnumApi | null
}

/** A finding with the findings that the server says it causes. Fixing it fixes them too. */
export interface HealthFindingGroup {
    finding: HealthPanelFinding
    effects: HealthPanelFinding[]
    /** The most severe of the finding and its effects. */
    severity: HealthPanelFinding['severity']
}

const SEVERITY_ORDER: Record<HealthPanelFinding['severity'], number> = { critical: 0, warning: 1, info: 2 }

// The icons differ in shape and color only, so each says its severity in words too.
export const HEALTH_FINDING_SEVERITY_LABELS: Record<HealthPanelFinding['severity'], string> = {
    info: 'Note',
    warning: 'Warning',
    critical: 'Critical',
}

export function hoursSinceStart(startDate: string | null | undefined): number | null {
    return startDate ? dayjs().diff(startDate, 'hour', true) : null
}

/**
 * The findings of the health panel, or null when the page shows no server findings: the reader does not
 * have the health findings flag, or the health request is pending or failed. The page then shows its
 * separate warnings instead of the panel.
 */
export function healthPanelFindings(
    health: ExperimentHealthApi | null,
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

function namedCause(finding: HealthPanelFinding, findings: HealthPanelFinding[]): HealthPanelFinding | null {
    const causedBy = finding.caused_by
    if (!causedBy || causedBy === finding.check) {
        return null
    }
    return findings.find(({ check }) => check === causedBy) ?? null
}

/**
 * The finding that the server names as the cause of this one, when the panel shows it. A cause that has a cause
 * of its own is shown under that one, so the finding stands on its own rather than two levels down.
 */
export function healthFindingCause(
    finding: HealthPanelFinding,
    findings: HealthPanelFinding[]
): HealthPanelFinding | null {
    const cause = namedCause(finding, findings)
    return cause && namedCause(cause, findings) === null ? cause : null
}

/**
 * The findings of the panel, each with the findings it causes, most severe first. A finding whose cause the panel
 * doesn't show, for example because the exposure answer is older than the experiment read, stands on its own.
 */
export function healthFindingGroups(findings: HealthPanelFinding[] | null): HealthFindingGroup[] {
    if (!findings) {
        return []
    }
    const causes = new Map(findings.map((finding) => [finding, healthFindingCause(finding, findings)]))
    const groups = findings
        .filter((finding) => causes.get(finding) === null)
        .map((finding) => {
            const effects = findings.filter((effect) => causes.get(effect) === finding)
            const severity = [finding, ...effects].reduce(
                (most, { severity }) => (SEVERITY_ORDER[severity] < SEVERITY_ORDER[most] ? severity : most),
                finding.severity
            )
            return { finding, effects, severity }
        })
    return groups.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
}

/** The groups the header chip counts: one per cause, so a cause with three findings is one issue to fix. */
export function healthIssueGroups(findings: HealthPanelFinding[] | null): HealthFindingGroup[] {
    return healthFindingGroups(findings).filter(({ severity }) => severity !== 'info')
}

/** The finding as the finding events report it. `cause` is the finding that the panel shows it under. */
export function reportedHealthFinding(
    finding: HealthPanelFinding,
    cause: HealthPanelFinding | null = null
): ExperimentHealthFinding {
    return {
        code: finding.code,
        subcode: finding.subcode ?? undefined,
        severity: finding.severity,
        reason: finding.reason ?? undefined,
        causedBy: cause?.check,
    }
}
