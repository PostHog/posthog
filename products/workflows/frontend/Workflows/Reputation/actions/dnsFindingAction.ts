import type { AwsTenantFindingApi } from 'products/workflows/frontend/generated/api.schemas'

import { defineReputationAction } from './defineReputationAction'
import { CHANNEL_SETUP_DOCS, openChannels } from './reputationActionCtas'
import { DNS_FINDING_TYPES, findingsOfType, isHighImpact, providerSays } from './reputationFindings'

/** A sending domain is missing a DKIM, DMARC or SPF record. Channels shows the records to add. */
export const dnsFindingAction = defineReputationAction<AwsTenantFindingApi>({
    kind: 'finding',
    detect: ({ findings }) => findingsOfType(findings, DNS_FINDING_TYPES),
    content: (finding) => ({
        key: `finding:${finding.finding_type}`,
        severity: isHighImpact(finding) ? 'high' : 'medium',
        slot: isHighImpact(finding) ? 'highFinding' : 'lowDnsFinding',
        title: `Fix your ${finding.finding_type} record`,
        description: `Your sending domain is missing a valid ${finding.finding_type} record.${providerSays(finding)} In Channels, expand each email domain and click Configure next to a sender to see the records to add at your DNS host, then click Re-check DNS records.`,
        docsLink: CHANNEL_SETUP_DOCS,
    }),
    cta: (_, context) => openChannels(context),
})
