import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { CustomerIOImportModal } from '../../OptOuts/CustomerIOImportModal'
import { OptOutCategories } from '../../OptOuts/OptOutCategories'
import { OnboardingWizardStepper } from './OnboardingWizardStepper'
import { WIZARD_STEP_COPY } from './onboardingWizardSteps'
import { WizardChannelStep } from './WizardChannelStep'
import { WizardConnectStep } from './WizardConnectStep'
import { WizardCreateStep } from './WizardCreateStep'
import { WizardDomainStep } from './WizardDomainStep'
import { WizardPushStep } from './WizardPushStep'
import { WizardTemplateStep } from './WizardTemplateStep'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

/** The first-run setup for one path, one step at a time, ending in the workflow editor. */
export function WorkflowsOnboardingWizard(): JSX.Element {
    const {
        wizardPath,
        stepKeys,
        stepIndex,
        currentStep,
        stepDone,
        isLastStep,
        continueDisabledReason,
        setupCheckFailed,
    } = useValues(workflowsOnboardingWizardLogic)
    const { setStepIndex, next, back, exit, loadHasMessagingWorkflow } = useActions(workflowsOnboardingWizardLogic)

    const copy = WIZARD_STEP_COPY[currentStep]
    const isSkip = copy.optional && !stepDone?.[currentStep]
    const continueLabel = isLastStep ? 'Open in editor' : isSkip ? 'Skip for now' : 'Continue'

    return (
        <div className="mx-auto w-full max-w-4xl flex flex-col gap-6 py-4" data-attr="workflows-onboarding-wizard">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <LemonTag type={wizardPath === 'messaging' ? 'completion' : 'default'}>
                        {wizardPath === 'messaging' ? 'Message your users' : 'Automate a process'}
                    </LemonTag>
                    <span className="text-secondary text-sm">{`Step ${stepIndex + 1} of ${stepKeys.length}`}</span>
                </div>
                <LemonButton size="small" type="tertiary" onClick={exit} data-attr="workflows-onboarding-wizard-exit">
                    Exit setup
                </LemonButton>
            </div>
            {setupCheckFailed && wizardPath === 'messaging' && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: loadHasMessagingWorkflow,
                        'data-attr': 'workflows-onboarding-wizard-retry-setup-check',
                    }}
                >
                    We couldn't check your setup, so some steps may show as not done.
                </LemonBanner>
            )}
            <OnboardingWizardStepper
                steps={stepKeys}
                currentIndex={stepIndex}
                stepDone={stepDone}
                onStepClick={setStepIndex}
            />
            <div>
                <h2 className="mb-1 text-xl font-bold">{copy.title}</h2>
                <p className="mb-0 text-secondary">{copy.description}</p>
                {currentStep === 'journey' && (
                    <div className="mt-1 text-secondary">
                        Sending one email to a list of people?{' '}
                        <Link
                            to={urls.broadcastNew()}
                            onClick={() => {
                                // pinned: analytics event name - renaming breaks dashboards
                                posthog.capture('workflows onboarding wizard broadcast clicked')
                            }}
                            data-attr="workflows-onboarding-wizard-broadcast"
                        >
                            Create a broadcast instead
                        </Link>
                        .
                    </div>
                )}
            </div>
            <LemonCard hoverEffect={false} className="p-6">
                {currentStep === 'channel' && <WizardChannelStep />}
                {currentStep === 'domain' && <WizardDomainStep />}
                {currentStep === 'opt-outs' && (
                    <>
                        <OptOutCategories />
                        <CustomerIOImportModal />
                    </>
                )}
                {currentStep === 'push' && <WizardPushStep />}
                {(currentStep === 'journey' || currentStep === 'template') && <WizardTemplateStep />}
                {currentStep === 'connect' && <WizardConnectStep />}
                {currentStep === 'create' && <WizardCreateStep />}
            </LemonCard>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
                <div>
                    {stepIndex > 0 && (
                        <LemonButton type="secondary" onClick={back} data-attr="workflows-onboarding-wizard-back">
                            Back
                        </LemonButton>
                    )}
                </div>
                <LemonButton
                    type={isSkip && !isLastStep ? 'secondary' : 'primary'}
                    onClick={next}
                    disabledReason={continueDisabledReason ?? undefined}
                    data-attr={`workflows-onboarding-wizard-next-${currentStep}`}
                >
                    {continueLabel}
                </LemonButton>
            </div>
        </div>
    )
}
