import { IconAI } from '@posthog/icons'

import {
    extractSandboxQuestionAnswer,
    parseSandboxQuestionAnswers,
    parseSandboxQuestions,
} from '../policy/questionUtils'
import { GenericMcpToolRenderer } from './tool/GenericMcpToolRenderer'
import { ToolActivity } from './tool/ToolActivity'
import type { ToolRendererProps } from './tool/toolRegistry'

/**
 * Thread recap for the `AskUserQuestion` Claude built-in. The interactive answering happens in the
 * input overlay (`QuestionInput`). The transcript details retain every question, including unanswered
 * ones, and any chosen answers. Malformed input falls back to the generic tool card.
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

    const entries = questions.map((question, index) => ({
        question: question.question,
        answer: answersByKey[question.question] ?? (index === 0 ? fallbackAnswer : null),
    }))

    const body = (
        <div className="flex flex-col gap-3 break-words">
            {entries.map((entry, index) => (
                <div key={index} className="flex flex-col gap-1 text-xs">
                    <div className="text-muted">{entry.question}</div>
                    {entry.answer && <span className="font-medium text-secondary">{entry.answer}</span>}
                </div>
            ))}
        </div>
    )

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconAI />}
            title={message.title || displayName || 'Question'}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}
