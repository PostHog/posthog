import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { emailDomainLogic } from './emailDomainLogic'
import { EmailDomainWizardLogicProps } from './emailDomainWizardLogic'
import { DomainStep } from './steps/DomainStep'
import { ReadyStep } from './steps/ReadyStep'
import { SettingsStep } from './steps/SettingsStep'
import { UnavailableStep } from './steps/UnavailableStep'
import { VerifyingStep } from './steps/VerifyingStep'

export interface EmailDomainStepsProps {
    domainLogicKey: string
    onDomainCreated: EmailDomainWizardLogicProps['onCreated']
    readyNextStep?: JSX.Element
    existingOpensNewTab?: boolean
}

export function EmailDomainSteps({
    domainLogicKey,
    onDomainCreated,
    readyNextStep,
    existingOpensNewTab,
}: EmailDomainStepsProps): JSX.Element {
    const { phase } = useValues(emailDomainLogic)
    switch (phase) {
        case 'domain':
            return (
                <DomainStep
                    logicKey={domainLogicKey}
                    onCreated={onDomainCreated}
                    existingOpensNewTab={existingOpensNewTab}
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
            return <ReadyStep nextStep={readyNextStep} />
    }
}
