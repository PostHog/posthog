import { useActions, useValues } from 'kea'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { ChannelCatalog } from './ChannelCatalog'
import { ChannelSetupModal } from './ChannelSetupModal'

const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio', 'firebase', 'apns'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]

export function MessageChannels(): JSX.Element {
    const { setupModalOpen, integrations, setupModalType, selectedIntegration } = useValues(integrationsLogic)
    const { closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)

    const allWorkflowIntegrations =
        integrations?.filter((integration) => MESSAGING_CHANNEL_TYPES.includes(integration.kind as ChannelType)) ?? []

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

            <div className="flex flex-col gap-4" data-attr="message-channels">
                <ChannelCatalog />
                {allWorkflowIntegrations.length > 0 && (
                    <h3 className="mb-0 text-base font-semibold">Your connections</h3>
                )}
                <EmailIntegrationsList />
                <IntegrationsList titleText="" onlyKinds={MESSAGING_CHANNEL_TYPES.filter((type) => type !== 'email')} />
            </div>
        </>
    )
}
