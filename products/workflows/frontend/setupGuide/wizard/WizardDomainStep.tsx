import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { ChannelSetupModal } from '../../Channels/ChannelSetupModal'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

export function WizardDomainStep(): JSX.Element {
    const { stepDone } = useValues(workflowsOnboardingWizardLogic)
    // A domain's "Configure" button opens this modal through integrationsLogic, so the step has to render it.
    const { setupModalOpen, setupModalType, selectedIntegration } = useValues(integrationsLogic)
    const { closeSetupModal } = useActions(integrationsLogic)

    return (
        <div className="flex flex-col gap-4">
            <ChannelSetupModal
                isOpen={setupModalOpen}
                channelType={setupModalType}
                integration={selectedIntegration || undefined}
                onClose={closeSetupModal}
                onComplete={closeSetupModal}
            />
            {stepDone?.domain ? (
                <LemonBanner type="success">Your domain is verified. Your email is ready to send.</LemonBanner>
            ) : (
                <LemonBanner type="info">
                    Open your domain below to see its DNS records. Add them at your DNS provider, then verify. Emails
                    send only after the domain is verified.
                </LemonBanner>
            )}
            <EmailIntegrationsList />
        </div>
    )
}
