import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { GuidedWizardStep, GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ContentStep } from './steps/ContentStep'
import { NameStep } from './steps/NameStep'
import { SenderStep } from './steps/SenderStep'
import { SendStep } from './steps/SendStep'
import { TransactionalEmailWizardStep, transactionalEmailWizardLogic } from './transactionalEmailWizardLogic'

const STEPS: GuidedWizardStep<TransactionalEmailWizardStep>[] = [
    { step: 'name', label: 'Name', dataAttr: 'transactional-email-wizard-step-name' },
    { step: 'sender', label: 'Sender', dataAttr: 'transactional-email-wizard-step-sender' },
    { step: 'content', label: 'Content', dataAttr: 'transactional-email-wizard-step-content' },
    { step: 'send', label: 'Send from your code', dataAttr: 'transactional-email-wizard-step-send' },
]

const STEP_CONTENT: Record<TransactionalEmailWizardStep, () => JSX.Element> = {
    name: NameStep,
    sender: SenderStep,
    content: ContentStep,
    send: SendStep,
}

export function TransactionalEmailWizard(): JSX.Element {
    useMountedLogic(transactionalEmailWizardLogic)
    const { currentStep, currentStepErrors, isCreating } = useValues(transactionalEmailWizardLogic)
    const { setStep, nextStep, previousStep, createTransactionalEmail } = useActions(transactionalEmailWizardLogic)
    const StepContent = STEP_CONTENT[currentStep]
    const isFirstStep = currentStep === STEPS[0].step
    const isLastStep = currentStep === STEPS[STEPS.length - 1].step

    return (
        <SceneContent data-attr="transactional-email-wizard">
            <SceneTitleSection
                name="New transactional email"
                description="Write the email once, then send it from your code with one API call"
                resourceType={{ type: 'transactional' }}
                actions={
                    <LemonButton type="secondary" size="small" to={urls.transactional()}>
                        Cancel
                    </LemonButton>
                }
            />
            <GuidedWizardStepper
                steps={STEPS}
                currentStep={currentStep}
                // The draft is already on its way, so edits made now would be lost.
                onStepClick={isCreating ? undefined : setStep}
                className="flex-wrap"
                aria-label="Transactional email wizard progress"
            />
            {/* The editor stays mounted, so an edit still saving when you leave Content isn't lost. */}
            <div hidden={currentStep !== 'content'}>
                <ContentStep />
            </div>
            {currentStep !== 'content' ? <StepContent /> : null}
            <div className="flex justify-between gap-2 border-t pt-3">
                {isFirstStep ? (
                    <span />
                ) : (
                    <LemonButton
                        type="secondary"
                        onClick={previousStep}
                        disabledReason={isCreating ? 'Creating the email' : undefined}
                    >
                        Back
                    </LemonButton>
                )}
                {isLastStep ? (
                    <LemonButton
                        type="primary"
                        onClick={createTransactionalEmail}
                        loading={isCreating}
                        data-attr="transactional-email-wizard-create"
                    >
                        Create transactional email
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        onClick={nextStep}
                        disabledReason={currentStepErrors[0]}
                        data-attr="transactional-email-wizard-next"
                    >
                        Next
                    </LemonButton>
                )}
            </div>
        </SceneContent>
    )
}
