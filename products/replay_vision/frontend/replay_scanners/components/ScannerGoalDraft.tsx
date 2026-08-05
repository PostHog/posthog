import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { replayScannerLogic } from '../replayScannerLogic'

/** "Tell PostHog AI what you want to accomplish" box on the template step: drafts a full scanner
 * from the stated goal and drops the user into the configure step to review it. */
export function ScannerGoalDraft(): JSX.Element {
    const [goal, setGoal] = useState('')
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const logic = replayScannerLogic({ id: 'new' })
    const { goalDraftLoading } = useValues(logic)
    const { draftScannerFromGoal } = useActions(logic)

    const handleSubmit = (): void => {
        if (goal.trim() && !goalDraftLoading) {
            draftScannerFromGoal(goal.trim())
        }
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-4">
                <div className="flex-1 border-t border-border" />
                <span className="text-xs text-tertiary uppercase tracking-wide">
                    or tell PostHog AI what you want to accomplish
                </span>
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
                        value={goal}
                        onChange={setGoal}
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
                            disabledReason={!goal.trim() ? 'Describe what the scanner should look for' : undefined}
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
