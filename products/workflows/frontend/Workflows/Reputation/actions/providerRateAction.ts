import { humanList } from 'lib/utils/strings'

import type { IspSendingHealthApi } from 'products/workflows/frontend/generated/api.schemas'

import { OTHER_ISP, RATE_THRESHOLDS, formatRate, ispDisplayName } from '../reputationUtils'
import { defineReputationAction } from './defineReputationAction'
import { ExceededLevel, exceededLevel } from './reputationActionContext'
import { LOWER_RATES_DOCS, VIEW_PROVIDERS } from './reputationActionCtas'

interface ProviderRate {
    isp: IspSendingHealthApi
    bounceRate: number
    level: ExceededLevel
}

/** A mailbox provider where too much of the project's email bounces. */
export const providerRateAction = defineReputationAction<ProviderRate>({
    kind: 'provider-rate',
    detect: ({ isps }) =>
        isps.flatMap((isp) => {
            if (isp.bounce_rate === null) {
                return []
            }
            const level = exceededLevel(isp.bounce_rate, 'bounce', isp.emails_sent)
            return level ? [{ isp, bounceRate: isp.bounce_rate, level }] : []
        }),
    content: ({ isp, bounceRate, level }, { sharedDomains }) => {
        const provider = isp.isp === OTHER_ISP ? 'other providers' : ispDisplayName(isp.isp)
        const sharedNote =
            sharedDomains.length > 0
                ? ` These counts include email other projects send from ${humanList(sharedDomains)}.`
                : ''
        return {
            key: `provider-bounce:${isp.isp}`,
            severity: level === 'high' ? 'medium' : 'low',
            slot: 'providerRate',
            rateKind: 'bounce',
            magnitude: bounceRate / RATE_THRESHOLDS.bounce.elevated,
            title: `${formatRate(bounceRate)} of email to ${provider} bounces`,
            description: `A high bounce rate at one provider can mean it rejects your email, or that many of your addresses there no longer exist. Compare its delivery rate with the other providers.${sharedNote}`,
            docsLink: LOWER_RATES_DOCS,
        }
    },
    cta: () => VIEW_PROVIDERS,
})
