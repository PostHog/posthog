import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { ChannelSetupModal } from './ChannelSetupModal'

const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]

export function MessageChannels(): JSX.Element {
    const { setupModalOpen, integrations, integrationsLoading, setupModalType, selectedIntegration } =
        useValues(integrationsLogic)
    const { openSetupModal, closeSetupModal } = useActions(integrationsLogic)
    const hasMessagingSesFeatureFlag = useFeatureFlag('MESSAGING_SES')

    const allMessagingIntegrations =
        integrations?.filter((integration) => MESSAGING_CHANNEL_TYPES.includes(integration.kind as ChannelType)) ?? []

    const showProductIntroduction = !integrationsLoading && !allMessagingIntegrations.length

    return (
        <>
            <ChannelSetupModal
                isOpen={setupModalOpen}
                channelType={setupModalType}
                integration={selectedIntegration || undefined}
                onComplete={() => closeSetupModal()}
            />

            <div className="flex flex-col gap-4">
                {integrationsLoading && !integrations?.length && (
                    <>
                        <LemonSkeleton className="h-20" />
                        <LemonSkeleton className="h-20" />
                        <LemonSkeleton className="h-20" />
                    </>
                )}
                {showProductIntroduction && (
                    <ProductIntroduction
                        productName="Messaging channel"
                        thingName="channel integration"
                        description="Configure channels to send messages from."
                        docsURL="https://posthog.com/docs/messaging"
                        action={() => openSetupModal(undefined, 'twilio')}
                        isEmpty
                    />
                )}
                {hasMessagingSesFeatureFlag && <EmailIntegrationsList />}
                <IntegrationsList titleText="" onlyKinds={MESSAGING_CHANNEL_TYPES.filter((type) => type !== 'email')} />
            </div>
        </>
    )
}
