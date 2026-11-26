import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronDown, IconSparkles } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    Field,
    FieldDescription,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Separator,
    Text,
    Textarea,
} from '@posthog/quill'

import { REPORT_DISCUSSION_QUESTION_MAX_LENGTH } from '../../inboxTaskKickoffLogic'
import { reportQuickAskLogic } from '../../logics/reportQuickAskLogic'
import { SignalReport } from '../../types'
import { REPORT_PR_AI_ACTION_ICONS } from './reportPrAiActionIcons'

export function QuillDiscussReportButton({
    report,
    reportUrl,
}: {
    report: SignalReport
    reportUrl: string
}): JSX.Element {
    const logic = reportQuickAskLogic({ report, reportUrl })
    const { isDiscussing, disabledReason, placeholder, suggestions, question, isOpen, prActions } = useValues(logic)
    const { setQuestion, setOpen, fillFromSuggestion, submit, openInSidebar, startPrAction } = useActions(logic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    return (
        <ButtonGroup>
            <Button
                variant="outline"
                loading={isDiscussing}
                disabledReason={disabledReason}
                tooltip="Ask PostHog AI about this report in the sidebar"
                onClick={openInSidebar}
            >
                <IconSparkles />
                Ask AI
            </Button>
            <Popover open={isOpen} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label="Quick ask and more AI actions"
                            tooltip="Quick ask and more AI actions"
                            data-attr="inbox-report-ask-ai-actions"
                        />
                    }
                >
                    <IconChevronDown />
                </PopoverTrigger>
                <PopoverContent align="end" className="w-88 max-w-[calc(100vw-2rem)]">
                    <div className="flex flex-col gap-2">
                        {suggestions.length > 0 && (
                            <div className="flex flex-col gap-1">
                                <Text size="xs" variant="muted" className="font-semibold">
                                    Suggestions
                                </Text>
                                {suggestions.map((suggestion) => (
                                    <Button
                                        key={suggestion}
                                        variant="outline"
                                        left
                                        className="h-auto w-full py-1.5 text-left whitespace-normal"
                                        onClick={() => {
                                            fillFromSuggestion(suggestion)
                                            textAreaRef.current?.focus()
                                        }}
                                        data-attr="inbox-report-suggested-prompt"
                                    >
                                        {suggestion}
                                    </Button>
                                ))}
                            </div>
                        )}
                        <Field>
                            <Textarea
                                ref={textAreaRef}
                                value={question}
                                onChange={(event) => setQuestion(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                                        event.preventDefault()
                                        submit()
                                    }
                                }}
                                aria-label="Question for PostHog AI"
                                placeholder={placeholder}
                                maxLength={REPORT_DISCUSSION_QUESTION_MAX_LENGTH}
                                rows={3}
                                autoFocus={suggestions.length === 0}
                            />
                            <FieldDescription>Enter to ask, Shift + Enter for a new line</FieldDescription>
                        </Field>
                        <div className="flex justify-end">
                            <Button
                                variant="primary"
                                loading={isDiscussing}
                                disabledReason={
                                    disabledReason ?? (question.trim() ? undefined : 'Enter a question first')
                                }
                                tooltip="AI works on it in the background. The sidebar stays as it is."
                                onClick={submit}
                                data-attr="inbox-report-ask-ai-quick-submit"
                            >
                                <IconSparkles />
                                Ask AI
                            </Button>
                        </div>
                        {prActions.length > 0 && (
                            <>
                                <Separator />
                                <div className="flex flex-col gap-px">
                                    {prActions.map((action) => (
                                        <Button
                                            key={action.key}
                                            left
                                            className="w-full"
                                            tooltip={action.disabledReason ? undefined : action.tooltip}
                                            disabledReason={action.disabledReason}
                                            onClick={() => startPrAction(action)}
                                            data-attr={action.dataAttr}
                                        >
                                            {REPORT_PR_AI_ACTION_ICONS[action.key]}
                                            {action.label}
                                        </Button>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>
                </PopoverContent>
            </Popover>
        </ButtonGroup>
    )
}
