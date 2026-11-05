import type { ListedHealthCheck } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'

export type HealthPanelSelection =
    | { kind: 'summary' }
    | { kind: 'finding'; key: string }
    | { kind: 'check'; key: ListedHealthCheck['key'] }

export type ResolvedHealthPanelSelection =
    | { kind: 'summary' }
    | { kind: 'finding'; key: string; finding: HealthPanelFinding }
    | { kind: 'check'; key: ListedHealthCheck['key']; check: ListedHealthCheck }

export function healthFindingKey(finding: HealthPanelFinding): string {
    return `${finding.code}:${finding.subcode ?? ''}`
}

// A refresh can remove the picked finding or check, so the pick holds only while it is still on the list. The summary
// is always there.
export function resolveHealthPanelSelection(
    picked: HealthPanelSelection | null,
    findings: HealthPanelFinding[],
    checks: ListedHealthCheck[]
): ResolvedHealthPanelSelection {
    switch (picked?.kind) {
        case 'summary':
            return picked
        case 'finding': {
            const finding = findings.find((candidate) => healthFindingKey(candidate) === picked.key)
            if (finding) {
                return { ...picked, finding }
            }
            break
        }
        case 'check': {
            const check = checks.find((candidate) => candidate.key === picked.key)
            if (check) {
                return { ...picked, check }
            }
            break
        }
    }
    // A note states a fact and needs no action, so only an issue opens without a click.
    const [firstIssue] = healthIssues(findings)
    return firstIssue
        ? { kind: 'finding', key: healthFindingKey(firstIssue), finding: firstIssue }
        : { kind: 'summary' }
}
