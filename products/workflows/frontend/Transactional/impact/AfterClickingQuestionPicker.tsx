import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { AfterClickingNotice } from './AfterClickingNotice'
import { AFTER_CLICKING_QUESTIONS, afterClickingScanLogic } from './afterClickingScanLogic'
import { IMPACT_DATE_RANGES } from './emailImpactLogic'

export function AfterClickingQuestionPicker({
    sessionCount,
    hasMore,
}: {
    sessionCount: number
    hasMore: boolean
}): JSX.Element {
    const { days, customQuestion } = useValues(afterClickingScanLogic)
    const { askQuestion, setCustomQuestion } = useActions(afterClickingScanLogic)
    const period = (IMPACT_DATE_RANGES.find((range) => range.value === days)?.label ?? '').toLowerCase()
    const askOwnQuestion = (): void => {
        if (customQuestion.trim()) {
            askQuestion(customQuestion.trim(), null)
        }
    }

    return (
        <AfterClickingNotice title="Ask Replay vision about these sessions">
            <span className="text-secondary text-sm">
                Replay vision watches {hasMore ? 'the newest ' : 'the '}
                {pluralize(sessionCount, 'session')} people started from this email in the {period} and answers your
                question for each one. Each session it scans uses Replay vision credits.
            </span>
            <div className="flex flex-wrap gap-2">
                {AFTER_CLICKING_QUESTIONS.map(({ key, question }) => (
                    <LemonButton
                        key={key}
                        type="secondary"
                        size="small"
                        onClick={() => askQuestion(question, key)}
                        data-attr={`email-impact-question-${key}`}
                    >
                        {question}
                    </LemonButton>
                ))}
            </div>
            <span className="font-semibold text-sm">Ask your own question</span>
            <div className="flex flex-wrap gap-2 w-full">
                <LemonInput
                    className="flex-1 min-w-60"
                    size="small"
                    placeholder="What do you want to know about these sessions?"
                    value={customQuestion}
                    onChange={setCustomQuestion}
                    onPressEnter={askOwnQuestion}
                    maxLength={1000}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={askOwnQuestion}
                    disabledReason={customQuestion.trim() ? undefined : 'Type a question first'}
                    data-attr="email-impact-ask-own-question"
                >
                    Ask
                </LemonButton>
            </div>
        </AfterClickingNotice>
    )
}
