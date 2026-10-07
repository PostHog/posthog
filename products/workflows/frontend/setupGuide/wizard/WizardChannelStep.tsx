import { useActions, useValues } from 'kea'

import { IconLetter } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { ChannelSetupModal } from '../../Channels/ChannelSetupModal'

export function WizardChannelStep(): JSX.Element {
    const { integrations, setupModalOpen, setupModalType, selectedIntegration } = useValues(integrationsLogic)
    const { openSetupModal, closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)
    const hasEmailChannel = !!integrations?.some((integration) => integration.kind === 'email')

    return (
        <>
            <ChannelSetupModal
                isOpen={setupModalOpen}
                channelType={setupModalType}
                integration={selectedIntegration || undefined}
                onClose={closeSetupModal}
                onComplete={() => {
                    markTaskAsCompleted(SetupTaskId.SetUpFirstWorkflowChannel)
                    closeSetupModal()
                }}
            />
            {hasEmailChannel ? (
                <div className="flex flex-col gap-4">
                    <LemonBanner type="success">
                        Your email channel is connected. Continue to the next step.
                    </LemonBanner>
                    <EmailIntegrationsList />
                </div>
            ) : (
                <div className="flex flex-col items-center gap-3 py-6 text-center">
                    <div className="flex items-center justify-center size-12 rounded-full bg-surface-secondary">
                        <IconLetter className="size-6" />
                    </div>
                    <p className="mb-0 max-w-md text-secondary">
                        You need a domain you control, such as mail.example.com. You can add SMS and push later in
                        Messaging setup.
                    </p>
                    <LemonButton
                        type="primary"
                        onClick={() => openSetupModal(undefined, 'email')}
                        data-attr="workflows-onboarding-wizard-connect-email"
                    >
                        Connect email
                    </LemonButton>
                </div>
            )}
        </>
    )
}
