import type { ListedHealthCheck } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'

export type HealthPanelSelection =
    | { kind: 'summary' }
    | { kind: 'finding'; key: string }
    | { kind: 'check'; key: ListedHealthCheck['key'] }

export function healthFindingKey(finding: HealthPanelFinding): string {
    return `${finding.code}:${finding.subcode ?? ''}`
}

// A refresh can remove the picked finding or check, so the pick holds only while it is still on the list.
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
    // A note states a fact and needs no action, so only an issue opens without a click.
    const [firstIssue] = healthIssues(findings)
    return firstIssue ? { kind: 'finding', key: healthFindingKey(firstIssue) } : { kind: 'summary' }
}
