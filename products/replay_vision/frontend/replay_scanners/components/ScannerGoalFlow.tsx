import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'

// Credits, not recordings: the agent picks the model, so a fixed recording count no longer maps to
// a fixed cost. The budget is what the user actually controls, and matches how we bill.
const MIN_SCAN_BUDGET = 1
const MAX_SCAN_BUDGET = 100000000

/** The goal-based creation flow's two questions (goal, monthly budget): drafts a full scanner
 * and lands the user on the overview step to review it. */
export function ScannerGoalFlow({ onManual }: { onManual: () => void }): JSX.Element {
    const logic = replayScannerLogic({ id: 'new' })
    const { goalDraftInput, goalBudgetInput, goalDraftLoading } = useValues(logic)
    const { draftScannerFromGoal, setGoalDraftInput, setGoalBudgetInput } = useActions(logic)

    // Drafting creates a scanner, so it needs the same editor access as the rest of the wizard.
    const editDisabledReason = getReplayVisionEditDisabledReason()
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    const budgetValid =
        goalBudgetInput != null && goalBudgetInput >= MIN_SCAN_BUDGET && goalBudgetInput <= MAX_SCAN_BUDGET

    const submit = (): void => {
        draftScannerFromGoal(goalDraftInput.trim(), goalBudgetInput ?? undefined)
    }
    const handleSubmit = (): void => {
        if (editDisabledReason || !goalDraftInput.trim() || !budgetValid || goalDraftLoading) {
            return
        }
        // Drafting calls an AI endpoint the backend rejects without org consent; interpose the
        // popover instead of letting the request 400.
        if (!dataProcessingAccepted) {
            setConsentRequested(true)
            return
        }
        submit()
    }

    return (
        <div className="space-y-4">
            <div className="rounded-xl border-2 border-[var(--color-ai)] p-4 flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <label htmlFor="vision-goal-flow-goal" className="text-sm font-medium">
                        What do you want to find out?
                    </label>
                    <LemonTextArea
                        id="vision-goal-flow-goal"
                        value={goalDraftInput}
                        onChange={setGoalDraftInput}
                        placeholder="e.g. Find out where people give up in billing"
                        minRows={2}
                        maxRows={5}
                        data-attr="vision-goal-flow-goal"
                    />
                    <div className="text-xs text-muted">
                        Say what to learn and which part of the product to watch. The agent maps it onto your real
                        pages.
                    </div>
                </div>

                <div className="flex flex-col gap-1">
                    <label htmlFor="vision-goal-flow-budget" className="text-sm font-medium">
                        About how much do you want to spend a month?
                    </label>
                    <div className="flex items-center gap-3">
                        <LemonInput
                            id="vision-goal-flow-budget"
                            type="number"
                            min={MIN_SCAN_BUDGET}
                            max={MAX_SCAN_BUDGET}
                            value={goalBudgetInput ?? undefined}
                            onChange={(value) => setGoalBudgetInput(value ?? null)}
                            suffix={<span className="text-muted">credits</span>}
                            className="w-40"
                            data-attr="vision-goal-flow-budget"
                        />
                        {budgetValid && goalBudgetInput != null ? (
                            <span className="text-xs text-muted">≈ {creditsToUsd(goalBudgetInput)} a month</span>
                        ) : null}
                    </div>
                    <div className="text-xs text-muted">
                        1,000 credits ≈ $10. The agent picks the model and fits the scanner to this.
                    </div>
                </div>

                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-xs text-tertiary">
                        <IconSparkles className="text-ai size-3.5" />
                        <span>PostHog AI</span>
                    </div>
                    <AIConsentPopoverWrapper
                        placement="bottom-end"
                        showArrow
                        ignoreDismissal
                        hideTrainingDisclaimer
                        hidden={!consentRequested}
                        onApprove={() => {
                            setConsentRequested(false)
                            submit()
                        }}
                        onDismiss={() => setConsentRequested(false)}
                    >
                        <LemonButton
                            type="primary"
                            loading={goalDraftLoading}
                            onClick={handleSubmit}
                            // The button is the popover's reference, so Lemon would add a dropdown
                            // chevron; it submits rather than opening a menu, so suppress it.
                            sideIcon={null}
                            disabledReason={
                                editDisabledReason ??
                                (!goalDraftInput.trim()
                                    ? 'Describe what you want to find out'
                                    : !budgetValid
                                      ? 'Enter a monthly credit budget'
                                      : undefined)
                            }
                            data-attr="vision-goal-flow-submit"
                        >
                            Draft my scanner
                        </LemonButton>
                    </AIConsentPopoverWrapper>
                </div>
            </div>

            <div className="flex items-center gap-4">
                <div className="flex-1 border-t border-border" />
                <span className="text-xs text-tertiary uppercase tracking-wide">or</span>
                <div className="flex-1 border-t border-border" />
            </div>

            <div className="text-center">
                <Link onClick={onManual} data-attr="vision-goal-flow-manual">
                    Set it up manually
                </Link>
            </div>
        </div>
    )
}
