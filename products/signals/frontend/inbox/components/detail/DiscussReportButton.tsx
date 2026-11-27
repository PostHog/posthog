import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { REPORT_DISCUSSION_QUESTION_MAX_LENGTH } from '../../inboxTaskKickoffLogic'
import { reportQuickAskLogic } from '../../logics/reportQuickAskLogic'
import { SignalReport } from '../../types'
import { REPORT_PR_AI_ACTION_ICONS } from './reportPrAiActionIcons'

export function DiscussReportButton({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const logic = reportQuickAskLogic({ report, reportUrl })
    const { isDiscussing, disabledReason, placeholder, suggestions, question, isOpen, prActions } = useValues(logic)
    const { setQuestion, setOpen, fillFromSuggestion, submit, openInSidebar, startPrAction } = useActions(logic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const items: LemonMenuItems = prActions.map((action) => ({
        label: action.label,
        icon: REPORT_PR_AI_ACTION_ICONS[action.key],
        tooltip: action.tooltip,
        onClick: () => startPrAction(action),
        disabledReason: action.disabledReason,
        'data-attr': action.dataAttr,
    }))

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles />}
            loading={isDiscussing}
            disabledReason={disabledReason}
            onClick={openInSidebar}
            tooltip="Ask PostHog AI about this report in the sidebar"
            sideAction={{
                tooltip: 'Quick ask and more AI actions',
                'aria-label': 'Quick ask and more AI actions',
                'data-attr': 'inbox-report-ask-ai-actions',
                dropdown: {
                    placement: 'bottom-end',
                    closeOnClickInside: false,
                    visible: isOpen,
                    onVisibilityChange: setOpen,
                    overlay: (
                        <div className="flex w-[22rem] max-w-full flex-col gap-2 p-2">
                            {suggestions.length > 0 && (
                                <div className="flex flex-col gap-1">
                                    <span className="text-xs font-semibold text-tertiary">Suggestions</span>
                                    {suggestions.map((suggestion) => (
                                        <LemonButton
                                            key={suggestion}
                                            // Secondary, not tertiary: above a textarea, rows with no
                                            // border read as a bulleted list, not as buttons.
                                            type="secondary"
                                            size="small"
                                            fullWidth
                                            onClick={() => {
                                                // Fills the box and stops, so a mis-click costs nothing and a nearly
                                                // right suggestion can be edited before it spends a run.
                                                fillFromSuggestion(suggestion)
                                                textAreaRef.current?.focus()
                                            }}
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
                                onPressEnter={submit}
                                placeholder={placeholder}
                                maxLength={REPORT_DISCUSSION_QUESTION_MAX_LENGTH}
                                rows={3}
                                // Focus scrolls the textarea into view, which on a short viewport
                                // hides the suggestions above it.
                                autoFocus={suggestions.length === 0}
                                actions={[
                                    <span key="shortcut" className="text-xs text-tertiary">
                                        Enter to ask, Shift + Enter for a new line
                                    </span>,
                                ]}
                            />
                            <div className="flex justify-end">
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    icon={<IconSparkles />}
                                    onClick={submit}
                                    loading={isDiscussing}
                                    disabledReason={
                                        disabledReason ?? (question.trim() ? undefined : 'Enter a question first')
                                    }
                                    tooltip="AI works on it in the background. The sidebar stays as it is."
                                    data-attr="inbox-report-ask-ai-quick-submit"
                                >
                                    Ask AI
                                </LemonButton>
                            </div>
                            {prActions.length > 0 && (
                                <div className="border-t border-primary pt-1">
                                    <LemonMenuOverlay items={items} />
                                </div>
                            )}
                        </div>
                    ),
                },
            }}
        >
            Ask AI
        </LemonButton>
    )
}
