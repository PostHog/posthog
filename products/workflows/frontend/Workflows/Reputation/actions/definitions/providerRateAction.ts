import { humanList } from 'lib/utils/strings'

import { OTHER_ISP, RATE_THRESHOLDS, formatRate, ispDisplayName } from '../../reputationUtils'
import { defineReputationAction } from '../defineReputationAction'
import type { ProviderOverLine } from '../reputationActionContext'
import { LOWER_RATES_DOCS, VIEW_PROVIDERS } from '../reputationActionCtas'

/** A mailbox provider where too much of the project's email bounces. */
export const providerRateAction = defineReputationAction<ProviderOverLine>({
    kind: 'provider-rate',
    detect: ({ providersOverLine }) => providersOverLine,
    content: ({ isp, bounceRate, level }, { response }) => {
        const provider = isp.isp === OTHER_ISP ? 'other providers' : ispDisplayName(isp.isp)
        const sharedDomains = response.isp_shared_domains
        const sharedNote =
            sharedDomains.length > 0
                ? ` These counts include email other projects send from ${humanList(sharedDomains)}.`
                : ''
        return {
            key: `provider-bounce:${isp.isp}`,
            rank: {
                severity: level === 'high' ? 'medium' : 'low',
                slot: 'providerRate',
                rateKind: 'bounce',
                magnitude: bounceRate / RATE_THRESHOLDS.bounce.elevated,
            },
            title: `${formatRate(bounceRate)} of email to ${provider} bounces`,
            description: `A high bounce rate at one provider can mean it rejects your email, or that many of your addresses there no longer exist. Compare its delivery rate with the other providers.${sharedNote}`,
            docsLink: LOWER_RATES_DOCS,
        }
    },
    cta: () => VIEW_PROVIDERS,
})
