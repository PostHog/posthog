import type { FindingTypeEnumApi } from 'products/workflows/frontend/generated/api.schemas'

import { defineReputationAction } from '../defineReputationAction'
import { CHANNEL_SETUP_DOCS, openChannels } from '../reputationActionCtas'
import { IndexedFinding, findingsOfType, isHighImpact } from '../reputationFindings'

export const DNS_FINDING_TYPES: readonly FindingTypeEnumApi[] = ['DKIM', 'DMARC', 'SPF']

/**
 * A sending domain is missing a DKIM, DMARC or SPF record. Channels shows the records to add. The
 * provider's description is left out: for these types it is usually a code such as "DKIM1".
 */
export const dnsFindingAction = defineReputationAction<IndexedFinding>({
    kind: 'dns-finding',
    detect: ({ findings }) => findingsOfType(findings, DNS_FINDING_TYPES),
    content: ({ finding, index }) => ({
        key: `finding:${finding.finding_type}`,
        rank: {
            severity: isHighImpact(finding) ? 'high' : 'medium',
            slot: isHighImpact(finding) ? 'highFinding' : 'lowDnsFinding',
            order: index,
        },
        title: `Fix your ${finding.finding_type} record`,
        description: `Your sending domain is missing a valid ${finding.finding_type} record. In Channels, expand each email domain and click Configure next to a sender to see the records to add at your DNS host, then click Re-check DNS records.`,
        docsLink: CHANNEL_SETUP_DOCS,
    }),
    cta: (_, context) => openChannels(context),
})
