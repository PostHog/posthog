import { endWithPunctation } from 'lib/utils/strings'

import type { AwsTenantFindingApi } from 'products/workflows/frontend/generated/api.schemas'

import { defineReputationAction } from '../defineReputationAction'
import { LOWER_RATES_DOCS, VIEW_WORKFLOWS } from '../reputationActionCtas'
import { IndexedFinding, isHighImpact } from '../reputationFindings'
import { BIMI_FINDING_TYPES } from './bimiFindingAction'
import { DNS_FINDING_TYPES } from './dnsFindingAction'
import { RATE_FINDING_TYPES } from './rateFindingAction'

// A finding action with its own types lists them here, or its findings also show up as generic rows.
const DEDICATED_FINDING_TYPES = new Set<string>([...RATE_FINDING_TYPES, ...DNS_FINDING_TYPES, ...BIMI_FINDING_TYPES])

const TITLES: Partial<Record<AwsTenantFindingApi['finding_type'], string>> = {
    IP_LISTING: 'Your email is on a blocklist',
    FEEDBACK_3P: 'Mailbox providers report problems with your email',
}

function providerReport(finding: AwsTenantFindingApi): string {
    const detail = endWithPunctation(finding.description)
    return detail
        ? `Your email provider reports: ${detail}`
        : 'Your email provider flagged a problem with email from this project.'
}

/** Every finding no other action handles, including types the provider adds later. */
export const otherFindingAction = defineReputationAction<IndexedFinding>({
    kind: 'other-finding',
    detect: ({ findings }) =>
        findings.flatMap((finding, index) =>
            DEDICATED_FINDING_TYPES.has(finding.finding_type) ? [] : [{ finding, index }]
        ),
    content: ({ finding, index }) => ({
        key: `finding:${finding.finding_type}`,
        rank: {
            severity: isHighImpact(finding) ? 'high' : 'medium',
            slot: isHighImpact(finding) ? 'highFinding' : 'lowFinding',
            order: index,
        },
        title: TITLES[finding.finding_type] ?? 'Your email provider flagged a problem',
        description: `${providerReport(finding)} This usually follows high bounce or spam complaint rates, so check your workflows for those first.`,
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: () => VIEW_WORKFLOWS,
})
