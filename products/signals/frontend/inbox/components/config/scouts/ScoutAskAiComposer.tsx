import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { captureScoutAction } from '../../../inboxAnalytics'
import { SCOUT_AI_STARTER_QUESTIONS, scoutAiLogic } from '../../../logics/scoutAiLogic'

/** A one-line question box under the scout header. The answer runs in the PostHog AI side panel. */
export function ScoutAskAiComposer({ skillName, scoutName }: { skillName: string; scoutName: string }): JSX.Element {
    const { isAsking, aiConsentDisabledReason } = useValues(scoutAiLogic)
    const { askScout } = useActions(scoutAiLogic)
    const [draft, setDraft] = useState('')
    const [starterId, setStarterId] = useState<string | null>(null)
    const focusCapturedRef = useRef(false)
    const inputRef = useRef<HTMLInputElement>(null)

    const submitDisabledReason = aiConsentDisabledReason ?? (draft.trim() ? undefined : 'Type a question first')

    const submit = (): void => {
        if (submitDisabledReason || isAsking) {
            return
        }
        // The question text stays out of analytics: it can name customer data.
        captureScoutAction({
            actionType: 'ask_ai',
            surface: 'scout_detail',
            skillName,
            extra: { source: starterId ? 'starter' : 'typed', starter_id: starterId },
        })
        askScout({ skillName, scoutName }, draft)
        setDraft('')
        setStarterId(null)
    }

    return (
        <div className="flex flex-col gap-2 border-b border-primary bg-surface-primary px-4 py-2">
            <div className="flex items-center gap-2">
                <LemonInput
                    inputRef={inputRef}
                    className="min-w-0 flex-1"
                    size="small"
                    prefix={<IconSparkles className="text-secondary" />}
                    placeholder={`Ask ${scoutName} anything…`}
                    value={draft}
                    onChange={(value) => {
                        setDraft(value)
                        // An edited starter is the person's own question now.
                        setStarterId(null)
                    }}
                    onPressEnter={submit}
                    onFocus={() => {
                        if (focusCapturedRef.current) {
                            return
                        }
                        focusCapturedRef.current = true
                        captureScoutAction({ actionType: 'focus_ask_ai', surface: 'scout_detail', skillName })
                    }}
                    disabled={!!aiConsentDisabledReason}
                    data-attr="scout-ask-ai-input"
                />
                <LemonButton
                    type="primary"
                    size="small"
                    loading={isAsking}
                    disabledReason={submitDisabledReason}
                    onClick={submit}
                    data-attr="scout-ask-ai-submit"
                >
                    Ask
                </LemonButton>
            </div>
            {aiConsentDisabledReason ? (
                <span className="text-xs text-secondary">{aiConsentDisabledReason}</span>
            ) : (
                <div className="flex flex-wrap gap-1.5">
                    {SCOUT_AI_STARTER_QUESTIONS.map(({ id, question }) => (
                        <LemonButton
                            key={id}
                            type="secondary"
                            size="xsmall"
                            onClick={() => {
                                captureScoutAction({
                                    actionType: 'click_ask_ai_starter',
                                    surface: 'scout_detail',
                                    skillName,
                                    extra: { starter_id: id },
                                })
                                setDraft(question)
                                setStarterId(id)
                                inputRef.current?.focus()
                            }}
                            data-attr="scout-ask-ai-starter"
                        >
                            {question}
                        </LemonButton>
                    ))}
                </div>
            )}
        </div>
    )
}
