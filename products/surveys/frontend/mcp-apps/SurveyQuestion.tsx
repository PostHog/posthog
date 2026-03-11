import type { ReactElement } from 'react'

import { Badge, Stack } from '@posthog/mosaic'

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
        <Stack gap="xs">
            <div className="flex items-center gap-2">
                <span className="text-xs text-text-secondary">Q{index + 1}</span>
                <Badge variant="neutral" size="sm">
                    {SURVEY_QUESTION_TYPE_LABELS[question.type] ?? question.type}
                </Badge>
            </div>
            <span className="text-sm text-text-primary">{question.question}</span>
            {question.description && <span className="text-xs text-text-secondary">{question.description}</span>}
            {question.choices && question.choices.length > 0 && (
                <ul className="list-disc list-inside text-xs text-text-secondary pl-2">
                    {question.choices.map((choice, i) => (
                        <li key={i}>{choice}</li>
                    ))}
                </ul>
            )}
            {question.type === 'rating' && question.scale && (
                <span className="text-xs text-text-secondary">
                    Scale: 1&ndash;{question.scale}&nbsp;{bounds}
                </span>
            )}
        </Stack>
    )
}
