import { defineReputationAction } from '../defineReputationAction'
import { LOWER_RATES_DOCS, VIEW_WORKFLOWS, contactSupport } from '../reputationActionCtas'

interface ProviderStatus {
    stopped: boolean
    critical: boolean
    hasFindings: boolean
}

/**
 * The provider's verdict on the project. A pause always shows, because only support can lift it.
 * A warning shows only when the provider names no finding: findings explain a bad verdict on their
 * own, and without them the verdict is the only signal.
 */
export const providerStatusAction = defineReputationAction<ProviderStatus>({
    kind: 'provider-status',
    detect: ({ response, findings, sendingStopped }) => {
        const flagged = !!response.aws && response.aws.health !== 'healthy' && findings.length === 0
        return sendingStopped || flagged
            ? [
                  {
                      stopped: sendingStopped,
                      critical: response.aws?.health === 'critical',
                      hasFindings: findings.length > 0,
                  },
              ]
            : []
    },
    content: ({ stopped, critical, hasFindings }) => ({
        key: 'provider-status',
        rank: {
            severity: stopped || critical ? 'high' : 'medium',
            slot: stopped ? 'sendingStopped' : 'providerVerdict',
        },
        blocksSending: stopped,
        title: stopped
            ? 'Your email provider paused sending for this project'
            : 'Your email provider flagged this project',
        description: !stopped
            ? 'It has not named a cause yet. Check your workflows for high bounce or spam complaint rates.'
            : hasFindings
              ? 'Fix the findings below, then contact support to get sending re-enabled.'
              : 'Lower your bounce and spam complaint rates, then contact support to get sending re-enabled.',
        docsLink: LOWER_RATES_DOCS,
    }),
    cta: ({ stopped }) =>
        stopped
            ? contactSupport(
                  'Our email provider paused sending for this project. Please review it and re-enable sending. What I changed to lower our bounce and spam complaint rates: '
              )
            : VIEW_WORKFLOWS,
})
