import { IconPlusSmall, IconWarning } from '@posthog/icons'
import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'

import { IntegrationType } from '~/types'

import { EmailSetupModal } from './EmailSetup/EmailSetupModal'
import { messageSendersLogic } from './messageSendersLogic'

function MessageSender({ integration }: { integration: IntegrationType }): JSX.Element {
    const { openNewSenderModal, deleteIntegration } = useActions(messageSendersLogic)

    const onDeleteClick = (integration: IntegrationType): void => {
        LemonDialog.open({
            title: `Do you want to disconnect this domain?`,
            description:
                'This cannot be undone. Campaigns and broadcasts configured to use this sender domain will remain but will stop working.',
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
                    <div>
                        <div className="flex gap-2 items-center">
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
                                prefix="Created"
                                className="text-secondary"
                            />
                        ) : null}
                    </div>
                </div>

                <div className="flex gap-2 items-center">
                    {!integration.config.mailjet_verified && (
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                openNewSenderModal(integration)
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

export function MessageSenders(): JSX.Element {
    const { isNewSenderModalOpen, selectedIntegration, integrations, integrationsLoading } =
        useValues(messageSendersLogic)
    const { openNewSenderModal, closeNewSenderModal } = useActions(messageSendersLogic)

    const emailIntegrations = integrations?.filter((integration) => integration.kind === 'email') ?? []

    return (
        <>
            <PageHeader
                caption="Manage email sending domains"
                buttons={
                    <LemonButton
                        data-attr="new-message-button"
                        icon={<IconPlusSmall />}
                        size="small"
                        type="primary"
                        onClick={() => openNewSenderModal()}
                    >
                        New sender
                    </LemonButton>
                }
            />
            {isNewSenderModalOpen && (
                <EmailSetupModal
                    integration={selectedIntegration}
                    onComplete={() => {
                        closeNewSenderModal()
                    }}
                />
            )}
            <div>
                <div className="flex flex-col gap-2">
                    {integrationsLoading && <LemonSkeleton className="h-10" />}
                    {!integrationsLoading &&
                        (emailIntegrations?.length ? (
                            emailIntegrations.map((integration) => (
                                <MessageSender key={integration.id} integration={integration} />
                            ))
                        ) : (
                            <ProductIntroduction
                                productName="Email sender"
                                thingName="sender domain"
                                description="Configure domains to send emails from. This ensures your emails are delivered to inboxes and not marked as spam."
                                docsURL="https://posthog.com/docs/messaging"
                                action={() => openNewSenderModal()}
                                isEmpty
                            />
                        ))}
                </div>
            </div>
        </>
    )
}
