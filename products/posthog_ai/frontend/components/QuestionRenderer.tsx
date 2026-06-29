import { IconAI } from '@posthog/icons'

import {
    extractSandboxQuestionAnswer,
    parseSandboxQuestionAnswers,
    parseSandboxQuestions,
} from '../policy/questionUtils'
import { GenericMcpToolRenderer } from './tool/GenericMcpToolRenderer'
import { ToolActivity } from './tool/ToolActivity'
import { truncateText } from './tool/toolContentUtils'
import type { ToolRendererProps } from './tool/toolRegistry'

/**
 * Thread recap for the `AskUserQuestion` Claude built-in. The interactive answering happens in the
 * input overlay (`QuestionInput`); this is the transcript record: the chosen answers preview on
 * the header's second line, and the full question + answer in the expandable body. Malformed input
 * falls back to the generic tool card.
 */
export function QuestionRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const questions = parseSandboxQuestions(message.rawInput)

    if (questions.length === 0) {
        return <GenericMcpToolRenderer {...props} />
    }

    const answersByKey = parseSandboxQuestionAnswers(message.rawOutput)
    // When the result didn't carry a per-question map, fall back to a single joined answer string
    // (the agent's `extractAnswer`) attributed to the first question, so the answer is never lost.
    const fallbackAnswer =
        Object.keys(answersByKey).length === 0 ? extractSandboxQuestionAnswer(message.rawOutput) : null

    const answered = questions
        .map((question, index) => {
            const answer = answersByKey[question.question] ?? (index === 0 ? fallbackAnswer : null)
            return answer ? { question: question.question, answer } : null
        })
        .filter((entry): entry is { question: string; answer: string } => entry !== null)

    const answerPreview = answered.map((entry) => entry.answer).join(', ')

    const body =
        answered.length > 0 ? (
            <div className="flex flex-col gap-3">
                {answered.map((entry, index) => (
                    <div key={index} className="flex flex-col gap-1 text-xs">
                        <div className="text-muted">{entry.question}</div>
                        <span className="font-medium text-secondary">{entry.answer}</span>
                    </div>
                ))}
            </div>
        ) : undefined

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconAI />}
            title={message.title || displayName || 'Question'}
            subtitle={answerPreview ? truncateText(answerPreview, 120) : undefined}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}
