import { IconLetter, IconPlusSmall, IconWarning } from '@posthog/icons'
import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'

import { IntegrationType } from '~/types'

import { ChannelSetupModal } from './ChannelSetupModal'
import { ChannelType, messageChannelsLogic } from './messageChannelsLogic'
import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons/icons'
import { messageChannelLogic } from './messageChannelLogic'

function MessageChannel({ integration }: { integration: IntegrationType }): JSX.Element {
    const { openNewChannelModal, deleteIntegration } = useActions(messageChannelsLogic)
    const { displayName, isVerified, isVerificationRequired } = useValues(messageChannelLogic({ integration }))

    const onDeleteClick = (integration: IntegrationType): void => {
        LemonDialog.open({
            title: `Do you want to disconnect this channel?`,
            description:
                'This cannot be undone. Any messages configured to use this channel will remain but will stop working.',
            primaryButton: {
                children: 'Yes, disconnect',
                status: 'danger',
                onClick: () => deleteIntegration(integration.id),
            },
            secondaryButton: {
                children: 'No thanks',
            },
        })
    }

    return (
        <div className="rounded border bg-surface-primary">
            <div className="flex justify-between items-center p-2">
                <div className="flex gap-4 items-center ml-2">
                    <div className="flex flex-col gap-[1px]">
                        <div className="flex gap-2 items-center">
                            <strong>{displayName}</strong>
                            {isVerificationRequired && (
                                <Tooltip
                                    title={
                                        isVerified
                                            ? 'This channel is ready to use'
                                            : 'You cannot send messages from this channel until it has been verified'
                                    }
                                >
                                    <LemonTag type={isVerified ? 'success' : 'warning'}>
                                        {isVerified ? 'Verified' : 'Unverified'}
                                    </LemonTag>
                                </Tooltip>
                            )}
                        </div>
                        {integration.created_by ? (
                            <UserActivityIndicator
                                at={integration.created_at}
                                by={integration.created_by}
                                prefix="Created"
                                className="text-secondary"
                            />
                        ) : null}
                    </div>
                </div>

                <div className="flex gap-2 items-center">
                    {!isVerified && (
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                openNewChannelModal(integration, integration.kind as ChannelType)
                            }}
                            icon={<IconWarning />}
                        >
                            Verify
                        </LemonButton>
                    )}
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => onDeleteClick(integration)}
                        icon={<IconTrash />}
                    >
                        Remove
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

function MessageChannelSection({
    title,
    icon,
    integrations,
}: {
    title: string
    icon: JSX.Element
    integrations: IntegrationType[]
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                {icon}
                <h3 className="mb-0">{title}</h3>
            </div>
            {integrations.length === 0 && <span className="text-muted">None configured yet</span>}
            {integrations.map((integration) => (
                <MessageChannel key={integration.id} integration={integration} />
            ))}
        </div>
    )
}

export function MessageChannels(): JSX.Element {
    const { isNewChannelModalOpen, selectedIntegration, integrations, integrationsLoading, channelType } =
        useValues(messageChannelsLogic)
    const { openNewChannelModal, closeNewChannelModal } = useActions(messageChannelsLogic)

    const messagingIntegrationTypes = ['email', 'slack', 'twilio', 'webhook']
    const allMessagingIntegrations =
        integrations?.filter((integration) => messagingIntegrationTypes.includes(integration.kind)) ?? []
    const emailIntegrations = integrations?.filter((integration) => integration.kind === 'email') ?? []
    const slackIntegrations = integrations?.filter((integration) => integration.kind === 'slack') ?? []
    const twilioIntegrations = integrations?.filter((integration) => integration.kind === 'twilio') ?? []

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
            onClick: () => openNewChannelModal(undefined, 'slack'),
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
                    <>
                        <MessageChannelSection
                            icon={<IconLetter className="text-xl" />}
                            title="Email addresses"
                            integrations={emailIntegrations}
                        />
                        <MessageChannelSection
                            icon={<IconSlack className="text-xl" />}
                            title="Slack apps"
                            integrations={slackIntegrations}
                        />
                        <MessageChannelSection
                            icon={<IconTwilio className="text-xl" />}
                            title="Phone numbers"
                            integrations={twilioIntegrations}
                        />
                    </>
                )}
            </div>
        </>
    )
}
