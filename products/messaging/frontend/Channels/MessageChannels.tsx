import { IconLetter, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { ChannelSetupModal } from './ChannelSetupModal'
import { messageChannelsLogic } from './messageChannelsLogic'
import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons/icons'
import { OtherIntegrations } from 'scenes/settings/environment/OtherIntegrations'
import api from 'lib/api'
import { urls } from 'scenes/urls'

export function MessageChannels(): JSX.Element {
    const { isNewChannelModalOpen, selectedIntegration, integrations, integrationsLoading, channelType } =
        useValues(messageChannelsLogic)
    const { openNewChannelModal, closeNewChannelModal } = useActions(messageChannelsLogic)

    const messagingIntegrationTypes = ['email', 'slack', 'twilio', 'webhook']
    const allMessagingIntegrations =
        integrations?.filter((integration) => messagingIntegrationTypes.includes(integration.kind)) ?? []

    const showProductIntroduction = !integrationsLoading && !allMessagingIntegrations.length

    const menuItems: LemonMenuItems = [
        {
            label: (
                <div className="flex items-center gap-1">
                    <IconLetter /> Email
                </div>
            ),
            onClick: () => openNewChannelModal(undefined, 'email'),
        },
        {
            label: (
                <div className="flex items-center gap-1">
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
                <div className="flex items-center gap-1">
                    <IconTwilio /> Twilio
                </div>
            ),
            onClick: () => openNewChannelModal(undefined, 'twilio'),
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
                isOpen={isNewChannelModalOpen}
                channelType={channelType}
                integration={selectedIntegration || undefined}
                onComplete={() => closeNewChannelModal()}
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
                        action={() => openNewChannelModal(undefined, 'email')}
                        isEmpty
                    />
                )}
                {allMessagingIntegrations.length > 0 && (
                    <OtherIntegrations titleText="" integrationKinds={['email', 'slack', 'twilio']} />
                )}
            </div>
        </>
    )
}
