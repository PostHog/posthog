import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCheckCircle, IconGitBranch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay, lemonToast } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { InboxQuestionSource, captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import {
    FIX_CI_REQUEST,
    inboxTaskKickoffLogic,
    isActionCapableReport,
    MERGE_PR_REQUEST,
    REPORT_DISCUSSION_QUESTION_MAX_LENGTH,
    ReportDiscussionIntent,
} from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { hasApprovedOpenReportPullRequest } from '../../utils/reportPullRequests'

// How much of a suggestion a draft has to keep, at one end or the other, to still count as an edit
// of it. Long enough that two suggestions opening on the same few words ("Which teams…", "Why did…")
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
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason, freeTrialDisabledReason, lastQuickAskFailure } =
        useValues(inboxTaskKickoffLogic)
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const { prChecksFailing, selectedPullRequest } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const prActionsEnabled = useFeatureFlag('INBOX_GET_IT_MERGED')
    const canMerge = prActionsEnabled && hasApprovedOpenReportPullRequest(report)
    const canMakeGreen = prActionsEnabled && prChecksFailing
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const [isQuickAskOpen, setIsQuickAskOpen] = useState(false)
    const [question, setQuestion] = useState('')
    // The suggestion the textarea was last filled from, so a submitted question can be reported as
    // sent as written, edited first, or written from scratch. Null until a row is clicked.
    const [filledFrom, setFilledFrom] = useState<string | null>(null)

    // A quick ask closes the dropdown before its run exists, so a failed ask puts the question back.
    useEffect(() => {
        if (lastQuickAskFailure?.reportId === report.id) {
            setQuestion(lastQuickAskFailure.question)
        }
    }, [lastQuickAskFailure, report.id])

    // Suggestions can be action requests, and the kickoff wrapper only carries actions out on
    // action-capable reports, so on any other report a stored suggestion would invite an action the
    // run then merely answers.
    const actionCapable = isActionCapableReport(report)
    const suggestions = actionCapable ? (report.suggested_prompts ?? []) : []
    const disabledReason = aiConsentDisabledReason ?? (isCreatingPr ? 'An implementation is starting.' : undefined)

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
        // Fills the box and stops, so a mis-click costs nothing and a nearly right suggestion can be
        // edited before it spends a run.
        textAreaRef.current?.focus()
    }

    const submitQuickAsk = (): void => {
        const trimmed = question.trim()
        // Enter submits straight from the textarea, so it never sees the button's `loading` or
        // `disabledReason`. Each guard has to hold here too, or a second press starts another run.
        if (
            !trimmed ||
            isDiscussing ||
            isCreatingPr ||
            Array.from(trimmed).length > REPORT_DISCUSSION_QUESTION_MAX_LENGTH
        ) {
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
            extra: {
                ...discussQuestionProperties({ source: questionSource(trimmed), suggestionCount: suggestions.length }),
                launch_mode: 'background',
            },
        })
        discussReport(report, reportUrl, trimmed, undefined, undefined, undefined, true)
        setQuestion('')
        setFilledFrom(null)
        setIsQuickAskOpen(false)
    }

    const startPrAction = (request: string, intent: ReportDiscussionIntent, pullRequestUrl?: string): void => {
        setIsQuickAskOpen(false)
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'detail_pane',
            extra: discussQuestionProperties({ source: 'suggested', suggestionCount: 1, intent }),
        })
        discussReport(report, reportUrl, request, undefined, intent, pullRequestUrl)
    }

    const items: LemonMenuItems = [
        canMerge && {
            label: 'Get it merged',
            icon: <IconGitBranch />,
            tooltip: 'Fix CI on the approved PR and merge it',
            onClick: () => startPrAction(MERGE_PR_REQUEST, 'merge_pr'),
            disabledReason: freeTrialDisabledReason,
            'data-attr': 'inbox-report-ask-ai-merge-pr',
        },
        canMakeGreen && {
            label: 'Make it green',
            icon: <IconCheckCircle />,
            tooltip: 'Fix failing CI on the PR and stop, so you can review and merge it',
            onClick: () => startPrAction(FIX_CI_REQUEST, 'fix_ci', selectedPullRequest.url),
            disabledReason: freeTrialDisabledReason,
            'data-attr': 'inbox-report-ask-ai-fix-ci',
        },
    ]

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles />}
            loading={isDiscussing}
            disabledReason={disabledReason}
            onClick={() => openReportDiscussion(report, reportUrl)}
            tooltip="Ask PostHog AI about this report in the sidebar"
            sideAction={{
                tooltip: 'Quick ask and more AI actions',
                'aria-label': 'Quick ask and more AI actions',
                'data-attr': 'inbox-report-ask-ai-actions',
                dropdown: {
                    placement: 'bottom-end',
                    closeOnClickInside: false,
                    visible: isQuickAskOpen,
                    onVisibilityChange: setIsQuickAskOpen,
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
                                onPressEnter={submitQuickAsk}
                                placeholder={
                                    actionCapable
                                        ? 'Ask a question, or tell AI what to do next'
                                        : 'Ask a question about this report'
                                }
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
                                    onClick={submitQuickAsk}
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
                            {(canMerge || canMakeGreen) && (
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
