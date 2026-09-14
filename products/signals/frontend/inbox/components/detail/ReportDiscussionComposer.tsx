import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { QuestionInput } from 'scenes/max/components/QuestionInput'
import { Intro } from 'scenes/max/Intro'
import { maxLogic } from 'scenes/max/maxLogic'
import { maxThreadLogic } from 'scenes/max/maxThreadLogic'

import { AttachedContextBar } from 'products/posthog_ai/frontend/api/primitives'

import { captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import {
    inboxTaskKickoffLogic,
    isActionCapableReport,
    REPORT_DISCUSSION_QUESTION_MAX_LENGTH,
} from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'

export function ReportDiscussionComposer({
    report,
    reportUrl,
}: {
    report: SignalReport
    reportUrl: string
}): JSX.Element {
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { discussReport } = useActions(inboxTaskKickoffLogic)
    const composerLogic = maxLogic({ panelId: `inbox-report-${report.id}`, syncUrl: false })
    const { threadLogicProps } = useValues(composerLogic)
    const { setQuestion } = useActions(composerLogic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const suggestions = isActionCapableReport(report) ? (report.suggested_prompts ?? []) : []
    const loading = isDiscussing || isCreatingPr

    const submit = (prompt: string, source: 'typed' | 'suggested'): void => {
        const trimmed = prompt.trim()
        if (!trimmed || loading || aiConsentDisabledReason) {
            return
        }
        setQuestion(prompt)
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'detail_pane',
            extra: discussQuestionProperties({ source, suggestionCount: suggestions.length }),
        })
        discussReport(report, reportUrl, trimmed)
    }

    return (
        <BindLogic logic={maxLogic} props={composerLogic.props}>
            <BindLogic logic={maxThreadLogic} props={threadLogicProps}>
                <div className="@container/max-welcome flex flex-col justify-center items-center gap-3 p-4 pb-7 min-w-0 min-h-full">
                    <Intro />
                    <QuestionInput
                        textAreaRef={textAreaRef}
                        containerClassName="px-0"
                        submission={{
                            onSend: (prompt) => submit(prompt, 'typed'),
                            loading,
                            disabledReason: aiConsentDisabledReason ?? undefined,
                            dataAttr: 'inbox-report-ask-ai-submit',
                            context: <AttachedContextBar />,
                            maxLength: REPORT_DISCUSSION_QUESTION_MAX_LENGTH,
                        }}
                    />
                    {suggestions.length > 0 && (
                        <div className="flex flex-col gap-2 w-full">
                            <span className="text-xs font-semibold text-secondary">
                                Suggested questions and actions
                            </span>
                            {suggestions.map((suggestion, index) => (
                                <LemonButton
                                    key={index}
                                    type="secondary"
                                    size="small"
                                    fullWidth
                                    disabledReason={
                                        aiConsentDisabledReason ?? (loading ? 'Wait for the task to start.' : undefined)
                                    }
                                    onClick={() => submit(suggestion, 'suggested')}
                                    data-attr="inbox-report-ask-ai-suggestion"
                                >
                                    <span className="whitespace-normal text-left">{suggestion}</span>
                                </LemonButton>
                            ))}
                        </div>
                    )}
                </div>
            </BindLogic>
        </BindLogic>
    )
}
