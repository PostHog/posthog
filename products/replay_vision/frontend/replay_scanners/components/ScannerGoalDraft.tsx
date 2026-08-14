import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'

/** "Tell PostHog AI what you want to accomplish" box on the template step and the zero-scanner
 * empty state: drafts a full scanner from the stated goal and drops the user into the details
 * step to review it. */
export function ScannerGoalDraft({
    gateSubmit,
}: {
    // Lets pre-consent surfaces interpose the AI consent popover before the draft request fires.
    gateSubmit?: (proceed: () => void) => void
}): JSX.Element {
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const logic = replayScannerLogic({ id: 'new' })
    const { goalDraftInput, goalDraftLoading } = useValues(logic)
    const { draftScannerFromGoal, setGoalDraftInput } = useActions(logic)

    // Drafting creates a scanner, so it needs the same editor access as the rest of the wizard.
    const editDisabledReason = getReplayVisionEditDisabledReason()

    const handleSubmit = (): void => {
        if (editDisabledReason || !goalDraftInput.trim() || goalDraftLoading) {
            return
        }
        const proceed = (): void => draftScannerFromGoal(goalDraftInput.trim())
        if (gateSubmit) {
            gateSubmit(proceed)
        } else {
            proceed()
        }
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-4">
                <div className="flex-1 border-t border-border" />
                <span className="text-xs text-tertiary uppercase tracking-wide">or describe what you want to find</span>
                <div className="flex-1 border-t border-border" />
            </div>

            <div className="rounded-xl border-2 border-[var(--color-ai)]">
                <label
                    htmlFor="vision-goal-draft-input"
                    className="flex flex-col cursor-text"
                    onClick={() => textAreaRef.current?.focus()}
                >
                    <LemonTextArea
                        id="vision-goal-draft-input"
                        ref={textAreaRef}
                        value={goalDraftInput}
                        onChange={setGoalDraftInput}
                        onPressEnter={handleSubmit}
                        placeholder="e.g., Find sessions where users get stuck during onboarding"
                        minRows={2}
                        maxRows={5}
                        className="!border-none !bg-transparent !shadow-none !rounded-none px-4 pt-4 pb-2 resize-none text-sm"
                        hideFocus
                        data-attr="vision-goal-draft-input"
                    />
                    <div className="flex items-center justify-between px-4 pb-3">
                        <div className="flex items-center gap-1.5 text-xs text-tertiary">
                            <IconSparkles className="text-ai size-3.5" />
                            <span>PostHog AI</span>
                        </div>
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconArrowRight />}
                            loading={goalDraftLoading}
                            onClick={handleSubmit}
                            disabledReason={
                                editDisabledReason ??
                                (!goalDraftInput.trim() ? 'Describe what the scanner should look for' : undefined)
                            }
                            data-attr="vision-goal-draft-submit"
                        >
                            Set up with AI
                        </LemonButton>
                    </div>
                </label>
            </div>
        </div>
    )
}
