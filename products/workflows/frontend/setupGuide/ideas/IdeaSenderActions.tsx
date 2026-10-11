import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { onboardingWizardUrl } from '../wizard/onboardingWizardSteps'
import type { IdeaEmailSender } from './ideaEmailSender'

/** The next step toward a verified sender, plus a link a person can hand to whoever manages their DNS. */
export function IdeaSenderActions({ sender }: { sender: IdeaEmailSender }): JSX.Element | null {
    if (sender.status !== 'none' && sender.status !== 'unverified') {
        return null
    }
    const setupUrl =
        sender.status === 'none' ? onboardingWizardUrl('messaging', { step: 'channel' }) : urls.workflows('channels')
    return (
        <>
            <LemonButton
                type="primary"
                size="small"
                to={setupUrl}
                // pinned: data-attr - autocapture dashboards read it
                data-attr={sender.status === 'none' ? 'workflow-idea-set-up-email' : 'workflow-idea-verify-domain'}
            >
                {sender.status === 'none' ? 'Set up email sending' : 'Finish verifying your domain'}
            </LemonButton>
            <LemonButton
                type="tertiary"
                size="small"
                onClick={() =>
                    void copyToClipboard(`${window.location.origin}${setupUrl}`, 'link to the email sender setup')
                }
                tooltip="Whoever manages your domain's DNS can add the records from this page."
                // pinned: data-attr - autocapture dashboards read it
                data-attr="workflow-idea-copy-sender-link"
            >
                Copy link for a teammate
            </LemonButton>
        </>
    )
}
