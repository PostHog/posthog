import type { AwsTenantFindingApi } from 'products/workflows/frontend/generated/api.schemas'

import { defineReputationAction } from './defineReputationAction'
import { LOWER_RATES_DOCS, VIEW_WORKFLOWS } from './reputationActionCtas'
import { findingsWithoutDedicatedAction, isHighImpact, providerSays } from './reputationFindings'

const TITLES: Partial<Record<AwsTenantFindingApi['finding_type'], string>> = {
    IP_LISTING: 'Your email is on a blocklist',
    FEEDBACK_3P: 'Mailbox providers report problems with your email',
}

/** Every finding no other action handles, including types the provider adds later. */
export const otherFindingAction = defineReputationAction<AwsTenantFindingApi>({
    kind: 'finding',
    detect: ({ findings }) => findingsWithoutDedicatedAction(findings),
    content: (finding) => ({
        key: `finding:${finding.finding_type}`,
        severity: isHighImpact(finding) ? 'high' : 'medium',
        slot: isHighImpact(finding) ? 'highFinding' : 'lowFinding',
        title: TITLES[finding.finding_type] ?? 'Your email provider flagged a problem',
        description: `${providerSays(finding).trim() || 'Your email provider flagged a problem with email from this project.'} This usually follows high bounce or spam complaint rates, so check your workflows for those first.`,
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: () => VIEW_WORKFLOWS,
})
