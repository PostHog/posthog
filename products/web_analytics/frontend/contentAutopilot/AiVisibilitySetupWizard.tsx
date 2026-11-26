import { useActions, useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { GuidedWizardStep, GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'

import { AiVisibilitySetupResultsStep } from './AiVisibilitySetupResultsStep'
import { AiVisibilitySetupReviewStep } from './AiVisibilitySetupReviewStep'
import { AiVisibilitySetupWebsiteStep } from './AiVisibilitySetupWebsiteStep'
import { SetupWizardStep, contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'
import { openRestartSetupDialog } from './restartSetupDialog'

const STEPS: GuidedWizardStep<SetupWizardStep>[] = [
    // pinned: data-attr values are API for autocapture dashboards
    { step: 'website', label: 'Your website', dataAttr: 'ai-visibility-setup-step-website' },
    { step: 'review', label: 'Review', dataAttr: 'ai-visibility-setup-step-review' },
    { step: 'results', label: 'First results', dataAttr: 'ai-visibility-setup-step-results' },
]

const WAIT_REASON = 'Wait for the first check, or stop it'
const SITE_FIRST_REASON = 'Set up your website first'

export const AiVisibilitySetupWizard = ({ step }: { step: SetupWizardStep }): JSX.Element => {
    const { siteSetUp, runInProgress, setupContext } = useValues(contentAutopilotSetupLogic)
    const { setWizardStep, startAgain } = useActions(contentAutopilotSetupLogic)

    const running = runInProgress
    const disabledSteps: Partial<Record<SetupWizardStep, string>> = running
        ? { results: WAIT_REASON }
        : !siteSetUp
          ? { review: SITE_FIRST_REASON, results: SITE_FIRST_REASON }
          : {}
    delete disabledSteps[step]
    const goToStep = (target: SetupWizardStep): void =>
        target === 'website' && (siteSetUp || running)
            ? openRestartSetupDialog(setupContext, startAgain)
            : setWizardStep(target)

    return (
        <LemonCard hoverEffect={false} className="w-full p-0" data-attr="ai-visibility-setup-wizard">
            <div className="overflow-x-auto border-b px-4 py-3">
                <GuidedWizardStepper
                    steps={STEPS}
                    currentStep={step}
                    onStepClick={goToStep}
                    disabledSteps={disabledSteps}
                    aria-label="AI visibility setup"
                />
            </div>
            <div className="p-6">
                {step === 'website' ? (
                    <AiVisibilitySetupWebsiteStep />
                ) : step === 'review' ? (
                    <AiVisibilitySetupReviewStep />
                ) : (
                    <AiVisibilitySetupResultsStep />
                )}
            </div>
        </LemonCard>
    )
}
