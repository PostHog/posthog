import { useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import {
    AttachedContextBar,
    Composer,
    pickHeadline,
    type SuggestionGroup,
    type SuggestionItem,
    Suggestions,
    Welcome,
} from 'products/posthog_ai/frontend/api/primitives'

import { captureInboxReportAction, discussQuestionProperties } from '../../inboxAnalytics'
import {
    inboxTaskKickoffLogic,
    isActionCapableReport,
    REPORT_DISCUSSION_QUESTION_MAX_LENGTH,
} from '../../inboxTaskKickoffLogic'
import type { SignalReport } from '../../types'

export function ReportDiscussionComposer({
    report,
    reportUrl,
}: {
    report: SignalReport
    reportUrl: string
}): JSX.Element {
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { discussReport } = useActions(inboxTaskKickoffLogic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const [draft, setDraft] = useState('')
    const [activeSuggestionGroup, setActiveSuggestionGroup] = useState<SuggestionGroup | null>(null)
    const [headline] = useState(() => pickHeadline())
    const suggestions = isActionCapableReport(report) ? (report.suggested_prompts ?? []) : []
    const loading = isDiscussing || isCreatingPr
    const promptLength = useMemo(
        () => (draft.length >= REPORT_DISCUSSION_QUESTION_MAX_LENGTH * 0.9 ? Array.from(draft.trim()).length : null),
        [draft]
    )
    const isOverLengthLimit = promptLength !== null && promptLength > REPORT_DISCUSSION_QUESTION_MAX_LENGTH
    const suggestionGroups = useMemo<SuggestionGroup[]>(
        () =>
            suggestions.length > 0
                ? [
                      {
                          label: suggestions.length === 1 ? suggestions[0] : 'Report suggestions',
                          icon: <IconSparkles />,
                          suggestions: suggestions.map((content) => ({
                              content,
                              dataAttr: 'inbox-report-ask-ai-suggestion',
                          })),
                      },
                  ]
                : [],
        [suggestions]
    )
    const disabledReason = isOverLengthLimit
        ? `Your message is too long. Shorten it to ${REPORT_DISCUSSION_QUESTION_MAX_LENGTH.toLocaleString()} characters or fewer.`
        : (aiConsentDisabledReason ?? undefined)

    const submit = (prompt: string, source: 'typed' | 'suggested'): void => {
        const trimmed = prompt.trim()
        if (
            !trimmed ||
            loading ||
            aiConsentDisabledReason ||
            Array.from(trimmed).length > REPORT_DISCUSSION_QUESTION_MAX_LENGTH
        ) {
            return
        }
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'detail_pane',
            extra: discussQuestionProperties({ source, suggestionCount: suggestions.length }),
        })
        discussReport(report, reportUrl, trimmed)
    }

    const selectSuggestion = (suggestion: SuggestionItem): void => {
        submit(suggestion.content, 'suggested')
    }

    return (
        <div className="flex flex-col h-full min-h-0 items-center justify-center overflow-y-auto p-4">
            <div className="w-full max-w-2xl flex flex-col items-center gap-4">
                <Welcome headline={headline} />
                <Suggestions.Root
                    activeGroup={activeSuggestionGroup}
                    onActiveGroupChange={setActiveSuggestionGroup}
                    onSelectSuggestion={selectSuggestion}
                    disabled={loading || !!aiConsentDisabledReason}
                    disabledReason={aiConsentDisabledReason ?? (loading ? 'Wait for the task to start.' : undefined)}
                >
                    <Composer.Root
                        value={draft}
                        onChange={setDraft}
                        onSubmit={() => submit(draft, 'typed')}
                        loading={loading}
                        disabled={loading}
                        disabledReason={disabledReason}
                        textAreaRef={textAreaRef}
                    >
                        <Composer.Frame>
                            <Composer.Header>
                                <AttachedContextBar />
                            </Composer.Header>
                            <Composer.Field>
                                <Composer.Placeholder>Ask a question</Composer.Placeholder>
                                <Composer.Textarea autoFocus data-attr="max-chat-input" />
                            </Composer.Field>
                            {promptLength !== null && (
                                <Composer.Footer>
                                    <div
                                        className={cn(
                                            'text-xs text-right pr-1',
                                            isOverLengthLimit ? 'text-error' : 'text-secondary'
                                        )}
                                    >
                                        {promptLength.toLocaleString()} /{' '}
                                        {REPORT_DISCUSSION_QUESTION_MAX_LENGTH.toLocaleString()}
                                    </div>
                                </Composer.Footer>
                            )}
                        </Composer.Frame>
                        <Suggestions.Dropdown />
                        <Composer.Submit data-attr="inbox-report-ask-ai-submit" />
                    </Composer.Root>
                    {suggestionGroups.length > 0 && (
                        <Suggestions.Buttons
                            data={suggestionGroups}
                            tip="Suggested questions and actions"
                            className="w-full"
                        />
                    )}
                </Suggestions.Root>
            </div>
        </div>
    )
}
