import type { ReactElement } from 'react'

import { Badge } from '@posthog/quill'

import { SURVEY_QUESTION_TYPE_LABELS } from './utils'

export interface SurveyQuestionData {
    type: string
    question: string
    description?: string | null
    choices?: string[] | null
    scale?: number | null
    lowerBoundLabel?: string | null
    upperBoundLabel?: string | null
    branching?: Record<string, unknown> | null
}

export interface SurveyQuestionProps {
    question: SurveyQuestionData
    index: number
}

export function SurveyQuestion({ question, index }: SurveyQuestionProps): ReactElement {
    const bounds =
        question.lowerBoundLabel || question.upperBoundLabel
            ? `(${question.lowerBoundLabel ?? ''}${question.lowerBoundLabel && question.upperBoundLabel ? ' to ' : ''}${question.upperBoundLabel ?? ''})`
            : ''

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Q{index + 1}</span>
                <Badge>{SURVEY_QUESTION_TYPE_LABELS[question.type] ?? question.type}</Badge>
            </div>
            <span className="text-sm">{question.question}</span>
            {question.description && <span className="text-xs text-muted-foreground">{question.description}</span>}
            {question.choices && question.choices.length > 0 && (
                <ul className="list-disc list-inside text-xs text-muted-foreground pl-2">
                    {question.choices.map((choice, i) => (
                        <li key={i}>{choice}</li>
                    ))}
                </ul>
            )}
            {question.type === 'rating' && question.scale && (
                <span className="text-xs text-muted-foreground">
                    Scale: 1&ndash;{question.scale}&nbsp;{bounds}
                </span>
            )}
        </div>
    )
}
