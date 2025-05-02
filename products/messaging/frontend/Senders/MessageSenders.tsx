import { IconPlusSmall, IconWarning } from '@posthog/icons'
import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { SceneExport } from 'scenes/sceneTypes'

import { IntegrationType } from '~/types'

import { EmailSetupModal } from '../EmailSetup/EmailSetupModal'
import { MessagingTabs } from '../MessagingTabs'
import { messageSendersLogic } from './messageSendersLogic'

function MessageSender({ integration }: { integration: IntegrationType }): JSX.Element {
    const { deleteIntegration, setIntegration } = useActions(messageSendersLogic)
    const { openNewSenderModal } = useActions(messageSendersLogic)

    const onDeleteClick = (integration: IntegrationType): void => {
        LemonDialog.open({
            title: `Do you want to disconnect from this ${integration.kind} integration?`,
            description:
                'This cannot be undone. PostHog resources configured to use this integration will remain but will stop working.',
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
                <div className="flex items-center gap-4 ml-2">
                    <img src={integration.icon_url} className="h-10 w-10 rounded" />
                    <div>
                        <div className="flex items-center gap-2">
                            <strong>{integration.config.domain || integration.display_name}</strong>
                            {integration.config.mailjet_verified !== undefined && (
                                <Tooltip
                                    title={
                                        integration.config.mailjet_verified
                                            ? 'This domain is ready to use'
                                            : 'You cannot send emails from this domain until it has been verified'
                                    }
                                >
                                    <LemonTag type={integration.config.mailjet_verified ? 'success' : 'warning'}>
                                        {integration.config.mailjet_verified ? 'Verified' : 'Unverified'}
                                    </LemonTag>
                                </Tooltip>
                            )}
                        </div>
                        {integration.created_by ? (
                            <UserActivityIndicator
                                at={integration.created_at}
                                by={integration.created_by}
                                prefix="Updated"
                                className="text-secondary"
                            />
                        ) : null}
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    {!integration.config.mailjet_verified && (
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                setIntegration(integration)
                                openNewSenderModal()
                            }}
                            icon={<IconWarning />}
                        >
                            Verify domain
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

function MessageSenders(): JSX.Element {
    const { isNewSenderModalOpen, integrations, integrationsLoading } = useValues(messageSendersLogic)
    const { openNewSenderModal, closeNewSenderModal } = useActions(messageSendersLogic)

    const emailIntegrations = integrations?.filter((integration) => integration.kind === 'email')

    return (
        <div className="messaging-senders">
            <MessagingTabs key="senders-tabs" />
            <PageHeader
                caption="Manage email sending domains"
                buttons={
                    <LemonButton
                        data-attr="new-message-button"
                        icon={<IconPlusSmall />}
                        size="small"
                        type="primary"
                        onClick={openNewSenderModal}
                    >
                        New sender
                    </LemonButton>
                }
            />
            {isNewSenderModalOpen && (
                <EmailSetupModal
                    onComplete={() => {
                        closeNewSenderModal()
                    }}
                />
            )}
            <div>
                <div className="deprecated-space-y-2">
                    {emailIntegrations?.length ? (
                        emailIntegrations.map((integration) => (
                            <MessageSender key={integration.id} integration={integration} />
                        ))
                    ) : integrationsLoading ? (
                        <LemonSkeleton className="h-10" />
                    ) : (
                        <p>No senders</p>
                    )}
                </div>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: MessageSenders,
    logic: messageSendersLogic,
}
