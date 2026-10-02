import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { AgentHandoffModal } from './components/AgentHandoffModal'
import { StepIndicator } from './components/StepIndicator'
import { emailDomainLogic } from './emailDomainLogic'
import { DomainStep } from './steps/DomainStep'
import { ReadyStep } from './steps/ReadyStep'
import { SettingsStep } from './steps/SettingsStep'
import { UnavailableStep } from './steps/UnavailableStep'
import { VerifyingStep } from './steps/VerifyingStep'

function CurrentStep(): JSX.Element {
    const { phase } = useValues(emailDomainLogic)
    switch (phase) {
        case 'domain':
            return (
                <DomainStep
                    logicKey="page"
                    onCreated={(integration) => router.actions.replace(urls.workflowsEmailDomain(integration.id))}
                />
            )
        case 'loading':
            return (
                <div className="flex flex-col gap-4">
                    <LemonSkeleton className="h-32" />
                    <LemonSkeleton className="h-12" />
                    <LemonSkeleton className="h-40" />
                </div>
            )
        case 'unavailable':
            return <UnavailableStep />
        case 'settings':
            return <SettingsStep />
        case 'verifying':
            return <VerifyingStep />
        case 'ready':
            return <ReadyStep />
    }
}

export function EmailDomainSetup(): JSX.Element {
    const { phase } = useValues(emailDomainLogic)
    return (
        <div className="@container flex flex-col items-center px-4 py-8 @3xl:py-14">
            <div className="w-full max-w-160 flex flex-col gap-8">
                <StepIndicator phase={phase} />
                <CurrentStep />
            </div>
            <AgentHandoffModal />
        </div>
    )
}
