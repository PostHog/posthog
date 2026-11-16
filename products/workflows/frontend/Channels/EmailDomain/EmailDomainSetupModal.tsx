import { useEffect, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { BindEmailDomainLogics } from './BindEmailDomainLogics'
import { AgentHandoffModal } from './components/AgentHandoffModal'
import { EmailDomainSetupEntry, captureEmailDomainSetupStarted, emailDomainSetupPath } from './emailDomainSetupLinks'
import { EmailDomainSteps } from './EmailDomainSteps'

export interface EmailDomainSetupModalProps {
    integration?: IntegrationType | null
    entry: EmailDomainSetupEntry
    onComplete: (integrationId?: number) => void
    onClose: (savedIntegrationId?: number) => void
}

function ModalSteps({
    integrationId,
    openInNewTab,
    onDomainCreated,
    onLeave,
}: {
    integrationId: number | null
    openInNewTab: boolean
    onDomainCreated: (integrationId: number) => void
    onLeave: (integrationId: number) => void
}): JSX.Element {
    return (
        <BindEmailDomainLogics id={integrationId === null ? 'new' : String(integrationId)}>
            <div className="@container flex flex-col gap-6">
                <EmailDomainSteps domainLogicKey="modal" onDomainCreated={(created) => onDomainCreated(created.id)} />
                {integrationId === null ? null : (
                    <LemonButton
                        type="tertiary"
                        className="self-center"
                        to={emailDomainSetupPath(integrationId)}
                        targetBlank={openInNewTab}
                        onClick={() => onLeave(integrationId)}
                        sideIcon={<IconExternal />}
                    >
                        Open full page
                    </LemonButton>
                )}
                <AgentHandoffModal />
            </div>
        </BindEmailDomainLogics>
    )
}

export function EmailDomainSetupModal({
    integration,
    entry,
    onComplete,
    onClose,
}: EmailDomainSetupModalProps): JSX.Element {
    const [integrationId, setIntegrationId] = useState<number | null>(integration?.id ?? null)

    useEffect(() => captureEmailDomainSetupStarted(entry), [entry])

    return (
        <LemonModal
            title={integrationId ? 'Verify your sending domain' : 'Set up a sending domain'}
            width={720}
            onClose={() => (integrationId ? onComplete(integrationId) : onClose())}
        >
            {/* A broadcast saves its new sender a moment after the modal hands it over, so leaving the
                page right away would drop it. The full page opens next to the broadcast instead. */}
            <ModalSteps
                integrationId={integrationId}
                openInNewTab={entry === 'broadcast'}
                onDomainCreated={setIntegrationId}
                onLeave={onComplete}
            />
        </LemonModal>
    )
}
