import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { AttachedContextBar } from 'products/posthog_ai/frontend/api/primitives'

import { captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic, isActionCapableReport } from '../../inboxTaskKickoffLogic'
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
    const [question, setQuestion] = useState('')
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
        <div className="flex flex-col gap-3 p-4 min-w-0">
            <h3 className="mb-0">Ask about this report</h3>
            <AttachedContextBar />
            <LemonTextArea
                value={question}
                onChange={setQuestion}
                onPressCmdEnter={() => submit(question, 'typed')}
                placeholder="Ask a question about this report"
                rows={4}
                maxLength={4000}
                disabled={loading}
                autoFocus
            />
            <LemonButton
                type="primary"
                onClick={() => submit(question, 'typed')}
                loading={loading}
                disabledReason={aiConsentDisabledReason ?? (!question.trim() ? 'Enter a question.' : undefined)}
                data-attr="inbox-report-ask-ai-submit"
            >
                {isCreatingPr ? 'Starting implementation' : 'Send'}
            </LemonButton>
            {suggestions.length > 0 && (
                <div className="flex flex-col gap-2">
                    <span className="text-xs font-semibold text-secondary">Suggested questions and actions</span>
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
    )
}
