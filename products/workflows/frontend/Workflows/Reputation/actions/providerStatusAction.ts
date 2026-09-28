import { defineReputationAction } from './defineReputationAction'
import { LOWER_RATES_DOCS, VIEW_WORKFLOWS, contactSupport } from './reputationActionCtas'

interface ProviderStatus {
    stopped: boolean
    critical: boolean
}

/**
 * The provider's verdict on the project when it names no finding. Findings explain a bad verdict
 * on their own. Without any, the verdict is the only signal, and leaving it out would show
 * "nothing to fix" under the sending-paused banner.
 */
export const providerStatusAction = defineReputationAction<ProviderStatus>({
    kind: 'provider-status',
    detect: ({ aws }) => {
        if (!aws || aws.findings.length > 0) {
            return []
        }
        const stopped = aws.sending_status === 'DISABLED' || aws.health === 'suspended'
        return stopped || aws.health !== 'healthy' ? [{ stopped, critical: aws.health === 'critical' }] : []
    },
    content: ({ stopped, critical }) => ({
        key: 'provider-status',
        severity: stopped || critical ? 'high' : 'medium',
        slot: stopped ? 'sendingStopped' : 'providerVerdict',
        blocksSending: stopped,
        title: stopped
            ? 'Your email provider paused sending for this project'
            : 'Your email provider flagged this project',
        description: stopped
            ? 'Lower your bounce and spam complaint rates, then contact support to get sending re-enabled.'
            : 'It has not named a cause yet. Check your workflows for high bounce or spam complaint rates.',
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: ({ stopped }) =>
        stopped
            ? contactSupport(
                  'Our email provider paused sending for this project. Please review it and re-enable sending. What I changed to lower our bounce and spam complaint rates: '
              )
            : VIEW_WORKFLOWS,
})
