import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { GuidedWizardPanel } from 'lib/components/GuidedWizard/GuidedWizardPanel'
import { GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'
import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WorkflowFromDestinationConnectStep } from './WorkflowFromDestinationConnectStep'
import {
    WorkflowFromDestinationLogicProps,
    WorkflowFromDestinationStep,
    workflowFromDestinationLogic,
} from './workflowFromDestinationLogic'
import { WorkflowFromDestinationMessageStep } from './WorkflowFromDestinationMessageStep'
import { WorkflowFromDestinationTriggerStep } from './WorkflowFromDestinationTriggerStep'

export const scene: SceneExport<WorkflowFromDestinationLogicProps> = {
    component: WorkflowFromDestinationScene,
    logic: workflowFromDestinationLogic,
    paramsToProps: ({ params: { templateId } }) => ({ templateId }),
    productKey: ProductKey.WORKFLOWS,
}

const STEP_LABELS: Record<WorkflowFromDestinationStep, string> = {
    trigger: 'Trigger',
    connect: 'Connect',
    message: 'Message',
}

export function WorkflowFromDestinationScene({ templateId }: WorkflowFromDestinationLogicProps): JSX.Element {
    const logic = workflowFromDestinationLogic({ templateId })
    const {
        template,
        templateLoadFailed,
        steps,
        currentStep,
        currentStepIndex,
        isLastStep,
        stepErrors,
        createdWorkflowLoading,
    } = useValues(logic)
    const { setStep, goToNextStep, goToPreviousStep, submitWizard, resetWizard } = useActions(logic)

    if (templateLoadFailed || (template && template.type !== 'destination')) {
        return (
            <NotFound
                object="destination template"
                caption={
                    <>
                        This template cannot be set up as a workflow. Go back to{' '}
                        <Link to={urls.destinations()}>destinations</Link> or start from a blank{' '}
                        <Link to={urls.workflowNew()}>workflow</Link>.
                    </>
                }
            />
        )
    }

    if (!template) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton className="h-40" />
            </SceneContent>
        )
    }

    const disabledSteps = Object.fromEntries(
        steps.slice(currentStepIndex + 1).map((step) => [step, 'Finish the current step first'])
    ) as Partial<Record<WorkflowFromDestinationStep, string>>

    return (
        <SceneContent data-attr="workflow-from-destination-scene">
            <SceneTitleSection
                name={`New ${template.name} workflow`}
                description="Set up the trigger and the message, then review the workflow in the editor."
                resourceType={{ type: 'workflows' }}
            />
            <LemonBanner type="info">
                {template.name} destinations are now created as workflows. A workflow triggers on the same events and
                sends the same message, and it can also add delays, conditions and more steps.{' '}
                <Link to={urls.destinations()} onClick={resetWizard}>
                    Back to destinations
                </Link>
            </LemonBanner>
            <GuidedWizardStepper
                steps={steps.map((step) => ({
                    step,
                    label: STEP_LABELS[step],
                    dataAttr: `workflow-from-destination-step-${step}`,
                }))}
                currentStep={currentStep}
                onStepClick={setStep}
                stepErrors={stepErrors}
                disabledSteps={disabledSteps}
            />
            <GuidedWizardPanel>
                {currentStep === 'trigger' ? (
                    <WorkflowFromDestinationTriggerStep templateId={templateId} />
                ) : currentStep === 'connect' ? (
                    <WorkflowFromDestinationConnectStep templateId={templateId} />
                ) : (
                    <WorkflowFromDestinationMessageStep templateId={templateId} />
                )}
            </GuidedWizardPanel>
            <div className="flex flex-wrap justify-between gap-2">
                <LemonButton
                    type="secondary"
                    onClick={goToPreviousStep}
                    disabledReason={currentStepIndex === 0 ? 'This is the first step' : undefined}
                    data-attr="workflow-from-destination-back"
                >
                    Back
                </LemonButton>
                {isLastStep ? (
                    <LemonButton
                        type="primary"
                        onClick={submitWizard}
                        loading={createdWorkflowLoading}
                        data-attr="workflow-from-destination-create"
                    >
                        Create workflow
                    </LemonButton>
                ) : (
                    <LemonButton type="primary" onClick={goToNextStep} data-attr="workflow-from-destination-next">
                        Next
                    </LemonButton>
                )}
            </div>
        </SceneContent>
    )
}
