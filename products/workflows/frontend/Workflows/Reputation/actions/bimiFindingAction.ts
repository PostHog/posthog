import type { AwsTenantFindingApi } from 'products/workflows/frontend/generated/api.schemas'

import { defineReputationAction } from './defineReputationAction'
import { BIMI_FINDING_TYPES, findingsOfType, providerSays } from './reputationFindings'

/** Optional logo setup. It happens at the DNS host, so no page in PostHog helps and the row has no button. */
export const bimiFindingAction = defineReputationAction<AwsTenantFindingApi>({
    kind: 'finding',
    detect: ({ findings }) => findingsOfType(findings, BIMI_FINDING_TYPES),
    content: (finding) => ({
        key: `finding:${finding.finding_type}`,
        severity: 'low',
        slot: 'optionalSetup',
        title: 'Set up BIMI to show your logo in inboxes',
        description: `BIMI is optional and is set up at your DNS host, not in PostHog. It needs a DMARC policy that quarantines or rejects, a logo file, and for some mailbox providers a certificate.${providerSays(finding)}`,
    }),
})
