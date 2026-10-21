import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import {
    isRealtimeCohortCalculating,
    realtimeCohortSendBlockedReason,
} from '../Workflows/hogflows/steps/realtimeCohortStatus'
import { manageDisabledReason } from './broadcastLifecycle'
import { BroadcastSceneHeader } from './BroadcastSceneHeader'
import { broadcastWizardLogic } from './broadcastWizardLogic'
import { BroadcastWizardStepper } from './BroadcastWizardStepper'
import { QuillBroadcastActionsMenu } from './QuillBroadcastActionsMenu'
import { BroadcastContentStep } from './steps/BroadcastContentStep'
import { BroadcastGoalStep } from './steps/BroadcastGoalStep'
import { BroadcastRecipientsStep } from './steps/BroadcastRecipientsStep'
import { BroadcastReviewStep } from './steps/BroadcastReviewStep'
import { BroadcastScheduleStep } from './steps/BroadcastScheduleStep'
import { useBroadcastAgentPanel } from './useBroadcastAgentPanel'

export function BroadcastWizard(): JSX.Element {
    const { currentStep, stepValidationErrors, currentStepHasErrors, saving, launching, scheduleMode, blastRadius } =
        useValues(broadcastWizardLogic)
    const realtimeCohort = blastRadius?.realtime_cohort
    const { setStep, prevStep, continueStep, launchBroadcast, archiveBroadcast, openInWorkflowEditor } =
        useActions(broadcastWizardLogic)
    const { broadcastId, broadcast } = useValues(broadcastWizardLogic)
    useBroadcastAgentPanel()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <SceneContent className="min-h-full w-full shrink-0" data-attr="broadcast-wizard">
            <BroadcastSceneHeader
                canEdit
                actions={
                    // A draft not saved yet has nothing to archive.
                    broadcastId ? (
                        todayRailNav ? (
                            <QuillBroadcastActionsMenu
                                items={[
                                    {
                                        label: 'Open in workflow editor',
                                        onClick: openInWorkflowEditor,
                                        disabledReason:
                                            saving || launching ? 'Wait for the broadcast to finish saving' : undefined,
                                        'data-attr': 'broadcast-open-in-workflow-editor',
                                    },
                                    {
                                        label: 'Archive',
                                        danger: true,
                                        onClick: archiveBroadcast,
                                        disabledReason:
                                            manageDisabledReason(broadcast?.user_access_level) ??
                                            (saving || launching
                                                ? 'Wait for the broadcast to finish saving'
                                                : undefined),
                                        'data-attr': 'broadcast-archive',
                                    },
                                ]}
                            />
                        ) : (
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Open in workflow editor',
                                        onClick: openInWorkflowEditor,
                                        disabledReason:
                                            saving || launching ? 'Wait for the broadcast to finish saving' : undefined,
                                        'data-attr': 'broadcast-open-in-workflow-editor',
                                    },
                                    {
                                        label: 'Archive',
                                        status: 'danger',
                                        onClick: archiveBroadcast,
                                        disabledReason:
                                            manageDisabledReason(broadcast?.user_access_level) ??
                                            (saving || launching
                                                ? 'Wait for the broadcast to finish saving'
                                                : undefined),
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
                        )
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
                                        : realtimeCohortSendBlockedReason(realtimeCohort)
                                }
                                onClick={launchBroadcast}
                                data-attr="broadcast-wizard-launch"
                            >
                                {scheduleMode !== 'now'
                                    ? 'Schedule broadcast'
                                    : isRealtimeCohortCalculating(realtimeCohort)
                                      ? 'Send when calculated'
                                      : 'Send now'}
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
