import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Card, CardContent, CardHeader } from '@posthog/quill'

import { AiVisibilitySetupRestartDialog } from './AiVisibilitySetupRestartDialog'
import { AiVisibilitySetupResultsStep } from './AiVisibilitySetupResultsStep'
import { AiVisibilitySetupReviewStep } from './AiVisibilitySetupReviewStep'
import { type AiVisibilitySetupStepDefinition, AiVisibilitySetupStepper } from './AiVisibilitySetupStepper'
import { AiVisibilitySetupWebsiteStep } from './AiVisibilitySetupWebsiteStep'
import { SetupWizardStep, contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

const STEPS: AiVisibilitySetupStepDefinition[] = [
    // pinned: data-attr values are API for autocapture dashboards
    { step: 'website', label: 'Your website', dataAttr: 'ai-visibility-setup-step-website' },
    { step: 'review', label: 'Review', dataAttr: 'ai-visibility-setup-step-review' },
    { step: 'results', label: 'First results', dataAttr: 'ai-visibility-setup-step-results' },
]

const WAIT_REASON = 'Wait for the first check, or stop it'
const SITE_FIRST_REASON = 'Set up your website first'

export const AiVisibilitySetupWizard = ({ step }: { step: SetupWizardStep }): JSX.Element => {
    const { siteSetUp, runInProgress } = useValues(contentAutopilotSetupLogic)
    const { setWizardStep } = useActions(contentAutopilotSetupLogic)
    const [restartOpen, setRestartOpen] = useState(false)

    const running = runInProgress
    const disabledSteps: Partial<Record<SetupWizardStep, string>> = running
        ? { results: WAIT_REASON }
        : !siteSetUp
          ? { review: SITE_FIRST_REASON, results: SITE_FIRST_REASON }
          : {}
    delete disabledSteps[step]
    const goToStep = (target: SetupWizardStep): void =>
        target === 'website' && (siteSetUp || running) ? setRestartOpen(true) : setWizardStep(target)

    return (
        <Card className="w-full" data-attr="ai-visibility-setup-wizard">
            <CardHeader className="overflow-x-auto border-b">
                <AiVisibilitySetupStepper
                    steps={STEPS}
                    currentStep={step}
                    onStepClick={goToStep}
                    disabledSteps={disabledSteps}
                />
            </CardHeader>
            <CardContent className="p-6">
                {step === 'website' ? (
                    <AiVisibilitySetupWebsiteStep />
                ) : step === 'review' ? (
                    <AiVisibilitySetupReviewStep onStartAgain={() => setRestartOpen(true)} />
                ) : (
                    <AiVisibilitySetupResultsStep />
                )}
            </CardContent>
            <AiVisibilitySetupRestartDialog open={restartOpen} onOpenChange={setRestartOpen} />
        </Card>
    )
}
