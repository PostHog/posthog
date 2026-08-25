import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Popover } from 'lib/lemon-ui/Popover'

import { InboxQuestionSource, captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'

// How much of a suggestion a draft has to keep, at one end or the other, to still count as an edit
// of it. Long enough that two questions opening on the same few words ("Which teams…", "Why did…")
// don't read as one, short enough that a heavy rewrite around a kept phrase still does.
const RECOGNIZABLE_RUN = 10

/** Whether a submitted draft is still the suggestion it was filled from, rather than a fresh question. */
function isEditOf(draft: string, suggestion: string): boolean {
    if (draft.length < RECOGNIZABLE_RUN || suggestion.length < RECOGNIZABLE_RUN) {
        return draft === suggestion
    }
    return (
        draft.slice(0, RECOGNIZABLE_RUN) === suggestion.slice(0, RECOGNIZABLE_RUN) ||
        draft.slice(-RECOGNIZABLE_RUN) === suggestion.slice(-RECOGNIZABLE_RUN)
    )
}

export function DiscussReportButton({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const { isDiscussing, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { discussReport } = useActions(inboxTaskKickoffLogic)
    const buttonRef = useRef<HTMLButtonElement>(null)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const [isOpen, setIsOpen] = useState(false)
    const [question, setQuestion] = useState('')
    // The suggestion the textarea was last filled from, so a submitted question can be reported as
    // sent as written, edited first, or written from scratch. Null until a row is clicked.
    const [filledFrom, setFilledFrom] = useState<string | null>(null)

    const suggestions = report.suggested_prompts ?? []

    const questionSource = (trimmed: string): InboxQuestionSource => {
        if (filledFrom === null) {
            return 'typed'
        }
        if (trimmed === filledFrom) {
            return 'suggested'
        }
        // Selecting the filled box and typing over it leaves nothing of the suggestion, so the
        // question is the reader's own. Counting it as an edit would read as adoption.
        return isEditOf(trimmed, filledFrom) ? 'edited_suggestion' : 'typed'
    }

    const fillFromSuggestion = (suggestion: string): void => {
        setQuestion(suggestion)
        setFilledFrom(suggestion)
        // Fills the box and stops. The reader still presses Ask AI, so a mis-click costs nothing and
        // a suggestion that is nearly right can be edited before it spends a run.
        textAreaRef.current?.focus()
    }

    const submit = (): void => {
        const trimmed = question.trim()
        // Cmd/Ctrl + Enter submits straight from the textarea, so it never sees the button's
        // `loading`/`disabledReason` – each guard has to hold here too, or an impatient second
        // press fires another paid task run for the same report.
        if (!trimmed || isDiscussing) {
            return
        }
        if (aiConsentDisabledReason) {
            lemonToast.error(aiConsentDisabledReason)
            return
        }
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'detail_pane',
            extra: discussQuestionProperties({
                source: questionSource(trimmed),
                suggestionCount: suggestions.length,
            }),
        })
        // The popover stays open on its spinner until the run is created and we navigate to it, so
        // the request is visibly in flight and a failure leaves the draft question to retry with.
        discussReport(report, reportUrl, trimmed)
    }

    return (
        <Popover
            visible={isOpen}
            onClickOutside={(event) => {
                if (event.target instanceof Node && buttonRef.current?.contains(event.target)) {
                    return
                }
                setIsOpen(false)
            }}
            placement="bottom-end"
            overlay={
                <div className="flex flex-col gap-2 p-2 w-[22rem]">
                    {suggestions.length > 0 && (
                        <div className="flex flex-col gap-1">
                            <span className="text-xs font-semibold text-tertiary">Suggested questions</span>
                            {suggestions.map((suggestion) => (
                                <LemonButton
                                    key={suggestion}
                                    // Secondary, not tertiary: these sit above a textarea rather than
                                    // in a menu, so with no border at rest they read as a bulleted
                                    // list and the reader never learns the rows are clickable.
                                    type="secondary"
                                    size="small"
                                    fullWidth
                                    disabledReason={isDiscussing ? 'Already asking AI' : undefined}
                                    onClick={() => fillFromSuggestion(suggestion)}
                                    data-attr="inbox-report-suggested-prompt"
                                >
                                    {suggestion}
                                </LemonButton>
                            ))}
                        </div>
                    )}
                    <LemonTextArea
                        ref={textAreaRef}
                        value={question}
                        onChange={setQuestion}
                        onPressCmdEnter={submit}
                        placeholder={
                            suggestions.length > 0
                                ? 'Pick a question above, or ask your own'
                                : 'What would you like to ask about this report?'
                        }
                        maxLength={4000}
                        rows={4}
                        // Focusing the textarea scrolls it into view, which on a short viewport pushes
                        // the suggestions above the popover's visible area — so a report that offers
                        // questions opens on the questions, and one that doesn't opens ready to type.
                        autoFocus={suggestions.length === 0}
                        rightFooter={<span className="text-xs text-tertiary">Cmd/Ctrl + Enter to ask AI</span>}
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={submit}
                            loading={isDiscussing}
                            disabledReason={
                                aiConsentDisabledReason ?? (question.trim() ? undefined : 'Enter a question first')
                            }
                            data-attr="inbox-report-ask-ai-submit"
                        >
                            Ask AI
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                ref={buttonRef}
                type="secondary"
                size="small"
                icon={<IconSparkles />}
                sideIcon={null}
                active={isOpen}
                loading={isDiscussing}
                onClick={() => setIsOpen((open) => !open)}
                tooltip="Ask AI about this report"
            >
                Ask AI
            </LemonButton>
        </Popover>
    )
}
