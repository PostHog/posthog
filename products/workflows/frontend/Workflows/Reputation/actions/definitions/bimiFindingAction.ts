import type { FindingTypeEnumApi } from 'products/workflows/frontend/generated/api.schemas'

import { defineReputationAction } from '../defineReputationAction'
import { IndexedFinding, findingsOfType } from '../reputationFindings'

export const BIMI_FINDING_TYPES: readonly FindingTypeEnumApi[] = ['BIMI']

/** Optional logo setup. It happens at the DNS host, so no page in PostHog helps and the row has no button. */
export const bimiFindingAction = defineReputationAction<IndexedFinding>({
    kind: 'bimi-finding',
    detect: ({ findings }) => findingsOfType(findings, BIMI_FINDING_TYPES),
    content: ({ finding, index }) => ({
        key: `finding:${finding.finding_type}`,
        rank: { severity: 'low', slot: 'optionalSetup', order: index },
        title: 'Set up BIMI to show your logo in inboxes',
        description:
            'BIMI is optional and is set up at your DNS host, not in PostHog. It needs a DMARC policy that quarantines or rejects, a logo file, and for some mailbox providers a certificate.',
    }),
})
