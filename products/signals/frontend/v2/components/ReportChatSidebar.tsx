import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'

import { reportChatLogic } from './reportChatLogic'

/** Demo PostHog AI panel content for a report. Rendered inside the app side panel; replies are canned and built from the report's mock content. */
export function ReportChatSidebar({ id }: { id: string }): JSX.Element | null {
    const { report, messages, draft, replying, suggestedQuestions } = useValues(reportChatLogic({ id }))
    const { setDraft, sendMessage } = useActions(reportChatLogic({ id }))

    if (!report) {
        return null
    }

    return (
        <div className="flex h-full flex-col">
            <SidePanelPaneHeader title="PostHog AI" className="mb-0" />

            <div className="flex flex-none flex-col gap-1 border-b border-primary bg-surface-secondary px-3 py-2">
                <span className="text-xxs font-semibold uppercase tracking-wide text-tertiary">In context</span>
                <div className="flex items-center gap-2">
                    <LemonTag type="muted" size="small">
                        Report
                    </LemonTag>
                    <span className="truncate text-xs" title={report.headline}>
                        {report.headline}
                    </span>
                </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
                {messages.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        <p className="m-0 text-sm text-secondary">
                            Ask anything about this report. The verdict, evidence, and proposed fix are already in
                            context.
                        </p>
                        <div className="flex flex-col items-start gap-1">
                            {suggestedQuestions.map((question) => (
                                <LemonButton
                                    key={question}
                                    size="small"
                                    type="secondary"
                                    onClick={() => {
                                        setDraft(question)
                                        sendMessage()
                                    }}
                                    data-attr="v2-report-chat-suggestion"
                                >
                                    {question}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                ) : null}
                {messages.map((message) => (
                    <div
                        key={message.id}
                        className={
                            message.role === 'user'
                                ? 'ml-6 self-end rounded-lg bg-surface-secondary px-3 py-2 text-sm'
                                : 'mr-6 text-sm leading-relaxed'
                        }
                    >
                        {message.text}
                    </div>
                ))}
                {replying ? <div className="text-sm text-tertiary">Thinking…</div> : null}
            </div>

            <form
                className="flex flex-none flex-col gap-2 border-t border-primary p-3"
                onSubmit={(e) => {
                    e.preventDefault()
                    sendMessage()
                }}
            >
                <LemonTextArea
                    value={draft}
                    onChange={setDraft}
                    onPressCmdEnter={sendMessage}
                    placeholder="Ask about this report"
                    minRows={2}
                    maxRows={5}
                    data-attr="v2-report-chat-input"
                />
                <div className="flex items-center justify-between">
                    <span className="text-xxs text-tertiary">Demo: answers are mocked</span>
                    <LemonButton
                        type="primary"
                        size="small"
                        htmlType="submit"
                        loading={replying}
                        disabledReason={!draft.trim() ? 'Type a question first' : undefined}
                        data-attr="v2-report-chat-send"
                    >
                        Send
                    </LemonButton>
                </div>
            </form>
        </div>
    )
}
