import { useActions, useValues } from 'kea'

import { IconLetter, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { EmailIntegrationsList } from 'lib/integrations/EmailIntegrationsList'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons/icons'
import { urls } from 'scenes/urls'

import { ChannelSetupModal } from './ChannelSetupModal'

const MESSAGING_CHANNEL_TYPES = ['email', 'slack', 'twilio'] as const
export type ChannelType = (typeof MESSAGING_CHANNEL_TYPES)[number]

export function MessageChannels(): JSX.Element {
    const { setupModalOpen, integrations, integrationsLoading, setupModalType, selectedIntegration } =
        useValues(integrationsLogic)
    const { openSetupModal, closeSetupModal } = useActions(integrationsLogic)

    const allMessagingIntegrations =
        integrations?.filter((integration) => MESSAGING_CHANNEL_TYPES.includes(integration.kind as ChannelType)) ?? []

    const showProductIntroduction = !integrationsLoading && !allMessagingIntegrations.length

    const menuItems: LemonMenuItems = [
        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconLetter /> Email
                </div>
            ),
            onClick: () => openSetupModal(undefined, 'email'),
        },
        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconSlack /> Slack
                </div>
            ),
            disableClientSideRouting: true,
            to: api.integrations.authorizeUrl({
                kind: 'slack',
                next: urls.messaging('channels'),
            }),
        },
        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconTwilio /> Twilio
                </div>
            ),
            onClick: () => openSetupModal(undefined, 'twilio'),
        },
    ]

    return (
        <>
            <PageHeader
                buttons={
                    <div className="flex items-center m-2 shrink-0">
                        <LemonMenu items={menuItems}>
                            <LemonButton
                                data-attr="new-channel-button"
                                icon={<IconPlusSmall />}
                                size="small"
                                type="primary"
                            >
                                New channel
                            </LemonButton>
                        </LemonMenu>
                    </div>
                }
            />
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
                        action={() => openSetupModal(undefined, 'email')}
                        isEmpty
                    />
                )}
                <EmailIntegrationsList />
                <IntegrationsList titleText="" onlyKinds={MESSAGING_CHANNEL_TYPES.filter((type) => type !== 'email')} />
            </div>
        </>
    )
}
