import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { BindEmailDomainLogics } from './BindEmailDomainLogics'
import { AgentHandoffModal } from './components/AgentHandoffModal'
import { emailDomainLogic } from './emailDomainLogic'
import { DomainStep } from './steps/DomainStep'
import { ReadyStep } from './steps/ReadyStep'
import { SettingsStep } from './steps/SettingsStep'
import { UnavailableStep } from './steps/UnavailableStep'
import { VerifyingStep } from './steps/VerifyingStep'

export interface EmailDomainSetupModalProps {
    integration?: IntegrationType | null
    entry: 'channels' | 'broadcast'
    onComplete: (integrationId?: number) => void
    onClose: (savedIntegrationId?: number) => void
}

function ModalStep(): JSX.Element {
    const { phase } = useValues(emailDomainLogic)
    switch (phase) {
        case 'unavailable':
            return <UnavailableStep />
        case 'settings':
            return <SettingsStep />
        case 'verifying':
            return <VerifyingStep />
        case 'ready':
            return <ReadyStep />
        default:
            return <LemonSkeleton className="h-40" />
    }
}

function ModalSettings({ integrationId }: { integrationId: number }): JSX.Element {
    return (
        <BindEmailDomainLogics id={String(integrationId)}>
            <div className="@container flex flex-col gap-6">
                <ModalStep />
                <LemonButton
                    type="tertiary"
                    className="self-center"
                    to={urls.workflowsEmailDomain(integrationId)}
                    sideIcon={<IconExternal />}
                >
                    Open full page
                </LemonButton>
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

    useEffect(() => {
        // pinned: analytics event name
        posthog.capture('email domain setup started', { entry })
    }, [entry])

    return (
        <LemonModal
            title={integrationId ? 'Verify your sending domain' : 'Set up a sending domain'}
            width={720}
            onClose={() => onClose(integrationId ?? undefined)}
        >
            {integrationId ? (
                <ModalSettings integrationId={integrationId} />
            ) : (
                <div className="@container">
                    <DomainStep
                        logicKey="modal"
                        onCreated={(created) => {
                            setIntegrationId(created.id)
                            onComplete(created.id)
                        }}
                    />
                </div>
            )}
        </LemonModal>
    )
}
