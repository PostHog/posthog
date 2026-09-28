import { endWithPunctation } from 'lib/utils/strings'

import type { AwsTenantFindingApi, FindingTypeEnumApi } from 'products/workflows/frontend/generated/api.schemas'

import { RATE_KINDS } from '../reputationUtils'

// Each finding type belongs to exactly one action. A type missing here falls back to the
// generic finding action, so a type the provider adds later still shows up in the list.
export const RATE_FINDING_TYPES: readonly FindingTypeEnumApi[] = [
    RATE_KINDS.bounce.findingType,
    RATE_KINDS.complaint.findingType,
]
export const DNS_FINDING_TYPES: readonly FindingTypeEnumApi[] = ['DKIM', 'DMARC', 'SPF']
export const BIMI_FINDING_TYPES: readonly FindingTypeEnumApi[] = ['BIMI']

const DEDICATED_FINDING_TYPES = new Set<string>([...RATE_FINDING_TYPES, ...DNS_FINDING_TYPES, ...BIMI_FINDING_TYPES])

export function findingsOfType(
    findings: readonly AwsTenantFindingApi[],
    types: readonly FindingTypeEnumApi[]
): AwsTenantFindingApi[] {
    return findings.filter((finding) => types.includes(finding.finding_type))
}

export function findingsWithoutDedicatedAction(findings: readonly AwsTenantFindingApi[]): AwsTenantFindingApi[] {
    return findings.filter((finding) => !DEDICATED_FINDING_TYPES.has(finding.finding_type))
}

export function isHighImpact(finding: AwsTenantFindingApi): boolean {
    return finding.impact === 'HIGH'
}

/** The provider's own words about a finding, as a sentence to append, or an empty string. */
export function providerSays(finding: AwsTenantFindingApi): string {
    const detail = endWithPunctation(finding.description)
    return detail ? ` Your email provider reports: ${detail}` : ''
}
