import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { analysisNudgeLogic } from '../logics/analysisNudgeLogic'
import { consumeGoalDraftIntent, markGoalDraftIntent } from '../replay_scanners/goalDraftIntent'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'

/** Card overlaying the player once the user has analyzed a few recordings this session:
 * collects what they're looking for and hands it to the scanner creation wizard's AI draft. */
export function AnalysisNudge(): JSX.Element | null {
    const { nudgeVisible, goalInput } = useValues(analysisNudgeLogic)
    const { dismissNudge, setGoalInput, submitGoal } = useActions(analysisNudgeLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    // The exact goal that initiated the consent ask; approving submits this, not the live input,
    // so edits made while the popover is open can't be sent unvalidated (or blank).
    const [pendingConsentGoal, setPendingConsentGoal] = useState<string | null>(null)

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
            // Stored before the consent ask: approving can trigger a full-page SSO reauth that
            // unloads before onApprove runs, and on return the wizard (pendingRedirectUrl below)
            // picks the goal up from the hand-off instead of losing it.
            markGoalDraftIntent(goal)
            setPendingConsentGoal(goal)
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
                hidden={pendingConsentGoal === null}
                pendingRedirectUrl={urls.replayVisionTemplates()}
                onApprove={() => {
                    if (pendingConsentGoal) {
                        submitGoal(pendingConsentGoal)
                    }
                    setPendingConsentGoal(null)
                }}
                onDismiss={() => {
                    // Disarm the hand-off so a later wizard visit can't auto-start a draft the
                    // user backed out of.
                    consumeGoalDraftIntent()
                    setPendingConsentGoal(null)
                }}
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
