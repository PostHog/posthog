import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { analysisNudgeLogic } from '../logics/analysisNudgeLogic'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'

/** Card overlaying the player once the user has analyzed a few recordings this session:
 * collects what they're looking for and hands it to the scanner creation wizard's AI draft. */
export function AnalysisNudge(): JSX.Element | null {
    const { nudgeVisible, goalInput } = useValues(analysisNudgeLogic)
    const { dismissNudge, setGoalInput, submitGoal } = useActions(analysisNudgeLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    // Creating a scanner needs editor access, so users who couldn't finish the flow never see it.
    if (!nudgeVisible || getReplayVisionEditDisabledReason()) {
        return null
    }

    const handleSubmit = (): void => {
        const goal = goalInput.trim()
        if (!goal) {
            return
        }
        if (dataProcessingAccepted) {
            submitGoal(goal)
        } else {
            setConsentRequested(true)
        }
    }

    return (
        <div
            className="absolute bottom-16 right-4 z-10 w-80 rounded-lg border bg-bg-light shadow-md p-3 flex flex-col gap-2"
            data-attr="vision-analysis-nudge"
        >
            <div className="flex items-center gap-1.5">
                <IconSparkles className="text-ai size-4" />
                <span className="font-semibold text-sm flex-1">Looking for something specific?</span>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={dismissNudge}
                    tooltip="Dismiss"
                    data-attr="vision-analysis-nudge-dismiss"
                />
            </div>
            <p className="text-xs text-secondary mb-0">
                Tell PostHog AI what you're looking for and it'll set up a scanner that watches every new recording for
                it.
            </p>
            <LemonTextArea
                value={goalInput}
                onChange={setGoalInput}
                onPressEnter={handleSubmit}
                placeholder="e.g., Find sessions where users get stuck during onboarding"
                minRows={2}
                maxRows={4}
                data-attr="vision-analysis-nudge-input"
            />
            <AIConsentPopoverWrapper
                placement="top"
                showArrow
                ignoreDismissal
                hideTrainingDisclaimer
                hidden={!consentRequested}
                onApprove={() => {
                    setConsentRequested(false)
                    submitGoal(goalInput.trim())
                }}
                onDismiss={() => setConsentRequested(false)}
            >
                <LemonButton
                    type="primary"
                    size="small"
                    fullWidth
                    center
                    onClick={handleSubmit}
                    disabledReason={!goalInput.trim() ? 'Describe what the scanner should look for' : undefined}
                    data-attr="vision-analysis-nudge-submit"
                >
                    Create a scanner with AI
                </LemonButton>
            </AIConsentPopoverWrapper>
        </div>
    )
}
