import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { manageDisabledReason } from './broadcastLifecycle'
import { BroadcastSceneHeader } from './BroadcastSceneHeader'
import { broadcastWizardLogic } from './broadcastWizardLogic'
import { BroadcastWizardStepper } from './BroadcastWizardStepper'
import { BroadcastContentStep } from './steps/BroadcastContentStep'
import { BroadcastGoalStep } from './steps/BroadcastGoalStep'
import { BroadcastRecipientsStep } from './steps/BroadcastRecipientsStep'
import { BroadcastReviewStep } from './steps/BroadcastReviewStep'
import { BroadcastScheduleStep } from './steps/BroadcastScheduleStep'

export function BroadcastWizard(): JSX.Element {
    const { currentStep, stepValidationErrors, currentStepHasErrors, saving, launching, scheduleMode } =
        useValues(broadcastWizardLogic)
    const { setStep, prevStep, continueStep, launchBroadcast, archiveBroadcast } = useActions(broadcastWizardLogic)
    const { broadcastId, broadcast } = useValues(broadcastWizardLogic)

    return (
        <SceneContent className="min-h-full w-full shrink-0" data-attr="broadcast-wizard">
            <BroadcastSceneHeader
                canEdit
                actions={
                    // A draft not saved yet has nothing to archive.
                    broadcastId ? (
                        <LemonMenu
                            items={[
                                {
                                    label: 'Archive',
                                    status: 'danger',
                                    onClick: archiveBroadcast,
                                    disabledReason:
                                        manageDisabledReason(broadcast?.user_access_level) ??
                                        (saving || launching ? 'Wait for the broadcast to finish saving' : undefined),
                                    'data-attr': 'broadcast-archive',
                                },
                            ]}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                sideIcon={<IconChevronDown />}
                                data-attr="broadcast-actions"
                            >
                                Actions
                            </LemonButton>
                        </LemonMenu>
                    ) : undefined
                }
            />
            <div className="mx-auto w-full max-w-4xl space-y-5">
                <div className="space-y-3">
                    <div className="flex justify-center">
                        <BroadcastWizardStepper
                            currentStep={currentStep}
                            onStepClick={setStep}
                            stepErrors={stepValidationErrors}
                        />
                    </div>
                </div>

                <div>
                    {currentStep === 'recipients' && <BroadcastRecipientsStep />}
                    {currentStep === 'goal' && <BroadcastGoalStep />}
                    {currentStep === 'content' && <BroadcastContentStep />}
                    {currentStep === 'schedule' && <BroadcastScheduleStep />}
                    {currentStep === 'review' && <BroadcastReviewStep />}
                </div>

                <div className="flex items-center justify-between border-t border-border pt-4">
                    <div>
                        {currentStep !== 'recipients' && (
                            <LemonButton type="secondary" onClick={prevStep} disabled={saving || launching}>
                                Back
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        {currentStep === 'review' ? (
                            <LemonButton
                                type="primary"
                                loading={launching}
                                disabled={saving}
                                disabledReason={
                                    stepValidationErrors.review.length > 0
                                        ? 'Fix the issues above before sending'
                                        : undefined
                                }
                                onClick={launchBroadcast}
                                data-attr="broadcast-wizard-launch"
                            >
                                {scheduleMode === 'now' ? 'Send now' : 'Schedule broadcast'}
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                loading={saving}
                                disabled={launching}
                                disabledReason={currentStepHasErrors ? 'Fix errors before continuing' : undefined}
                                onClick={continueStep}
                                data-attr="broadcast-wizard-continue"
                            >
                                Continue
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>
        </SceneContent>
    )
}
