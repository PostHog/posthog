import type { AwsTenantFindingApi, FindingTypeEnumApi } from 'products/workflows/frontend/generated/api.schemas'

export interface IndexedFinding {
    finding: AwsTenantFindingApi
    /** The finding's position in the provider's list, which settles ties between findings. */
    index: number
}

export function findingsOfType(
    findings: readonly AwsTenantFindingApi[],
    types: readonly FindingTypeEnumApi[]
): IndexedFinding[] {
    return findings.flatMap((finding, index) => (types.includes(finding.finding_type) ? [{ finding, index }] : []))
}

export function isHighImpact(finding: AwsTenantFindingApi): boolean {
    return finding.impact === 'HIGH'
}
