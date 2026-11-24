import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AgentHandoffModal } from './components/AgentHandoffModal'
import { StepIndicator } from './components/StepIndicator'
import { emailDomainLogic } from './emailDomainLogic'
import { emailDomainSetupPath } from './emailDomainSetupLinks'
import { EmailDomainSteps } from './EmailDomainSteps'

export function EmailDomainSetup(): JSX.Element {
    const { phase, origin, originConfig } = useValues(emailDomainLogic)
    return (
        <div className="@container flex flex-col items-center px-4 py-8 @3xl:py-14">
            <div className="w-full max-w-160 flex flex-col gap-8">
                <LemonButton
                    type="tertiary"
                    size="small"
                    className="self-start"
                    icon={<IconArrowLeft />}
                    to={originConfig.backUrl}
                    data-attr={originConfig.backDataAttr}
                >
                    {originConfig.backLabel}
                </LemonButton>
                <StepIndicator phase={phase} />
                <EmailDomainSteps
                    domainLogicKey="page"
                    onDomainCreated={(integration) =>
                        router.actions.replace(emailDomainSetupPath(integration.id, origin))
                    }
                />
            </div>
            <AgentHandoffModal />
        </div>
    )
}
