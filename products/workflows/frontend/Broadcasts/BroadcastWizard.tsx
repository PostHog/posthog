import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { urls } from 'scenes/urls'

import { broadcastWizardLogic } from './broadcastWizardLogic'
import { BroadcastWizardStepper } from './BroadcastWizardStepper'
import { BroadcastContentStep } from './steps/BroadcastContentStep'
import { BroadcastGoalStep } from './steps/BroadcastGoalStep'
import { BroadcastRecipientsStep } from './steps/BroadcastRecipientsStep'
import { BroadcastReviewStep } from './steps/BroadcastReviewStep'
import { BroadcastScheduleStep } from './steps/BroadcastScheduleStep'

export function BroadcastWizard(): JSX.Element {
    const { currentStep, name, stepValidationErrors, currentStepHasErrors, saving, launching, scheduleMode } =
        useValues(broadcastWizardLogic)
    const { setStep, prevStep, continueStep, launchBroadcast, setName } = useActions(broadcastWizardLogic)

    return (
        <div className="min-h-full w-full shrink-0 bg-bg-light">
            <div className="mx-auto max-w-4xl space-y-5 px-6 py-6">
                <div className="space-y-3">
                    <div className="flex items-center justify-between">
                        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.broadcasts()}>
                            Broadcasts
                        </LemonButton>
                    </div>
                    <div>
                        <label htmlFor="broadcast-name" className="text-xs font-medium text-muted">
                            Broadcast name
                        </label>
                        <EditableField
                            name="broadcast-name"
                            value={name}
                            onSave={(value) => setName(value)}
                            placeholder="Untitled broadcast"
                            saveOnBlur
                            clickToEdit
                            compactIcon
                            showEditIconOnHover
                            className="text-xl font-semibold"
                            editingIndication="underlined"
                        />
                    </div>
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
        </div>
    )
}
