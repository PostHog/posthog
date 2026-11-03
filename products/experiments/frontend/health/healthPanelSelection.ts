import type { ListedHealthCheck } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'

/** What the detail side of the health checks shows. */
export type HealthPanelSelection =
    | { kind: 'summary' }
    | { kind: 'finding'; key: string }
    | { kind: 'check'; key: ListedHealthCheck['key'] }

export function healthFindingKey(finding: HealthPanelFinding): string {
    return `${finding.code}:${finding.subcode ?? ''}`
}

/**
 * The selection that the reader picked, while its finding or check is still on the list. A refresh can remove the
 * finding or check, and the detail side then shows the first issue again.
 */
export function resolveHealthPanelSelection(
    picked: HealthPanelSelection | null,
    findings: HealthPanelFinding[],
    checks: ListedHealthCheck[]
): HealthPanelSelection {
    switch (picked?.kind) {
        case 'finding':
            if (findings.some((finding) => healthFindingKey(finding) === picked.key)) {
                return picked
            }
            break
        case 'check':
            if (checks.some((check) => check.key === picked.key)) {
                return picked
            }
            break
    }
    // A note states a fact and needs no action, so it waits for a click, as it did when it was a collapsed row.
    const [firstIssue] = healthIssues(findings)
    return firstIssue ? { kind: 'finding', key: healthFindingKey(firstIssue) } : { kind: 'summary' }
}
